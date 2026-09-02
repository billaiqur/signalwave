"""
Multi-platform client package.
Supports Facebook, Instagram (via Meta Graph API), and YouTube.
"""
from src.platforms.base import BasePlatformClient
from src.platforms.facebook import FacebookClient
from src.platforms.instagram import InstagramClient
from src.platforms.youtube import YouTubeClient


def get_platform_client(platform: str, channel_id: str, access_token: str) -> BasePlatformClient:
    """
    Factory — returns the correct platform client based on the platform string.

    Args:
        platform:      "facebook" | "instagram" | "youtube"
        channel_id:    Native platform ID (page ID / IG business account ID / YT channel ID)
        access_token:  Page/User access token (Facebook & Instagram) or OAuth2 token (YouTube)
    """
    platform = platform.lower()
    if platform == "facebook":
        return FacebookClient(channel_id, access_token)
    elif platform == "instagram":
        return InstagramClient(channel_id, access_token)
    elif platform == "youtube":
        return YouTubeClient(channel_id, access_token)
    else:
        raise ValueError(f"Unsupported platform: '{platform}'. Choose from: facebook, instagram, youtube")


__all__ = [
    "BasePlatformClient",
    "FacebookClient",
    "InstagramClient",
    "YouTubeClient",
    "get_platform_client",
]
