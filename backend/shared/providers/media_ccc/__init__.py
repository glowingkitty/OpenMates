"""Public media.ccc.de caption retrieval (no authentication or proxy)."""

from .client import MediaCCCClient, MediaCCCError, extract_media_ccc_slug

__all__ = ["MediaCCCClient", "MediaCCCError", "extract_media_ccc_slug"]
