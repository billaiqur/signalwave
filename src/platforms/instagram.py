"""
Instagram Graph API client.

Instagram is accessed via the SAME Meta Graph API as Facebook.
You need a Facebook App connected to an Instagram Professional account
(Business or Creator) through the Meta Developer portal.

Token flow:
  1. User grants permissions via Facebook Login / Meta Business Suite.
  2. Exchange for a long-lived User Access Token.
  3. Retrieve the connected Instagram Business Account ID.
  4. Use that account ID + the token here.

Required permissions:
  instagram_basic, instagram_manage_comments,
  instagram_manage_insights, pages_show_list

API reference: https://developers.facebook.com/docs/instagram-api
"""
import os
import requests
from loguru import logger
from dotenv import load_dotenv

from src.platforms.base import BasePlatformClient

load_dotenv()

GRAPH_API_VERSION = os.getenv("GRAPH_API_VERSION", "v19.0")
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


class InstagramClient(BasePlatformClient):
    """
    Wrapper around the Instagram Graph API (via Meta).

    channel_id : Instagram Business Account ID (NOT the @username).
                 Retrieve it with:
                   GET /{page-id}?fields=instagram_business_account&access_token=...
    access_token: Page Access Token of the linked Facebook Page.
    """

    platform = "instagram"

    def __init__(self, channel_id: str, access_token: str):
        self.channel_id = channel_id
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
        """Return {"id": ..., "name": ...} for the Instagram business account."""
        data = self._get(self.channel_id, {"fields": "id,name,username"})
        return {
            "id": data.get("id"),
            "name": data.get("name") or data.get("username", self.channel_id),
        }

    def get_posts(self, limit: int = 25) -> list[dict]:
        """
        Fetch recent media (posts/reels/stories) for the account.
        Normalised to the common schema with message → caption.
        """
        data = self._get(
            f"{self.channel_id}/media",
            {
                "fields": "id,caption,permalink,timestamp,media_type",
                "limit": limit,
            },
        )
        posts = []
        for item in data.get("data", []):
            posts.append({
                "id": item["id"],
                "message": item.get("caption", ""),          # normalised field name
                "permalink_url": item.get("permalink", ""),  # normalised field name
                "created_time": item.get("timestamp", ""),   # normalised field name
                "media_type": item.get("media_type", ""),
            })
        logger.info(f"[Instagram] Fetched {len(posts)} media from account {self.channel_id}")
        return posts

    def get_comments(self, post_id: str, limit: int = 100) -> list[dict]:
        """
        Fetch all comments on an Instagram media object.
        NOTE: Instagram does NOT expose commenter's user_id for privacy reasons;
              only the username is available.
        """
        comments = []
        params = {
            "fields": "id,username,text,timestamp,hidden",
            "limit": limit,
        }
        endpoint = f"{post_id}/comments"

        while endpoint:
            data = self._get(endpoint, params)
            for item in data.get("data", []):
                comments.append({
                    "id": item["id"],
                    "from": {
                        "id": item.get("username", "unknown"),  # IG has no numeric user ID here
                        "name": item.get("username", ""),
                    },
                    "message": item.get("text", ""),
                    "created_time": item.get("timestamp", ""),
                    "is_hidden": item.get("hidden", False),
                })
            next_url = data.get("paging", {}).get("next")
            endpoint = next_url if next_url else None
            params = {}  # params are embedded in the cursor URL

        logger.info(f"[Instagram] Fetched {len(comments)} comments from media {post_id}")
        return comments

    def hide_comment(self, comment_id: str) -> bool:
        """
        Hide an Instagram comment using the Graph API.
        Requires: instagram_manage_comments permission.
        """
        try:
            result = self._post(comment_id, {"hide": "true"})
            success = result.get("success", False)
            if success:
                logger.info(f"[Instagram] Hidden comment {comment_id}")
            return success
        except Exception as e:
            logger.error(f"[Instagram] Failed to hide comment {comment_id}: {e}")
            return False

    def unhide_comment(self, comment_id: str) -> bool:
        try:
            result = self._post(comment_id, {"hide": "false"})
            return result.get("success", False)
        except Exception as e:
            logger.error(f"[Instagram] Failed to unhide comment {comment_id}: {e}")
            return False

    def delete_comment(self, comment_id: str) -> bool:
        """
        Permanently delete an Instagram comment.
        Requires: instagram_manage_comments permission.
        """
        try:
            url = f"{BASE_URL}/{comment_id}"
            resp = requests.delete(url, params={"access_token": self.access_token}, timeout=30)
            resp.raise_for_status()
            return resp.json().get("success", False)
        except Exception as e:
            logger.error(f"[Instagram] Failed to delete comment {comment_id}: {e}")
            return False
