# backend/apps/models3d/billing.py
#
# Dependency-light billing helpers for models3d generation. Keeping this outside
# the Celery task module lets unit contracts validate charge payloads without
# importing worker-only dependencies such as celery.

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")
INTERNAL_API_SHARED_TOKEN = os.getenv("INTERNAL_API_SHARED_TOKEN")
HI3D_MODEL_REF = "hi3d/hitem3dv2.1-fast-pbr"


async def charge_model_generation_credits(
    *,
    user_id: str,
    user_id_hash: str,
    app_id: str,
    skill_id: str,
    credits: int,
    chat_id: Any,
    message_id: Any,
    api_key_hash: str | None,
    device_hash: str | None,
    log_prefix: str,
) -> None:
    """Charge successful Hi3D generations after provider output is persisted."""
    if credits <= 0:
        return
    headers = {"Content-Type": "application/json"}
    if INTERNAL_API_SHARED_TOKEN:
        headers["X-Internal-Service-Token"] = INTERNAL_API_SHARED_TOKEN
    payload = {
        "user_id": user_id,
        "user_id_hash": user_id_hash,
        "credits": credits,
        "skill_id": skill_id,
        "app_id": app_id,
        "api_key_hash": api_key_hash,
        "device_hash": device_hash,
        "usage_details": {
            "chat_id": chat_id,
            "message_id": message_id,
            "units_processed": 1,
            "unit_name": "generated_model",
            "model_used": HI3D_MODEL_REF,
            "server_provider": "Hi3D",
            "server_region": "global",
        },
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{INTERNAL_API_BASE_URL}/internal/billing/charge",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
    except Exception as exc:
        logger.error("%s Failed to charge models3d generation credits: %s", log_prefix, exc, exc_info=True)
        raise
