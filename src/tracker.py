"""
Main tracker loop.

Polls all active monitored channels across Facebook, Instagram, and YouTube,
fetches new comments, runs harassment detection, saves to DB, and hides/holds
flagged comments where the platform supports it.

Credentials are loaded from the database (PlatformAppCredential table),
NOT from .env. .env only stores DB connection and AI provider keys.
"""
import os
from datetime import datetime
from loguru import logger
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from src.db.database import SessionLocal, init_schema
from src.db.models import (
    MonitoredChannel, PlatformAppCredential, TrackedPost,
    Comment, CommentAction, FlaggedUser, ActionType, Platform,
)
from src.platforms import get_platform_client
from src.platforms.base import BasePlatformClient
from src.detection.detector import analyse_comment

load_dotenv()

AUTO_HIDE = os.getenv("AUTO_HIDE_COMMENTS", "true").lower() == "true"


def _get_access_token(db: Session, channel: MonitoredChannel) -> str:
    """
    Return a valid access token for the channel.
    For YouTube: refresh the token via DB-stored OAuth credentials if expired.
    For Facebook/Instagram: use the stored page token directly.
    """
    if channel.platform != Platform.YOUTUBE:
        return channel.access_token

    # YouTube — check expiry and refresh if needed
    cred = (
        db.query(PlatformAppCredential)
        .filter_by(client_id=channel.client_id, platform=Platform.YOUTUBE)
        .first()
    )
    if not cred:
        logger.warning(f"[YouTube] No app credentials for channel {channel.id} — using stored token")
        return channel.access_token

    if cred.yt_token_expiry and cred.yt_token_expiry < datetime.utcnow():
        logger.info(f"[YouTube] Access token expired for channel {channel.id} — refreshing...")
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request

            c = Credentials(
                token=cred.yt_access_token,
                refresh_token=cred.yt_refresh_token,
                client_id=cred.yt_client_id,
                client_secret=cred.yt_client_secret,
                token_uri="https://oauth2.googleapis.com/token",
            )
            c.refresh(Request())
            cred.yt_access_token = c.token
            cred.yt_token_expiry = c.expiry
            channel.access_token = c.token
            db.commit()
            logger.info(f"[YouTube] Token refreshed and saved to DB for channel {channel.id}")
            return c.token
        except Exception as e:
            logger.error(f"[YouTube] Token refresh failed: {e}")

    return cred.yt_access_token or channel.access_token


def upsert_post(db: Session, channel: MonitoredChannel, post_data: dict) -> TrackedPost:
    """Insert or update a TrackedPost record from normalised post_data."""
    post = db.get(TrackedPost, post_data["id"])
    if not post:
        post = TrackedPost(
            id=post_data["id"],
            channel_id=channel.id,
            platform=channel.platform,
            message=post_data.get("message", ""),
            title=post_data.get("title", ""),
            permalink=post_data.get("permalink_url", ""),
            created_time=datetime.fromisoformat(
                post_data["created_time"].replace("Z", "+00:00")
            ) if post_data.get("created_time") else None,
        )
        db.add(post)
    post.last_fetched_at = datetime.utcnow()
    db.commit()
    return post


def process_comment(
    db: Session,
    post: TrackedPost,
    client: BasePlatformClient,
    comment_data: dict,
):
    """
    Analyse a single comment.

    Storage policy:
      - ALL comments are counted on the parent TrackedPost
        (total_comments_seen + harassing_count).
      - Only HARASSING comments are saved as full Comment rows in the DB.
      - Clean comments are counted but not stored — saves space at scale.
    """
    cid = comment_data["id"]

    text = comment_data.get("message", "")
    from_info = comment_data.get("from", {})
    platform_user_id   = from_info.get("id", "unknown")
    platform_user_name = from_info.get("name", "")

    # Run detection
    result = analyse_comment(text)
    is_harassing = result["is_harassing"]

    # Always increment total comment counter on the post
    post.total_comments_seen = (post.total_comments_seen or 0) + 1

    # If already stored (re-run), skip re-processing
    if db.get(Comment, cid):
        db.commit()
        return

    if not is_harassing:
        # Clean comment — count only, do not store full record
        db.commit()
        return

    # ── Harassing comment — save in full ─────────────────────
    post.harassing_count = (post.harassing_count or 0) + 1

    # Parse timestamp
    created_time = None
    if comment_data.get("created_time"):
        try:
            created_time = datetime.fromisoformat(
                comment_data["created_time"].replace("Z", "+00:00")
            )
        except ValueError:
            pass

    comment = Comment(
        id=cid,
        post_id=post.id,
        platform=post.platform,
        platform_user_id=platform_user_id,
        platform_user_name=platform_user_name,
        message=text,
        created_time=created_time,
        is_harassing=True,
        harassment_score=result["harassment_score"],
        detected_language=result["detected_language"],
        detection_reasons=result["detection_reasons"],
        is_hidden=comment_data.get("is_hidden", False),
    )
    db.add(comment)
    db.commit()

    logger.warning(
        f"[{post.platform.value}] Harassment in comment {cid} "
        f"(score={result['harassment_score']}): {text[:80]}"
    )

    # Auto-hide / hold
    if AUTO_HIDE and not comment.is_hidden:
        hidden = client.hide_comment(cid)
        if hidden:
            comment.is_hidden = True
            db.add(CommentAction(
                comment_id=cid,
                action=ActionType.HIDDEN,
                performed_by="system",
                notes=f"Auto-hidden. Score: {result['harassment_score']}",
            ))
            db.commit()

    # Update flagged-user stats (composite PK: user_id + platform)
    flagged = db.get(FlaggedUser, (platform_user_id, post.platform))
    if not flagged:
        flagged = FlaggedUser(
            platform_user_id=platform_user_id,
            platform=post.platform,
            platform_user_name=platform_user_name,
        )
        db.add(flagged)
    flagged.total_harassing_comments = (flagged.total_harassing_comments or 0) + 1
    flagged.last_seen_at = datetime.utcnow()
    db.commit()


def run_tracker():
    """Main entry point — fetch and process all channels/posts/comments."""
    init_schema()
    db = SessionLocal()

    try:
        channels = db.query(MonitoredChannel).filter(MonitoredChannel.is_active == True).all()

        if not channels:
            logger.warning(
                "No active monitored channels found. "
                "Add channels via the API or scripts/add_channel.py"
            )
            return

        for channel in channels:
            logger.info(f"Processing channel: {channel.name} ({channel.platform.value} / {channel.id})")
            token = _get_access_token(db, channel)
            client = get_platform_client(channel.platform.value, channel.id, token)

            posts = client.get_posts(limit=10)
            for post_data in posts:
                post = upsert_post(db, channel, post_data)
                comments = client.get_comments(post.id)
                for c in comments:
                    process_comment(db, post, client, c)

        logger.info("Tracker run complete.")
    finally:
        db.close()


if __name__ == "__main__":
    run_tracker()
