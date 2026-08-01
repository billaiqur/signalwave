# SignalWave — Social Media Harassment Tracker

Monitors **Facebook pages**, **Instagram business accounts**, and **YouTube channels** for harassing comments in **English**, **Tamil**, and **Tanglish**.
Stores everything in PostgreSQL, flags repeat offenders, and can automatically hide or delete flagged comments via each platform''s API.

---

## Architecture

```
Facebook Graph API  ─┐
Instagram Graph API ─┼──► src/platforms/          ← unified platform clients
YouTube Data API v3 ─┘         │
                                ▼
                    src/detection/detector.py      ← keyword match + AI (GPT-4o / Gemini / Ollama)
                                │
                                ▼
                    src/tracker.py                 ← fetch → detect → save → hide
                                │
                                ▼
                    PostgreSQL (schema: harassment_tracker)
                                │
                                ▼
                    api/main.py (FastAPI)          ← REST API for React frontend
```

---

## Quick Start

### 1. Clone and create virtual environment
```bash
git clone https://github.com/billaiqur/signalwave.git
cd signalwave
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac/Linux
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure environment
```bash
copy .env.example .env
# Edit .env — database connection, AI provider, YouTube auth mode
```

### 4. Add a client and credentials
```bash
python scripts/manage.py add-client
python scripts/manage.py add-credentials --client-id 1 --platform facebook
python scripts/manage.py add-credentials --client-id 1 --platform youtube
```

### 5. Add channels to monitor
```bash
python scripts/manage.py add-channel --client-id 1 --platform facebook
python scripts/manage.py add-channel --client-id 1 --platform youtube
```

### 6. Run the tracker
```bash
python scripts/manage.py run-tracker
```

### 7. Start the API server
```bash
uvicorn api.main:app --reload --port 8001
```
Then open: http://localhost:8001/docs

### 8. Start the auto-scheduler
```bash
python scheduler.py
```

---

## Project Structure

```
signalwave/
├── api/
│   └── main.py                  ← FastAPI REST API
├── scripts/
│   ├── manage.py                ← Unified CLI (clients, channels, keywords, tracker)
│   ├── moderate_comments.py     ← Moderate comments (delete/hide) by ID / post / user
│   └── test_youtube.py          ← Test YouTube channel fetch + detection
├── src/
│   ├── platforms/
│   │   ├── base.py              ← Abstract BasePlatformClient
│   │   ├── facebook.py          ← Facebook Graph API client
│   │   ├── instagram.py         ← Instagram Graph API client (via Meta)
│   │   └── youtube.py           ← YouTube Data API v3 client (OAuth2)
│   ├── db/
│   │   ├── database.py          ← SQLAlchemy engine, session, schema init + keyword seed
│   │   └── models.py            ← ORM models
│   ├── detection/
│   │   └── detector.py          ← Multi-language harassment detection engine
│   └── tracker.py               ← Orchestration: fetch → detect → save → hide
├── scheduler.py                 ← APScheduler polling loop
├── requirements.txt
├── .env.example
└── README.md
```

---

## Database Schema (`harassment_tracker`)

| Table | Purpose |
|-------|---------|
| `clients` | Businesses / people using the tracker |
| `platform_app_credentials` | Developer app credentials per client per platform |
| `monitored_channels` | Channels / pages / accounts being monitored |
| `tracked_posts` | Posts, videos, or media on those channels |
| `comments` | Harassing comments with scores and detection details |
| `comment_actions` | Audit log of hide / delete / report actions |
| `flagged_users` | Users with repeated harassment (composite PK: user_id + platform) |
| `harassment_keywords` | Keyword list loaded by the detector (DB-managed, not hardcoded) |

---

## Supported Platforms

| Platform | Fetch | Hide | Delete | Notes |
|----------|-------|------|--------|-------|
| **Facebook** | ✅ | ✅ | ✅ | Long-lived Page Access Token |
| **Instagram** | ✅ | ✅ | ✅ | Page token of linked Facebook Page; no numeric user IDs |
| **YouTube** | ✅ | ✅ | ✅ | OAuth2 required for moderation; token auto-refreshed from DB |

---

## Detection Engine

1. **Keyword scan** (offline, instant) — checks the `harassment_keywords` DB table
2. **AI scoring** — sends the comment to the configured LLM with a Tamil/Tanglish-aware system prompt

### AI Providers (set `AI_PROVIDER` in `.env`)

| Provider | Model | Env vars needed |
|----------|-------|-----------------|
| `openai` *(default)* | `gpt-4o` | `OPENAI_API_KEY` |
| `gemini` | `gemini-2.0-flash` | `GEMINI_API_KEY` |
| `ollama` | `llama3.3` (local) | Ollama running on `localhost:11434` |

### Manage keywords via CLI
```bash
python scripts/manage.py list-keywords
python scripts/manage.py add-keyword
python scripts/manage.py delete-keyword --keyword-id 5
```

---

## Moderation CLI

```bash
python scripts/moderate_comments.py --list
python scripts/moderate_comments.py --comment-id <id>
python scripts/moderate_comments.py --post-id <id>
python scripts/moderate_comments.py --user-id <id> --action hide
python scripts/moderate_comments.py --all --platform youtube --dry-run
```

---

## Environment Variables

Copy `.env.example` to `.env` — **never commit `.env`**.

| Variable | Description |
|----------|-------------|
| `POSTGRES_HOST/PORT/DB/USER/PASSWORD` | PostgreSQL connection |
| `POSTGRES_SCHEMA` | Schema name (default: `harassment_tracker`) |
| `AUTO_HIDE_COMMENTS` | `true` to auto-hide detected harassment |
| `POLL_INTERVAL_SECONDS` | Scheduler interval (default: 300) |
| `AI_PROVIDER` | `openai` / `gemini` / `ollama` |
| `OPENAI_API_KEY` | OpenAI API key |
| `OPENAI_MODEL` | Model name (default: `gpt-4o`) |
| `GEMINI_API_KEY` | Google Gemini API key |
| `YOUTUBE_AUTH_MODE` | `oauth` (required for moderation) |
| `GRAPH_API_VERSION` | Meta API version (default: `v19.0`) |
