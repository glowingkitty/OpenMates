"""OpenMates-funded public discovery: fixed versioned queries, no user context.

Only the public daily-default video pool may be reused, never personalized pool
rows. Publication keeps one batch per allowlisted app, without user identifiers.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path
import time
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from backend.core.api.app.services.apps_workspace_recommendations_store import AppsRecommendationsStore

logger = logging.getLogger(__name__)
DAY = 86400
QUERY_VERSION = "2026-10-20.1"
# This is an editorial allowlist, independent of account, locale, location,
# browser headers, saved searches, memories, projects, or billing identity.
PUBLIC_QUERIES = {
    "code": {"skill_id": "search_repos", "parameters": {"requests": [{"query": "stars:>1000", "count": 6}]},
             "en": ("Explore active open source projects", "Show active open source projects"),
             "de": ("Aktive Open-Source-Projekte entdecken", "Zeige aktive Open-Source-Projekte")},
    "news": {"skill_id": "search", "parameters": {"requests": [{"query": "science technology discoveries", "count": 6}]},
             "en": ("Explore science and technology news", "Show science and technology news"),
             "de": ("Nachrichten aus Wissenschaft und Technik", "Zeige Nachrichten aus Wissenschaft und Technik")},
    "videos": {"skill_id": "search", "parameters": {"requests": [{"query": "science documentary discoveries", "count": 6}]},
               "en": ("Discover science videos", "Show science documentaries"),
               "de": ("Wissenschaftsvideos entdecken", "Zeige Wissenschaftsdokumentationen")},
    "models3d": {"skill_id": "search", "parameters": {"requests": [{"query": "desk organizer", "sort": "popular", "free_only": True, "count": 6}]},
                 "en": ("Explore popular free 3D models", "Show popular free desk organizer 3D models"),
                 "de": ("Beliebte kostenlose 3D-Modelle", "Zeige beliebte kostenlose 3D-Modelle für Schreibtisch-Organizer")},
}


def public_search_input(app_id: str, now: int) -> dict[str, Any]:
    """Derive only editorial UTC recency; never request/user-dependent context."""
    parameters = deepcopy(PUBLIC_QUERIES[app_id]["parameters"])
    if app_id == "code":
        cutoff = (datetime.fromtimestamp(now, timezone.utc) - timedelta(days=7)).date().isoformat()
        parameters["requests"][0]["query"] += f" pushed:>{cutoff}"
    return parameters


class AppsWorkspacePublicService:
    def __init__(self, *, store: AppsRecommendationsStore | None = None, adapter: Any = None, directus: Any = None) -> None:
        if store is None:
            directory = os.environ.get("APPS_RECOMMENDATIONS_DIR")
            if not directory:
                raise RuntimeError("APPS_RECOMMENDATIONS_DIR is required")
            store = AppsRecommendationsStore(Path(directory) / "public")
        self.store, self.adapter, self.directus = store, adapter, directus

    async def library(self, app_id: str, language: str = "en", *, now: int | None = None) -> dict[str, Any]:
        now = int(time.time()) if now is None else now
        definition = PUBLIC_QUERIES.get(app_id)
        language = "de" if language == "de" else "en"
        response = {"app_id": app_id, "query_version": QUERY_VERSION, "created_at": None,
                    "expires_at": None, "recommendations": [], "cta": None}
        if definition is None:
            return response
        label, query = definition[language]
        response["cta"] = {"label": label, "query": query}
        scope = self.store.scope("public", app_id, None)
        async with self.store.locked(scope):
            self.store.expire_batch(scope, now)
            batch = self.store.read(scope, "batch")
        if batch and batch.get("query_version") == QUERY_VERSION:
            response.update({"created_at": batch["created_at"], "expires_at": batch["expires_at"]})
            recommendation = {**batch, "title": label, "request_text": query, "query": query}
            response["recommendations"] = [recommendation]
        return response

    async def _published_video_results(self, now: int) -> dict[str, Any] | None:
        """Reuse only today's already-public defaults, with external media fields.

        Private-derived phrases and assistant responses are never copied. The
        public defaults selection already applies publication/content checks.
        """
        if self.directus is None:
            return None
        defaults = getattr(self.directus, "inspiration_defaults", None)
        if defaults is None:
            return None
        date = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
        entries = await defaults.get_defaults_for_date(date, "en")
        results = []
        for row in entries:
            video_id = row.get("youtube_id")
            if row.get("content_type", "video") != "video" or row.get("category") != "science" or not video_id:
                continue
            # Only factual external video metadata from the published pool.
            results.append({"id": video_id, "video_id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}",
                "title": row.get("video_title") or "", "thumbnail_url": row.get("video_thumbnail_url"),
                "channel_name": row.get("video_channel_name"), "duration_seconds": row.get("video_duration_seconds")})
        return {"results": results[:6], "source": "public_daily_inspiration_defaults"} if results else None

    async def refresh(self, app_id: str, *, now: int | None = None) -> bool:
        now = int(time.time()) if now is None else now
        definition = PUBLIC_QUERIES.get(app_id)
        if definition is None:
            return False
        scope = self.store.scope("public", app_id, None)
        async with self.store.locked(scope):
            self.store.expire_batch(scope, now)
            meta = self.store.read(scope, "meta") or {}
            if meta.get("last_attempt_at", 0) > now - DAY:
                return False
            # Content-free durable claim caps OpenMates provider spend, even
            # after duplicate scheduler deliveries or failed provider requests.
            self.store.write(scope, "meta", {"last_attempt_at": now, "query_version": QUERY_VERSION})
        parameters = public_search_input(app_id, now)
        result = await self._published_video_results(now) if app_id == "videos" else None
        if result is None:
            if self.adapter is None:
                from backend.core.api.app.services.workflow_app_skill_adapter import WorkflowAppSkillAdapter
                self.adapter = WorkflowAppSkillAdapter()
            # No user_id, Team context, model override or billing_context. This
            # fixed editorial run is paid from OpenMates provider accounts.
            result = await self.adapter.execute(app_id, definition["skill_id"], deepcopy(parameters))
        if not isinstance(result, dict) or result.get("error") or result.get("success") is False:
            return False
        batch = {"id": str(uuid5(NAMESPACE_URL, f"apps-public:{QUERY_VERSION}:{app_id}:{now}")),
                 "skill_id": definition["skill_id"], "query_version": QUERY_VERSION,
                 "input": parameters, "created_at": now, "expires_at": now + DAY,
                 "result": result}
        async with self.store.locked(scope):
            self.store.write(scope, "batch", batch)
        return True

    async def refresh_all(self) -> dict[str, int]:
        refreshed = failed = 0
        await self.store.cleanup()
        for app_id in PUBLIC_QUERIES:
            try:
                refreshed += int(await self.refresh(app_id))
            except Exception:
                failed += 1
                logger.warning("Public Apps discovery refresh failed app=%s", app_id)
        return {"refreshed": refreshed, "failed": failed}
