# backend/core/api/app/services/skill_registry.py
#
# In-process app + skill registry. Replaces the per-app FastAPI containers
# (one Uvicorn per backend/apps/{name}/) with a single in-process map of
# {app_id: BaseApp instance}, dispatched directly via Python method calls.
#
# Why this exists:
#   The 20 sync app-* containers were 130 MiB-each idle Python wrappers around
#   a single skill_class.execute() call. They burned ~2.6 GiB of RAM, added
#   ~10 ms per skill call (HTTP serialization), and required a 60-line
#   docker-compose entry per new app — a trip-wire that silently broke
#   nutrition.search_recipes (chat 4ac73800-fb16-4a76-8ae4-2019d0706c9a) when
#   the entry was forgotten. They also provided NONE of their claimed benefits
#   (independent scaling, fault isolation, dependency isolation).
#
# How it works:
#   1. At api startup, discover_apps() in main.py filesystem-scans
#      backend/apps/*/app.yml, applies stage filtering, then constructs a
#      BaseApp(register_http_routes=False, preloaded_config_dict=...) per app.
#      Each BaseApp resolves its skill class_path strings via importlib at
#      construction time.
#   2. discover_apps() registers each BaseApp in the global SkillRegistry.
#   3. The REST handler in apps_api.call_app_skill() dispatches to the
#      registry instead of HTTPing to app-{id}:8000/skills/{id}.
#   4. Celery workers (app-ai-worker etc.) build their own SkillRegistry
#      instance at worker_process_init time using the same flow, then call
#      it directly from skill_executor.execute_skill().
#
# Architecture: docs/architecture/apps/app-skills.md (in-process loading)
# Linear: OPE-342

import logging
import os
from typing import Any, Dict, List, Optional

import yaml
from fastapi import HTTPException

from backend.apps.base_app import BaseApp
from backend.shared.python_schemas.app_metadata_schemas import AppYAML

logger = logging.getLogger(__name__)

# Path inside every container that has backend/apps/ mounted
APPS_DIR = "/app/backend/apps"


def scan_filesystem_for_apps(apps_dir: str = APPS_DIR) -> List[str]:
    """
    Scan the apps directory for subdirectories containing an app.yml file.
    Returns the list of app IDs (directory names). Used by both api startup
    and Celery worker_process_init.
    """
    app_ids: List[str] = []
    if not os.path.isdir(apps_dir):
        logger.warning(f"[SkillRegistry] Apps directory not found: {apps_dir}")
        return app_ids
    try:
        for item in sorted(os.listdir(apps_dir)):
            item_path = os.path.join(apps_dir, item)
            if os.path.isdir(item_path) and os.path.isfile(os.path.join(item_path, "app.yml")):
                app_ids.append(item)
    except OSError as e:
        logger.error(f"[SkillRegistry] Error scanning apps directory {apps_dir}: {e}")
    return app_ids


def filter_app_components_by_stage(
    app_metadata_json: Dict[str, Any],
    server_environment: str,
) -> Optional[Dict[str, Any]]:
    """
    Filter an app's raw config dict by component stage. Returns the filtered
    dict, or None if the app has no remaining valid components.

    Rules:
      - Production server: include components with stage == 'production' only
      - Development server: include components with stage in {'development', 'production'}
    """
    if server_environment.lower() == "production":
        required_stages = {"production"}
    else:
        required_stages = {"development", "production"}

    filtered = app_metadata_json.copy()

    # Skills
    skills_data = filtered.get("skills", [])
    if isinstance(skills_data, list):
        filtered["skills"] = [
            s for s in skills_data
            if isinstance(s, dict) and s.get("stage", "").lower() in required_stages
        ]
    else:
        filtered["skills"] = []

    # Focuses (key may be 'focuses' or 'focus_modes')
    focuses_data: List[Dict[str, Any]] = []
    if isinstance(filtered.get("focuses"), list):
        focuses_data = filtered["focuses"]
    elif isinstance(filtered.get("focus_modes"), list):
        focuses_data = filtered["focus_modes"]
    filtered["focuses"] = [
        f for f in focuses_data
        if isinstance(f, dict) and f.get("stage", "").lower() in required_stages
    ]

    # Memory fields (key may be 'settings_and_memories', 'memory_fields', or 'memory')
    memory_data: List[Dict[str, Any]] = []
    if isinstance(filtered.get("settings_and_memories"), list):
        memory_data = filtered["settings_and_memories"]
    elif isinstance(filtered.get("memory_fields"), list):
        memory_data = filtered["memory_fields"]
    elif isinstance(filtered.get("memory"), list):
        memory_data = filtered["memory"]
    filtered["settings_and_memories"] = [
        m for m in memory_data
        if isinstance(m, dict) and m.get("stage", "").lower() in required_stages
    ]

    has_valid_skill = bool(filtered.get("skills"))
    has_valid_focus = bool(filtered.get("focuses"))
    has_valid_memory = bool(filtered.get("settings_and_memories"))
    has_instructions = bool(filtered.get("instructions"))

    if has_valid_skill or has_valid_focus or has_valid_memory or has_instructions:
        return filtered
    return None


def build_skill_registry(
    disabled_app_ids: Optional[List[str]] = None,
    server_environment: Optional[str] = None,
) -> tuple["SkillRegistry", Dict[str, AppYAML]]:
    """
    Build a fresh SkillRegistry by filesystem-scanning backend/apps/, applying
    stage filtering, and instantiating an in-process BaseApp per app.

    Returns (registry, metadata_dict). The metadata dict is provided for the
    legacy ``app.state.discovered_apps_metadata`` consumers in main.py — the
    authoritative state lives in the registry.

    Used by:
      - api gateway: ``discover_apps()`` in ``backend/core/api/main.py``
      - Celery workers: ``init_worker_process()`` in
        ``backend/core/api/app/tasks/celery_config.py``

    Skills whose ``class_path`` import fails are logged ERROR (inside
    ``BaseApp._resolve_skill_classes``) and become unavailable; the rest of
    the app keeps working. Apps that fail to load entirely are logged ERROR
    and skipped.
    """
    if disabled_app_ids is None:
        disabled_app_ids = []
    if server_environment is None:
        server_environment = os.getenv("SERVER_ENVIRONMENT", "development").lower()

    registry = SkillRegistry()
    metadata: Dict[str, AppYAML] = {}
    failed_apps: List[str] = []
    excluded_apps: List[str] = []

    all_app_ids = scan_filesystem_for_apps()
    logger.info(f"[SkillRegistry] Building registry for {len(all_app_ids)} app(s) (env={server_environment})")

    for app_id in all_app_ids:
        if app_id in disabled_app_ids:
            logger.info(f"[SkillRegistry] Skipping '{app_id}' (disabled in config)")
            continue

        app_dir = os.path.join(APPS_DIR, app_id)
        app_yml_path = os.path.join(app_dir, "app.yml")

        try:
            with open(app_yml_path, 'r') as f:
                raw_config = yaml.safe_load(f)
            if not raw_config:
                logger.warning(f"[SkillRegistry] app.yml is empty for '{app_id}', skipping")
                failed_apps.append(app_id)
                continue
        except Exception as e:
            logger.error(f"[SkillRegistry] Failed to read app.yml for '{app_id}': {e}", exc_info=True)
            failed_apps.append(app_id)
            continue

        filtered = filter_app_components_by_stage(raw_config, server_environment)
        if filtered is None:
            logger.info(f"[SkillRegistry] '{app_id}' excluded (no components match stage '{server_environment}')")
            excluded_apps.append(app_id)
            continue

        try:
            base_app = BaseApp(
                app_dir=app_dir,
                register_http_routes=False,
                preloaded_config_dict=filtered,
            )
        except Exception as e:
            logger.error(f"[SkillRegistry] Failed to instantiate BaseApp for '{app_id}': {e}", exc_info=True)
            failed_apps.append(app_id)
            continue

        if not base_app.is_valid or base_app.app_config is None:
            logger.error(f"[SkillRegistry] BaseApp for '{app_id}' loaded but is_valid=False — skipping")
            failed_apps.append(app_id)
            continue

        if base_app.app_config.id and base_app.app_config.id != app_id:
            logger.warning(
                f"[SkillRegistry] App ID mismatch for '{app_id}': "
                f"app.yml says '{base_app.app_config.id}'. Using directory name."
            )
        base_app.app_config.id = app_id

        registry.register(app_id, base_app)
        metadata[app_id] = base_app.app_config

    if failed_apps:
        logger.error(
            f"[SkillRegistry] {len(failed_apps)} app(s) FAILED to load: {failed_apps}. "
            f"See ERROR logs above for details."
        )
    if excluded_apps:
        logger.info(f"[SkillRegistry] {len(excluded_apps)} app(s) excluded by stage filter: {excluded_apps}")

    logger.info(f"[SkillRegistry] Build complete: {len(metadata)} app(s) loaded in-process")
    return registry, metadata


class SkillRegistry:
    """
    Holds in-process BaseApp instances keyed by app_id and provides the
    dispatch entry point used by both the REST API and Celery workers.

    Thread-safety: registration happens once at startup (before any requests).
    Dispatch is read-only after that. The underlying skill execute() methods
    are responsible for their own concurrency. No locks needed here.
    """

    def __init__(self) -> None:
        self.apps: Dict[str, BaseApp] = {}

    def register(self, app_id: str, base_app: BaseApp) -> None:
        """Register a BaseApp instance under the given app_id."""
        if app_id in self.apps:
            logger.warning(f"[SkillRegistry] Replacing existing registration for app '{app_id}'")
        self.apps[app_id] = base_app
        skill_count = len(base_app.skill_classes)
        logger.info(f"[SkillRegistry] Registered app '{app_id}' with {skill_count} resolved skill(s)")

    def has_app(self, app_id: str) -> bool:
        return app_id in self.apps

    def is_skill_available(self, app_id: str, skill_id: str) -> bool:
        """True if the app exists in the registry AND the skill class resolved at startup."""
        app = self.apps.get(app_id)
        return app is not None and skill_id in app.skill_classes

    def get_metadata(self, app_id: str) -> Optional[AppYAML]:
        app = self.apps.get(app_id)
        return app.app_config if app is not None else None

    def all_metadata(self) -> Dict[str, AppYAML]:
        """Return {app_id: AppYAML} for every successfully-registered app."""
        return {
            app_id: app.app_config
            for app_id, app in self.apps.items()
            if app.app_config is not None
        }

    async def dispatch_skill(
        self,
        app_id: str,
        skill_id: str,
        request_body: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Dispatch a skill in-process and return its JSON result.

        Raises:
            HTTPException(404) if the app or skill is not registered.
            HTTPException(4xx/5xx) if the skill itself raises one (validation,
                billing, internal error). Re-raised as-is so REST callers can
                propagate the status code; worker callers can catch and
                inspect ``.status_code`` / ``.detail``.
        """
        app = self.apps.get(app_id)
        if app is None:
            raise HTTPException(
                status_code=404,
                detail=f"App '{app_id}' is not registered in the in-process skill registry",
            )
        return await app.dispatch_skill(skill_id, request_body)


# ----------------------------------------------------------------------
# Module-level singleton
# ----------------------------------------------------------------------
# The api process stores the registry on app.state.skill_registry (lifespan
# startup). Celery workers run in a separate process and don't have access
# to FastAPI's app.state, so they use the module-level singleton below,
# initialized from worker_process_init in celery_config.py.
#
# Both code paths ultimately call SkillRegistry.dispatch_skill().

_global_registry: Optional[SkillRegistry] = None


def get_global_registry() -> SkillRegistry:
    """
    Return the process-global SkillRegistry, lazily creating it on first access.

    The api process initializes this from main.py lifespan (so app.state and
    the global agree); Celery workers initialize it from worker_process_init
    in celery_config.py.
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = SkillRegistry()
    return _global_registry


def set_global_registry(registry: SkillRegistry) -> None:
    """Replace the process-global registry. Used by tests and explicit init paths."""
    global _global_registry
    _global_registry = registry
