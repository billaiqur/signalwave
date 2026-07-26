"""
Multi-platform client package.
Supports Facebook, Instagram (via Meta Graph API), and YouTube.

Credentials are loaded from the database (platform_credentials + channel_tokens),
NOT from environment variables.
"""
from src.platforms.base import BasePlatformClient
from src.platforms.facebook import FacebookClient
from src.platforms.instagram import InstagramClient
from src.platforms.youtube import YouTubeClient


def get_platform_client(platform: str, channel_id: str, access_token: str) -> BasePlatformClient:
    """
    Simple factory — used internally by the tracker with a token already resolved.

    For new channel setup use get_client_from_db() which loads everything from DB.
    """
    platform = platform.lower()
    if platform == "facebook":
        return FacebookClient(channel_id, access_token)
    elif platform == "instagram":
        return InstagramClient(channel_id, access_token)
    elif platform == "youtube":
        return YouTubeClient(channel_id, access_token)
    else:
        raise ValueError(f"Unsupported platform: '{platform}'. Choose: facebook, instagram, youtube")


def get_client_from_db(channel, db_session) -> BasePlatformClient:
    """
    Build the correct platform client for a MonitoredChannel by loading
    credentials from the database (ChannelToken + PlatformCredential).

    Priority:
      1. channel_tokens row  → freshest token (auto-refreshed for YouTube)
      2. channel.access_token → fallback cached token
    """
    from src.db.models import ChannelToken, PlatformCredential

    platform = channel.platform.value

    # Load the stored token for this channel
    token_row: ChannelToken | None = db_session.get(ChannelToken, channel.id) \
        if hasattr(channel, "token") else None
    if channel.token:
        token_row = channel.token

    if platform == "youtube":
        # YouTube needs the full credential (client_id + client_secret) for token refresh
        cred = None
        if channel.client_id:
            cred = (
                db_session.query(PlatformCredential)
                .filter_by(client_id=channel.client_id, platform="youtube", is_active=True)
                .first()
            )
        return YouTubeClient(
            channel_id=channel.id,
            access_token=token_row.access_token if token_row else channel.access_token,
            refresh_token=token_row.refresh_token if token_row else None,
            token_expiry=token_row.token_expiry if token_row else None,
            yt_client_id=cred.yt_client_id if cred else None,
            yt_client_secret=cred.yt_client_secret if cred else None,
            db_session=db_session,
            token_row=token_row,
        )
    elif platform == "facebook":
        return FacebookClient(
            channel.id,
            token_row.access_token if token_row else channel.access_token,
        )
    elif platform == "instagram":
        return InstagramClient(
            channel.id,
            token_row.access_token if token_row else channel.access_token,
        )
    else:
        raise ValueError(f"Unsupported platform: '{platform}'")


__all__ = [
    "BasePlatformClient",
    "FacebookClient",
    "InstagramClient",
    "YouTubeClient",
    "get_platform_client",
    "get_client_from_db",
]

