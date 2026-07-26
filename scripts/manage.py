#!/usr/bin/env python3
"""
Unified CLI to manage the Social Media Harassment Tracker.

Usage:
  python scripts/manage.py <command> [options]

Commands:
  ── Clients ─────────────────────────────────────────
  add-client          Add a new client
  list-clients        List all clients

  ── Platform App Credentials ────────────────────────
  add-credentials     Store app credentials for a client on a platform
  list-credentials    List stored credentials for a client

  ── Channels (pages / accounts / YT channels) ───────
  add-channel         Add a social-media channel to monitor for a client
  list-channels       List monitored channels

  ── Operations ──────────────────────────────────────
  run-tracker         Run the tracker immediately (fetch + detect + save)
  show-comments       Show recent detected harassing comments

  ── Keywords ────────────────────────────────────────
  list-keywords       Show all harassment keywords stored in the DB
  add-keyword         Add a new keyword to the DB
  delete-keyword      Disable (soft-delete) a keyword by ID
  reload-keywords     Re-read keywords from DB into the detector cache

Examples:
  python scripts/manage.py add-client
  python scripts/manage.py add-credentials --client-id 1 --platform facebook
  python scripts/manage.py add-channel --client-id 1 --platform facebook
  python scripts/manage.py list-channels
  python scripts/manage.py run-tracker
  python scripts/manage.py show-comments --limit 20
"""
import sys
import os
import argparse
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

from src.db.database import SessionLocal, init_schema
from src.db.models import (
    Client, PlatformAppCredential, MonitoredChannel,
    Platform, Comment, TrackedPost,
)

# ── ANSI colours ───────────────────────────────────────────────
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"


# ── Helpers ────────────────────────────────────────────────────

def _db():
    return SessionLocal()


def _pick_client(db, client_id: int | None) -> Client:
    """Return a client by ID, or prompt the user to pick one."""
    if client_id:
        c = db.get(Client, client_id)
        if not c:
            print(f"❌  No client found with id={client_id}")
            sys.exit(1)
        return c

    clients = db.query(Client).filter(Client.is_active == True).all()
    if not clients:
        print("❌  No clients found. Run: python scripts/manage.py add-client")
        sys.exit(1)

    print("\n── Available Clients ─────────────────────────")
    for c in clients:
        print(f"  [{c.id}] {c.name}  ({c.contact_email or 'no email'})")
    print()
    cid = input("Enter client ID: ").strip()
    c = db.get(Client, int(cid))
    if not c:
        print(f"❌  Invalid client ID: {cid}")
        sys.exit(1)
    return c


def _hr(char="─", width=56):
    print(char * width)


# ── Commands ───────────────────────────────────────────────────

def cmd_add_client(args):
    """Interactively add a new client."""
    print("\n── Add New Client ────────────────────────────")
    name  = input("Client name          : ").strip()
    email = input("Contact email        : ").strip()
    phone = input("Phone (optional)     : ").strip()
    notes = input("Notes (optional)     : ").strip()

    if not name:
        print("❌  Client name is required.")
        sys.exit(1)

    db = _db()
    client = Client(
        name=name,
        contact_email=email or None,
        phone=phone or None,
        notes=notes or None,
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    print(f"\n✅  Client added  →  id={client.id}  name='{client.name}'")
    db.close()


def cmd_list_clients(args):
    """List all clients."""
    db = _db()
    clients = db.query(Client).order_by(Client.id).all()
    _hr()
    print(f"{'ID':<5} {'Name':<25} {'Email':<30} {'Active'}")
    _hr()
    for c in clients:
        print(f"{c.id:<5} {c.name:<25} {(c.contact_email or ''):<30} {c.is_active}")
    _hr()
    print(f"Total: {len(clients)}")
    db.close()


def cmd_add_credentials(args):
    """Store developer app credentials for a client on a platform."""
    db = _db()
    client = _pick_client(db, args.client_id)
    platform = args.platform or _pick_platform()

    print(f"\n── Add Credentials: {platform.upper()} for '{client.name}' ──────")

    # Check for existing
    existing = (
        db.query(PlatformAppCredential)
        .filter_by(client_id=client.id, platform=Platform(platform))
        .first()
    )
    cred = existing or PlatformAppCredential(
        client_id=client.id,
        platform=Platform(platform),
    )

    if platform == "facebook" or platform == "instagram":
        print("\nGet these from: https://developers.facebook.com/apps/")
        cred.fb_app_id     = _prompt("Meta App ID", cred.fb_app_id)
        cred.fb_app_secret = _prompt("Meta App Secret", cred.fb_app_secret, secret=True)
        print("\nGet a long-lived User Access Token from:")
        print("  https://developers.facebook.com/tools/explorer")
        print("  Steps: Get Token → User Token → add pages_read_engagement,")
        print("         pages_manage_posts, pages_manage_engagement,")
        print("         instagram_basic, instagram_manage_comments")
        cred.fb_long_lived_token = _prompt(
            "Long-lived User Access Token", cred.fb_long_lived_token, secret=True
        )

    elif platform == "youtube":
        print("\nGet these from: https://console.cloud.google.com/apis/credentials")
        print("  → Your 'harassment-tracker-desktop' OAuth 2.0 Client ID")
        cred.yt_client_id     = _prompt("YouTube Client ID", cred.yt_client_id)
        cred.yt_client_secret = _prompt("YouTube Client Secret", cred.yt_client_secret, secret=True)

        print("\nGenerating YouTube OAuth token (will open browser)...")
        yt_tokens = _run_youtube_oauth(cred.yt_client_id, cred.yt_client_secret)
        if yt_tokens:
            cred.yt_access_token  = yt_tokens["access_token"]
            cred.yt_refresh_token = yt_tokens["refresh_token"]
            cred.yt_token_expiry  = yt_tokens["expiry"]
            print("✅  YouTube OAuth token obtained and stored in DB.")
        else:
            print("⚠️   OAuth flow skipped — you can run it later with:")
            print("     python scripts/manage.py add-credentials --client-id", client.id,
                  "--platform youtube")

    if not existing:
        db.add(cred)
    db.commit()
    print(f"\n✅  Credentials saved for client '{client.name}' / {platform}")
    db.close()


def _pick_platform() -> str:
    print("\nPlatform: [1] facebook  [2] instagram  [3] youtube")
    choice = input("Choose (1/2/3): ").strip()
    return {"1": "facebook", "2": "instagram", "3": "youtube"}.get(choice, "facebook")


def _prompt(label: str, current=None, secret=False) -> str:
    """Prompt for a value, showing masked current value if exists."""
    if current:
        display = ("*" * 8 + current[-4:]) if secret else current[:40] + "..."
        val = input(f"  {label} [{display}]: ").strip()
        return val if val else current
    else:
        val = input(f"  {label}: ").strip()
        return val


def _run_youtube_oauth(client_id: str, client_secret: str) -> dict | None:
    """Run the OAuth2 flow for YouTube and return tokens."""
    try:
        import json as _json
        import tempfile
        from google_auth_oauthlib.flow import InstalledAppFlow

        secret_data = {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "project_id": "harassment-tracker",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "redirect_uris": ["http://localhost"],
            }
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            _json.dump(secret_data, f)
            tmp_path = f.name

        scopes = ["https://www.googleapis.com/auth/youtube.force-ssl"]
        flow = InstalledAppFlow.from_client_secrets_file(tmp_path, scopes)

        print("\n  ┌─ Google OAuth Instructions ─────────────────────────────────────┐")
        print("  │  If you see 'Access blocked' or 'App not verified':             │")
        print("  │   1. Click 'Advanced' (bottom-left of the error screen)         │")
        print("  │   2. Click 'Go to Harassment_tracker (unsafe)'                  │")
        print("  │   3. Click 'Continue'                                            │")
        print("  │                                                                  │")
        print("  │  OR — add your email as a Test User first:                      │")
        print("  │  console.cloud.google.com/apis/oauth-consent → Test users       │")
        print("  └──────────────────────────────────────────────────────────────────┘\n")

        # run_local_server opens browser; if browser flow fails, fall back to console
        try:
            creds = flow.run_local_server(
                port=0,
                open_browser=True,
                # Allow unverified apps in test mode
                authorization_prompt_message="Opening browser for Google login...\n"
                    "If blocked, click Advanced → Go to app (unsafe)\n",
                success_message="✅ Authentication complete! You may close this tab.",
            )
        except Exception:
            print("\n  Browser flow failed — switching to manual URL method.")
            print("  Copy the URL below into your browser, authorise, then paste the code here.\n")
            flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
            auth_url, _ = flow.authorization_url(prompt="consent")
            print(f"  Auth URL:\n  {auth_url}\n")
            code = input("  Paste the authorisation code here: ").strip()
            flow.fetch_token(code=code)
            creds = flow.credentials

        os.unlink(tmp_path)

        expiry = None
        if creds.expiry:
            expiry = creds.expiry if isinstance(creds.expiry, datetime) else \
                     datetime.fromisoformat(str(creds.expiry))

        return {
            "access_token":  creds.token,
            "refresh_token": creds.refresh_token,
            "expiry":        expiry,
        }
    except Exception as e:
        print(f"⚠️   OAuth flow error: {e}")
        return None


def cmd_list_credentials(args):
    """List stored credentials for a client."""
    db = _db()
    client = _pick_client(db, args.client_id)

    creds = (
        db.query(PlatformAppCredential)
        .filter_by(client_id=client.id)
        .all()
    )
    _hr()
    print(f"Credentials for client: {client.name} (id={client.id})")
    _hr()
    if not creds:
        print("  No credentials stored yet.")
        print(f"  Run: python scripts/manage.py add-credentials --client-id {client.id}")
    for c in creds:
        print(f"\n  Platform : {c.platform.value}")
        if c.fb_app_id:
            print(f"  FB App ID: {c.fb_app_id}")
            print(f"  FB Token : {'✅ set' if c.fb_long_lived_token else '❌ missing'}")
        if c.yt_client_id:
            print(f"  YT Client: {c.yt_client_id[:40]}...")
            print(f"  YT Token : {'✅ set' if c.yt_access_token else '❌ missing'}")
            if c.yt_token_expiry:
                print(f"  YT Expiry: {c.yt_token_expiry.strftime('%Y-%m-%d %H:%M')}")
    _hr()
    db.close()


def cmd_add_channel(args):
    """Add a social-media channel to monitor for a client."""
    db = _db()
    client = _pick_client(db, args.client_id)
    platform = args.platform or _pick_platform()

    print(f"\n── Add Channel: {platform.upper()} for '{client.name}' ──────────")

    # Look up stored credentials for this platform
    cred = (
        db.query(PlatformAppCredential)
        .filter_by(client_id=client.id, platform=Platform(platform))
        .first()
    )
    if not cred:
        print(f"⚠️   No {platform} credentials found for this client.")
        print(f"    Run first: python scripts/manage.py add-credentials "
              f"--client-id {client.id} --platform {platform}")
        sys.exit(1)

    channel_id = input(f"\n  {platform.capitalize()} Channel/Page/Account ID: ").strip()

    # Determine the access token to use
    access_token = _resolve_access_token(platform, cred, channel_id)
    if not access_token:
        print("❌  Could not resolve an access token. Aborting.")
        sys.exit(1)

    # Validate by calling the live API
    from src.platforms import get_platform_client
    print(f"\n  Validating with {platform} API...")
    try:
        pc = get_platform_client(platform, channel_id, access_token)
        info = pc.get_channel_info()
        print(f"  ✅  Found: {info.get('name')}  (id={info.get('id')})")
    except Exception as e:
        print(f"  ❌  API validation failed: {e}")
        sys.exit(1)

    # Save / update in DB
    existing = db.get(MonitoredChannel, channel_id)
    if existing:
        existing.access_token = access_token
        existing.is_active    = True
        existing.client_id    = client.id
        db.commit()
        print(f"\n✅  Updated channel: {existing.name}  [{platform}]")
    else:
        ch = MonitoredChannel(
            id=channel_id,
            client_id=client.id,
            platform=Platform(platform),
            name=info.get("name", channel_id),
            access_token=access_token,
        )
        db.add(ch)
        db.commit()
        print(f"\n✅  Added channel: {ch.name}  [{platform}]  client='{client.name}'")
    db.close()


def _resolve_access_token(platform: str, cred: PlatformAppCredential, channel_id: str) -> str | None:
    """
    Get the right access token for the given platform and channel.
    For Facebook: exchange long-lived user token → page token.
    For Instagram: same as Facebook page token.
    For YouTube: use stored OAuth access token (refresh if expired).
    """
    if platform in ("facebook", "instagram"):
        if not cred.fb_long_lived_token:
            print("❌  No Facebook long-lived token stored for this client.")
            return None
        # Exchange user token for page-specific token
        if platform == "facebook":
            return _get_fb_page_token(cred.fb_long_lived_token, channel_id)
        else:
            # For Instagram, the page access token of the linked Facebook page is used
            # channel_id here is the IG Business Account ID
            # The user token itself is used to query IG
            return cred.fb_long_lived_token

    elif platform == "youtube":
        if not cred.yt_access_token:
            print("❌  No YouTube token stored. Run add-credentials first.")
            return None
        # Refresh if expired
        if cred.yt_token_expiry and cred.yt_token_expiry < datetime.utcnow():
            print("  🔄  YouTube token expired — refreshing...")
            new_token = _refresh_yt_token(cred)
            if new_token:
                return new_token
        return cred.yt_access_token
    return None


def _get_fb_page_token(user_token: str, page_id: str) -> str | None:
    """Exchange a long-lived user token for a specific page's access token."""
    import requests
    import os
    version = os.getenv("GRAPH_API_VERSION", "v19.0")
    url = f"https://graph.facebook.com/{version}/{page_id}"
    resp = requests.get(url, params={
        "fields": "access_token,name",
        "access_token": user_token,
    }, timeout=15)
    if resp.ok:
        data = resp.json()
        token = data.get("access_token")
        if token:
            print(f"  ✅  Got page access token for '{data.get('name', page_id)}'")
            return token
    print(f"  ⚠️   Could not get page token: {resp.text[:200]}")
    print(f"  Using user token as fallback.")
    return user_token


def _refresh_yt_token(cred: PlatformAppCredential) -> str | None:
    """Refresh a YouTube access token using the stored refresh token."""
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

        # Save refreshed values back to the cred object
        # (caller must commit)
        cred.yt_access_token = c.token
        cred.yt_token_expiry = c.expiry
        print("  ✅  YouTube token refreshed.")
        return c.token
    except Exception as e:
        print(f"  ❌  Token refresh failed: {e}")
        return None


def cmd_list_channels(args):
    """List all monitored channels."""
    db = _db()
    q = db.query(MonitoredChannel)
    if args.client_id:
        q = q.filter(MonitoredChannel.client_id == args.client_id)
    if args.platform:
        q = q.filter(MonitoredChannel.platform == args.platform)
    channels = q.order_by(MonitoredChannel.platform, MonitoredChannel.name).all()

    _hr()
    print(f"{'ID':<25} {'Platform':<12} {'Name':<30} {'Client':<20} {'Active'}")
    _hr()
    for ch in channels:
        client_name = ch.client.name if ch.client else "—"
        print(f"{ch.id:<25} {ch.platform.value:<12} {ch.name:<30} {client_name:<20} {ch.is_active}")
    _hr()
    print(f"Total: {len(channels)}")
    db.close()


def cmd_run_tracker(args):
    """Run the tracker immediately."""
    from src.tracker import run_tracker
    print("\n🚀  Starting tracker run...")
    run_tracker()
    print("✅  Tracker run complete.")


def cmd_show_comments(args):
    """Show recent harassing comments."""
    db = _db()
    q = (
        db.query(Comment)
        .filter(Comment.is_harassing == True)
        .order_by(Comment.fetched_at.desc())
        .limit(args.limit)
    )
    comments = q.all()

    _hr()
    print(f"Recent Harassing Comments (limit={args.limit})")
    _hr()
    if not comments:
        print("  No harassing comments found yet.")
        print("  Run the tracker first: python scripts/manage.py run-tracker")
    for c in comments:
        post = db.get(TrackedPost, c.post_id)
        channel_name = post.channel.name if post and post.channel else "?"
        print(f"\n  [{c.platform.value.upper()}] Channel: {channel_name}")
        print(f"  User    : {c.platform_user_name or c.platform_user_id}")
        print(f"  Score   : {c.harassment_score}/100  | Lang: {c.detected_language}")
        print(f"  Comment : {c.message[:120]}")
        print(f"  Hidden  : {c.is_hidden}  | Reviewed: {c.is_reviewed}")
        print(f"  Time    : {c.created_time or c.fetched_at}")
        _hr("-")
    db.close()


# ── Keyword management ─────────────────────────────────────────

def cmd_list_keywords(args):
    """Print all keywords stored in the DB, grouped by language."""
    from src.db.models import HarassmentKeyword
    db = SessionLocal()
    try:
        rows = db.query(HarassmentKeyword).order_by(
            HarassmentKeyword.language, HarassmentKeyword.category, HarassmentKeyword.keyword
        ).all()
        if not rows:
            print("No keywords found. Run any test script to auto-seed them.")
            return

        current_lang = None
        for kw in rows:
            if kw.language != current_lang:
                current_lang = kw.language
                print(f"\n  {BOLD}── {current_lang.upper()} ──{RESET}")
                print(f"  {'ID':<5}  {'Active':<7}  {'Category':<20}  Keyword")
                print(f"  {'─'*4}  {'─'*6}  {'─'*19}  {'─'*30}")
            status = f"{GREEN}✓{RESET}" if kw.is_active else f"{DIM}✗{RESET}"
            kw_display = kw.keyword[:50]
            print(f"  {kw.id:<5}  {status:<15}  {(kw.category or ''):<20}  {kw_display}")

        total   = len(rows)
        active  = sum(1 for r in rows if r.is_active)
        print(f"\n  Total: {total}  |  Active: {GREEN}{active}{RESET}  |  Disabled: {DIM}{total - active}{RESET}")
    finally:
        db.close()


def cmd_add_keyword(args):
    """Interactively add a new harassment keyword to the DB."""
    from src.db.models import HarassmentKeyword
    db = SessionLocal()
    try:
        print(f"\n{BOLD}Add Harassment Keyword{RESET}")
        print("─" * 40)
        keyword  = input("  Keyword / phrase  : ").strip()
        if not keyword:
            print("  ✗ Keyword cannot be empty.")
            return

        print("  Language options  : tanglish | tamil | english | universal")
        language = input("  Language          : ").strip().lower() or "universal"

        print("  Category options  : body_insult | family_insult | threat | "
              "identity_insult | intellect_insult | general")
        category = input("  Category          : ").strip() or "general"
        notes    = input("  Notes (optional)  : ").strip() or None

        # Check for duplicate
        existing = db.query(HarassmentKeyword).filter_by(
            keyword=keyword, language=language
        ).first()
        if existing:
            if not existing.is_active:
                existing.is_active = True
                db.commit()
                print(f"\n  {YELLOW}⚠  Keyword already existed but was disabled → re-enabled (ID {existing.id}){RESET}")
            else:
                print(f"\n  {YELLOW}⚠  Keyword already exists (ID {existing.id}){RESET}")
            return

        row = HarassmentKeyword(
            keyword=keyword, language=language, category=category, notes=notes
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        print(f"\n  {GREEN}✓ Keyword added (ID {row.id}){RESET}")
        print(f"    Keyword  : {keyword}")
        print(f"    Language : {language}  |  Category: {category}")

        # Invalidate in-process cache so the new keyword is used immediately
        try:
            from src.detection.detector import reload_keywords
            n = reload_keywords()
            print(f"  {GREEN}↻ Detector cache refreshed ({n} active keywords){RESET}")
        except Exception:
            pass
    finally:
        db.close()


def cmd_delete_keyword(args):
    """Disable a keyword by its DB ID (soft-delete — keeps the row)."""
    from src.db.models import HarassmentKeyword
    db = SessionLocal()
    try:
        if not hasattr(args, "keyword_id") or not args.keyword_id:
            id_str = input("  Keyword ID to disable: ").strip()
            if not id_str.isdigit():
                print("  ✗ Please enter a numeric ID (see list-keywords)")
                return
            kw_id = int(id_str)
        else:
            kw_id = args.keyword_id

        row = db.get(HarassmentKeyword, kw_id)
        if not row:
            print(f"  {RED}✗ No keyword with ID {kw_id}{RESET}")
            return
        if not row.is_active:
            print(f"  {YELLOW}Already disabled: '{row.keyword}' (ID {kw_id}){RESET}")
            return

        row.is_active = False
        db.commit()
        print(f"  {GREEN}✓ Disabled keyword ID {kw_id}: '{row.keyword}'{RESET}")

        try:
            from src.detection.detector import reload_keywords
            reload_keywords()
        except Exception:
            pass
    finally:
        db.close()


def cmd_reload_keywords(_args):
    """Force-reload the keyword cache from the DB."""
    try:
        from src.detection.detector import reload_keywords
        n = reload_keywords()
        print(f"  {GREEN}✓ Keyword cache refreshed — {n} active keywords loaded{RESET}")
    except Exception as e:
        print(f"  {RED}✗ Failed: {e}{RESET}")


# ── Main ───────────────────────────────────────────────────────

COMMANDS = {
    "add-client":       cmd_add_client,
    "list-clients":     cmd_list_clients,
    "add-credentials":  cmd_add_credentials,
    "list-credentials": cmd_list_credentials,
    "add-channel":      cmd_add_channel,
    "list-channels":    cmd_list_channels,
    "run-tracker":      cmd_run_tracker,
    "show-comments":    cmd_show_comments,
    "list-keywords":    cmd_list_keywords,
    "add-keyword":      cmd_add_keyword,
    "delete-keyword":   cmd_delete_keyword,
    "reload-keywords":  cmd_reload_keywords,
}


def main():
    parser = argparse.ArgumentParser(
        description="Social Media Harassment Tracker — management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("command", choices=list(COMMANDS.keys()), help="Command to run")
    parser.add_argument("--client-id",  type=int, default=None, help="Client ID")
    parser.add_argument("--platform",   choices=["facebook", "instagram", "youtube"],
                        default=None, help="Platform")
    parser.add_argument("--limit",      type=int, default=20, help="Result limit (show-comments)")
    parser.add_argument("--keyword-id", type=int, default=None, dest="keyword_id",
                        help="Keyword DB ID (delete-keyword)")

    args = parser.parse_args()

    # Initialise DB schema (creates tables if they don't exist)
    init_schema()

    COMMANDS[args.command](args)


if __name__ == "__main__":
    main()
