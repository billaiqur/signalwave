#!/usr/bin/env python3
"""
Social-Media Harassment Comment Moderation Script
Supports: Facebook, Instagram, YouTube

Delete or hide harassing comments stored in the database.
Filter by comment ID, post/video ID, user ID, or act on everything.
All actions are recorded in the comment_actions audit table.

Usage examples:

  # List all stored harassing comments across all platforms
  python scripts/moderate_comments.py --list

  # List only Facebook or Instagram or YouTube comments
  python scripts/moderate_comments.py --list --platform facebook
  python scripts/moderate_comments.py --list --platform instagram
  python scripts/moderate_comments.py --list --platform youtube

  # Delete a specific comment by its ID
  python scripts/moderate_comments.py --comment-id <id>

  # Delete all harassing comments on a specific post/video
  python scripts/moderate_comments.py --post-id <id>

  # Delete all harassing comments by a specific user
  python scripts/moderate_comments.py --user-id <id>

  # Target everything on one platform
  python scripts/moderate_comments.py --all --platform facebook

  # Hide instead of delete (Facebook/Instagram hide = is_hidden; YouTube = heldForReview)
  python scripts/moderate_comments.py --all --platform instagram --action hide

  # Dry-run: preview without calling any API
  python scripts/moderate_comments.py --all --dry-run
"""

import sys
import os
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv()

from src.db.database import SessionLocal, init_schema
from src.db.models import (
    Comment, CommentAction, ActionType, TrackedPost,
    MonitoredChannel, PlatformAppCredential, Platform,
)
from src.platforms.facebook  import FacebookClient
from src.platforms.instagram import InstagramClient
from src.platforms.youtube   import YouTubeClient

# ── ANSI colours ──────────────────────────────────────────────
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BLUE   = "\033[94m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

PLATFORM_COLOR = {
    "facebook":  BLUE,
    "instagram": "\033[95m",   # magenta
    "youtube":   RED,
}


def _hr(char="─", width=70, color=CYAN):
    print(f"{color}{char * width}{RESET}")


# ── Platform client factory ────────────────────────────────────

def _get_client(db, channel: MonitoredChannel):
    """Build the correct platform API client for the channel."""
    platform = channel.platform.value if hasattr(channel.platform, "value") else channel.platform

    cred = (
        db.query(PlatformAppCredential)
        .filter_by(client_id=channel.client_id, platform=channel.platform)
        .first()
    )

    if platform in ("facebook", "instagram"):
        # Facebook & Instagram use the access_token stored directly on the channel row
        token = channel.access_token
        if not token:
            print(f"  {YELLOW}[WARN] No access token for channel {channel.id}{RESET}")
            return None
        if platform == "facebook":
            return FacebookClient(channel.id, token)
        else:
            return InstagramClient(channel.id, token)

    elif platform == "youtube":
        if not cred or not cred.yt_access_token:
            print(f"  {RED}✗ No YouTube credentials for channel {channel.id}{RESET}")
            return None

        # Auto-refresh if expired
        if cred.yt_token_expiry and cred.yt_token_expiry < datetime.utcnow():
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
                print(f"  {GREEN}↻ YouTube token refreshed{RESET}")
            except Exception as e:
                print(f"  {RED}✗ Token refresh failed: {e}{RESET}")

        return YouTubeClient(channel.id, cred.yt_access_token)

    else:
        print(f"  {YELLOW}[WARN] Unknown platform: {platform}{RESET}")
        return None


# ── Core moderation logic ──────────────────────────────────────

def moderate_comment(
    db,
    comment: Comment,
    action: str,
    dry_run: bool,
    channel_cache: dict,
) -> bool:
    """
    Hide or delete a single comment via the platform API.
    Updates the DB and writes a CommentAction audit row.
    Returns True on success (or dry-run preview).
    """
    cid = comment.id

    # Skip already-actioned comments
    already_hidden  = comment.is_hidden
    already_deleted = db.query(CommentAction).filter_by(
        comment_id=cid, action=ActionType.DELETED
    ).first()

    if action == "delete" and already_deleted:
        print(f"  {DIM}[SKIP] {cid[:45]} — already deleted{RESET}")
        return False
    if action == "hide" and already_hidden:
        print(f"  {DIM}[SKIP] {cid[:45]} — already hidden{RESET}")
        return False

    # Parent post → channel
    post = db.get(TrackedPost, comment.post_id)
    if not post:
        print(f"  {YELLOW}[WARN] {cid[:45]} — parent post not found{RESET}")
        return False

    ch_id = post.channel_id
    if ch_id not in channel_cache:
        channel = db.get(MonitoredChannel, ch_id)
        if not channel:
            print(f"  {YELLOW}[WARN] {cid[:45]} — channel {ch_id} not found{RESET}")
            return False
        channel_cache[ch_id] = (channel, _get_client(db, channel))

    channel, api_client = channel_cache[ch_id]
    if not api_client:
        return False

    platform = channel.platform.value if hasattr(channel.platform, "value") else channel.platform
    pcolor = PLATFORM_COLOR.get(platform, RESET)
    user      = comment.platform_user_name or comment.platform_user_id or "unknown"
    text      = (comment.message or "")[:80]
    score     = comment.harassment_score
    lang      = comment.detected_language
    vid_title = (post.title or post.id)[:55] if post else comment.post_id

    print(f"\n  {'[DRY-RUN] ' if dry_run else ''}"
          f"{'🗑  DELETE' if action == 'delete' else '🙈  HIDE  '} comment  "
          f"{pcolor}[{platform.upper()}]{RESET}")
    print(f"  Comment ID : {cid}")
    print(f"  Post       : {vid_title}")
    print(f"  User       : {user}")
    print(f"  Score      : {score}/100  |  Lang: {lang}")
    print(f"  Text       : {text}")

    if dry_run:
        print(f"  {YELLOW}→ Dry-run: no API call made{RESET}")
        return True

    # ── Call the platform API ──────────────────────────────────
    try:
        if action == "delete":
            success = api_client.delete_comment(cid)
        else:
            success = api_client.hide_comment(cid)
    except Exception as e:
        print(f"  {RED}✗ API error: {e}{RESET}")
        return False

    if success:
        comment.is_hidden = True
        db.add(CommentAction(
            comment_id=cid,
            action=ActionType.DELETED if action == "delete" else ActionType.HIDDEN,
            performed_by="moderator",
            notes=f"Manual {action} via moderate_comments.py [{platform}]",
        ))
        db.commit()
        print(f"  {GREEN}✓ {action.upper()}D successfully{RESET}")
        return True
    else:
        print(f"  {RED}✗ API returned failure — no DB change{RESET}")
        return False


# ── Query helpers ──────────────────────────────────────────────

def _filter_platform(query, platform_str: str | None):
    if platform_str:
        try:
            plat = Platform(platform_str.lower())
        except ValueError:
            print(f"{RED}✗ Unknown platform '{platform_str}'. "
                  f"Choose: facebook, instagram, youtube{RESET}")
            sys.exit(1)
        query = query.filter(Comment.platform == plat)
    return query


def _get_by_comment_id(db, cid: str) -> list[Comment]:
    c = db.get(Comment, cid)
    if not c:
        print(f"{RED}✗ Comment not found in DB: {cid}{RESET}")
        return []
    if not c.is_harassing:
        print(f"{YELLOW}⚠  Comment {cid} is not flagged as harassing.{RESET}")
        if input("  Proceed anyway? [y/N]: ").strip().lower() != "y":
            return []
    return [c]


def _get_by_post(db, post_id: str, platform_str: str | None) -> list[Comment]:
    post = db.get(TrackedPost, post_id)
    if not post:
        print(f"{RED}✗ Post/video not found in DB: {post_id}{RESET}")
        return []
    q = db.query(Comment).filter(
        Comment.post_id == post_id,
        Comment.is_harassing == True,
    )
    q = _filter_platform(q, platform_str)
    comments = q.all()
    print(f"  Found {len(comments)} harassing comment(s) on post: {post.title or post_id}")
    return comments


def _get_by_user(db, user_id: str, platform_str: str | None) -> list[Comment]:
    q = db.query(Comment).filter(
        Comment.platform_user_id == user_id,
        Comment.is_harassing == True,
    )
    q = _filter_platform(q, platform_str)
    comments = q.all()
    print(f"  Found {len(comments)} harassing comment(s) by user: {user_id}")
    return comments


def _get_all(db, platform_str: str | None) -> list[Comment]:
    q = db.query(Comment).filter(
        Comment.is_harassing == True,
        Comment.is_hidden == False,
    )
    q = _filter_platform(q, platform_str)
    comments = q.order_by(Comment.harassment_score.desc()).all()
    label = f"[{platform_str}] " if platform_str else ""
    print(f"  Found {len(comments)} unactioned {label}harassing comment(s)")
    return comments


# ── List command ───────────────────────────────────────────────

def cmd_list(db, platform_str: str | None):
    q = db.query(Comment).filter(Comment.is_harassing == True)
    q = _filter_platform(q, platform_str)
    comments = q.order_by(Comment.harassment_score.desc()).all()

    _hr("═")
    label = f" [{platform_str.upper()}]" if platform_str else " (all platforms)"
    print(f"{BOLD}  Harassing Comments{label}  —  {len(comments)} total{RESET}")
    _hr("═")

    if not comments:
        print(f"  {DIM}None found. Run the test scripts first to populate the DB.{RESET}")
        return

    for i, c in enumerate(comments, 1):
        post    = db.get(TrackedPost, c.post_id)
        pcolor  = PLATFORM_COLOR.get(
            c.platform.value if hasattr(c.platform, "value") else str(c.platform), RESET
        )
        plat    = c.platform.value if hasattr(c.platform, "value") else str(c.platform)
        vid_ttl = (post.title or c.post_id)[:55] if post else c.post_id
        status  = f"{GREEN}active{RESET}" if not c.is_hidden else f"{YELLOW}hidden/deleted{RESET}"

        actions = db.query(CommentAction).filter_by(comment_id=c.id).all()
        action_tags = " ".join(f"[{a.action.value.upper()}]" for a in actions) if actions else ""

        print(f"\n  {BOLD}#{i}{RESET}  {pcolor}[{plat.upper()}]{RESET}")
        print(f"  Comment ID : {c.id}")
        print(f"  Post       : {vid_ttl}")
        print(f"  Post ID    : {c.post_id}")
        print(f"  User       : {c.platform_user_name or c.platform_user_id}")
        print(f"  User ID    : {c.platform_user_id}")
        print(f"  Date       : {str(c.created_time or c.fetched_at)[:10]}")
        print(f"  Score      : {RED}{c.harassment_score}/100{RESET}  |  Lang: {c.detected_language}")
        print(f"  Status     : {status}  {action_tags}")
        reasons = c.detection_reasons or {}
        if reasons.get("keywords_matched"):
            print(f"  Keywords   : {', '.join(reasons['keywords_matched'])}")
        if reasons.get("ai_reason"):
            print(f"  AI note    : {reasons['ai_reason'][:120]}")
        print(f"  Comment    : {(c.message or '')[:150]}")
        _hr("-", 70, DIM)


# ── Main ───────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Moderate harassing comments on Facebook, Instagram, and YouTube",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # ── Filters (mutually exclusive) ──────────────────────────
    fg = parser.add_mutually_exclusive_group()
    fg.add_argument("--comment-id", help="Target a specific comment ID")
    fg.add_argument("--post-id",    help="Target all harassing comments on a post/video")
    fg.add_argument("--user-id",    help="Target all harassing comments by a user")
    fg.add_argument("--all",        action="store_true",
                    help="Target all unactioned harassing comments")
    fg.add_argument("--list",       action="store_true",
                    help="List stored harassing comments (no action)")

    # ── Options ───────────────────────────────────────────────
    parser.add_argument(
        "--platform",
        choices=["facebook", "instagram", "youtube"],
        help="Limit to a specific platform (optional for --all / --list)",
    )
    parser.add_argument(
        "--action",
        choices=["delete", "hide"],
        default="delete",
        help="Action: delete (permanent) or hide. Default: delete",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would happen without making any API calls",
    )

    args = parser.parse_args()

    if not any([args.comment_id, args.post_id, args.user_id, args.all, args.list]):
        parser.print_help()
        print(f"\n{YELLOW}⚠  Specify a filter: --comment-id, --post-id, --user-id, --all, or --list{RESET}")
        sys.exit(1)

    init_schema()
    db = SessionLocal()

    try:
        # ── List ──────────────────────────────────────────────
        if args.list:
            cmd_list(db, args.platform)
            return

        # ── Resolve target comments ───────────────────────────
        if args.comment_id:
            comments = _get_by_comment_id(db, args.comment_id)
        elif args.post_id:
            comments = _get_by_post(db, args.post_id, args.platform)
        elif args.user_id:
            comments = _get_by_user(db, args.user_id, args.platform)
        else:  # --all
            comments = _get_all(db, args.platform)

        if not comments:
            print(f"\n{YELLOW}No comments to process.{RESET}")
            return

        # ── Confirm bulk actions ──────────────────────────────
        _hr("═")
        act_label = "DELETE (permanent)" if args.action == "delete" else "HIDE"
        plat_label = f" [{args.platform.upper()}]" if args.platform else " [all platforms]"
        print(f"\n{BOLD}  Action    : {RED}{act_label}{RESET}")
        print(f"{BOLD}  Platform  : {plat_label}{RESET}")
        print(f"{BOLD}  Comments  : {len(comments)}{RESET}")
        if args.dry_run:
            print(f"  {YELLOW}Mode      : DRY-RUN (no real API calls){RESET}")
        _hr()

        if not args.dry_run and len(comments) > 1:
            ans = input(
                f"\n  Proceed with {args.action.upper()} on "
                f"{len(comments)} comment(s)? [y/N]: "
            ).strip().lower()
            if ans != "y":
                print("  Aborted.")
                return

        # ── Execute ───────────────────────────────────────────
        channel_cache = {}
        success_count = 0
        fail_count    = 0

        for comment in comments:
            ok = moderate_comment(db, comment, args.action, args.dry_run, channel_cache)
            if ok:
                success_count += 1
            else:
                fail_count += 1

        # ── Summary ───────────────────────────────────────────
        _hr("═")
        print(f"\n{BOLD}  Summary{RESET}")
        print(f"  Processed  : {len(comments)}")
        if args.dry_run:
            print(f"  {YELLOW}Dry-run — no changes made{RESET}")
        else:
            print(f"  {GREEN}✓ Success  : {success_count}{RESET}")
            if fail_count:
                print(f"  {RED}✗ Failed   : {fail_count}{RESET}")
        _hr("═")

    finally:
        db.close()


if __name__ == "__main__":
    main()
