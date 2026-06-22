# backend/core/api/app/utils/api_key_device_ownership.py
#
# Pure ownership helpers for API key device management routes.
# Keeps permission checks testable without importing FastAPI route modules.
# API key device rows store only a hashed user identifier for privacy.

import hashlib
from typing import Any


def api_key_device_belongs_to_user(device: dict[str, Any] | None, user_id: str) -> bool:
    if not device:
        return False

    expected_user_hash = hashlib.sha256(user_id.encode()).hexdigest()
    return device.get('hashed_user_id') == expected_user_hash
