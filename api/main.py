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
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional, Literal
from dotenv import load_dotenv
from loguru import logger

from src.db.database import get_db, init_schema
from src.db.models import (
    MonitoredChannel, TrackedPost, Comment, CommentAction,
    FlaggedUser, ActionType, Platform, User, PlatformAppCredential,
)
from src.platforms import get_platform_client
from src.tracker import run_tracker
from api.auth import router as auth_router, get_current_user

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
    allow_origins=["*"],  # Restrict in production to your GitHub Pages URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)

# ── Serve static frontend files ───────────────────────────────
_DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs")
if os.path.isdir(_DOCS_DIR):
    @app.get("/", include_in_schema=False)
    def root():
        return FileResponse(os.path.join(_DOCS_DIR, "index.html"))

    @app.get("/{page}.html", include_in_schema=False)
    def serve_page(page: str):
        file_path = os.path.join(_DOCS_DIR, f"{page}.html")
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(_DOCS_DIR, "index.html"))


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
    access_token: str = ""   # optional: looked up from PlatformAppCredential if blank
    platform: Literal["facebook", "instagram", "youtube"] = "facebook"
    channel_name: str = ""   # optional display name hint (used if API lookup fails)


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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all monitored channels for the current user."""
    q = db.query(MonitoredChannel).filter(MonitoredChannel.client_id == current_user.client_id)
    if platform:
        q = q.filter(MonitoredChannel.platform == platform)
    return [_channel_to_dict(c) for c in q.all()]


@app.post("/api/channels")
def add_channel(
    req: AddChannelRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Add a channel to monitor for the current user.
    For YouTube: if no access_token is provided, the stored OAuth token is used
    automatically from PlatformAppCredential (set during YouTube connect flow).
    """
    access_token = req.access_token or ""

    # ── Resolve access token for YouTube ──────────────────────
    # The YouTube OAuth callback stores the token in PlatformAppCredential,
    # NOT in the profile list returned to the frontend. So we look it up here.
    if req.platform == "youtube" and not access_token:
        cred = db.query(PlatformAppCredential).filter_by(
            client_id=current_user.client_id,
            platform=Platform.YOUTUBE,
        ).first()
        if not cred or not cred.yt_access_token:
            raise HTTPException(
                status_code=400,
                detail="No YouTube credentials found. Please reconnect your YouTube account.",
            )
        access_token = cred.yt_access_token

    # ── Validate with platform API ────────────────────────────
    channel_name = req.channel_name or req.channel_id
    try:
        client = get_platform_client(req.platform, req.channel_id, access_token)
        info = client.get_channel_info()
        channel_name = info.get("name", channel_name)
    except Exception as e:
        logger.warning(f"[{req.platform}] Could not validate channel {req.channel_id}: {e}")
        # Don't fail hard — we already have a verified OAuth token, trust it
        if not req.channel_name:
            raise HTTPException(
                status_code=400,
                detail=f"Could not reach {req.platform} API: {e}",
            )

    # ── Upsert MonitoredChannel ───────────────────────────────
    existing = db.query(MonitoredChannel).filter_by(
        id=req.channel_id,
        client_id=current_user.client_id,
    ).first()

    if existing:
        existing.access_token = access_token
        existing.is_active = True
        db.commit()
        return {
            "message": "Channel updated",
            "id": req.channel_id,
            "name": channel_name,
            "platform": req.platform,
        }

    channel = MonitoredChannel(
        id=req.channel_id,
        client_id=current_user.client_id,
        platform=Platform(req.platform),
        name=channel_name,
        access_token=access_token,
    )
    db.add(channel)
    db.commit()
    return {
        "message": "Channel added",
        "id": req.channel_id,
        "name": channel_name,
        "platform": req.platform,
    }


class StartTrackingRequest(BaseModel):
    scan_interval_hours: int  # 1=hourly, 24=daily, 168=weekly, 0=once


@app.post("/api/channels/{channel_id}/start-tracking")
def start_tracking(
    channel_id: str,
    req: StartTrackingRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Save the scan frequency for a channel and trigger the first tracker run immediately.
    Called from onboarding Step 5 (frequency picker).
    """
    channel = db.query(MonitoredChannel).filter_by(
        id=channel_id,
        client_id=current_user.client_id,
    ).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    channel.scan_interval_hours = req.scan_interval_hours
    channel.is_active = True
    db.commit()

    # Kick off first tracker run in background
    try:
        from src.tracker import run_tracker
        run_tracker()
    except Exception as e:
        logger.warning(f"First tracker run failed (non-fatal): {e}")

    interval_label = {1: "Hourly", 24: "Daily", 168: "Weekly", 0: "Once"}.get(
        req.scan_interval_hours, f"Every {req.scan_interval_hours}h"
    )
    return {
        "success": True,
        "channel_id": channel_id,
        "schedule": interval_label,
        "message": f"Tracking started. First scan running now. Schedule: {interval_label}.",
    }


# ── Stats Summary ─────────────────────────────────────────────
@app.get("/api/stats/summary")
def stats_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns aggregate counts for the current user's tracked channels.
    Used by dashboard.html to populate stat cards.
    """
    # Channels for this user
    channels = db.query(MonitoredChannel).filter_by(
        client_id=current_user.client_id,
        is_active=True,
    ).all()
    channel_ids = [c.id for c in channels]

    if not channel_ids:
        return {
            "channels": 0,
            "videos": 0,
            "total_comments": 0,
            "harassing_comments": 0,
            "hidden_comments": 0,
            "flagged_users": 0,
            "last_scanned_at": None,
        }

    # Aggregate via TrackedPost and Comment tables
    posts = db.query(TrackedPost).filter(
        TrackedPost.channel_id.in_(channel_ids)
    ).all()
    post_ids = [p.id for p in posts]

    total_comments = 0
    harassing_comments = 0
    hidden_comments = 0

    if post_ids:
        from sqlalchemy import func
        total_comments = db.query(func.count(Comment.id)).filter(
            Comment.post_id.in_(post_ids)
        ).scalar() or 0
        harassing_comments = db.query(func.count(Comment.id)).filter(
            Comment.post_id.in_(post_ids),
            Comment.is_harassing == True,
        ).scalar() or 0
        hidden_comments = db.query(func.count(Comment.id)).filter(
            Comment.post_id.in_(post_ids),
            Comment.is_hidden == True,
        ).scalar() or 0

    # Flagged users (global for now — scope to user later if needed)
    from sqlalchemy import func as f2
    flagged_users = db.query(f2.count(FlaggedUser.platform_user_id)).scalar() or 0

    # Last scan time from most recently updated channel
    last_scanned = max(
        (c.last_scanned_at for c in channels if c.last_scanned_at),
        default=None,
    )

    return {
        "channels": len(channel_ids),
        "videos": len(post_ids),
        "total_comments": total_comments,
        "harassing_comments": harassing_comments,
        "hidden_comments": hidden_comments,
        "flagged_users": flagged_users,
        "last_scanned_at": last_scanned,
    }


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


# ── Keywords ──────────────────────────────────────────────────
from src.db.models import HarassmentKeyword
from src.detection.detector import reload_keywords


@app.get("/api/keywords")
def list_keywords(
    language: Optional[str] = Query(None),
    active_only: bool = Query(True),
    db: Session = Depends(get_db),
):
    q = db.query(HarassmentKeyword)
    if language:
        q = q.filter(HarassmentKeyword.language == language)
    if active_only:
        q = q.filter(HarassmentKeyword.is_active == True)
    rows = q.order_by(HarassmentKeyword.language, HarassmentKeyword.keyword).all()
    return [
        {
            "id": r.id, "keyword": r.keyword, "language": r.language,
            "category": r.category, "is_active": r.is_active, "notes": r.notes,
        }
        for r in rows
    ]


class AddKeywordRequest(BaseModel):
    keyword: str
    language: str = "universal"
    category: str = "general"
    notes: str = ""


@app.post("/api/keywords")
def add_keyword(req: AddKeywordRequest, db: Session = Depends(get_db)):
    existing = db.query(HarassmentKeyword).filter_by(
        keyword=req.keyword, language=req.language
    ).first()
    if existing:
        if not existing.is_active:
            existing.is_active = True
            db.commit()
            reload_keywords()
            return {"message": "Keyword re-enabled", "id": existing.id}
        raise HTTPException(status_code=409, detail="Keyword already exists")

    row = HarassmentKeyword(
        keyword=req.keyword, language=req.language,
        category=req.category, notes=req.notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    reload_keywords()
    return {"message": "Keyword added", "id": row.id}


@app.delete("/api/keywords/{keyword_id}")
def delete_keyword(keyword_id: int, db: Session = Depends(get_db)):
    row = db.get(HarassmentKeyword, keyword_id)
    if not row:
        raise HTTPException(status_code=404, detail="Keyword not found")
    row.is_active = False
    db.commit()
    reload_keywords()
    return {"message": "Keyword disabled", "id": keyword_id}

