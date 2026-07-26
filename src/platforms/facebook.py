"""
Facebook Graph API client.

Uses the Meta Graph API (v19.0+) to fetch posts and comments from a Facebook Page
and to moderate (hide/unhide/delete) comments.

Access token: a long-lived Page Access Token obtained via the Meta Developer portal.
Required permissions: pages_read_engagement, pages_manage_posts,
                      pages_manage_engagement (for hiding comments).
"""
import os
import requests
from loguru import logger
from dotenv import load_dotenv

from src.platforms.base import BasePlatformClient

load_dotenv()

GRAPH_API_VERSION = os.getenv("GRAPH_API_VERSION", "v19.0")
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


class FacebookClient(BasePlatformClient):
    """Wrapper around the Facebook Graph API."""

    platform = "facebook"

    def __init__(self, page_id: str, access_token: str):
        self.page_id = page_id
        self.access_token = access_token

    # ── Internal helpers ──────────────────────────────────────

    def _get(self, endpoint: str, params: dict = None) -> dict:
        params = params or {}
        params["access_token"] = self.access_token
        url = f"{BASE_URL}/{endpoint}" if not endpoint.startswith("http") else endpoint
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _post(self, endpoint: str, data: dict = None) -> dict:
        data = data or {}
        data["access_token"] = self.access_token
        url = f"{BASE_URL}/{endpoint}" if not endpoint.startswith("http") else endpoint
        resp = requests.post(url, data=data, timeout=30)
        resp.raise_for_status()
        return resp.json()

    # ── BasePlatformClient interface ──────────────────────────

    def get_channel_info(self) -> dict:
        """Fetch basic page info — normalised as {"id": ..., "name": ...}."""
        data = self._get(self.page_id, {"fields": "id,name"})
        return {"id": data.get("id"), "name": data.get("name")}

    # Keep the original name as an alias for backward compatibility.
    def get_page_info(self) -> dict:
        return self.get_channel_info()

    def get_posts(self, limit: int = 25) -> list[dict]:
        """Get recent posts from the page in the normalised schema."""
        data = self._get(
            f"{self.page_id}/posts",
            {"fields": "id,message,permalink_url,created_time", "limit": limit},
        )
        posts = data.get("data", [])
        logger.info(f"[Facebook] Fetched {len(posts)} posts from page {self.page_id}")
        return posts  # already matches the normalised schema

    def get_comments(self, post_id: str, limit: int = 100) -> list[dict]:
        """Get all comments on a post, handling pagination."""
        comments = []
        params = {
            "fields": "id,from,message,created_time,is_hidden",
            "limit": limit,
            "filter": "stream",
        }
        endpoint = f"{post_id}/comments"

        while endpoint:
            data = self._get(endpoint, params)
            batch = data.get("data", [])
            comments.extend(batch)
            next_url = data.get("paging", {}).get("next")
            if next_url:
                # Subsequent pages: use the full URL directly (no base prefix)
                resp = requests.get(next_url, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                comments.extend(data.get("data", []))
                endpoint = None  # pagination cursor is embedded in next_url already consumed
            else:
                endpoint = None

        logger.info(f"[Facebook] Fetched {len(comments)} comments from post {post_id}")
        return comments  # already matches the normalised schema

    def hide_comment(self, comment_id: str) -> bool:
        try:
            result = self._post(comment_id, {"is_hidden": "true"})
            success = result.get("success", False)
            if success:
                logger.info(f"[Facebook] Hidden comment {comment_id}")
            return success
        except Exception as e:
            logger.error(f"[Facebook] Failed to hide comment {comment_id}: {e}")
            return False

    def unhide_comment(self, comment_id: str) -> bool:
        try:
            result = self._post(comment_id, {"is_hidden": "false"})
            return result.get("success", False)
        except Exception as e:
            logger.error(f"[Facebook] Failed to unhide comment {comment_id}: {e}")
            return False

    def delete_comment(self, comment_id: str) -> bool:
        try:
            url = f"{BASE_URL}/{comment_id}"
            resp = requests.delete(url, params={"access_token": self.access_token}, timeout=30)
            resp.raise_for_status()
            return resp.json().get("success", False)
        except Exception as e:
            logger.error(f"[Facebook] Failed to delete comment {comment_id}: {e}")
            return False
