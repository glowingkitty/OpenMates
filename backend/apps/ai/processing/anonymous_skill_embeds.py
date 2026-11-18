"""Transient app-skill embeds for anonymous (signed-out) chats.

Anonymous chats have no vault key, so their skill embeds are never persisted
server-side. The worker builds plaintext embed payloads here, streams the parent
reference into the answer and hands the payloads to the anonymous SSE adapter,
which the client stores only in encrypted local storage.

The payload shapes mirror the authenticated embed creation in
``EmbedService.create_embeds_from_skill_results``:
- composite skills (``embed_types[].child_type`` in app.yml): one parent
  ``app_skill_use`` embed plus one child embed per result;
- non-composite skills (for example ``math.calculate``): one ``app_skill_use``
  embed that carries its results inline and has no children.

Spec: specifications/features/apps-workspace/specification.yml (apps.anonymous.local-results-and-promotion)
Tests: backend/tests/test_anonymous_skill_embeds.py
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from toon_format import encode

from backend.core.api.app.services.embed_service import EmbedService


@dataclass(frozen=True)
class AnonymousSkillEmbeds:
    """Embed payloads for the SSE adapter and the reference streamed into the answer."""

    payloads: List[Dict[str, Any]]
    reference: str


def build_anonymous_skill_embeds(
    *,
    app_id: str,
    skill_id: str,
    results: List[Dict[str, Any]],
    preview_data: Dict[str, Any],
    child_type: Optional[str],
    flatten: Callable[[Any], Any],
) -> AnonymousSkillEmbeds:
    """Build transient embeds for one finished skill call in an anonymous chat.

    ``child_type`` is the composite child embed type, or ``None`` for a
    non-composite skill. ``flatten`` is the TOON tabular flattener the caller
    already uses for the tool result, so the embed content matches it.
    """
    parent_embed_id = str(uuid.uuid4())
    now = int(time.time())
    request_metadata = {key: value for key, value in preview_data.items() if key != "results_toon"}

    if child_type is None:
        content: Dict[str, Any] = {
            "app_id": app_id,
            "skill_id": skill_id,
            **request_metadata,
            "results": [flatten(result) for result in results],
            "result_count": len(results),
            "status": "finished",
        }
        child_embed_ids: List[str] = []
    else:
        child_embed_ids = [str(uuid.uuid4()) for _ in results]
        content = {
            "app_id": app_id,
            "skill_id": skill_id,
            "result_count": len(results),
            "embed_ids": child_embed_ids,
            "status": "finished",
            **request_metadata,
            **EmbedService._build_parent_preview_metadata(app_id, skill_id, results),
        }
    content["embed_ref"] = EmbedService._generate_direct_embed_ref(f"{app_id}-{skill_id}", parent_embed_id)
    content = EmbedService._sanitize_final_app_skill_content(app_id, skill_id, content)

    payloads: List[Dict[str, Any]] = [{
        "embed_id": parent_embed_id,
        "embed_ref": content["embed_ref"],
        "type": "app_skill_use",
        "content": encode(flatten(content)),
        "status": "finished",
        "embed_ids": child_embed_ids or None,
        "app_id": app_id,
        "skill_id": skill_id,
        "created_at": now,
        "updated_at": now,
    }]
    for child_embed_id, result in zip(child_embed_ids, results):
        child_content = {
            **flatten(result),
            "type": child_type,
            "app_id": app_id,
            "skill_id": child_type,
            "status": "finished",
        }
        payloads.append({
            "embed_id": child_embed_id,
            "type": child_type,
            "content": encode(child_content),
            "status": "finished",
            "parent_embed_id": parent_embed_id,
            "app_id": app_id,
            "skill_id": child_type,
            "created_at": now,
            "updated_at": now,
        })

    reference = json.dumps({
        "type": "app_skill_use",
        "embed_id": parent_embed_id,
        "app_id": app_id,
        "skill_id": skill_id,
    })
    return AnonymousSkillEmbeds(payloads=payloads, reference=reference)
