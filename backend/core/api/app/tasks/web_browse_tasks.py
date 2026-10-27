"""Independent idle cleanup: never resumes browser compute or runs inference."""

from __future__ import annotations

import asyncio

from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app


@app.task(name="web.browse.sweep", base=BaseServiceTask, bind=True)
def sweep_browser_sessions(self: BaseServiceTask) -> dict[str, int]:
    async def run() -> dict[str, int]:
        try:
            await self.initialize_services()
            from backend.core.api.app.services.skill_registry import get_global_registry
            from backend.core.api.app.services.web_browse_service import BrowseService

            web = get_global_registry().apps.get("web")
            if not web:
                return {"processed": 0}
            service = BrowseService(
                app=web,
                directus=self.directus_service,
                encryption=self.encryption_service,
                cache=self.cache_service,
                secrets_manager=self.secrets_manager,
            )
            return {"processed": await service.sweep()}
        finally:
            await self.cleanup_services()

    return asyncio.run(run())
