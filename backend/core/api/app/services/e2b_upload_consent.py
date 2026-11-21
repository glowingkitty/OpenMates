"""Per-account consent before user code or Project files are sent to E2B.

One decision per account (allowed or declined) is stored on the Directus user
with its server timestamp. The field names carry the wording version, so a
meaningful change of wording or provider is a new version that asks again and
older decisions never carry over. Reads go to the database, never to the
session cache, so a stale cache cannot admit an upload.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from fastapi import HTTPException

E2B_UPLOAD_CONSENT_VERSION = 1
CONSENT_FIELD = f"e2b_upload_consent_v{E2B_UPLOAD_CONSENT_VERSION}"
CONSENT_AT_FIELD = f"{CONSENT_FIELD}_at"
DECISIONS = ("allowed", "declined")

Decision = Literal["allowed", "declined"]


def _unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="E2B upload consent unavailable")


def _directus(directus_service: Any | None) -> Any:
    if directus_service is not None:
        return directus_service
    from backend.core.api.app.services.directus import DirectusService

    return DirectusService()


async def get_decision(user_id: str, directus_service: Any | None = None) -> dict[str, Any]:
    """Return {decision, decided_at, version}; decision is None when none was made."""
    fields = await _directus(directus_service).get_user_fields_direct(
        user_id, [CONSENT_FIELD, CONSENT_AT_FIELD], no_cache=True
    )
    if fields is None:
        raise _unavailable()
    decision = fields.get(CONSENT_FIELD)
    decided_at = fields.get(CONSENT_AT_FIELD)
    if decision not in DECISIONS:
        return {"decision": None, "decided_at": None, "version": E2B_UPLOAD_CONSENT_VERSION}
    return {
        "decision": decision,
        "decided_at": decided_at if type(decided_at) is int else None,
        "version": E2B_UPLOAD_CONSENT_VERSION,
    }


async def record_decision(
    user_id: str, decision: str, directus_service: Any | None = None
) -> dict[str, Any]:
    """Persist the decision with a server timestamp and return the stored state."""
    if decision not in DECISIONS:
        raise HTTPException(status_code=422, detail="Unsupported E2B upload decision")
    directus = _directus(directus_service)
    ok = await directus.update_user(
        user_id, {CONSENT_FIELD: decision, CONSENT_AT_FIELD: int(time.time())}
    )
    if not ok:
        raise _unavailable()
    stored = await get_decision(user_id, directus)
    if stored["decision"] != decision:
        raise _unavailable()
    return stored


async def record_allowed_if_unset(
    user_id: str, directus_service: Any | None = None
) -> dict[str, Any]:
    """Explicit-flag path: record allowed only when no decision exists; never override declined."""
    current = await get_decision(user_id, directus_service)
    if current["decision"] is None:
        return await record_decision(user_id, "allowed", directus_service)
    return current


async def require_e2b_upload_consent(user_id: str, directus_service: Any | None = None) -> None:
    """Raise 403 unless the account allowed E2B uploads; call before anything is queued."""
    current = await get_decision(user_id, directus_service)
    if current["decision"] == "allowed":
        return
    code = "e2b_consent_declined" if current["decision"] == "declined" else "e2b_consent_required"
    raise HTTPException(status_code=403, detail={"code": code})
