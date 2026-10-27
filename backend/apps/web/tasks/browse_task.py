"""Detached Browse execution, encrypted results, and ordinary assistant continuation."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app
from backend.shared.python_schemas.web_browse import (
    BrowseRequest,
    owner_hash,
)
from backend.shared.python_utils.private_inference_logging import (
    private_inference_logging,
)


@app.task(
    bind=True,
    name="web.browse.refill",
    base=BaseServiceTask,
    queue="app_code",
    soft_time_limit=100,
    time_limit=120,
)
def refill_browser_pool(self: BaseServiceTask) -> dict[str, int]:
    async def run():
        from backend.core.api.app.services.web_browse_pool import BrowsePool, pool_size
        from backend.core.api.app.services.web_browse_service import BrowseStore
        from backend.shared.providers.e2b_browser import E2BBrowser
        from backend.shared.providers.e2b_code_runner import get_e2b_api_key_async

        if not pool_size():
            return {"prepared": 0}
        try:
            await self.initialize_core_services()
            store = BrowseStore(
                self.directus_service, self.encryption_service, self.cache_service
            )
            driver = E2BBrowser(await get_e2b_api_key_async(self.secrets_manager))
            with private_inference_logging():
                return {"prepared": await BrowsePool(store, driver).refill()}
        finally:
            await self.cleanup_services()

    return asyncio.run(run())


@app.task(
    bind=True,
    name="apps.web.tasks.skill_browse",
    base=BaseServiceTask,
    queue="app_code",
    soft_time_limit=820,
    time_limit=880,
)
def browse_task(
    self: BaseServiceTask, app_id: str, skill_id: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    return asyncio.run(execute_browser_job(self, arguments))


async def execute_browser_job(
    worker: BaseServiceTask, arguments: dict[str, Any]
) -> dict[str, Any]:
    from backend.core.api.app.services.skill_registry import get_global_registry
    from backend.core.api.app.services.web_browse_service import BrowseService
    from backend.core.api.app.services.embed_service import EmbedService
    from backend.apps.ai.tasks.async_skill_continuation import (
        dispatch_async_skill_continuation,
    )

    try:
        await worker.initialize_services()
        service = BrowseService(
            app=get_global_registry().apps["web"],
            directus=worker.directus_service,
            encryption=worker.encryption_service,
            cache=worker.cache_service,
            secrets_manager=worker.secrets_manager,
        )
        user_id, chat_id, message_id = (
            arguments[k] for k in ("user_id", "chat_id", "message_id")
        )
        session_id, run_id = arguments["session_id"], arguments["run_id"]
        record = await service.store.load(session_id, user_id, chat_id)
        request = BrowseRequest.model_validate(record["request"])
        with private_inference_logging():
            try:
                result = await service.run(
                    request,
                    user_id=user_id,
                    chat_id=chat_id,
                    message_id=message_id,
                    vault_key_id=arguments["user_vault_key_id"],
                    prepared_run_id=run_id,
                )
            except Exception:
                # A stopped queue admission must still resolve the skill embed;
                # restoring a terminal result never starts provider work.
                result = await service.finish_failed_job(
                    session_id, run_id, user_id, chat_id
                )
            payload = result.model_dump()
        if not arguments.get("external_request"):
            await EmbedService(
                cache_service=worker.cache_service,
                directus_service=worker.directus_service,
                encryption_service=worker.encryption_service,
            ).update_embed_with_results(
                embed_id=arguments["embed_id"],
                app_id="web",
                skill_id="browse",
                # The shared TOON table flattens dictionaries. Keep arbitrary
                # structured output lossless (underscores, nulls, empty arrays)
                # for saved embeds without trying to reverse that flattening.
                results=[{**payload, "data_json": json.dumps(payload["data"], ensure_ascii=False)}],
                chat_id=chat_id,
                message_id=message_id,
                user_id=user_id,
                user_id_hash=owner_hash(user_id),
                user_vault_key_id=arguments["user_vault_key_id"],
                task_id=worker.request.id,
                request_metadata={
                    "task": request.task,
                    "session_id": session_id,
                    "run_id": run_id,
                },
            )
            model_payload = {
                k: v
                for k, v in payload.items()
                if k not in ("screenshot_base64", "metrics", "observations")
            }
            await dispatch_async_skill_continuation(
                cache_service=worker.cache_service,
                async_task_id=worker.request.id,
                completed_results=[model_payload],
                request_metadata={
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "same_turn_batch_id": arguments.get("same_turn_batch_id"),
                },
            )
        return {
            "browse_session_id": session_id,
            "browse_run_id": run_id,
            "user_id_hash": owner_hash(user_id),
        }
    finally:
        await worker.cleanup_services()
