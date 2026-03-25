# backend/core/api/app/services/directus/user/device_management.py
#
# Manages the connected_devices JSON field on user records.
# Each entry is a dict with {hash, first_seen, last_seen} for auto-expiry support.
# Backward-compatible: legacy plain-string entries are migrated on read.
#
# Architecture: docs/architecture/core/security.md
# Tests: backend/tests/test_device_management.py

import logging
import json
import time
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

MAX_DEVICES = 10  # Maximum number of device records to store per user
DEVICE_EXPIRY_DAYS = 90  # Devices not seen in this many days are eligible for cleanup


def _normalize_device_entry(entry: Any) -> Dict[str, Any]:
    """Convert a legacy plain-string device hash to the new dict format.
    New entries: {"hash": "abc123", "first_seen": 1711000000, "last_seen": 1711000000}
    Legacy entries: "abc123" -> migrated with first_seen=0 (unknown) and last_seen=0.
    """
    if isinstance(entry, dict) and "hash" in entry:
        return entry
    if isinstance(entry, str):
        return {"hash": entry, "first_seen": 0, "last_seen": 0}
    return None


def _normalize_device_list(raw: Any) -> List[Dict[str, Any]]:
    """Parse and normalize a connected_devices field from cache or Directus."""
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(raw, list):
        return []
    result = []
    for entry in raw:
        normalized = _normalize_device_entry(entry)
        if normalized:
            result.append(normalized)
    return result


async def _fetch_connected_devices(self, user_id: str) -> Tuple[List[Dict[str, Any]], bool]:
    """Fetch connected_devices from cache or Directus. Returns (devices, success)."""
    # Try cache first
    user_data = await self.cache.get_user_by_id(user_id)
    if user_data:
        raw = user_data.get("connected_devices")
        if raw is not None:
            devices = _normalize_device_list(raw)
            if devices or raw == "[]":
                logger.debug(f"Retrieved connected_devices from cache for user {user_id[:6]}...")
                return devices, True

    # Fall back to Directus
    user_url = f"{self.base_url}/users/{user_id}"
    get_response = await self._make_api_request("GET", user_url, params={"fields": "connected_devices"})
    if get_response.status_code != 200:
        logger.error(f"Failed to retrieve user {user_id} for device hash update: {get_response.status_code}")
        return [], False

    raw = get_response.json().get("data", {}).get("connected_devices")
    devices = _normalize_device_list(raw)
    logger.debug(f"Retrieved connected_devices from Directus for user {user_id[:6]}...")
    return devices, True


async def add_user_device_hash(
    self,
    user_id: str,
    device_hash: str
) -> Tuple[bool, str]:
    """
    Adds or updates a device hash in a user's connected_devices list.
    Updates last_seen timestamp if the device already exists.
    Prunes old hashes if the list exceeds MAX_DEVICES.
    Prioritizes writing to cache first, then Directus.

    Args:
        self: The DirectusService instance.
        user_id: The ID of the user.
        device_hash: The new device hash to add.

    Returns:
        Tuple[bool, str]: Success status and a message.
    """
    try:
        connected_devices, success = await _fetch_connected_devices(self, user_id)
        if not success:
            return False, "Failed to retrieve user device data"

        now = int(time.time())
        needs_update = False

        # Check if device already exists — update last_seen
        existing = next((d for d in connected_devices if d["hash"] == device_hash), None)
        if existing:
            existing["last_seen"] = now
            needs_update = True
            logger.debug(f"Device hash {device_hash[:8]}... already known for user {user_id}. Updated last_seen.")
        else:
            # Add new device
            logger.info(f"Adding new device hash {device_hash[:8]}... for user {user_id}")
            connected_devices.append({
                "hash": device_hash,
                "first_seen": now,
                "last_seen": now,
            })
            needs_update = True

        # Prune old devices if exceeding MAX_DEVICES (keep most recently seen)
        if len(connected_devices) > MAX_DEVICES:
            logger.info(f"Device count ({len(connected_devices)}) exceeds limit ({MAX_DEVICES}) for user {user_id}. Pruning...")
            connected_devices.sort(key=lambda d: d.get("last_seen", 0))
            connected_devices = connected_devices[-MAX_DEVICES:]
            needs_update = True

        if needs_update:
            serialized = json.dumps(connected_devices)
            try:
                await self.cache.update_user(user_id, {"connected_devices": serialized})
                logger.debug(f"Updated connected_devices in cache for user {user_id[:6]}...")

                user_url = f"{self.base_url}/users/{user_id}"
                patch_response = await self._make_api_request(
                    "PATCH", user_url, json={"connected_devices": serialized}
                )
                if patch_response.status_code == 200:
                    logger.info(f"Updated connected_devices in Directus for user {user_id}")
                    return True, "Device information updated successfully"
                else:
                    logger.error(f"Failed to update connected_devices in Directus for user {user_id}: {patch_response.status_code}")
                    return False, f"Failed to update device info: {patch_response.status_code}"
            except Exception as e:
                logger.error(f"Error updating connected_devices for user {user_id}: {str(e)}", exc_info=True)
                return False, f"Error updating devices: {str(e)}"
        else:
            return True, "Device information is up to date"

    except Exception as e:
        error_msg = f"Unexpected error adding device hash for user {user_id}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg


async def get_user_device_hashes(
    self,
    user_id: str
) -> List[str]:
    """
    Retrieves the list of known device hashes for a user.
    Returns plain hash strings for backward compatibility with callers
    that only need to check membership.

    Args:
        self: The DirectusService instance.
        user_id: The ID of the user.

    Returns:
        List[str]: A list of device hashes, or an empty list if none found.
    """
    try:
        connected_devices, _ = await _fetch_connected_devices(self, user_id)
        return [d["hash"] for d in connected_devices]
    except Exception as e:
        logger.error(f"Unexpected error retrieving device hashes for user {user_id}: {str(e)}", exc_info=True)
        return []


async def get_user_device_records(
    self,
    user_id: str
) -> List[Dict[str, Any]]:
    """
    Retrieves the full device records (with timestamps) for a user.
    Used by the session management UI to show device age.

    Args:
        self: The DirectusService instance.
        user_id: The ID of the user.

    Returns:
        List[Dict]: Device records with hash, first_seen, last_seen fields.
    """
    try:
        connected_devices, _ = await _fetch_connected_devices(self, user_id)
        return connected_devices
    except Exception as e:
        logger.error(f"Unexpected error retrieving device records for user {user_id}: {str(e)}", exc_info=True)
        return []
