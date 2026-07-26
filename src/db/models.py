"""
SQLAlchemy ORM Models for the harassment_tracker schema.

Tables:
  - clients                : Businesses / people using this tracker service
  - platform_app_credentials : Developer app credentials per client per platform
                               (FB App ID/Secret, YT OAuth client ID/secret + tokens)
  - monitored_channels     : Social-media channels being monitored (linked to a client)
  - tracked_posts          : Posts / videos / media on those channels
  - comments               : All fetched comments (harassing + clean)
  - comment_actions        : Actions taken (hidden, reported, etc.)
  - flagged_users          : Users who repeatedly post harassing content
"""
import enum
from datetime import datetime
from sqlalchemy import (
    Column, String, Text, Boolean, DateTime, Integer,
    ForeignKey, Enum as SAEnum, JSON, UniqueConstraint
)
from sqlalchemy.orm import relationship
from src.db.database import Base


# ── Enums ─────────────────────────────────────────────────────

class Platform(str, enum.Enum):
    FACEBOOK  = "facebook"
    INSTAGRAM = "instagram"
    YOUTUBE   = "youtube"


class Language(str, enum.Enum):
    ENGLISH  = "english"
    TAMIL    = "tamil"
    TANGLISH = "tanglish"
    OTHER    = "other"
    UNKNOWN  = "unknown"


class ActionType(str, enum.Enum):
    HIDDEN   = "hidden"
    REPORTED = "reported"
    DELETED  = "deleted"
    REVIEWED = "reviewed"
    IGNORED  = "ignored"


# ── Models ────────────────────────────────────────────────────

class Client(Base):
    """
    A business or individual who has signed up to use the harassment tracker.
    All channels and credentials are linked to a client.
    """
    __tablename__ = "clients"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    name          = Column(String, nullable=False)           # e.g. "Acme Corp"
    contact_email = Column(String)
    phone         = Column(String)
    notes         = Column(Text)
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    credentials = relationship("PlatformAppCredential", back_populates="client",
                               cascade="all, delete-orphan")
    channels    = relationship("MonitoredChannel", back_populates="client")


class PlatformAppCredential(Base):
    """
    Developer app credentials for a client on a specific platform.

    Facebook / Instagram
    ──────────────────────────────────────────────────────────────
    fb_app_id       : Meta App ID  (from developers.facebook.com)
    fb_app_secret   : Meta App Secret
    fb_long_lived_token : Long-lived User Access Token (60-day)
                         Generated from short-lived token using app credentials.

    YouTube
    ──────────────────────────────────────────────────────────────
    yt_client_id     : OAuth2 Client ID   (from console.cloud.google.com)
    yt_client_secret : OAuth2 Client Secret
    yt_access_token  : Short-lived access token (auto-refreshed)
    yt_refresh_token : Long-lived refresh token (does not expire)
    yt_token_expiry  : When the current access token expires
    """
    __tablename__ = "platform_app_credentials"

    id        = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    platform  = Column(SAEnum(Platform), nullable=False)

    # ── Facebook / Instagram ──────────────────────────────────
    fb_app_id           = Column(String)
    fb_app_secret       = Column(Text)
    fb_long_lived_token = Column(Text)   # 60-day user token; used to get page tokens

    # ── YouTube ───────────────────────────────────────────────
    yt_client_id     = Column(String)
    yt_client_secret = Column(Text)
    yt_access_token  = Column(Text)
    yt_refresh_token = Column(Text)
    yt_token_expiry  = Column(DateTime)

    is_active  = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("client_id", "platform", name="uq_cred_client_platform"),
    )

    client = relationship("Client", back_populates="credentials")


class MonitoredChannel(Base):
    """
    A social-media channel / page / account being monitored.
    Each channel belongs to a client and uses the client's stored app credentials.
    """
    __tablename__ = "monitored_channels"

    id        = Column(String, primary_key=True)   # native platform ID
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    platform  = Column(SAEnum(Platform), nullable=False, default=Platform.FACEBOOK)
    name      = Column(String, nullable=False)

    # Channel-level access token (page token for FB/IG; channel token for YT)
    # Derived from the client's PlatformAppCredential at onboarding time.
    access_token = Column(Text, nullable=False)

    is_active  = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("id", "platform", name="uq_channel_platform"),
    )

    client = relationship("Client", back_populates="channels")
    posts  = relationship("TrackedPost", back_populates="channel")


# Keep the old name as an alias so any leftover imports don't break immediately.
MonitoredPage = MonitoredChannel


class TrackedPost(Base):
    """A post / video / media item being monitored for harassing comments."""
    __tablename__ = "tracked_posts"

    id              = Column(String, primary_key=True)
    channel_id      = Column(String, ForeignKey("monitored_channels.id"), nullable=False)
    platform        = Column(SAEnum(Platform), nullable=False)
    message         = Column(Text)
    title           = Column(String)
    permalink       = Column(String)
    created_time    = Column(DateTime)
    last_fetched_at = Column(DateTime)
    is_active       = Column(Boolean, default=True)
    created_at      = Column(DateTime, default=datetime.utcnow)

    # Comment counters — we store only harassing comments in full,
    # but track the total seen so we can report clean vs harassing ratio.
    total_comments_seen = Column(Integer, default=0)   # all comments fetched
    harassing_count     = Column(Integer, default=0)   # harassing only

    channel  = relationship("MonitoredChannel", back_populates="posts")
    comments = relationship("Comment", back_populates="post")


class Comment(Base):
    """A comment fetched from a tracked post/video/media."""
    __tablename__ = "comments"

    id       = Column(String, primary_key=True)
    post_id  = Column(String, ForeignKey("tracked_posts.id"), nullable=False)
    platform = Column(SAEnum(Platform), nullable=False)

    platform_user_id   = Column(String, nullable=False)
    platform_user_name = Column(String)

    message      = Column(Text, nullable=False)
    created_time = Column(DateTime)

    is_harassing      = Column(Boolean, default=False)
    harassment_score  = Column(Integer, default=0)
    detected_language = Column(SAEnum(Language), default=Language.UNKNOWN)
    detection_reasons = Column(JSON)

    is_hidden   = Column(Boolean, default=False)
    is_reviewed = Column(Boolean, default=False)
    fetched_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    post    = relationship("TrackedPost", back_populates="comments")
    actions = relationship("CommentAction", back_populates="comment")


class CommentAction(Base):
    """Audit log of every moderation action taken on a comment."""
    __tablename__ = "comment_actions"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    comment_id   = Column(String, ForeignKey("comments.id"), nullable=False)
    action       = Column(SAEnum(ActionType), nullable=False)
    performed_by = Column(String, default="system")
    notes        = Column(Text)
    performed_at = Column(DateTime, default=datetime.utcnow)

    comment = relationship("Comment", back_populates="actions")


class HarassmentKeyword(Base):
    """
    Keyword / phrase used in offline harassment detection.

    language : tanglish | tamil | english | universal
               'universal' matches regardless of detected language.
    category : body_insult | family_insult | threat | identity_insult |
               intellect_insult | general  (free-form label for UI grouping)
    is_active: set to False to disable without deleting
    """
    __tablename__ = "harassment_keywords"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    keyword    = Column(String, nullable=False)
    language   = Column(String, nullable=False, default="universal")   # tanglish|tamil|english|universal
    category   = Column(String, default="general")
    is_active  = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    notes      = Column(Text)

    __table_args__ = (
        UniqueConstraint("keyword", "language", name="uq_keyword_language"),
    )


class FlaggedUser(Base):
    """Users / accounts flagged for repeated harassment — one row per platform."""
    __tablename__ = "flagged_users"

    platform_user_id   = Column(String, primary_key=True)
    platform           = Column(SAEnum(Platform), primary_key=True)
    platform_user_name = Column(String)

    total_harassing_comments = Column(Integer, default=0)
    first_seen_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at  = Column(DateTime, default=datetime.utcnow)
    is_blocked    = Column(Boolean, default=False)
    notes         = Column(Text)


    total_harassing_comments = Column(Integer, default=0)
    first_seen_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at  = Column(DateTime, default=datetime.utcnow)
    is_blocked    = Column(Boolean, default=False)
    notes         = Column(Text)
