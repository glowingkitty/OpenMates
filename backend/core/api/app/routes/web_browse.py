"""First-party Browse execution and ephemeral browser controls.

Hidden from public developer API documentation. Session auth or an approved
device credential is required; broad API keys and shared viewers cannot enter.
Every operation rechecks the owner and is rate limited before paid work.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from backend.shared.python_schemas.web_browse import (
    BrowseControl,
    BrowseRequest,
    owner_hash,
)
from backend.core.api.app.services.web_browse_service import BrowseService


class PrivateBrowserRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                response = await original(request)
            except RequestValidationError:
                raise HTTPException(422, "Invalid browser request.") from None
            response.headers["Cache-Control"] = "no-store, private"
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response

        return handler


router = APIRouter(include_in_schema=False, route_class=PrivateBrowserRoute)


class BrowseClientRequest(BrowseRequest):
    chat_id: UUID
    message_id: UUID


async def current_actor(
    request: Request,
    response: Response,
    refresh_token: str | None = Cookie(
        None, alias="auth_refresh_token", include_in_schema=False
    ),
) -> Any:
    from backend.core.api.app.routes.auth_routes.auth_dependencies import (
        get_current_user_or_api_key,
    )

    user = await get_current_user_or_api_key(
        request,
        response,
        request.app.state.directus_service,
        request.app.state.cache_service,
        refresh_token,
    )
    info = getattr(request.state, "auth_info", {}) or {}
    if info.get("auth_source") == "api_key":
        if not info.get("device_hash"):
            raise HTTPException(
                403, "An approved first-party device is required for Browse."
            )
        from backend.core.api.app.services.api_key_authorization import (
            ApiKeyAuthorizationService,
            ApiKeyScopeError,
        )

        try:
            ApiKeyAuthorizationService().require_app_skill_scope(
                info.get("api_key_metadata") or {}, "web", "browse"
            )
        except ApiKeyScopeError:
            raise HTTPException(
                403, "This device is not authorized to use Browse."
            ) from None
    return user


def service(request: Request) -> BrowseService:
    state = request.app.state
    registry = state.skill_registry
    web = registry.apps.get("web")
    if not web or not registry.is_skill_available("web", "browse"):
        raise HTTPException(503, "Browse is currently unavailable.")
    return BrowseService(
        app=web,
        directus=state.directus_service,
        encryption=state.encryption_service,
        cache=state.cache_service,
        secrets_manager=state.secrets_manager,
    )


async def rate_limit(
    request: Request, user_id: str, operation: str, limit: int
) -> None:
    redis = await request.app.state.cache_service.client
    key = "web_browse:rate:" + owner_hash(user_id) + ":" + operation
    count = await redis.eval(
        "local n=redis.call('incr',KEYS[1]); if n==1 then redis.call('expire',KEYS[1],60) end; return n",
        1,
        key,
    )
    if count > limit:
        raise HTTPException(
            429,
            "Too many browser operations; wait before retrying.",
            headers={"Retry-After": "60"},
        )


@router.post("/v1/apps/web/skills/browse")
async def browse(
    body: BrowseClientRequest, request: Request, actor: Any = Depends(current_actor)
) -> dict[str, Any]:
    await rate_limit(request, actor.id, "run", 6)
    db = request.app.state.directus_service
    metadata = await db.chat.get_chat_metadata(str(body.chat_id), admin_required=True)
    if not metadata or not await db.chat.check_chat_ownership(
        str(body.chat_id), actor.id, authoritative_metadata=metadata
    ):
        raise HTTPException(404, "The originating chat is unavailable.")
    request_data = BrowseRequest.model_validate(
        body.model_dump(exclude={"chat_id", "message_id"})
    )
    info = getattr(request.state, "auth_info", {}) or {}

    async def check_budget(credits: int) -> None:
        from backend.core.api.app.routes.apps_api import (
            require_api_key_budget_for_charge,
        )

        await require_api_key_budget_for_charge(
            db, user_info={**info, "user_id": actor.id}, requested_credits=credits
        )

    result = await service(request).run(
        request_data,
        user_id=actor.id,
        chat_id=str(body.chat_id),
        message_id=str(body.message_id),
        vault_key_id=actor.vault_key_id,
        billing_actor={k: info.get(k) for k in ("api_key_hash", "device_hash")},
        budget_check=check_budget,
        prepare_only=True,
    )
    from backend.shared.python_utils.chat_recovery_context import (
        AuthenticatedDirectSkill,
        active_authenticated_direct_skill,
    )
    from backend.shared.python_utils.web_browse_dispatch import dispatch_browser_job
    from backend.core.api.app.tasks.celery_config import app as producer

    token = active_authenticated_direct_skill.set(
        AuthenticatedDirectSkill(
            owner_id=actor.id,
            owner_hash=owner_hash(actor.id),
            app_id="web",
            skill_id="browse",
        )
    )
    try:
        job = await dispatch_browser_job(
            result,
            producer=producer,
            user_id=actor.id,
            chat_id=str(body.chat_id),
            message_id=str(body.message_id),
            vault_key_id=actor.vault_key_id,
            external_request=True,
        )
        return job.model_dump()
    finally:
        active_authenticated_direct_skill.reset(token)


@router.get("/v1/apps/web/browse/{session_id}")
async def state(
    session_id: UUID, request: Request, actor: Any = Depends(current_actor)
) -> dict[str, Any]:
    await rate_limit(request, actor.id, "state", 90)
    return await service(request).state(str(session_id), actor.id)


@router.get("/v1/apps/web/browse/{session_id}/frame")
async def frame(
    session_id: UUID, request: Request, actor: Any = Depends(current_actor)
) -> Response:
    await rate_limit(request, actor.id, "frame", 90)
    image = await service(request).frame(str(session_id), actor.id)
    return Response(
        image,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store, private",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/v1/apps/web/browse/{session_id}/control")
async def control(
    session_id: UUID,
    body: BrowseControl,
    request: Request,
    actor: Any = Depends(current_actor),
) -> dict[str, Any]:
    await rate_limit(request, actor.id, "control", 120)
    return await service(request).control(str(session_id), actor.id, body)
