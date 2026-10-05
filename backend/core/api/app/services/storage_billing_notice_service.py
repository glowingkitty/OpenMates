"""Owner-scoped frozen notice metadata, shared by the first-party route and mailer."""

from __future__ import annotations

import hashlib
from typing import Any

from backend.core.api.app.schemas.settings import StorageNoticeResponse


async def read_storage_notice(
    orchestration: Any, user_id: str, *, episode_id: str | None = None,
    after_unit_id: str | None = None, limit: int = 50,
) -> StorageNoticeResponse:
    if not 1 <= limit <= 100:
        raise ValueError("Invalid storage notice page size")
    data = {
        "protocol_version": 1, "user_id": user_id,
        "hashed_user_id": hashlib.sha256(user_id.encode()).hexdigest(),
        "limit": limit,
    }
    if episode_id is not None:
        data["episode_id"] = episode_id
    if after_unit_id is not None:
        data["after_unit_id"] = after_unit_id
    result = await orchestration.execute("list_storage_warning_units", data)
    if not isinstance(result, dict) or not isinstance(result.get("units"), list):
        raise RuntimeError("Storage notice metadata is incomplete")
    if len(result["units"]) > limit or not isinstance(result.get("has_more"), bool):
        raise RuntimeError("Storage notice page is invalid")
    # Pydantic drops internal fields, including the immutable fingerprints.
    notice = StorageNoticeResponse.model_validate(result)
    if notice.has_more and (
        not notice.units or notice.next_after_unit_id != notice.units[-1].unit_id
    ):
        raise RuntimeError("Storage notice cursor did not advance")
    if notice.units and not notice.episode_id:
        raise RuntimeError("Storage notice has no episode")
    return notice
