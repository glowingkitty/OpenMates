"""Private Apps daily runner. Broker arguments/results contain no search data."""
from __future__ import annotations

import asyncio
from typing import Any

from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.services.apps_workspace_recommendations_service import AppsWorkspaceRecommendationsService
from backend.core.api.app.services.apps_workspace_recommendations_store import AppsRecommendationsStore
from backend.core.api.app.services.workflow_app_skill_adapter import WorkflowAppSkillAdapter
from backend.core.api.app.tasks.celery_config import app
from backend.shared.python_utils.private_inference_logging import private_inference_logging


class AppsRecommendationsTask(BaseServiceTask):
    async def initialize_services(self) -> None:
        await self.initialize_core_services()


@app.task(name="apps_workspace.refresh_daily", base=AppsRecommendationsTask, bind=True,
          soft_time_limit=900, time_limit=930, ignore_result=True)
def refresh_daily(self: Any, limit: int = 100) -> dict[str, int]:
    async def operation() -> dict[str, int]:
        with private_inference_logging():
            try:
                await self.initialize_services()
                adapter = WorkflowAppSkillAdapter(directus_service=self.directus_service,
                    secrets_manager=self.secrets_manager, cache_service=self.cache_service)
                service = AppsWorkspaceRecommendationsService(self.directus_service, self.encryption_service, adapter=adapter)
                return await service.refresh_daily(limit=min(max(limit, 1), 100))
            finally:
                await self.cleanup_services()
    return asyncio.run(operation())


@app.task(name="apps_workspace.cleanup_expired", ignore_result=True)
def cleanup_expired() -> dict[str, int]:
    async def operation() -> dict[str, int]:
        from backend.core.api.app.services.apps_workspace_public_service import AppsWorkspacePublicService
        deleted = await AppsRecommendationsStore().cleanup()
        deleted += await AppsWorkspacePublicService().store.cleanup()
        return {"deleted": deleted}
    return asyncio.run(operation())


@app.task(name="apps_workspace.refresh_public", base=AppsRecommendationsTask, bind=True,
          soft_time_limit=900, time_limit=930, ignore_result=True)
def refresh_public(self: Any) -> dict[str, int]:
    async def operation() -> dict[str, int]:
        from backend.core.api.app.services.apps_workspace_public_service import AppsWorkspacePublicService
        try:
            await self.initialize_services()
            adapter = WorkflowAppSkillAdapter(secrets_manager=self.secrets_manager, cache_service=self.cache_service)
            return await AppsWorkspacePublicService(adapter=adapter, directus=self.directus_service).refresh_all()
        finally:
            await self.cleanup_services()
    return asyncio.run(operation())
