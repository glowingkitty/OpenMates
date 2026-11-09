# backend/apps/ai/processing/postprocessing_workflow_context.py
#
# Optional context for chat Recommendations: the user's saved workflow titles and
# descriptions, decrypted server-side for ONE post-processing call. The rows are
# held in memory only (no cache, no disk, no logs) and passed to the postprocessor.
# Plan: docs/plans/chat-recommendations/plan.yml (D-5)
# test-file: backend/tests/test_postprocessing_recommendations.py

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

import httpx

from backend.apps.ai.processing.agentic_context import first_party

logger = logging.getLogger(__name__)

# Failures of this optional enrichment are logged by type only and never block post-processing.
_OPTIONAL_CONTEXT_ERRORS = (RuntimeError, ValueError, LookupError, PermissionError, OSError, httpx.HTTPError)


async def fetch_user_workflow_metadata(request: Any, cache: Any) -> List[Dict[str, Any]]:
    """Return every persisted workflow's {workflow_id, title, description, updated_at}, or [] when unavailable."""
    if not first_party(request) or cache is None or getattr(request, "is_sub_chat", False):
        return []
    # Reuse the discovery helpers' vault-key lookup, team authorization and client cleanup.
    from backend.apps.ai.processing.context_preselection import (
        _authorize_workflow_team, _close_workflow_service, _workflow_service,
    )
    service = None
    try:
        await _authorize_workflow_team(request, cache)
        binding = await _workflow_service(request, cache)
        if not binding:
            return []
        service, vault_key_id = binding
        return await asyncio.to_thread(
            service.list_discovery_metadata, request.user_id, vault_key_id,
            team_id=getattr(request, "team_id", None), include_all=True,
        )
    except _OPTIONAL_CONTEXT_ERRORS as exc:
        logger.warning("[Recommendations] Workflow awareness unavailable (%s); continuing without workflow list", type(exc).__name__)
        return []
    finally:
        if service is not None:
            await _close_workflow_service(service)
