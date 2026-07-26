"""
Facebook Graph API client — backward-compatibility shim.

The real implementation has moved to src/platforms/facebook.py.
This module re-exports FacebookClient so that any existing imports
from src.facebook.client continue to work without changes.
"""
from src.platforms.facebook import FacebookClient  # noqa: F401

__all__ = ["FacebookClient"]
