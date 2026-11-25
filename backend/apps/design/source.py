"""Validate the explicitly attached client snapshot against the current personal Design head."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.apps.design.scene import DesignScene

MAX_SOURCE_BYTES = 128_000


class DesignSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    embed_id: UUID
    base_version: Annotated[int, Field(strict=True, ge=1)]
    scene: DesignScene = Field(repr=False)


def attached_design(value: Any) -> DesignSource | None:
    """Validate an inference snapshot without retaining a server working copy."""
    try:
        if not isinstance(value, dict) or len(json.dumps(value, ensure_ascii=False).encode()) > MAX_SOURCE_BYTES:
            return None
        source = DesignSource.model_validate(value)
    except (ValidationError, ValueError):
        return None
    return source if source.embed_id.int else None


async def design_skill_arguments(
    arguments: dict[str, Any], request: Any, directus_service: Any,
) -> dict[str, Any]:
    """Verify live scope before authoring. The model never supplies scene or embed IDs."""
    allowed = bool(
        request.user_id and request.chat_id and not request.team_id and not request.is_incognito
        and not request.is_anonymous and not request.is_external and directus_service is not None
    )
    enriched = {**arguments, "_design_source": None, "_design_author_allowed": allowed}
    if not allowed:
        return enriched
    source = attached_design(getattr(request, "design_source", None))
    if source is None:
        return enriched
    # A selected Design anchors the call even if the model omits the revision flag.
    enriched["revise"] = True
    head = await directus_service.embed.get_sync_embed_by_id(str(source.embed_id))
    if not head or (
        head.get("hashed_user_id") != hashlib.sha256(request.user_id.encode()).hexdigest()
        or head.get("hashed_chat_id") != hashlib.sha256(request.chat_id.encode()).hexdigest()
        or head.get("app_id") != "design" or head.get("skill_id") != "document"
        or head.get("parent_embed_id") or head.get("hashed_team_id") or head.get("encryption_mode") != "client"
        or (head.get("version_number") or 1) != source.base_version
    ):
        return enriched
    enriched["_design_source"] = source
    return enriched
