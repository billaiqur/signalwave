#!/usr/bin/env python3
"""
Quick script to add a Facebook page to the monitoring list.

Usage:
  python scripts/add_page.py --page-id 123456 --token EAAxxxx...
"""
import argparse
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

from src.db.database import SessionLocal, init_schema
from src.db.models import MonitoredPage
from src.facebook.client import FacebookClient


def main():
    parser = argparse.ArgumentParser(description="Add a Facebook page to monitor")
    parser.add_argument("--page-id", required=True, help="Facebook Page ID")
    parser.add_argument("--token", required=True, help="Page Access Token")
    args = parser.parse_args()

    init_schema()
    client = FacebookClient(args.page_id, args.token)

    print(f"Validating token for page {args.page_id}...")
    try:
        info = client.get_page_info()
        print(f"✅ Page found: {info.get('name')}")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

    db = SessionLocal()
    existing = db.get(MonitoredPage, args.page_id)
    if existing:
        existing.access_token = args.token
        existing.is_active = True
        db.commit()
        print(f"✅ Updated existing page: {existing.name}")
    else:
        page = MonitoredPage(
            id=args.page_id,
            name=info.get("name", args.page_id),
            access_token=args.token,
        )
        db.add(page)
        db.commit()
        print(f"✅ Added page: {page.name} ({page.id})")
    db.close()


if __name__ == "__main__":
    main()
