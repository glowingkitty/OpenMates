"""First-party Apps interpretation; session or approved device authentication.

Authenticated access is first-party only; official-cloud guests retain their
existing inline-skill/free-pool limits. Caddy's Apps prefix can reach this route,
so the first-party check is enforced here. It never executes a skill or reads
client-supplied embed/chat IDs. Team membership is checked before inference.
Parsing is internally budgeted; published skill charges remain on execution.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user_or_api_key
from backend.core.api.app.services.apps_workspace_metadata import execution_status, request_schema
from backend.core.api.app.services.apps_workspace_request_service import AppsRequestSkill, AppsWorkspaceRequestService
from backend.core.api.app.services.directus.team_methods import TeamPermissionError
from backend.core.api.app.services.limiter import limiter
from backend.shared.providers.typesafe.assets import DecisionAssets, MAX_DECISION_BODY_BYTES, validate_asset_references

router = APIRouter(prefix="/v1/apps/workspace", tags=["Apps Workspace"])
# Atomic, fail-closed supplier-spend admission. Only opaque hashes/counters are
# retained; unlike a data cache, there is no private database content to recover.
_ADMIT = """
if redis.call('EXISTS', KEYS[1]) == 1 then return -1 end
if tonumber(redis.call('GET', KEYS[2]) or '0') >= 100 then return -2 end
if tonumber(redis.call('GET', KEYS[3]) or '0') >= 2000 then return -2 end
redis.call('SET', KEYS[1], '1', 'EX', 86400)
redis.call('INCR', KEYS[2]); redis.call('EXPIRE', KEYS[2], 172800)
redis.call('INCR', KEYS[3]); redis.call('EXPIRE', KEYS[3], 172800)
return 1
"""


class AppsRequestContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    input: dict[str, Any] = Field(default_factory=dict)
    embed_id: UUID | None = None
    chat_id: UUID | None = None
    result: Any = None


class InterpretAppsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    app_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    text: str = Field(min_length=1, max_length=8000)
    request_id: UUID
    expected_user_id: UUID | None = None
    timezone: str = Field(default="UTC", min_length=1, max_length=100)
    locale: str = Field(default="en", min_length=2, max_length=35, pattern=r"^[a-zA-Z0-9_-]+$")
    team_id: UUID | None = None
    context: AppsRequestContext | None = None
    attachments: list[dict[str, Any]] = Field(default_factory=list, max_length=10)
    assets: DecisionAssets = Field(default_factory=dict)

    @field_validator("timezone")
    @classmethod
    def timezone_exists(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Invalid timezone") from exc
        return value

    @model_validator(mode="after")
    def bounded_context(self) -> "InterpretAppsRequest":
        try:
            complete = self.model_dump(mode="json")
            if len(json.dumps(complete, ensure_ascii=False, allow_nan=False).encode()) > MAX_DECISION_BODY_BYTES:
                raise ValueError("Request exceeds image body limit")
            complete.pop("assets", None)
            size = len(json.dumps(complete, ensure_ascii=False, allow_nan=False))
            validate_asset_references(self.assets, {"attachments": self.attachments}, {})
        except (ValueError, RecursionError) as exc:
            raise ValueError("Invalid request context") from exc
        if size > 24_000:
            raise ValueError("Request context exceeds size limit")
        return self



class AppsRankCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=200)
    title: str = Field(default="", max_length=200)
    text: str = Field(default="", max_length=800)


class RankAppsResults(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    app_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    request_id: UUID
    expected_user_id: UUID | None = None
    text: str = Field(default="", max_length=8000)
    team_id: UUID | None = None
    assets: DecisionAssets
    candidates: list[AppsRankCandidate] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def bounded_images_and_candidates(self) -> "RankAppsResults":
        if not self.assets:
            raise ValueError("Image relevance requires image assets")
        if len({candidate.id for candidate in self.candidates}) != len(self.candidates):
            raise ValueError("Candidate IDs must be unique")
        if len(json.dumps(self.model_dump(mode="json"), ensure_ascii=False, allow_nan=False).encode()) > MAX_DECISION_BODY_BYTES:
            raise ValueError("Request exceeds image body limit")
        return self


def _rate_key(request: Request) -> str:
    auth = getattr(request.state, "auth_info", {})
    if isinstance(auth, dict) and auth.get("user_id"):
        return "apps-interpret:" + hashlib.sha256(str(auth["user_id"]).encode()).hexdigest()
    from backend.core.api.app.routes.anonymous import _anonymous_client_ip
    return "apps-interpret-ip:" + hashlib.sha256(_anonymous_client_ip(request).encode()).hexdigest()


def _require_first_party(request: Request) -> None:
    auth = getattr(request.state, "auth_info", {})
    if not isinstance(auth, dict) or not (
        auth.get("auth_source") == "session"
        or auth.get("auth_source") == "api_key" and auth.get("device_hash")
    ):
        raise HTTPException(403, "FIRST_PARTY_AUTH_REQUIRED")


async def _admit(request: Request, user_id: str, request_id: UUID) -> Any:
    try:
        client = await request.app.state.cache_service.client
        if client is None:
            raise RuntimeError("Admission unavailable")
        owner = hashlib.sha256(user_id.encode()).hexdigest()
        operation = hashlib.sha256(f"{user_id}:{request_id}".encode()).hexdigest()
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        admitted = await client.eval(_ADMIT, 3, f"apps-interpret:request:{operation}",
                                     f"apps-interpret:daily:{day}:{owner}", f"apps-interpret:daily:{day}:global")
    except Exception as exc:
        raise HTTPException(503, "INTERPRETATION_ADMISSION_UNAVAILABLE") from exc
    if admitted == -1:
        raise HTTPException(409, "REQUEST_ALREADY_INTERPRETED")
    if admitted != 1:
        raise HTTPException(429, "INTERPRETATION_DAILY_LIMIT", headers={"Retry-After": "3600"})
    return client


async def _catalog(request: Request, app_id: str, *, anonymous: bool = False) -> list[AppsRequestSkill]:
    from backend.core.api.app.services.workflow_capability_registry import WorkflowCapabilityRegistry
    metadata = getattr(request.app.state, "discovered_apps_metadata", {}).get(app_id)
    if metadata is None:
        raise HTTPException(404, "APP_NOT_FOUND")
    registry = getattr(request.app.state, "skill_registry", None)
    capabilities = WorkflowCapabilityRegistry(skill_registry=registry) if registry else None
    result = []
    for skill in metadata.skills or []:
        if anonymous:
            from backend.shared.python_utils.anonymous_skill_policy import is_anonymous_inline_skill
            if not is_anonymous_inline_skill(app_id, skill):
                continue
        if skill.internal:
            continue
        capability = capabilities.get_capability(f"{app_id}.{skill.id}") if capabilities else None
        executable, _, _ = execution_status(app_id=app_id, skill=skill, registry=registry, capability=capability)
        schema = request_schema(skill)
        if executable and schema:
            result.append(AppsRequestSkill(skill.id, skill.preprocessor_hint or skill.id.replace("_", " "), schema))
    return result[:40]


async def _request_actor(request: Request, response: Response,
                         refresh_token: str | None = Cookie(default=None, alias="auth_refresh_token", include_in_schema=False)) -> User | None:
    # Invalid supplied credentials must never silently downgrade to guest access.
    if refresh_token or request.headers.get("Authorization"):
        return await get_current_user_or_api_key(
            request=request, response=response, directus_service=request.app.state.directus_service,
            cache_service=request.app.state.cache_service, refresh_token=refresh_token,
        )
    return None


def _anonymous_tariffs(request: Request) -> tuple[dict[str, Any], dict[str, Any]]:
    from backend.core.api.app.utils.config_manager import ConfigManager
    config = getattr(request.app.state, "config_manager", None) or ConfigManager()
    jev = config.get_model_pricing("typesafe", "jev-1.14")
    mercury = config.get_model_pricing("inception", "mercury-3")
    if not jev or not mercury:
        raise HTTPException(503, "INTERPRETATION_PRICING_UNAVAILABLE")
    return jev, mercury


async def _anonymous_admission(request: Request, body: InterpretAppsRequest,
                               skills: list[AppsRequestSkill]) -> tuple[Any, str, Any, tuple[dict[str, Any], dict[str, Any]]]:
    from backend.core.api.app.routes.anonymous import (
        _anonymous_client_ip, _anonymous_header_id, _anonymous_usage_service,
        _allowance_denial, _require_official_cloud, _reject_anonymous_skill_references,
    )
    from backend.shared.python_utils.billing_utils import calculate_total_credits
    _require_official_cloud(request)
    if body.team_id or body.assets or body.attachments or body.context and (body.context.embed_id or body.context.chat_id):
        raise HTTPException(403, "ANONYMOUS_PRIVATE_CONTEXT_UNAVAILABLE")
    if body.context:
        _reject_anonymous_skill_references(body.context.model_dump(mode="json", exclude_none=True))
    usage = _anonymous_usage_service(request.app.state.directus_service, request.app.state.cache_service)
    ip = _anonymous_client_ip(request)
    anonymous_id = _anonymous_header_id(request)
    identity = usage.request_identity(None, ip)
    try:
        allowed = await usage.consume_local_rate_limit(f"apps-interpret:{identity}", max_requests=10)
    except Exception as exc:
        raise HTTPException(503, "INTERPRETATION_ADMISSION_UNAVAILABLE") from exc
    if not allowed:
        raise HTTPException(429, "INTERPRETATION_RATE_LIMIT")
    client = await _admit(request, identity, body.request_id)
    tariffs = _anonymous_tariffs(request)
    # Jev allows <=30k estimated input tokens per transport, two logical calls
    # and at most two hosts per call. UTF-8 bytes conservatively bound Mercury's
    # input tokens, including the largest selected schema and static framing.
    mercury_bound = len(json.dumps(body.model_dump(mode="json"), ensure_ascii=False).encode("utf-8")) + max(
        len(json.dumps(skill.schema, ensure_ascii=False).encode("utf-8")) for skill in skills
    ) + 8192
    quote = calculate_total_credits(pricing_config=tariffs[0], input_tokens=120_000, output_tokens=0) + calculate_total_credits(
        pricing_config=tariffs[1], input_tokens=mercury_bound, output_tokens=4096,
    )
    # Server-derived identity prevents one guest reusing another guest's ledger.
    operation_id = "apps-interpret:" + hashlib.sha256(f"{identity}:{body.request_id}".encode()).hexdigest()
    try:
        parent_id = operation_id.replace("apps-interpret:", "apps-interpret-request:", 1)
        admission = await usage.open_request(request_id=parent_id, anonymous_id=anonymous_id, ip_address=ip)
        if not admission.accepted:
            raise HTTPException(429, _allowance_denial(admission.reason))
        reservation = await usage.reserve_operation(
            parent_request_id=parent_id, operation_id=operation_id, charge_id=operation_id, quoted_credits=quote,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, "INTERPRETATION_ADMISSION_UNAVAILABLE") from exc
    if not reservation.accepted:
        raise HTTPException(429, _allowance_denial(reservation.reason))
    return usage, operation_id, client, tariffs


async def _settle_anonymous(usage: Any, operation_id: str, service: AppsWorkspaceRequestService,
                            tariffs: tuple[dict[str, Any], dict[str, Any]]) -> None:
    from backend.shared.python_utils.billing_utils import calculate_total_credits
    # Ambiguous transport attempts retain their hold for the existing expiry
    # path; missing provider usage must never silently make paid work free.
    if (not service.accounting or any(not row.get("success") or row.get("input_tokens") is None for row in service.accounting)
            or service.mercury_dispatched and not service.mercury_usage):
        return
    actual = calculate_total_credits(pricing_config=tariffs[0],
                                    input_tokens=sum(row.get("input_tokens") or 0 for row in service.accounting), output_tokens=0)
    if service.mercury_dispatched:
        actual += calculate_total_credits(pricing_config=tariffs[1],
                                          input_tokens=service.mercury_usage["input_tokens"],
                                          output_tokens=service.mercury_usage["output_tokens"])
    try:
        await usage.finalize_charge(operation_id, actual_credits=actual)
    except Exception as exc:
        raise HTTPException(503, "INTERPRETATION_SETTLEMENT_UNAVAILABLE") from exc


@router.post("/interpret")
@limiter.limit("10/minute", key_func=_rate_key)
async def interpret_apps_request(body: InterpretAppsRequest, request: Request,
                                 user: User | None = Depends(_request_actor)) -> dict[str, Any]:
    if body.expected_user_id is not None and (user is None or str(body.expected_user_id) != user.id):
        raise HTTPException(409, "APPS_REQUEST_ACCOUNT_CHANGED")
    if user is not None:
        _require_first_party(request)
    if user is not None and body.team_id:
        try:
            await request.app.state.directus_service.team.require_team_role(
                str(body.team_id), user.id, {"owner", "admin", "member"},
            )
        except TeamPermissionError as exc:
            raise HTTPException(403, "TEAM_PERMISSION_DENIED") from exc
    skills = await _catalog(request, body.app_id, anonymous=user is None)
    if not skills:
        return {"request_id": str(body.request_id), "action": "chat", "reason": "NO_DIRECT_SKILL"}
    anonymous_usage = None
    if user is None:
        anonymous_usage, operation_id, client, tariffs = await _anonymous_admission(request, body, skills)
    else:
        client = await _admit(request, user.id, body.request_id)
    service = AppsWorkspaceRequestService(request.app.state.secrets_manager)
    result = await service.interpret(
        request_id=str(body.request_id), app_id=body.app_id, text=body.text, skills=skills,
        timezone=body.timezone, locale=body.locale,
        context=body.context.model_dump(mode="json") if body.context else None,
        attachments=body.attachments, assets={key: value.model_dump() for key, value in body.assets.items()},
    )
    if anonymous_usage is not None:
        await _settle_anonymous(anonymous_usage, operation_id, service, tariffs)
        if result.get("action") == "execute":
            from backend.core.api.app.routes.anonymous import _reject_anonymous_skill_references
            from backend.shared.python_utils.anonymous_skill_policy import has_single_anonymous_provider_request
            _reject_anonymous_skill_references(result["input"])
            if not has_single_anonymous_provider_request(body.app_id, result["skill_id"], result["input"]):
                result = {"request_id": str(body.request_id), "action": "chat", "reason": "ANONYMOUS_SINGLE_REQUEST_REQUIRED"}
    # Numeric supplier usage only. This is internal cost accounting, never an
    # extra customer charge, and failure cannot invalidate an interpreted input.
    try:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for provider, usage in (("jev", {"input_tokens": sum(row.get("input_tokens") or 0 for row in service.accounting),
                                         "output_tokens": sum(row.get("output_tokens") or 0 for row in service.accounting)}),
                                ("mercury", service.mercury_usage)):
            for kind in ("input_tokens", "output_tokens"):
                key = f"apps-interpret:usage:{day}:{provider}:{kind}"
                await client.incrby(key, usage.get(kind, 0))
                await client.expire(key, 172800)
    except Exception:
        pass
    if user is not None:
        try:
            from backend.core.api.app.services.apps_workspace_recommendations_store import AppsRecommendationsStore
            await AppsRecommendationsStore().mark_activity(user.id)
        except (RuntimeError, OSError):
            pass
    return result


@router.post("/rank")
@limiter.limit("10/minute", key_func=_rate_key)
async def rank_apps_results(body: RankAppsResults, request: Request,
                            user: User | None = Depends(_request_actor)) -> dict[str, Any]:
    # This image-dependent first-party helper cannot expand guest upload rights.
    if user is None:
        raise HTTPException(401, "FIRST_PARTY_AUTH_REQUIRED")
    _require_first_party(request)
    if body.expected_user_id is not None and str(body.expected_user_id) != user.id:
        raise HTTPException(409, "APPS_REQUEST_ACCOUNT_CHANGED")
    if body.team_id:
        try:
            await request.app.state.directus_service.team.require_team_role(
                str(body.team_id), user.id, {"owner", "admin", "member"},
            )
        except TeamPermissionError as exc:
            raise HTTPException(403, "TEAM_PERMISSION_DENIED") from exc
    if body.app_id not in getattr(request.app.state, "discovered_apps_metadata", {}):
        raise HTTPException(404, "APP_NOT_FOUND")
    client = await _admit(request, user.id, body.request_id)
    service = AppsWorkspaceRequestService(request.app.state.secrets_manager)
    result = await service.rank(request_id=str(body.request_id), app_id=body.app_id, text=body.text,
                                assets={key: value.model_dump() for key, value in body.assets.items()},
                                candidates=[candidate.model_dump() for candidate in body.candidates])
    try:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for kind in ("input_tokens", "output_tokens"):
            key = f"apps-interpret:usage:{day}:jev:{kind}"
            await client.incrby(key, sum(row.get(kind) or 0 for row in service.accounting))
            await client.expire(key, 172800)
    except Exception:
        pass
    return result
