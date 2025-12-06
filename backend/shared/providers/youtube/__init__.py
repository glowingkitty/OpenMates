# backend/shared/providers/youtube/__init__.py
#
# YouTube Data API provider module.
# Provides functions for fetching YouTube video metadata.

from backend.shared.providers.youtube.youtube_metadata import (
    get_video_metadata_batched,
    get_channel_thumbnails_batched,
    extract_youtube_id_from_url
)

__all__ = [
    'get_video_metadata_batched',
    'get_channel_thumbnails_batched',
    'extract_youtube_id_from_url'
]
