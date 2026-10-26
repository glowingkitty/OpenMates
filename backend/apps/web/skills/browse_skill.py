"""Browse — bounded, owner-scoped interactive browsing in E2B.

Architecture: docs/plans/web-browse/plan.yml
The shared service owns execution and its cumulative supplier-cost ledger.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from backend.apps.base_skill import BaseSkill
from backend.shared.python_schemas.web_browse import BrowseRequest, BrowseJob


class BrowseSkill(BaseSkill):
    async def execute(
        self,
        task: str,
        start_url: str | None = None,
        session_id: str | None = None,
        max_steps: int = 40,
        timeout_seconds: int = 180,
        max_credits: int = 250,
        output_schema: dict[str, Any] | None = None,
        *,
        secrets_manager: Any = None,
        cache_service: Any = None,
        encryption_service: Any = None,
        user_id: str | None = None,
        chat_id: str | None = None,
        message_id: str | None = None,
        user_vault_key_id: str | None = None,
        external_request: bool = False,
        **kwargs: Any,
    ) -> BrowseJob:
        # Broad developer skill execution has no browser/chat authority. Official
        # clients use the authenticated custom route, which validates the chat.
        if external_request:
            raise HTTPException(
                403, "Browse requires an authenticated first-party chat."
            )
        if not self.celery_producer:
            raise HTTPException(503, "Browser execution is temporarily unavailable.")
        from backend.shared.python_utils.volatile_embed_authority import (
            active_volatile_ai_context,
        )

        if active_volatile_ai_context.get() is not None:
            raise HTTPException(
                409,
                "Start Browse in a saved chat so its session can be restored safely.",
            )
        if not all(
            (
                user_id,
                chat_id,
                message_id,
                user_vault_key_id,
                cache_service,
                encryption_service,
                secrets_manager,
            )
        ):
            raise HTTPException(
                401,
                "Browse requires an authenticated chat and encrypted session storage.",
            )
        from backend.core.api.app.services.directus import DirectusService
        from backend.core.api.app.services.web_browse_service import BrowseService

        request = BrowseRequest(
            task=task,
            start_url=start_url,
            session_id=session_id,
            max_steps=max_steps,
            timeout_seconds=timeout_seconds,
            max_credits=max_credits,
            output_schema=output_schema,
        )
        service = BrowseService(
            app=self.app,
            directus=DirectusService(
                cache_service=cache_service, encryption_service=encryption_service
            ),
            encryption=encryption_service,
            cache=cache_service,
            secrets_manager=secrets_manager,
        )
        job = await service.run(
            request,
            user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
            vault_key_id=user_vault_key_id,
            prepare_only=True,
        )
        from backend.shared.python_utils.web_browse_dispatch import dispatch_browser_job

        placeholders = kwargs.get("placeholder_embed_ids") or []
        return await dispatch_browser_job(
            job,
            producer=self.celery_producer,
            user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
            vault_key_id=user_vault_key_id,
            embed_id=placeholders[0] if placeholders else None,
            same_turn_batch_id=kwargs.get("same_turn_batch_id"),
        )
