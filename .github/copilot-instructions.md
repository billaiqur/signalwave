# Social Media Harassment Tracker — Copilot Instructions

## Project Overview
Python backend that monitors **Facebook pages, Instagram business accounts, and YouTube channels**
for harassing comments in English, Tamil, and Tanglish.
Stores everything in PostgreSQL under the `harassment_tracker` schema.
FastAPI REST API exposes data for a React frontend (Step 2).

## Tech Stack
- Python 3.11+
- FastAPI + Uvicorn
- SQLAlchemy 2.x + PostgreSQL (psycopg2)
- **Facebook & Instagram**: Meta Graph API (v19.0) — same base URL, different endpoints
- **YouTube**: Google Data API v3 (google-api-python-client + google-auth)
- OpenAI GPT-4o (optional — for AI-powered detection)
- APScheduler (polling scheduler)
- langdetect (language detection)

## Platform Integration Notes
- **Facebook**: Long-lived Page Access Token. Permissions: `pages_read_engagement`,
  `pages_manage_posts`, `pages_manage_engagement`.
- **Instagram**: Same Meta Graph API. Requires a connected Instagram Business Account.
  Token: Page Access Token of the linked Facebook Page.
  Permissions: `instagram_basic`, `instagram_manage_comments`.
  Note: Instagram does NOT expose numeric user IDs for commenters — only usernames.
- **YouTube**: API key (read-only) or OAuth2 access token (moderation).
  Set `YOUTUBE_AUTH_MODE=oauth` in `.env` for hide/delete. Scope: `youtube.force-ssl`.
  "Hiding" on YouTube = setting comment to `heldForReview`.

## Key Files
- `src/platforms/base.py`       — Abstract `BasePlatformClient` interface
- `src/platforms/facebook.py`   — Facebook Graph API client
- `src/platforms/instagram.py`  — Instagram Graph API client (via Meta)
- `src/platforms/youtube.py`    — YouTube Data API v3 client
- `src/platforms/__init__.py`   — `get_platform_client()` factory
- `src/facebook/client.py`      — Backward-compat shim (re-exports FacebookClient)
- `src/db/database.py`          — SQLAlchemy engine, session, schema init
- `src/db/models.py`            — ORM models (MonitoredChannel, TrackedPost, Comment,
                                  CommentAction, FlaggedUser, Platform enum)
- `src/detection/detector.py`   — Harassment detection (keywords + AI)
- `src/tracker.py`              — Main orchestration: fetch → detect → save → hide
- `api/main.py`                 — FastAPI REST API
- `scheduler.py`                — APScheduler polling loop
- `scripts/add_channel.py`      — CLI tool to add channels (all platforms)

## Coding Rules
- All platform clients must extend `BasePlatformClient` and implement its interface
- All DB access via SQLAlchemy ORM (no raw SQL except schema creation)
- Use `loguru` for all logging; prefix log messages with `[Facebook]`, `[Instagram]`, `[YouTube]`
- Use `pydantic-settings` for config when needed
- Schema is always `harassment_tracker` (configurable via `.env`)
- Access tokens must NEVER be logged
- Detection keywords live in `src/detection/detector.py`
- `MonitoredPage` is an alias for `MonitoredChannel` (kept for backward compat)
- `FlaggedUser` uses a composite PK: `(platform_user_id, platform)`

