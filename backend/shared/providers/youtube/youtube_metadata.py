# backend/shared/providers/youtube/youtube_metadata.py
#
# YouTube Data API provider functions.
# Provides video metadata functionality using the YouTube Data API v3.
#
# Documentation: https://developers.google.com/youtube/v3/docs
#
# Key Features:
# - Batched metadata retrieval (up to 50 videos per request, 1 quota unit per batch)
# - Efficient quota usage (1 quota unit regardless of batch size or parts requested)
# - Extracts full metadata including statistics, snippet, contentDetails, and status

import logging
import os
import re
from typing import Dict, List, Optional
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.python_utils.url_normalizer import sanitize_url_remove_fragment

logger = logging.getLogger(__name__)

# Vault path for YouTube API key
YOUTUBE_SECRET_PATH = "kv/data/providers/youtube"
YOUTUBE_API_KEY_NAME = "api_key"


async def _get_youtube_api_key(secrets_manager: SecretsManager) -> Optional[str]:
    """
    Retrieves the YouTube Data API key from Vault, with fallback to environment variables.
    
    Checks Vault first, then falls back to environment variables if Vault lookup fails.
    Supports both SECRET__YOUTUBE__API_KEY and SECRET__GOOGLE__YOUTUBE__API_KEY for compatibility.
    
    Args:
        secrets_manager: The SecretsManager instance to use
        
    Returns:
        The API key if found, None otherwise
    """
    # First, try to get the API key from Vault
    try:
        api_key = await secrets_manager.get_secret(
            secret_path=YOUTUBE_SECRET_PATH,
            secret_key=YOUTUBE_API_KEY_NAME
        )
        if api_key:
            logger.debug("YouTube API key retrieved from Vault")
            return api_key
    except Exception as e:
        logger.debug(f"Failed to retrieve YouTube API key from Vault: {e}")
    
    # Fallback to environment variables
    api_key = os.getenv("SECRET__YOUTUBE__API_KEY") or os.getenv("SECRET__GOOGLE__YOUTUBE__API_KEY")
    if api_key:
        logger.debug("YouTube API key retrieved from environment variable")
        return api_key
    
    logger.warning("YouTube API key not found in Vault or environment variables")
    return None


def extract_youtube_id_from_url(url: str) -> Optional[str]:
    """
    Extract YouTube video ID from various URL formats.
    
    Supports:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://youtube.com/watch?v=VIDEO_ID
    
    **Security**: URL fragments (#{text}) are removed before extraction as a security measure.
    Fragments can contain malicious content and are not needed for video ID extraction.
    
    Args:
        url: YouTube video URL
        
    Returns:
        Video ID if found, None otherwise
    """
    if not url:
        return None
    
    # Sanitize URL by removing fragment parameters (#{text}) as a security measure
    # Fragments can contain malicious content and are not needed for video ID extraction
    sanitized_url = sanitize_url_remove_fragment(url)
    if not sanitized_url:
        logger.warning(f"Failed to sanitize YouTube URL for ID extraction: '{url}'")
        return None
    
    # Use sanitized URL for extraction
    url = sanitized_url
    
    # Pattern for youtube.com/watch?v=VIDEO_ID and youtu.be/VIDEO_ID
    match = re.search(r'(?:youtube\.com/watch\?v=|youtu\.be/)([\w-]{11})', url)
    if match:
        return match.group(1)
    
    return None


async def get_video_metadata_batched(
    video_ids: List[str],
    secrets_manager: SecretsManager,
    batch_size: int = 50
) -> Dict[str, Dict]:
    """
    Get full metadata for YouTube videos using batched API requests.
    
    YouTube API videos.list costs 1 quota unit per request, regardless of how many
    video IDs are included (up to 50 per request) or which parts are requested.
    This function batches IDs to minimize quota usage and requests all relevant parts.
    
    Args:
        video_ids: List of YouTube video IDs
        secrets_manager: SecretsManager instance for retrieving API key
        batch_size: Number of video IDs per batch (max 50, default 50)
        
    Returns:
        Dictionary mapping video_id -> full metadata dict from YouTube API
        Returns empty dict if API key is not available or if all requests fail
        
    Raises:
        ValueError: If API key is not available
    """
    # Get API key
    api_key = await _get_youtube_api_key(secrets_manager)
    if not api_key:
        raise ValueError("YouTube API key not available. Please configure it in Vault or set SECRET__YOUTUBE__API_KEY environment variable.")
    
    youtube = build('youtube', 'v3', developerKey=api_key)
    all_metadata = {}
    
    # Batch video IDs (max 50 per request)
    batch_size = min(batch_size, 50)
    batches = [video_ids[i:i+batch_size] for i in range(0, len(video_ids), batch_size)]
    
    logger.debug(f"Processing {len(video_ids)} YouTube videos in {len(batches)} batch(es) (1 quota unit per batch)")
    
    for i, batch in enumerate(batches, 1):
        logger.debug(f"Batch {i}/{len(batches)}: Processing {len(batch)} videos...")
        
        try:
            # Request all relevant parts for complete metadata
            # This costs 1 quota unit regardless of batch size or parts requested
            request = youtube.videos().list(
                part='snippet,contentDetails,statistics,status',
                id=','.join(batch)
            )
            
            response = request.execute()
            
            # Store full metadata for each video
            for item in response.get('items', []):
                video_id = item['id']
                all_metadata[video_id] = item
            
            logger.debug(f"Retrieved full metadata for {len(response.get('items', []))} videos in batch {i}")
            
        except HttpError as e:
            error_msg = f"YouTube API error in batch {i}: {e.resp.status} - {e.content}"
            logger.error(error_msg)
            # Continue with other batches even if one fails
        except Exception as e:
            error_msg = f"Error processing YouTube API batch {i}: {e}"
            logger.error(error_msg, exc_info=True)
            # Continue with other batches even if one fails
    
    logger.info(f"YouTube metadata retrieval completed: {len(all_metadata)}/{len(video_ids)} videos processed using {len(batches)} quota units")
    
    return all_metadata


async def get_channel_thumbnails_batched(
    channel_ids: List[str],
    secrets_manager: SecretsManager,
    batch_size: int = 50
) -> Dict[str, Dict]:
    """
    Get channel thumbnails (profile images) for YouTube channels using batched API requests.
    
    YouTube API channels.list costs 1 quota unit per request, regardless of how many
    channel IDs are included (up to 50 per request) or which parts are requested.
    This function batches channel IDs to minimize quota usage.
    
    Args:
        channel_ids: List of YouTube channel IDs
        secrets_manager: SecretsManager instance for retrieving API key
        batch_size: Number of channel IDs per batch (max 50, default 50)
        
    Returns:
        Dictionary mapping channel_id -> channel metadata dict with thumbnails
        Returns empty dict if API key is not available or if all requests fail
        
    Raises:
        ValueError: If API key is not available
    """
    if not channel_ids:
        return {}
    
    # Get API key
    api_key = await _get_youtube_api_key(secrets_manager)
    if not api_key:
        raise ValueError("YouTube API key not available. Please configure it in Vault or set SECRET__YOUTUBE__API_KEY environment variable.")
    
    youtube = build('youtube', 'v3', developerKey=api_key)
    all_channel_data = {}
    
    # Remove duplicates while preserving order
    unique_channel_ids = list(dict.fromkeys(channel_ids))
    
    # Batch channel IDs (max 50 per request)
    batch_size = min(batch_size, 50)
    batches = [unique_channel_ids[i:i+batch_size] for i in range(0, len(unique_channel_ids), batch_size)]
    
    logger.debug(f"Processing {len(unique_channel_ids)} unique YouTube channels in {len(batches)} batch(es) (1 quota unit per batch)")
    
    for i, batch in enumerate(batches, 1):
        logger.debug(f"Channel batch {i}/{len(batches)}: Processing {len(batch)} channels...")
        
        try:
            # Request snippet part to get channel thumbnails
            # This costs 1 quota unit regardless of batch size
            request = youtube.channels().list(
                part='snippet',
                id=','.join(batch)
            )
            
            response = request.execute()
            
            # Store channel data with thumbnails
            for item in response.get('items', []):
                channel_id = item['id']
                all_channel_data[channel_id] = item
            
            logger.debug(f"Retrieved thumbnails for {len(response.get('items', []))} channels in batch {i}")
            
        except HttpError as e:
            error_msg = f"YouTube API error in channel batch {i}: {e.resp.status} - {e.content}"
            logger.error(error_msg)
            # Continue with other batches even if one fails
        except Exception as e:
            error_msg = f"Error processing YouTube API channel batch {i}: {e}"
            logger.error(error_msg, exc_info=True)
            # Continue with other batches even if one fails
    
    logger.info(f"YouTube channel thumbnails retrieval completed: {len(all_channel_data)}/{len(unique_channel_ids)} channels processed using {len(batches)} quota units")
    
    return all_channel_data
