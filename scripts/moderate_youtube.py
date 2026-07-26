#!/usr/bin/env python3
"""
YouTube Comment Moderation Script

Delete or hide harassing comments on YouTube videos.
Filters by comment ID, video ID, or user ID.
All actions are logged to the DB comment_actions table.

Usage examples:

  # Delete a specific comment by its ID
  python scripts/moderate_youtube.py --comment-id UgzpEmT5-aAql8GmwH94AaABAg

  # Delete ALL harassing comments on a specific video
  python scripts/moderate_youtube.py --video-id pPgtMif0aws

  # Delete ALL harassing comments by a specific user (across all videos)
  python scripts/moderate_youtube.py --user-id UCIFZVc1mGpZXX1LqsS1FXaw

  # Delete ALL unactioned harassing comments across all channels
  python scripts/moderate_youtube.py --all

  # Use --action hide instead of delete (sets comment to heldForReview)
  python scripts/moderate_youtube.py --all --action hide

  # Dry-run: show what WOULD be deleted without doing it
  python scripts/moderate_youtube.py --all --dry-run

  # Show all stored harassing comments first (no action)
  python scripts/moderate_youtube.py --list
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
    MonitoredChannel, PlatformAppCredential, Platform, FlaggedUser,
)
from src.platforms.youtube import YouTubeClient

# ── ANSI colours ──────────────────────────────────────────────
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"


def _hr(char="─", width=70, color=CYAN):
    print(f"{color}{char * width}{RESET}")


# ── YouTube client factory ─────────────────────────────────────

def _get_yt_client(db, channel: MonitoredChannel) -> YouTubeClient | None:
    """Return a refreshed YouTubeClient for the given channel."""
    cred = (
        db.query(PlatformAppCredential)
        .filter_by(client_id=channel.client_id, platform=Platform.YOUTUBE)
        .first()
    )
    if not cred or not cred.yt_access_token:
        print(f"{RED}  ✗ No YouTube credentials for channel {channel.id}{RESET}")
        return None

    # Refresh if expired
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
            print(f"{GREEN}  ↻ YouTube token refreshed{RESET}")
        except Exception as e:
            print(f"{RED}  ✗ Token refresh failed: {e}{RESET}")

    return YouTubeClient(channel.id, cred.yt_access_token)


# ── Core moderation function ───────────────────────────────────

def moderate_comment(
    db,
    comment: Comment,
    action: str,
    dry_run: bool,
    channel_cache: dict,
) -> bool:
    """
    Delete or hide a single comment via the YouTube API.
    Updates DB status and writes to comment_actions audit log.

    Returns True if action was successful (or skipped in dry-run).
    """
    cid = comment.id

    # Skip already actioned comments
    already_hidden  = comment.is_hidden
    already_deleted = db.query(CommentAction).filter_by(
        comment_id=cid, action=ActionType.DELETED
    ).first()

    if action == "delete" and already_deleted:
        print(f"  {DIM}[SKIP] {cid[:40]} — already deleted{RESET}")
        return False
    if action == "hide" and already_hidden:
        print(f"  {DIM}[SKIP] {cid[:40]} — already hidden{RESET}")
        return False

    # Get the parent post + channel
    post = db.get(TrackedPost, comment.post_id)
    if not post:
        print(f"  {YELLOW}[WARN] {cid[:40]} — parent post not found{RESET}")
        return False

    # Get or cache the YouTube client per channel
    ch_id = post.channel_id
    if ch_id not in channel_cache:
        channel = db.get(MonitoredChannel, ch_id)
        if not channel:
            print(f"  {YELLOW}[WARN] {cid[:40]} — channel not found{RESET}")
            return False
        channel_cache[ch_id] = (channel, _get_yt_client(db, channel))

    channel, yt_client = channel_cache[ch_id]
    if not yt_client:
        return False

    # Print what we're about to do
    user   = comment.platform_user_name or comment.platform_user_id
    text   = (comment.message or "")[:80]
    score  = comment.harassment_score
    lang   = comment.detected_language
    vid_title = (post.title or post.id)[:50]

    print(f"\n  {'[DRY-RUN] ' if dry_run else ''}{'🗑  DELETE' if action == 'delete' else '🙈  HIDE  '} comment")
    print(f"  Comment ID : {cid}")
    print(f"  Video      : {vid_title}")
    print(f"  User       : {user}")
    print(f"  Score      : {score}/100  |  Lang: {lang}")
    print(f"  Text       : {text}")

    if dry_run:
        print(f"  {YELLOW}→ Dry-run: no action taken{RESET}")
        return True

    # Execute the API call
    try:
        if action == "delete":
            success = yt_client.delete_comment(cid)
        else:
            success = yt_client.hide_comment(cid)
    except Exception as e:
        print(f"  {RED}✗ API error: {e}{RESET}")
        return False

    if success:
        # Update comment record
        if action == "delete":
            comment.is_hidden = True   # deleted = also hidden from view
        else:
            comment.is_hidden = True

        # Write audit log
        db.add(CommentAction(
            comment_id=cid,
            action=ActionType.DELETED if action == "delete" else ActionType.HIDDEN,
            performed_by="moderator",
            notes=f"Manual {action} via moderate_youtube.py",
        ))
        db.commit()
        print(f"  {GREEN}✓ {action.upper()}D successfully{RESET}")
        return True
    else:
        print(f"  {RED}✗ {action.upper()} failed — YouTube API returned False{RESET}")
        return False


# ── Query builders ─────────────────────────────────────────────

def _get_comments_by_comment_id(db, comment_id: str) -> list[Comment]:
    c = db.get(Comment, comment_id)
    if not c:
        print(f"{RED}✗ Comment not found in DB: {comment_id}{RESET}")
        print("  (Run test_youtube.py first to fetch and store harassing comments)")
        return []
    if not c.is_harassing:
        print(f"{YELLOW}⚠  Comment {comment_id} is not flagged as harassing.{RESET}")
        ans = input("  Proceed anyway? [y/N]: ").strip().lower()
        if ans != "y":
            return []
    return [c]


def _get_comments_by_video(db, video_id: str) -> list[Comment]:
    post = db.get(TrackedPost, video_id)
    if not post:
        print(f"{RED}✗ Video ID not found in DB: {video_id}{RESET}")
        print("  (Run test_youtube.py first to populate the DB)")
        return []
    comments = (
        db.query(Comment)
        .filter(
            Comment.post_id == video_id,
            Comment.platform == Platform.YOUTUBE,
            Comment.is_harassing == True,
        )
        .all()
    )
    print(f"  Found {len(comments)} harassing comment(s) on video: {post.title or video_id}")
    return comments


def _get_comments_by_user(db, user_id: str) -> list[Comment]:
    comments = (
        db.query(Comment)
        .filter(
            Comment.platform_user_id == user_id,
            Comment.platform == Platform.YOUTUBE,
            Comment.is_harassing == True,
        )
        .all()
    )
    print(f"  Found {len(comments)} harassing comment(s) by user: {user_id}")
    return comments


def _get_all_harassing_comments(db) -> list[Comment]:
    comments = (
        db.query(Comment)
        .filter(
            Comment.platform == Platform.YOUTUBE,
            Comment.is_harassing == True,
            Comment.is_hidden == False,
        )
        .order_by(Comment.harassment_score.desc())
        .all()
    )
    print(f"  Found {len(comments)} unactioned harassing comment(s)")
    return comments


# ── List command ───────────────────────────────────────────────

def cmd_list(db):
    """Print all stored harassing YouTube comments."""
    comments = (
        db.query(Comment)
        .filter(
            Comment.platform == Platform.YOUTUBE,
            Comment.is_harassing == True,
        )
        .order_by(Comment.harassment_score.desc())
        .all()
    )

    _hr("═")
    print(f"{BOLD}  Stored Harassing YouTube Comments  ({len(comments)} total){RESET}")
    _hr("═")

    if not comments:
        print(f"  {DIM}None found. Run test_youtube.py first.{RESET}")
        return

    for i, c in enumerate(comments, 1):
        post = db.get(TrackedPost, c.post_id)
        vid_title = (post.title or c.post_id)[:55] if post else c.post_id

        actions = db.query(CommentAction).filter_by(comment_id=c.id).all()
        action_tags = " ".join(
            f"[{a.action.value.upper()}]" for a in actions
        ) if actions else f"{DIM}[no action yet]{RESET}"

        status = f"{GREEN}active{RESET}" if not c.is_hidden else f"{YELLOW}hidden/deleted{RESET}"

        print(f"\n  {BOLD}#{i}{RESET}")
        print(f"  Comment ID : {c.id}")
        print(f"  Video      : {vid_title}")
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
        description="YouTube comment moderation tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Filter arguments — pick exactly ONE
    filter_group = parser.add_mutually_exclusive_group()
    filter_group.add_argument("--comment-id", help="Target a specific comment ID")
    filter_group.add_argument("--video-id",   help="Target all harassing comments on a video")
    filter_group.add_argument("--user-id",    help="Target all harassing comments by a user")
    filter_group.add_argument("--all",        action="store_true",
                              help="Target all unactioned harassing comments")
    filter_group.add_argument("--list",       action="store_true",
                              help="List stored harassing comments (no action)")

    # Action arguments
    parser.add_argument(
        "--action",
        choices=["delete", "hide"],
        default="delete",
        help="Action to take: delete (permanent) or hide (heldForReview). Default: delete",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without calling the YouTube API",
    )

    args = parser.parse_args()

    # Must specify at least one filter
    if not any([args.comment_id, args.video_id, args.user_id, args.all, args.list]):
        parser.print_help()
        print(f"\n{YELLOW}⚠  Please specify a filter: --comment-id, --video-id, --user-id, --all, or --list{RESET}")
        sys.exit(1)

    init_schema()
    db = SessionLocal()

    try:
        # ── List mode ─────────────────────────────────────────
        if args.list:
            cmd_list(db)
            return

        # ── Resolve target comments ───────────────────────────
        if args.comment_id:
            comments = _get_comments_by_comment_id(db, args.comment_id)
        elif args.video_id:
            comments = _get_comments_by_video(db, args.video_id)
        elif args.user_id:
            comments = _get_comments_by_user(db, args.user_id)
        else:  # --all
            comments = _get_all_harassing_comments(db)

        if not comments:
            print(f"\n{YELLOW}No comments to process.{RESET}")
            return

        # ── Confirm before bulk actions ───────────────────────
        _hr("═")
        action_label = "DELETE (permanent)" if args.action == "delete" else "HIDE (heldForReview)"
        print(f"\n{BOLD}  Action   : {RED}{action_label}{RESET}")
        print(f"{BOLD}  Comments : {len(comments)}{RESET}")
        if args.dry_run:
            print(f"  {YELLOW}Mode     : DRY-RUN (no real API calls){RESET}")
        _hr()

        if not args.dry_run and len(comments) > 1:
            ans = input(f"\n  Proceed with {args.action.upper()} on {len(comments)} comment(s)? [y/N]: ").strip().lower()
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
        print(f"  Processed : {len(comments)}")
        if args.dry_run:
            print(f"  {YELLOW}Dry-run — no changes made{RESET}")
        else:
            print(f"  {GREEN}✓ Success : {success_count}{RESET}")
            if fail_count:
                print(f"  {RED}✗ Failed  : {fail_count}{RESET}")
        _hr("═")

    finally:
        db.close()


if __name__ == "__main__":
    main()
