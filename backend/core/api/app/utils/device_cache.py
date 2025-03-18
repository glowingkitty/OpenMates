import time
import json
import logging
from typing import Dict, Any, Optional, Tuple, List

from app.services.cache import CacheService
from app.utils.device_fingerprint import get_device_fingerprint
from fastapi import Request

logger = logging.getLogger(__name__)

async def store_device_in_cache(
    cache_service: CacheService,
    user_id: str,
    device_fingerprint: str,
    device_location: str,
    is_new_device: bool = False
) -> None:
    """
    Store a device in the cache for quick lookup.
    
    Args:
        cache_service: The cache service to use
        user_id: User ID
        device_fingerprint: Hashed device fingerprint
        device_location: Device location string
        is_new_device: Whether this is a new device for the user
    """
    current_time = int(time.time())
    
    # Create a cache entry for the device
    device_data = {
        "loc": device_location,
        "first": current_time if is_new_device else None,  # Only set first time if new
        "recent": current_time,
        "user_id": user_id  # Include user ID for lookups
    }
    
    # Set in cache with 24-hour TTL
    await cache_service.set(
        f"device:{user_id}:{device_fingerprint}", 
        device_data,
        ttl=86400  # 24 hours
    )
    
    # Also add to a user's device list for quick lookups of all devices
    # First get the current list
    device_list_key = f"user_devices:{user_id}"
    device_list = await cache_service.get(device_list_key) or []
    
    # Add if not already in list
    if device_fingerprint not in device_list:
        device_list.append(device_fingerprint)
        await cache_service.set(device_list_key, device_list, ttl=86400)
    
    logger.debug(f"Stored device {device_fingerprint} in cache for user {user_id}")

async def check_device_in_cache(
    cache_service: CacheService,
    user_id: str,
    device_fingerprint: str
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Check if a device exists in the cache.
    
    Args:
        cache_service: The cache service to use
        user_id: User ID
        device_fingerprint: Device fingerprint to check
        
    Returns:
        Tuple of (exists, device_data)
    """
    device_key = f"device:{user_id}:{device_fingerprint}"
    device_data = await cache_service.get(device_key)
    
    return (device_data is not None, device_data)

async def get_user_cached_devices(
    cache_service: CacheService,
    user_id: str
) -> List[Dict[str, Any]]:
    """
    Get all cached devices for a user.
    
    Args:
        cache_service: The cache service to use
        user_id: User ID
        
    Returns:
        List of device data dictionaries
    """
    # Get the list of device fingerprints
    device_list_key = f"user_devices:{user_id}"
    fingerprints = await cache_service.get(device_list_key) or []
    
    devices = []
    for fingerprint in fingerprints:
        device_key = f"device:{user_id}:{fingerprint}"
        device_data = await cache_service.get(device_key)
        if device_data:
            devices.append({
                "fingerprint": fingerprint,
                **device_data
            })
    
    return devices

async def update_device_cache(
    cache_service: CacheService,
    user_id: str, 
    device_fingerprint: str,
    update_data: Dict[str, Any]
) -> None:
    """
    Update specific fields of a cached device.
    
    Args:
        cache_service: The cache service to use
        user_id: User ID
        device_fingerprint: Device fingerprint to update
        update_data: Dict of fields to update
    """
    device_key = f"device:{user_id}:{device_fingerprint}"
    device_data = await cache_service.get(device_key)
    
    if device_data:
        # Update the fields
        device_data.update(update_data)
        await cache_service.set(device_key, device_data, ttl=86400)
