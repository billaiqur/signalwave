#!/usr/bin/env python3
"""
YouTube Integration Test Script

Fetches videos and comments from all active YouTube channels,
runs harassment detection, and prints a detailed report.
Stores only harassing comments in DB; counts clean ones.

Usage:
  python scripts/test_youtube.py
  python scripts/test_youtube.py --channel-id UCxxxxxxx   # test one channel
  python scripts/test_youtube.py --max-videos 5 --max-comments 50
  python scripts/test_youtube.py --dry-run                # no DB writes
"""
import sys
import os
import argparse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv()

from src.db.database import SessionLocal, init_schema
from src.db.models import (
    MonitoredChannel, PlatformAppCredential, TrackedPost, Comment,
    Platform, FlaggedUser, CommentAction, ActionType,
)
from src.platforms.youtube import YouTubeClient
from src.detection.detector import analyse_comment

AUTO_HIDE = os.getenv("AUTO_HIDE_COMMENTS", "false").lower() == "true"

# ANSI colours for terminal output
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"
DIM    = "\033[2m"


def _hr(char="─", width=70, color=CYAN):
    print(f"{color}{char * width}{RESET}")


def _get_yt_client(db, channel: MonitoredChannel) -> YouTubeClient | None:
    """Build a YouTubeClient with a valid (refreshed if needed) token."""
    cred = (
        db.query(PlatformAppCredential)
        .filter_by(client_id=channel.client_id, platform=Platform.YOUTUBE)
        .first()
    )
    if not cred or not cred.yt_access_token:
        print(f"{RED}  ✗ No YouTube credentials found for channel {channel.id}{RESET}")
        print(f"  Run: python scripts/manage.py add-credentials "
              f"--client-id {channel.client_id} --platform youtube")
        return None

    # Refresh token if expired
    if cred.yt_token_expiry and cred.yt_token_expiry < datetime.utcnow():
        print(f"{YELLOW}  ↻ Access token expired — refreshing...{RESET}")
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
            print(f"{GREEN}  ✓ Token refreshed{RESET}")
        except Exception as e:
            print(f"{RED}  ✗ Token refresh failed: {e}{RESET}")

    return YouTubeClient(channel.id, cred.yt_access_token)


def test_channel(db, channel: MonitoredChannel, args) -> dict:
    """Fetch and analyse one YouTube channel. Returns summary stats."""
    _hr("═")
    print(f"{BOLD}{CYAN}▶ YouTube Channel: {channel.name}{RESET}")
    print(f"  Channel ID  : {channel.id}")
    print(f"  Client      : {channel.client.name if channel.client else '—'}")
    _hr()

    client = _get_yt_client(db, channel)
    if not client:
        return {}

    # ── Fetch videos ──────────────────────────────────────────
    print(f"\n{BOLD}Fetching videos (max={args.max_videos})...{RESET}")
    try:
        videos = client.get_posts(limit=args.max_videos)
    except Exception as e:
        print(f"{RED}  ✗ Failed to fetch videos: {e}{RESET}")
        return {}

    if not videos:
        print(f"{YELLOW}  No videos found.{RESET}")
        return {}

    print(f"  Found {len(videos)} video(s)\n")

    total_comments  = 0
    total_harassing = 0
    total_clean     = 0
    harassing_rows  = []

    for video in videos:
        vid_id    = video["id"]
        vid_title = video.get("title", "(no title)")
        vid_url   = video.get("permalink_url", "")
        vid_date  = video.get("created_time", "")

        # Pretty-print video info
        _hr("-", 70, DIM)
        print(f"{BOLD}  📹 {vid_title}{RESET}")
        print(f"  ID      : {vid_id}")
        print(f"  URL     : {vid_url}")
        print(f"  Posted  : {vid_date[:10] if vid_date else '—'}")

        # Upsert post in DB (unless dry-run)
        post = None
        if not args.dry_run:
            post = db.get(TrackedPost, vid_id)
            if not post:
                post = TrackedPost(
                    id=vid_id,
                    channel_id=channel.id,
                    platform=Platform.YOUTUBE,
                    title=vid_title,
                    message=video.get("message", ""),
                    permalink=vid_url,
                    created_time=_parse_dt(vid_date),
                )
                db.add(post)
                db.commit()

        # ── Fetch comments ────────────────────────────────────
        print(f"\n  Fetching comments (max={args.max_comments})...", end="", flush=True)
        try:
            comments = client.get_comments(vid_id, limit=args.max_comments)
        except Exception as e:
            print(f"\n{RED}  ✗ Failed to fetch comments: {e}{RESET}")
            continue

        print(f" {len(comments)} found")

        if not comments:
            print(f"  {DIM}(no comments){RESET}\n")
            continue

        # ── Analyse each comment ──────────────────────────────
        vid_harassing = 0
        vid_clean     = 0

        print(f"\n  {'#':<4} {'User':<30} {'Date':<12} {'Score':>5}  {'Lang':<10}  Comment")
        print(f"  {'─'*4} {'─'*30} {'─'*12} {'─'*5}  {'─'*10}  {'─'*30}")

        for i, c in enumerate(comments, 1):
            cid        = c["id"]
            text       = c.get("message", "")
            from_info  = c.get("from", {})
            user_id    = from_info.get("id", "unknown")
            user_name  = from_info.get("name", user_id)[:28]
            c_date     = c.get("created_time", "")[:10]

            result     = analyse_comment(text)
            harassing  = result["is_harassing"]
            score      = result["harassment_score"]
            lang       = result["detected_language"]

            # Print row
            flag  = f"{RED}⚠ HARASS{RESET}" if harassing else f"{GREEN}  clean {RESET}"
            score_col = f"{RED}{score:>5}{RESET}" if harassing else f"{DIM}{score:>5}{RESET}"
            text_preview = text[:50].replace("\n", " ")
            print(f"  {i:<4} {user_name:<30} {c_date:<12} {score_col}  {lang:<10}  {text_preview}")

            if harassing:
                vid_harassing += 1
                harassing_rows.append({
                    "video_title": vid_title,
                    "video_id":    vid_id,
                    "comment_id":  cid,
                    "user_id":     user_id,
                    "user_name":   user_name,
                    "text":        text,
                    "score":       score,
                    "lang":        lang,
                    "date":        c_date,
                    "reasons":     result["detection_reasons"],
                })

                # Save to DB
                if not args.dry_run and post:
                    _save_harassing_comment(db, post, c, result)
            else:
                vid_clean += 1
                # Just update the counter on the post
                if not args.dry_run and post:
                    post.total_comments_seen = (post.total_comments_seen or 0) + 1
                    db.commit()

        # Update post counters
        if not args.dry_run and post:
            post.total_comments_seen = (post.total_comments_seen or 0) + len(comments)
            post.harassing_count = (post.harassing_count or 0) + vid_harassing
            post.last_fetched_at = datetime.utcnow()
            db.commit()

        total_comments  += len(comments)
        total_harassing += vid_harassing
        total_clean     += vid_clean

        # Per-video summary
        bar_len   = 30
        h_filled  = int(bar_len * vid_harassing / max(len(comments), 1))
        bar       = f"{RED}{'█' * h_filled}{GREEN}{'░' * (bar_len - h_filled)}{RESET}"
        print(f"\n  Comments: {len(comments)}  |  {RED}Harassing: {vid_harassing}{RESET}"
              f"  |  {GREEN}Clean: {vid_clean}{RESET}")
        print(f"  [{bar}]  {int(100*vid_harassing/max(len(comments),1))}% harassing\n")

    # ── Channel summary ───────────────────────────────────────
    _hr("═")
    print(f"\n{BOLD}  📊 Channel Summary: {channel.name}{RESET}")
    print(f"  Videos fetched   : {len(videos)}")
    print(f"  Total comments   : {total_comments}")
    print(f"  {RED}Harassing        : {total_harassing}{RESET}")
    print(f"  {GREEN}Clean (counted)  : {total_clean}{RESET}")
    if total_comments:
        pct = round(100 * total_harassing / total_comments, 1)
        print(f"  Harassment rate  : {pct}%")
    print(f"  Stored in DB     : {'harassing rows only (dry-run skipped)' if args.dry_run else 'harassing rows saved ✓'}\n")

    # ── Detailed harassing comment list ───────────────────────
    if harassing_rows:
        _hr()
        print(f"\n{BOLD}{RED}  ⚠  Harassing Comments Detail{RESET}\n")
        for r in harassing_rows:
            print(f"  Video   : {r['video_title'][:60]}")
            print(f"  Post ID : {r['video_id']}")
            print(f"  Cmt ID  : {r['comment_id']}")
            print(f"  User    : {r['user_name']}  (id: {r['user_id']})")
            print(f"  Date    : {r['date']}")
            print(f"  Score   : {r['score']}/100  |  Lang: {r['lang']}")
            reasons = r["reasons"]
            if reasons.get("keywords_matched"):
                print(f"  Keywords: {', '.join(reasons['keywords_matched'])}")
            if reasons.get("ai_reason"):
                print(f"  AI note : {reasons['ai_reason'][:120]}")
            print(f"  Comment : {r['text'][:200]}")
            _hr("-", 70, DIM)

    return {
        "videos": len(videos),
        "total_comments": total_comments,
        "harassing": total_harassing,
        "clean": total_clean,
    }


def _save_harassing_comment(db, post: TrackedPost, c: dict, result: dict):
    """Save a harassing comment to DB if not already present."""
    cid = c["id"]
    if db.get(Comment, cid):
        return

    from_info = c.get("from", {})
    comment = Comment(
        id=cid,
        post_id=post.id,
        platform=Platform.YOUTUBE,
        platform_user_id=from_info.get("id", "unknown"),
        platform_user_name=from_info.get("name", ""),
        message=c.get("message", ""),
        created_time=_parse_dt(c.get("created_time", "")),
        is_harassing=True,
        harassment_score=result["harassment_score"],
        detected_language=result["detected_language"],
        detection_reasons=result["detection_reasons"],
        is_hidden=False,
    )
    db.add(comment)

    # Update flagged user
    uid = from_info.get("id", "unknown")
    flagged = db.get(FlaggedUser, (uid, Platform.YOUTUBE))
    if not flagged:
        flagged = FlaggedUser(
            platform_user_id=uid,
            platform=Platform.YOUTUBE,
            platform_user_name=from_info.get("name", ""),
        )
        db.add(flagged)
    flagged.total_harassing_comments = (flagged.total_harassing_comments or 0) + 1
    flagged.last_seen_at = datetime.utcnow()
    db.commit()


def _parse_dt(s: str):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(description="Test YouTube integration")
    parser.add_argument("--channel-id",   default=None, help="Test a specific channel ID only")
    parser.add_argument("--max-videos",   type=int, default=5,  help="Max videos to fetch per channel")
    parser.add_argument("--max-comments", type=int, default=100, help="Max comments to fetch per video")
    parser.add_argument("--dry-run",      action="store_true",  help="Do not write anything to DB")
    args = parser.parse_args()

    init_schema()
    db = SessionLocal()

    try:
        q = db.query(MonitoredChannel).filter(
            MonitoredChannel.platform == Platform.YOUTUBE,
            MonitoredChannel.is_active == True,
        )
        if args.channel_id:
            q = q.filter(MonitoredChannel.id == args.channel_id)

        channels = q.all()

        if not channels:
            print(f"{YELLOW}No active YouTube channels found.{RESET}")
            print("Add one with:")
            print("  python scripts/manage.py add-channel --platform youtube")
            return

        if args.dry_run:
            print(f"\n{YELLOW}⚠  DRY-RUN mode — nothing will be written to DB{RESET}\n")

        overall = {"videos": 0, "total_comments": 0, "harassing": 0, "clean": 0}

        for channel in channels:
            stats = test_channel(db, channel, args)
            for k in overall:
                overall[k] += stats.get(k, 0)

        if len(channels) > 1:
            _hr("═")
            print(f"\n{BOLD}  🏁 Overall Summary ({len(channels)} channels){RESET}")
            print(f"  Total videos   : {overall['videos']}")
            print(f"  Total comments : {overall['total_comments']}")
            print(f"  {RED}Harassing      : {overall['harassing']}{RESET}")
            print(f"  {GREEN}Clean          : {overall['clean']}{RESET}")
            _hr("═")
    finally:
        db.close()


if __name__ == "__main__":
    main()
