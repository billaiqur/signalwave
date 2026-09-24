"""
Database connection and session management.
Uses SQLAlchemy with PostgreSQL.
"""
import os
from urllib.parse import quote_plus
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

POSTGRES_HOST     = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT     = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB       = os.getenv("POSTGRES_DB", "harassment_db")
POSTGRES_USER     = os.getenv("POSTGRES_USER", "tracker_user")
POSTGRES_PASSWORD = quote_plus(os.getenv("POSTGRES_PASSWORD", ""))  # URL-encode special chars
POSTGRES_SCHEMA   = os.getenv("POSTGRES_SCHEMA", "harassment_tracker")

DATABASE_URL = (
    f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    f"?options=-csearch_path%3D{POSTGRES_SCHEMA}&sslmode=require"
)

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Dependency for FastAPI — yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_schema():
    """Create the schema if it doesn't exist, then create all tables."""
    # Import ALL models here so their tables are registered on Base.metadata
    import src.db.models  # noqa: F401 — side-effect import registers all ORM classes
    with engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {POSTGRES_SCHEMA}"))
        conn.commit()
    Base.metadata.create_all(bind=engine)

    # ── Safe column migrations (ADD COLUMN IF NOT EXISTS) ─────
    _run_migrations()

    logger.info(f"Database schema '{POSTGRES_SCHEMA}' and tables initialised.")
    _seed_keywords()


def _run_migrations():
    """Add new columns to existing tables without dropping data."""
    migrations = [
        # monitored_channels: schedule fields added in Phase 2
        f"ALTER TABLE {POSTGRES_SCHEMA}.monitored_channels ADD COLUMN IF NOT EXISTS scan_interval_hours INTEGER",
        f"ALTER TABLE {POSTGRES_SCHEMA}.monitored_channels ADD COLUMN IF NOT EXISTS last_scanned_at TIMESTAMP",
        # users: youtube connection ID
        f"ALTER TABLE {POSTGRES_SCHEMA}.users ADD COLUMN IF NOT EXISTS youtube_id VARCHAR",
    ]
    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
            except Exception as e:
                logger.warning(f"Migration skipped ({e}): {sql[:60]}")
        conn.commit()
    logger.debug("Column migrations applied.")


def _seed_keywords():
    """
    Populate harassment_keywords with the built-in starter list if the table is empty.
    This only runs once — once you add keywords via manage.py, it won't overwrite them.
    """
    from src.db.models import HarassmentKeyword  # late import to avoid circular
    db = SessionLocal()
    try:
        if db.query(HarassmentKeyword).count() > 0:
            return  # already seeded

        seed = [
            # ── Tanglish (Tamil in Latin script) ──────────────────
            ("otha",         "tanglish", "body_insult"),
            ("oothu",        "tanglish", "body_insult"),
            ("punda",        "tanglish", "body_insult"),
            ("pundai",       "tanglish", "body_insult"),
            ("sunni",        "tanglish", "body_insult"),
            ("koothi",       "tanglish", "body_insult"),
            ("lavada",       "tanglish", "body_insult"),
            ("lavde",        "tanglish", "body_insult"),
            ("poolu",        "tanglish", "body_insult"),
            ("sootha",       "tanglish", "body_insult"),
            ("myiru",        "tanglish", "body_insult"),
            ("thool",        "tanglish", "body_insult"),
            ("thevdiya",     "tanglish", "identity_insult"),
            ("thevidiya",    "tanglish", "identity_insult"),
            ("thayoli",      "tanglish", "family_insult"),
            ("thayir",       "tanglish", "family_insult"),
            ("paiyan",       "tanglish", "family_insult"),
            ("naaye",        "tanglish", "identity_insult"),
            ("naye",         "tanglish", "identity_insult"),
            ("naai",         "tanglish", "identity_insult"),
            ("naai payan",   "tanglish", "identity_insult"),
            ("loosu",        "tanglish", "intellect_insult"),
            ("baadu",        "tanglish", "intellect_insult"),
            ("kazhuthai",    "tanglish", "intellect_insult"),
            ("kazhutha",     "tanglish", "intellect_insult"),
            ("vennai",       "tanglish", "intellect_insult"),
            ("thikku",       "tanglish", "intellect_insult"),
            ("kena",         "tanglish", "intellect_insult"),
            ("pattai",       "tanglish", "intellect_insult"),
            ("seththu po",   "tanglish", "threat"),
            ("sethu po",     "tanglish", "threat"),
            ("saagu",        "tanglish", "threat"),
            ("thala vettu",  "tanglish", "threat"),
            # ── Tamil Unicode ──────────────────────────────────────
            ("ஓத்த",         "tamil",    "body_insult"),
            ("ஊத்து",        "tamil",    "body_insult"),
            ("புண்ட",        "tamil",    "body_insult"),
            ("புண்டை",       "tamil",    "body_insult"),
            ("சுன்னி",       "tamil",    "body_insult"),
            ("கூத்தி",       "tamil",    "body_insult"),
            ("தேவடிய",       "tamil",    "identity_insult"),
            ("நாயே",         "tamil",    "identity_insult"),
            ("கழுதை",        "tamil",    "intellect_insult"),
            ("மயிர்",        "tamil",    "body_insult"),
            ("தாயோலி",       "tamil",    "family_insult"),
            ("பைத்தியம்",    "tamil",    "intellect_insult"),
            ("வெண்ணை",      "tamil",    "intellect_insult"),
            ("செத்துபோ",     "tamil",    "threat"),
            ("தலை வெட்டு",  "tamil",    "threat"),
            # ── English ───────────────────────────────────────────
            ("idiot",            "english", "intellect_insult"),
            ("stupid",           "english", "intellect_insult"),
            ("moron",            "english", "intellect_insult"),
            ("loser",            "english", "intellect_insult"),
            ("retard",           "english", "intellect_insult"),
            ("die",              "english", "threat"),
            ("kill yourself",    "english", "threat"),
            ("kys",              "english", "threat"),
            ("go kill",          "english", "threat"),
            ("shut up",          "english", "general"),
            ("shut your",        "english", "general"),
            ("f*** you",         "english", "general"),
            ("fk you",           "english", "general"),
            ("b****",            "english", "body_insult"),
            ("bitch",            "english", "body_insult"),
            ("a**hole",          "english", "body_insult"),
            ("asshole",          "english", "body_insult"),
            ("trash",            "english", "general"),
            ("scum",             "english", "general"),
            ("disgusting",       "english", "general"),
            ("piece of shit",    "english", "general"),
            ("ugly",             "english", "general"),
            ("fat",              "english", "general"),
            ("hate you",         "english", "general"),
            ("go to hell",       "english", "threat"),
            ("pathetic",         "english", "general"),
            ("worthless",        "english", "general"),
            ("useless",          "english", "general"),
            ("garbage",          "english", "general"),
            ("terrorist",        "english", "threat"),
            ("threat",           "english", "threat"),
        ]

        for kw, lang, cat in seed:
            db.add(HarassmentKeyword(keyword=kw, language=lang, category=cat,
                                     notes="seeded from built-in list"))
        db.commit()
        logger.info(f"Seeded {len(seed)} harassment keywords into the database.")
    except Exception as e:
        db.rollback()
        logger.warning(f"Keyword seeding failed (non-fatal): {e}")
    finally:
        db.close()
