"""
Abstract base class for all platform clients.
Every platform (Facebook, Instagram, YouTube) must implement this interface.

Normalized data contracts
─────────────────────────
get_channel_info() → {"id": str, "name": str}

get_posts() → list of:
    {"id": str, "message": str, "permalink_url": str, "created_time": str (ISO-8601)}

get_comments(post_id) → list of:
    {
        "id": str,
        "from": {"id": str, "name": str},   # YouTube/Instagram may omit "id"
        "message": str,
        "created_time": str (ISO-8601),
        "is_hidden": bool,
    }
"""
from abc import ABC, abstractmethod


class BasePlatformClient(ABC):
    """Common interface that all platform clients must implement."""

    platform: str  # class-level constant: "facebook" | "instagram" | "youtube"

    # ── Channel / Account info ────────────────────────────────
    @abstractmethod
    def get_channel_info(self) -> dict:
        """Return {"id": ..., "name": ...} for the channel/page/account."""

    # ── Content ───────────────────────────────────────────────
    @abstractmethod
    def get_posts(self, limit: int = 25) -> list[dict]:
        """Return a list of recent posts/videos/media in the normalised schema."""

    @abstractmethod
    def get_comments(self, post_id: str, limit: int = 100) -> list[dict]:
        """Return all comments on a post/video/media in the normalised schema."""

    # ── Moderation ────────────────────────────────────────────
    @abstractmethod
    def hide_comment(self, comment_id: str) -> bool:
        """Hide / hold-for-review a comment. Returns True on success."""

    @abstractmethod
    def unhide_comment(self, comment_id: str) -> bool:
        """Restore a previously hidden comment. Returns True on success."""

    @abstractmethod
    def delete_comment(self, comment_id: str) -> bool:
        """Permanently delete a comment. Returns True on success."""
