# backend/shared/python_utils/content_hasher.py
#
# Content hashing utilities for creator income tracking.
# Provides privacy-preserving hashing of owner IDs and content IDs.

import hashlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def hash_owner_id(owner_id: str) -> Optional[str]:
    """
    Hash an owner ID (channel ID or domain) for privacy-preserving storage.
    
    Owner IDs are hashed before storage to protect privacy while allowing
    creators to claim their income by providing the original owner ID.
    
    Args:
        owner_id: The owner identifier to hash
            - For videos: YouTube channel ID (e.g., 'UCxxxxxxxxxxxxxxxxxxxxxxxxxx')
            - For websites: Normalized domain (e.g., 'example.com')
        
    Returns:
        SHA-256 hash of the owner ID (64-character hex string) or None if input is invalid
        
    Example:
        >>> hash_owner_id("UCxxxxxxxxxxxxxxxxxxxxxxxxxx")
        'a1b2c3d4e5f6...'  # 64-character hex string
    """
    if not owner_id or not isinstance(owner_id, str) or not owner_id.strip():
        logger.warning(f"Invalid owner_id provided for hashing: {owner_id}")
        return None
    
    try:
        # Hash with SHA-256
        hashed = hashlib.sha256(owner_id.strip().encode('utf-8')).hexdigest()
        return hashed
    except Exception as e:
        logger.error(f"Error hashing owner_id '{owner_id}': {e}", exc_info=True)
        return None


def hash_content_id(content_id: str) -> Optional[str]:
    """
    Hash a content ID (video ID or normalized URL) for privacy-preserving storage.
    
    Content IDs are hashed to allow tracking which specific content was processed
    for statistics, while maintaining privacy.
    
    Args:
        content_id: The content identifier to hash
            - For videos: Video ID (e.g., 'dQw4w9WgXcQ')
            - For websites: Normalized URL (e.g., 'https://example.com/article')
        
    Returns:
        SHA-256 hash of the content ID (64-character hex string) or None if input is invalid
        
    Example:
        >>> hash_content_id("dQw4w9WgXcQ")
        'a1b2c3d4e5f6...'  # 64-character hex string
    """
    if not content_id or not isinstance(content_id, str) or not content_id.strip():
        logger.warning(f"Invalid content_id provided for hashing: {content_id}")
        return None
    
    try:
        # Hash with SHA-256
        hashed = hashlib.sha256(content_id.strip().encode('utf-8')).hexdigest()
        return hashed
    except Exception as e:
        logger.error(f"Error hashing content_id '{content_id}': {e}", exc_info=True)
        return None


def hash_app_id(app_id: str) -> Optional[str]:
    """
    Hash an app ID for privacy-preserving storage.
    
    Args:
        app_id: The app identifier to hash (e.g., 'videos', 'web')
        
    Returns:
        SHA-256 hash of the app ID (64-character hex string) or None if input is invalid
    """
    if not app_id or not isinstance(app_id, str) or not app_id.strip():
        logger.warning(f"Invalid app_id provided for hashing: {app_id}")
        return None
    
    try:
        hashed = hashlib.sha256(app_id.strip().encode('utf-8')).hexdigest()
        return hashed
    except Exception as e:
        logger.error(f"Error hashing app_id '{app_id}': {e}", exc_info=True)
        return None


def hash_skill_id(skill_id: str) -> Optional[str]:
    """
    Hash a skill ID for privacy-preserving storage.
    
    Args:
        skill_id: The skill identifier to hash (e.g., 'get_transcript', 'read')
        
    Returns:
        SHA-256 hash of the skill ID (64-character hex string) or None if input is invalid
    """
    if not skill_id or not isinstance(skill_id, str) or not skill_id.strip():
        logger.warning(f"Invalid skill_id provided for hashing: {skill_id}")
        return None
    
    try:
        hashed = hashlib.sha256(skill_id.strip().encode('utf-8')).hexdigest()
        return hashed
    except Exception as e:
        logger.error(f"Error hashing skill_id '{skill_id}': {e}", exc_info=True)
        return None
