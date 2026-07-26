#!/usr/bin/env python3
"""
CLI tool to add a social-media channel to the harassment tracker.

Supports Facebook pages, Instagram business accounts, and YouTube channels.

Usage examples:
  # Facebook page
  python scripts/add_channel.py --platform facebook --channel-id 123456 --token EAAxxxx

  # Instagram business account
  python scripts/add_channel.py --platform instagram --channel-id 17841400000000000 --token EAAxxxx

  # YouTube channel (API key, read-only)
  python scripts/add_channel.py --platform youtube --channel-id UCxxxxxx --token AIzaSy...

  # YouTube channel (OAuth2 access token, with moderation)
  python scripts/add_channel.py --platform youtube --channel-id UCxxxxxx --token ya29.xxx

Notes:
  - Facebook & Instagram: use a long-lived Page Access Token from Meta Developer portal.
    For Instagram, first retrieve your Instagram Business Account ID:
      GET /{fb-page-id}?fields=instagram_business_account&access_token=...
  - YouTube read-only: use an API key from Google Cloud Console.
  - YouTube moderation: use an OAuth2 access token with youtube.force-ssl scope
    and set YOUTUBE_AUTH_MODE=oauth in your .env file.
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

from src.db.database import SessionLocal, init_schema
from src.db.models import MonitoredChannel, Platform
from src.platforms import get_platform_client

SUPPORTED_PLATFORMS = ["facebook", "instagram", "youtube"]


def main():
    parser = argparse.ArgumentParser(
        description="Add a social-media channel to the harassment tracker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--platform",
        required=True,
        choices=SUPPORTED_PLATFORMS,
        help="Platform to add (facebook | instagram | youtube)",
    )
    parser.add_argument(
        "--channel-id",
        required=True,
        help=(
            "Native platform ID — "
            "Facebook/Instagram: numeric account ID; "
            "YouTube: channel ID starting with UC…"
        ),
    )
    parser.add_argument(
        "--token",
        required=True,
        help="Access token or API key for the platform",
    )
    args = parser.parse_args()

    # ── Validate credentials against the live API ─────────────
    print(f"🔍 Validating credentials for {args.platform} channel {args.channel_id}...")
    client = get_platform_client(args.platform, args.channel_id, args.token)
    try:
        info = client.get_channel_info()
        print(f"✅ Channel found: {info.get('name')} (id={info.get('id')})")
    except Exception as e:
        print(f"❌ Error validating credentials: {e}")
        sys.exit(1)

    # ── Save to database ──────────────────────────────────────
    init_schema()
    db = SessionLocal()
    try:
        existing = db.get(MonitoredChannel, args.channel_id)
        if existing and existing.platform.value == args.platform:
            existing.access_token = args.token
            existing.is_active = True
            db.commit()
            print(f"✅ Updated existing channel: {existing.name} ({args.platform})")
        else:
            channel = MonitoredChannel(
                id=args.channel_id,
                platform=Platform(args.platform),
                name=info.get("name", args.channel_id),
                access_token=args.token,
            )
            db.add(channel)
            db.commit()
            print(f"✅ Added channel: {channel.name} ({args.platform} / {args.channel_id})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
