# backend/core/api/app/routes/memory_suggestions.py
#
# Surface: first-party client only (session auth). Accepts cleartext memory and
# chat text for ONE explicit user action; text is never logged or stored.
# Rate limited; refuses when the wallet is empty. The model request is charged
# and attributed to the originating chat; the usage record holds token counts
# and chat_id only. A false-positive ("unchanged") request is charged too.
# Spec: app-memories.suggestions.billing
# test-file: backend/tests/test_postprocessing_context_suggestions.py

import hashlib
import logging
import uuid
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.apps.ai.processing.memory_update_preview import MemoryPreviewError, run_memory_update_preview
from backend.apps.ai.processing.memory_preview_billing import charge_preview, priced_buckets
from backend.apps.ai.processing.postprocessor import POSTPROCESSING_MODEL_ID
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.services.billing_service import BillingService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.utils.config_manager import config_manager

router = APIRouter(prefix="/v1/memory-suggestions", tags=["Memory Suggestions"])
logger = logging.getLogger(__name__)


class PreviewMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=8_000)


class UpdatePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chat_id: str = Field(min_length=1, max_length=64)
    memory_id: str = Field(min_length=1, max_length=240)
    memory_markdown: str = Field(min_length=1, max_length=24_000, repr=False)
    messages: List[PreviewMessage] = Field(min_length=1, max_length=24, repr=False)


@router.post("/update-preview", include_in_schema=False)
@limiter.limit("20/minute")
async def update_preview(request: Request, response: Response, body: UpdatePreviewRequest) -> Dict[str, Any]:
    state = request.app.state
    user = await _user(request, response)
    user_id_hash = hashlib.sha256(user.id.encode()).hexdigest()
    billing = BillingService(state.cache_service, state.directus_service, state.encryption_service)
    if await billing.get_authoritative_personal_balance(user_id=user.id, user_id_hash=user_id_hash) < 1:
        raise HTTPException(status_code=402, detail="Insufficient credits")
    usage_events: List[Dict[str, Any]] = []
    task_id = f"memory-update-preview-{uuid.uuid4()}"
    try:
        updated, telemetry = await run_memory_update_preview(
            task_id=task_id, model_id=POSTPROCESSING_MODEL_ID, memory_markdown=body.memory_markdown,
            messages=[m.model_dump() for m in body.messages], secrets_manager=state.secrets_manager,
            usage_callback=usage_events.append,
        )
        error: Optional[MemoryPreviewError] = None
    except MemoryPreviewError as exc:
        updated, telemetry, error = None, None, exc
    # Charge whatever was incurred, including unchanged and unusable results.
    buckets = priced_buckets(usage_events[-1] if usage_events else telemetry)
    if buckets:
        await charge_preview(billing, config_manager.get_model_pricing, user_id=user.id, user_id_hash=user_id_hash,
                             chat_id=body.chat_id, operation_id=task_id, buckets=buckets)
    if error is not None:
        raise HTTPException(status_code=502, detail="Memory update preview failed")
    return {"status": "unchanged"} if updated is None else {"status": "updated", "body": updated}


async def _user(request: Request, response: Response):
    state = request.app.state
    return await get_current_user(
        directus_service=state.directus_service, cache_service=state.cache_service,
        request=request, response=response, refresh_token=request.cookies.get("auth_refresh_token"),
    )
