"""
YouTube Data API v3 client.

Uses google-api-python-client to fetch videos and comments from a YouTube channel
and to moderate (hide/delete) comments.

Auth flow:
  - For public comment reading: an API Key is sufficient.
  - For hiding/deleting comments: OAuth2 with the channel owner's credentials is required.
  - The `access_token` field in MonitoredChannel stores either:
      * A plain API key (read-only mode), OR
      * An OAuth2 access token (moderation mode).
    Set YOUTUBE_AUTH_MODE=oauth in .env to enable moderation.

Required scopes (OAuth2):
  https://www.googleapis.com/auth/youtube.force-ssl

API reference: https://developers.google.com/youtube/v3/docs
"""
import os
from loguru import logger
from dotenv import load_dotenv

from src.platforms.base import BasePlatformClient

load_dotenv()

YOUTUBE_AUTH_MODE   = os.getenv("YOUTUBE_AUTH_MODE", "apikey")   # "apikey" | "oauth"
YOUTUBE_TOKEN_FILE  = os.getenv("YOUTUBE_TOKEN_FILE", "youtube_token.json")
SCOPES              = ["https://www.googleapis.com/auth/youtube.force-ssl"]


def _build_youtube_service(access_token: str):
    """Build the googleapiclient YouTube service object."""
    try:
        from googleapiclient.discovery import build
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError:
        raise ImportError(
            "google-api-python-client and google-auth are required for YouTube support. "
            "Run: pip install google-api-python-client google-auth"
        )

    # Auto-detect token type:
    # OAuth2 access tokens always start with "ya29."
    # API keys typically start with "AIza"
    is_oauth_token = access_token.startswith("ya29.")
    use_oauth = YOUTUBE_AUTH_MODE == "oauth" or is_oauth_token

    if use_oauth:
        # Prefer saved token file (auto-refreshes) over raw access token
        if os.path.exists(YOUTUBE_TOKEN_FILE):
            creds = Credentials.from_authorized_user_file(YOUTUBE_TOKEN_FILE, SCOPES)
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(YOUTUBE_TOKEN_FILE, "w") as f:
                    f.write(creds.to_json())
        else:
            creds = Credentials(token=access_token)
        return build("youtube", "v3", credentials=creds)
    else:
        # API key — read-only, no moderation
        return build("youtube", "v3", developerKey=access_token)


class YouTubeClient(BasePlatformClient):
    """
    Wrapper around the YouTube Data API v3.

    channel_id:   YouTube Channel ID (starts with "UC…")
    access_token: API key (read-only) or OAuth2 access token (moderation).
    """

    platform = "youtube"

    def __init__(self, channel_id: str, access_token: str):
        self.channel_id = channel_id
        self.access_token = access_token
        self._service = None  # lazy-init

    def _svc(self):
        """Lazily initialise the Google API client service."""
        if self._service is None:
            self._service = _build_youtube_service(self.access_token)
        return self._service

    # ── BasePlatformClient interface ──────────────────────────

    def get_channel_info(self) -> dict:
        """Return {"id": ..., "name": ...} for the YouTube channel."""
        resp = (
            self._svc()
            .channels()
            .list(part="snippet", id=self.channel_id)
            .execute()
        )
        items = resp.get("items", [])
        if not items:
            raise ValueError(f"Channel not found: {self.channel_id}")
        snippet = items[0]["snippet"]
        return {"id": self.channel_id, "name": snippet.get("title", self.channel_id)}

    def get_posts(self, limit: int = 25) -> list[dict]:
        """
        Fetch recent videos uploaded to the channel.
        Normalised to the common schema.
        """
        # First, get the uploads playlist ID
        ch_resp = (
            self._svc()
            .channels()
            .list(part="contentDetails", id=self.channel_id)
            .execute()
        )
        items = ch_resp.get("items", [])
        if not items:
            return []
        uploads_playlist = (
            items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        )

        # Then fetch videos from that playlist
        pl_resp = (
            self._svc()
            .playlistItems()
            .list(
                part="snippet",
                playlistId=uploads_playlist,
                maxResults=min(limit, 50),
            )
            .execute()
        )

        posts = []
        for item in pl_resp.get("items", []):
            snip = item["snippet"]
            video_id = snip["resourceId"]["videoId"]
            posts.append({
                "id": video_id,
                "message": snip.get("description", ""),         # normalised
                "permalink_url": f"https://www.youtube.com/watch?v={video_id}",
                "created_time": snip.get("publishedAt", ""),    # normalised
                "title": snip.get("title", ""),
            })

        logger.info(f"[YouTube] Fetched {len(posts)} videos from channel {self.channel_id}")
        return posts

    def get_comments(self, post_id: str, limit: int = 100) -> list[dict]:
        """
        Fetch top-level comments (commentThreads) for a video.
        Normalised to the common schema.
        NOTE: YouTube does not support hiding — only holding (OAuth) or deleting.
        """
        comments = []
        page_token = None

        while len(comments) < limit:
            kwargs = {
                "part": "snippet",
                "videoId": post_id,
                "maxResults": min(100, limit - len(comments)),
                "textFormat": "plainText",
            }
            if page_token:
                kwargs["pageToken"] = page_token

            try:
                resp = self._svc().commentThreads().list(**kwargs).execute()
            except Exception as e:
                logger.error(f"[YouTube] Failed to fetch comments for video {post_id}: {e}")
                break

            for thread in resp.get("items", []):
                top = thread["snippet"]["topLevelComment"]["snippet"]
                comments.append({
                    "id": thread["snippet"]["topLevelComment"]["id"],
                    "from": {
                        "id": top.get("authorChannelId", {}).get("value", "unknown"),
                        "name": top.get("authorDisplayName", ""),
                    },
                    "message": top.get("textDisplay", ""),
                    "created_time": top.get("publishedAt", ""),
                    "is_hidden": False,  # YouTube doesn't expose a hidden flag in API
                })

            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        logger.info(f"[YouTube] Fetched {len(comments)} comments from video {post_id}")
        return comments

    def hide_comment(self, comment_id: str) -> bool:
        """
        Set a comment to 'heldForReview' (equivalent of hiding on YouTube).
        Requires OAuth2 with youtube.force-ssl scope.
        """
        if YOUTUBE_AUTH_MODE != "oauth":
            logger.warning("[YouTube] hide_comment requires OAuth2 mode (YOUTUBE_AUTH_MODE=oauth)")
            return False
        try:
            self._svc().comments().setModerationStatus(
                id=comment_id,
                moderationStatus="heldForReview",
            ).execute()
            logger.info(f"[YouTube] Held comment {comment_id} for review")
            return True
        except Exception as e:
            logger.error(f"[YouTube] Failed to hold comment {comment_id}: {e}")
            return False

    def unhide_comment(self, comment_id: str) -> bool:
        """
        Approve (publish) a previously held comment.
        Requires OAuth2 with youtube.force-ssl scope.
        """
        if YOUTUBE_AUTH_MODE != "oauth":
            logger.warning("[YouTube] unhide_comment requires OAuth2 mode (YOUTUBE_AUTH_MODE=oauth)")
            return False
        try:
            self._svc().comments().setModerationStatus(
                id=comment_id,
                moderationStatus="published",
            ).execute()
            logger.info(f"[YouTube] Published comment {comment_id}")
            return True
        except Exception as e:
            logger.error(f"[YouTube] Failed to publish comment {comment_id}: {e}")
            return False

    def delete_comment(self, comment_id: str) -> bool:
        """
        Permanently delete a comment.
        Requires OAuth2 with youtube.force-ssl scope.
        """
        if YOUTUBE_AUTH_MODE != "oauth":
            logger.warning("[YouTube] delete_comment requires OAuth2 mode (YOUTUBE_AUTH_MODE=oauth)")
            return False
        try:
            self._svc().comments().delete(id=comment_id).execute()
            logger.info(f"[YouTube] Deleted comment {comment_id}")
            return True
        except Exception as e:
            logger.error(f"[YouTube] Failed to delete comment {comment_id}: {e}")
            return False
