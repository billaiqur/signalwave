"""
FastAPI backend — REST API for the React frontend.

Endpoints:
  GET  /health
  GET  /api/channels            — list monitored channels (FB pages, IG accounts, YT channels)
  POST /api/channels            — add a channel to monitor
  GET  /api/posts               — list tracked posts/videos
  GET  /api/comments            — list comments (filter by channel/post/harassing)
  POST /api/comments/{id}/hide
  POST /api/comments/{id}/unhide
  POST /api/comments/{id}/review
  GET  /api/flagged-users       — list flagged users
  POST /api/tracker/run         — trigger a manual tracker run

Backward-compat aliases (deprecated, will be removed in a future version):
  GET  /api/pages   → same as /api/channels
  POST /api/pages   → same as /api/channels
"""
import os
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional, Literal
from dotenv import load_dotenv
from loguru import logger

from src.db.database import get_db, init_schema
from src.db.models import (
    MonitoredChannel, TrackedPost, Comment, CommentAction,
    FlaggedUser, ActionType, Platform,
)
from src.platforms import get_platform_client
from src.tracker import run_tracker

load_dotenv()

app = FastAPI(
    title="Social Media Harassment Tracker API",
    version="2.0.0",
    description=(
        "API for tracking and moderating harassing comments "
        "across Facebook, Instagram, and YouTube."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_schema()
    logger.info("Social Media Harassment Tracker API started.")


# ── Health ────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "version": "2.0.0"}


# ── Channels ──────────────────────────────────────────────────

class AddChannelRequest(BaseModel):
    channel_id: str
    access_token: str
    platform: Literal["facebook", "instagram", "youtube"] = "facebook"


def _channel_to_dict(c: MonitoredChannel) -> dict:
    return {
        "id": c.id,
        "platform": c.platform.value,
        "name": c.name,
        "is_active": c.is_active,
        "created_at": c.created_at,
    }


@app.get("/api/channels")
def list_channels(
    platform: Optional[str] = Query(None, description="Filter by platform"),
    db: Session = Depends(get_db),
):
    q = db.query(MonitoredChannel)
    if platform:
        q = q.filter(MonitoredChannel.platform == platform)
    return [_channel_to_dict(c) for c in q.all()]


@app.post("/api/channels")
def add_channel(req: AddChannelRequest, db: Session = Depends(get_db)):
    """
    Add a channel to monitor. Validates the token by calling the platform API.
    For Facebook & Instagram use a Page Access Token.
    For YouTube use an API key (read-only) or an OAuth2 access token (moderation).
    """
    client = get_platform_client(req.platform, req.channel_id, req.access_token)
    try:
        info = client.get_channel_info()
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Could not validate credentials for {req.platform}: {e}",
        )

    existing = db.get(MonitoredChannel, req.channel_id)
    if existing:
        existing.access_token = req.access_token
        existing.is_active = True
        db.commit()
        return {"message": "Channel updated", "id": req.channel_id, "name": info.get("name"), "platform": req.platform}

    channel = MonitoredChannel(
        id=req.channel_id,
        platform=Platform(req.platform),
        name=info.get("name", req.channel_id),
        access_token=req.access_token,
    )
    db.add(channel)
    db.commit()
    return {"message": "Channel added", "id": req.channel_id, "name": channel.name, "platform": req.platform}


# ── Backward-compat aliases for /api/pages ────────────────────
@app.get("/api/pages", include_in_schema=False)
def list_pages_compat(db: Session = Depends(get_db)):
    """Deprecated — use /api/channels instead."""
    return list_channels(db=db)


@app.post("/api/pages", include_in_schema=False)
def add_page_compat(req: AddChannelRequest, db: Session = Depends(get_db)):
    """Deprecated — use /api/channels instead."""
    return add_channel(req, db)


# ── Posts ─────────────────────────────────────────────────────
@app.get("/api/posts")
def list_posts(
    channel_id: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(TrackedPost)
    if channel_id:
        q = q.filter(TrackedPost.channel_id == channel_id)
    if platform:
        q = q.filter(TrackedPost.platform == platform)
    posts = q.order_by(TrackedPost.created_time.desc()).limit(100).all()
    return [
        {
            "id": p.id,
            "channel_id": p.channel_id,
            "platform": p.platform.value if p.platform else None,
            "title": p.title,
            "message": (p.message or "")[:200],
            "permalink": p.permalink,
            "created_time": p.created_time,
            "last_fetched_at": p.last_fetched_at,
        }
        for p in posts
    ]


# ── Comments ──────────────────────────────────────────────────
@app.get("/api/comments")
def list_comments(
    post_id: Optional[str] = Query(None),
    channel_id: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    harassing_only: bool = Query(False),
    unreviewed_only: bool = Query(False),
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
):
    q = db.query(Comment)
    if post_id:
        q = q.filter(Comment.post_id == post_id)
    if channel_id:
        q = q.join(TrackedPost).filter(TrackedPost.channel_id == channel_id)
    if platform:
        q = q.filter(Comment.platform == platform)
    if harassing_only:
        q = q.filter(Comment.is_harassing == True)
    if unreviewed_only:
        q = q.filter(Comment.is_reviewed == False, Comment.is_harassing == True)
    comments = q.order_by(Comment.fetched_at.desc()).limit(limit).all()
    return [
        {
            "id": c.id, "post_id": c.post_id,
            "platform": c.platform.value if c.platform else None,
            "platform_user_id": c.platform_user_id,
            "platform_user_name": c.platform_user_name,
            "message": c.message,
            "is_harassing": c.is_harassing,
            "harassment_score": c.harassment_score,
            "detected_language": c.detected_language,
            "detection_reasons": c.detection_reasons,
            "is_hidden": c.is_hidden,
            "is_reviewed": c.is_reviewed,
            "created_time": c.created_time,
        }
        for c in comments
    ]


def _get_comment_and_channel(comment_id: str, db: Session) -> tuple[Comment, MonitoredChannel]:
    comment = db.get(Comment, comment_id)
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    post = db.get(TrackedPost, comment.post_id)
    channel = db.get(MonitoredChannel, post.channel_id)
    return comment, channel


@app.post("/api/comments/{comment_id}/hide")
def hide_comment(comment_id: str, db: Session = Depends(get_db)):
    comment, channel = _get_comment_and_channel(comment_id, db)
    client = get_platform_client(channel.platform.value, channel.id, channel.access_token)
    success = client.hide_comment(comment_id)
    if not success:
        raise HTTPException(status_code=502, detail=f"{channel.platform.value} API failed to hide comment")
    comment.is_hidden = True
    db.add(CommentAction(comment_id=comment_id, action=ActionType.HIDDEN, performed_by="reviewer"))
    db.commit()
    return {"success": True}


@app.post("/api/comments/{comment_id}/unhide")
def unhide_comment(comment_id: str, db: Session = Depends(get_db)):
    comment, channel = _get_comment_and_channel(comment_id, db)
    client = get_platform_client(channel.platform.value, channel.id, channel.access_token)
    success = client.unhide_comment(comment_id)
    if not success:
        raise HTTPException(status_code=502, detail=f"{channel.platform.value} API failed to unhide comment")
    comment.is_hidden = False
    db.add(CommentAction(comment_id=comment_id, action=ActionType.REVIEWED, performed_by="reviewer", notes="Unhidden"))
    db.commit()
    return {"success": True}


@app.post("/api/comments/{comment_id}/review")
def review_comment(comment_id: str, db: Session = Depends(get_db)):
    comment = db.get(Comment, comment_id)
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    comment.is_reviewed = True
    db.add(CommentAction(comment_id=comment_id, action=ActionType.REVIEWED, performed_by="reviewer"))
    db.commit()
    return {"success": True}


# ── Flagged Users ─────────────────────────────────────────────
@app.get("/api/flagged-users")
def list_flagged_users(db: Session = Depends(get_db)):
    users = db.query(FlaggedUser).order_by(FlaggedUser.total_harassing_comments.desc()).all()
    return [
        {
            "platform_user_id": u.platform_user_id,
            "platform": u.platform.value if u.platform else None,
            "platform_user_name": u.platform_user_name,
            "total_harassing_comments": u.total_harassing_comments,
            "first_seen_at": u.first_seen_at,
            "last_seen_at": u.last_seen_at,
            "is_blocked": u.is_blocked,
        }
        for u in users
    ]


# ── Manual Trigger ────────────────────────────────────────────
@app.post("/api/tracker/run")
def trigger_tracker():
    """Manually trigger a tracker run (async in production — sync here for MVP)."""
    try:
        run_tracker()
        return {"success": True, "message": "Tracker run complete"}
    except Exception as e:
        logger.error(f"Tracker run failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
