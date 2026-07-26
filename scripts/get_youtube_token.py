#!/usr/bin/env python3
"""
One-time script to generate a YouTube OAuth2 access token.

It will automatically build client_secret.json from your .env if
YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET are set there.

Alternatively you can download client_secret.json manually from:
  Google Cloud Console → APIs & Services → Credentials
  → your OAuth client (harassment-tracker-desktop) → Download JSON

Usage:
  python scripts/get_youtube_token.py

After running:
  - A browser window opens → log in with the YouTube channel owner's account
  - youtube_token.json is saved in the project root (used for all future runs)
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

CLIENT_SECRET_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "client_secret.json")
TOKEN_FILE         = os.path.join(os.path.dirname(os.path.dirname(__file__)), "youtube_token.json")
SCOPES             = ["https://www.googleapis.com/auth/youtube.force-ssl"]


def _build_client_secret_from_env():
    """
    If client_secret.json doesn't exist, build it from
    YOUTUBE_CLIENT_ID + YOUTUBE_CLIENT_SECRET in .env.
    """
    client_id     = os.getenv("YOUTUBE_CLIENT_ID", "")
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET", "")

    if not client_id or client_id == "your_google_client_id_here.apps.googleusercontent.com":
        return False  # Not configured yet

    secret_data = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "project_id": "harassment-tracker",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris": ["http://localhost"]
        }
    }
    with open(CLIENT_SECRET_FILE, "w") as f:
        json.dump(secret_data, f, indent=2)
    print(f"✅  Built client_secret.json from .env credentials")
    return True


def main():
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError:
        print("❌  Missing packages. Run: pip install google-auth-oauthlib")
        sys.exit(1)

    # Check for existing valid token first
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        if creds and creds.valid:
            print("✅  Existing valid token found in youtube_token.json")
            _print_summary(creds)
            return
        if creds and creds.expired and creds.refresh_token:
            print("🔄  Refreshing expired token...")
            creds.refresh(Request())
            _save_token(creds)
            print("✅  Token refreshed successfully!")
            _print_summary(creds)
            return

    # Build client_secret.json from .env if needed
    if not os.path.exists(CLIENT_SECRET_FILE):
        print("🔧  client_secret.json not found — building from .env...")
        if not _build_client_secret_from_env():
            print("\n❌  YOUTUBE_CLIENT_ID is not set in .env!")
            print("\n    Steps to get your Client ID:")
            print("    1. Go to https://console.cloud.google.com")
            print("    2. APIs & Services → Credentials")
            print("    3. Click your 'harassment-tracker-desktop' OAuth client")
            print("    4. Copy the 'Client ID' (ends in .apps.googleusercontent.com)")
            print("    5. Add to .env:  YOUTUBE_CLIENT_ID=<paste here>")
            sys.exit(1)

    # Run OAuth flow — opens browser for user consent
    print("\n🌐  Opening browser for Google login...")
    print("    ➜  Log in with the Google account that OWNS the YouTube channel.\n")
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)

    _save_token(creds)
    print("\n✅  Authentication successful!")
    _print_summary(creds)


def _save_token(creds):
    with open(TOKEN_FILE, "w") as f:
        f.write(creds.to_json())
    print(f"💾  Token saved → {TOKEN_FILE}")


def _print_summary(creds):
    print("\n" + "=" * 60)
    print("  youtube_token.json is ready.")
    print("  Your .env already has YOUTUBE_AUTH_MODE=oauth")
    print("  Now add your YouTube channel:")
    print()
    print("  python scripts/add_channel.py \\")
    print("    --platform youtube \\")
    print("    --channel-id UCxxxxxxxxxxxxxxxxxx \\")
    print(f"    --token {creds.token[:30]}...")
    print("=" * 60)


if __name__ == "__main__":
    main()



def main():
    if not os.path.exists(CLIENT_SECRET_FILE):
        print("❌  client_secret.json not found!")
        print("    Download it from Google Cloud Console:")
        print("    APIs & Services → Credentials → your OAuth client → Download JSON")
        print(f"    Save it as: {CLIENT_SECRET_FILE}")
        sys.exit(1)

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.oauth2.credentials import Credentials
    except ImportError:
        print("❌  Missing packages. Run: pip install google-auth-oauthlib")
        sys.exit(1)

    # Check for existing saved token
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        if creds and creds.valid:
            print("✅  Existing valid token found in youtube_token.json")
            _print_env_instructions(creds)
            return
        # Try to refresh
        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
            _save_token(creds)
            print("✅  Token refreshed successfully!")
            _print_env_instructions(creds)
            return

    # Run OAuth flow — opens browser
    print("🌐  Opening browser for Google login...")
    print("    Log in with the Google account that OWNS the YouTube channel.\n")
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)

    _save_token(creds)
    print("\n✅  Authentication successful!")
    _print_env_instructions(creds)


def _save_token(creds):
    with open(TOKEN_FILE, "w") as f:
        f.write(creds.to_json())
    print(f"💾  Token saved to: {TOKEN_FILE}")


def _print_env_instructions(creds):
    print("\n" + "="*60)
    print("Add these to your .env file:")
    print("="*60)
    print(f"YOUTUBE_AUTH_MODE=oauth")
    print(f"YOUTUBE_ACCESS_TOKEN={creds.token}")
    if creds.refresh_token:
        print(f"YOUTUBE_REFRESH_TOKEN={creds.refresh_token}")
    print("="*60)
    print("\nOr use the saved youtube_token.json directly in your code.")


if __name__ == "__main__":
    main()
