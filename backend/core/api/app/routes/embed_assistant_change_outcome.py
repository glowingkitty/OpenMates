# backend/core/api/app/routes/embed_assistant_change_outcome.py
"""The requester's client reports what happened to an assistant change.

The assistant task waits on the stored outcome (backend/apps/ai/assistant_live_changes.py).
Spec: docs/plans/live-collaboration-crdt/build-contract.md section 4.
"""

import hashlib
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.apps.ai.assistant_live_changes import record_outcome
from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user

router = APIRouter(prefix="/v1/embeds", tags=["Embeds"])


class AssistantChangeOutcome(BaseModel):
    turn_id: str = Field(min_length=1, max_length=128)
    outcome: Literal["applied", "same_spot", "target_deleted", "needs_recheck"]
    details: dict[str, Any] = Field(default_factory=dict)


@router.post("/{embed_id}/assistant-change-outcome")
async def post_assistant_change_outcome(
    embed_id: str, body: AssistantChangeOutcome, request: Request,
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    cache_service = request.app.state.cache_service
    try:
        outcome = await record_outcome(
            cache_service, user_id_hash=hashlib.sha256(current_user.id.encode()).hexdigest(),
            embed_id=embed_id, turn_id=body.turn_id, outcome=body.outcome, details=body.details,
            encryption_service=request.app.state.encryption_service, user_vault_key_id=current_user.vault_key_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"outcome": outcome}
