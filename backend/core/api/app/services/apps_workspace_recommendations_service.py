"""Per-owner saved searches and short-lived paid daily Apps recommendations.

Plaintext exists only during authenticated reads or execution. Vault Transit uses
server-managed per-user keys, as scheduled Workflows do; never client keys.
"""
from __future__ import annotations

from datetime import datetime
import json
import logging
import time
from typing import Any
from uuid import uuid4

from backend.core.api.app.services.apps_workspace_recommendations_store import AppsRecommendationsStore
from backend.core.api.app.services.apps_workspace_libraries_repository import AppsLibrariesRepository
from backend.shared.python_utils.private_inference_logging import private_inference_logging

logger = logging.getLogger(__name__)
DAY = 86_400
MAX_DAILY_CREDITS = 100
MAX_SAVED_SEARCHES = 500


class AppsLibraryUnavailable(ValueError):
    """A safe, content-free library rejection."""


class AppsWorkspaceRecommendationsService:
    def __init__(self, directus: Any, encryption: Any, *, store: AppsRecommendationsStore | None = None,
                 adapter: Any = None, registry: Any = None) -> None:
        self.directus = directus
        self.repository = AppsLibrariesRepository(directus)
        self.encryption = encryption
        self.store = store or AppsRecommendationsStore()
        self.adapter = adapter
        self.registry = registry

    async def _authorize(self, user_id: str, team_id: str | None, *, spend: bool = False) -> dict[str, Any]:
        if team_id:
            roles = {"owner", "admin", "member"} if spend else {"owner", "admin", "member", "viewer"}
            await self.directus.team.require_team_role(team_id, user_id, roles)
        ok, profile, _ = await self.directus.get_user_profile(user_id)
        if not ok or not profile or not profile.get("vault_key_id") or profile.get("status") not in {None, "active"}:
            raise AppsLibraryUnavailable("APPS_LIBRARY_UNAVAILABLE")
        return profile

    async def _encrypt(self, value: Any, key: str) -> dict[str, Any]:
        plaintext = json.dumps(value, separators=(",", ":"), allow_nan=False)
        if len(plaintext.encode()) > 4_000_000:
            raise AppsLibraryUnavailable("APPS_LIBRARY_PAYLOAD_TOO_LARGE")
        ciphertext, _ = await self.encryption.encrypt_with_user_key(plaintext, key)
        if not isinstance(ciphertext, str) or not ciphertext.startswith("vault:"):
            raise RuntimeError("Apps library Vault encryption failed")
        return {"ciphertext": ciphertext}

    async def _decrypt(self, blob: dict[str, Any] | None, key: str, default: Any) -> Any:
        if not blob:
            return default
        plaintext = await self.encryption.decrypt_with_user_key(blob["ciphertext"], key)
        if plaintext is None:
            raise RuntimeError("Apps library Vault decryption failed")
        return json.loads(plaintext)

    async def _configuration(self, scope: str, key: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        record = await self.repository.get(scope)
        blob = {"ciphertext": record["encrypted_config"]} if record else None
        config = await self._decrypt(blob, key, {"saved_searches": [], "daily_searches_enabled": True})
        return record, config

    async def _save_configuration(self, scope: str, previous: dict[str, Any] | None,
                                  config: dict[str, Any], profile: dict[str, Any],
                                  user_id: str, app_id: str, team_id: str | None) -> None:
        encrypted = await self._encrypt(config, profile["vault_key_id"])
        await self.repository.put(scope, previous, {"owner_user_id": user_id, "app_id": app_id,
            "team_id": team_id, "encrypted_config": encrypted["ciphertext"]})

    async def mark_activity(self, user_id: str) -> None:
        await self.store.mark_activity(user_id)

    async def library(self, user_id: str, app_id: str, team_id: str | None = None) -> dict[str, Any]:
        profile = await self._authorize(user_id, team_id)
        now = int(time.time())
        await self.store.mark_activity(user_id, now)
        scope = self.store.scope(user_id, app_id, team_id)
        async with self.store.locked(scope):
            self.store.expire_batch(scope, now)
            _, config = await self._configuration(scope, profile["vault_key_id"])
            saved = config["saved_searches"]
            batch = await self._decrypt(self.store.read(scope, "batch"), profile["vault_key_id"], None)
        return {"app_id": app_id, "daily_searches_enabled": config["daily_searches_enabled"],
                "saved_searches": saved, "recommendations": [batch] if batch else [],
                "recommendations_expires_at": batch["expires_at"] if batch else None}

    def _validate_search(self, app_id: str, skill_id: str, parameters: dict[str, Any]) -> None:
        # Only synchronous search reads are eligible. Async generation, actions,
        # connected-account skills, and model selection never enter this runner.
        if not (skill_id == "search" or skill_id.startswith("search_")):
            raise AppsLibraryUnavailable("APPS_DAILY_SEARCH_UNSUPPORTED")
        if self.registry is None:
            from backend.core.api.app.services.skill_registry import get_global_registry
            self.registry = get_global_registry()
        if not self.registry.is_skill_available(app_id, skill_id):
            raise AppsLibraryUnavailable("APPS_DAILY_SEARCH_UNSUPPORTED")
        metadata = self.registry.get_metadata(app_id)
        skills = metadata.get("skills", []) if isinstance(metadata, dict) else metadata.skills
        skill = next((s for s in skills if (s.get("id") if isinstance(s, dict) else s.id) == skill_id), None)
        if skill is None:
            raise AppsLibraryUnavailable("APPS_DAILY_SEARCH_UNSUPPORTED")
        from backend.core.api.app.services.workflow_app_skill_adapter import _require_workflow_runtime_safe
        _require_workflow_runtime_safe(app_id, skill_id, metadata)
        from backend.core.api.app.services.workflow_capability_registry import _load_workflow_classifications
        workflow = skill.get("workflow") if isinstance(skill, dict) else getattr(skill, "workflow", None)
        if hasattr(workflow, "model_dump"):
            workflow = workflow.model_dump(mode="json")
        workflow = workflow or _load_workflow_classifications().get(f"{app_id}.{skill_id}") or {}
        if (workflow.get("execution_mode") != "sync" or workflow.get("effect") != "read"
            or workflow.get("unattended") is not True or workflow.get("available") is not True
            or workflow.get("binding_requirements") not in (None, [], ["none"])):
            raise AppsLibraryUnavailable("APPS_DAILY_SEARCH_UNSUPPORTED")
        if any(name.startswith("_") or name in {"user_id", "team_id", "model", "provider", "external_request"} for name in parameters):
            raise AppsLibraryUnavailable("APPS_SEARCH_PARAMETERS_INVALID")
        from backend.core.api.app.services.apps_workspace_metadata import request_schema
        from jsonschema import Draft202012Validator
        schema = request_schema(skill)
        if schema and next(Draft202012Validator(schema).iter_errors(parameters), None) is not None:
            raise AppsLibraryUnavailable("APPS_SEARCH_PARAMETERS_INVALID")
        requests = parameters.get("requests")
        if requests is not None and (not isinstance(requests, list) or len(requests) != 1):
            raise AppsLibraryUnavailable("APPS_SEARCH_PARAMETERS_INVALID")
        if len(json.dumps(parameters, allow_nan=False).encode()) > 65_536:
            raise AppsLibraryUnavailable("APPS_SEARCH_PARAMETERS_INVALID")

    async def save_search(self, user_id: str, app_id: str, data: dict[str, Any]) -> dict[str, Any]:
        team_id = data.get("team_id")
        profile = await self._authorize(user_id, team_id, spend=True)
        self._validate_search(app_id, data["skill_id"], data["parameters"])
        scope = self.store.scope(user_id, app_id, team_id)
        now = int(time.time())
        async with self.store.locked(scope):
            record, config = await self._configuration(scope, profile["vault_key_id"])
            saved = config["saved_searches"]
            if len(saved) >= MAX_SAVED_SEARCHES:
                raise AppsLibraryUnavailable("APPS_SAVED_SEARCH_LIMIT")
            first_save = not saved
            saved.insert(0, {"id": str(uuid4()), "skill_id": data["skill_id"], "title": data["title"],
                             "query": data["query"], "parameters": data["parameters"], "saved_at": now})
            await self._save_configuration(scope, record, config, profile, user_id, app_id, team_id)
        result = await self.library(user_id, app_id, team_id)
        result["first_save"] = first_save
        return result

    async def settings(self, user_id: str, app_id: str, enabled: bool, team_id: str | None = None) -> dict[str, Any]:
        profile = await self._authorize(user_id, team_id, spend=True)
        scope = self.store.scope(user_id, app_id, team_id)
        async with self.store.locked(scope):
            record, config = await self._configuration(scope, profile["vault_key_id"])
            config["daily_searches_enabled"] = enabled
            await self._save_configuration(scope, record, config, profile, user_id, app_id, team_id)
        return await self.library(user_id, app_id, team_id)

    async def detail(self, user_id: str, app_id: str, batch_id: str, team_id: str | None = None) -> dict[str, Any] | None:
        library = await self.library(user_id, app_id, team_id)
        return next((batch for batch in library["recommendations"] if batch["id"] == batch_id), None)

    @staticmethod
    def _timestamp(value: Any) -> int:
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            if value.isdecimal():
                return int(value)
            try:
                return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
            except ValueError:
                return 0
        return 0

    async def refresh_scope(self, scope: str, *, now: int | None = None) -> bool:
        now = int(time.time()) if now is None else now
        # Claim while holding the same process-shared lock as saves/settings.
        # Persist BEFORE provider work: crash retries never rerun a paid search.
        async with self.store.locked(scope):
            self.store.expire_batch(scope, now)
            record = await self.repository.get(scope)
            if not record or int(record.get("last_attempt_at") or 0) > now - DAY:
                return False
            user_id, app_id, team_id = record["owner_user_id"], record["app_id"], record.get("team_id")
            profile = await self._authorize(user_id, team_id, spend=True)
            config = await self._decrypt({"ciphertext": record["encrypted_config"]}, profile["vault_key_id"], None)
            if not config["daily_searches_enabled"]:
                return False
            activity = self.store.read(self.store.scope(user_id, "activity", None), "activity") or {}
            general_activity = await self.repository.activity(user_id)
            active_at = max(activity.get("last_active_at", 0),
                self._timestamp(general_activity.get("last_online_timestamp")),
                self._timestamp(general_activity.get("last_access")))
            if active_at <= now - 7 * DAY:
                return False
            searches = config["saved_searches"]
            if not searches:
                return False
            search = searches[0]
            self._validate_search(app_id, search["skill_id"], search["parameters"])
            run_id = str(uuid4())
            await self.repository.put(scope, record, {"last_attempt_at": now, "attempt_id": run_id})
            # A content-free manifest makes expiry cleanup independent of DB uptime.
            self.store.write(scope, "meta", {"attempt_id": run_id})
        from backend.core.api.app.services.workflow_app_skill_adapter import WorkflowAppSkillAdapter
        adapter = self.adapter or WorkflowAppSkillAdapter(registry=self.registry, directus_service=self.directus)
        with private_inference_logging():
            result = await adapter.execute(app_id, search["skill_id"], search["parameters"], user_id=user_id,
                billing_context={"workflow_id": f"apps-daily:{scope}", "run_id": run_id, "node_id": search["id"],
                                 "source": "workflow", "team_id": team_id, "max_credits_remaining": MAX_DAILY_CREDITS})
        if result.get("error") or result.get("success") is False:
            return False
        batch = {"id": run_id, "skill_id": search["skill_id"], "created_at": now, "expires_at": now + DAY,
                 "result": result, "input": search["parameters"], "request_text": search["query"], "query": search["query"]}
        encrypted = await self._encrypt(batch, profile["vault_key_id"])
        async with self.store.locked(scope):
            # Revalidate membership/config immediately before publication.
            await self._authorize(user_id, team_id, spend=True)
            current, latest = await self._configuration(scope, profile["vault_key_id"])
            if (not current or current.get("attempt_id") != run_id or not latest["daily_searches_enabled"]
                or not latest["saved_searches"] or latest["saved_searches"][0]["id"] != search["id"]):
                return False
            self.store.write(scope, "batch", {**encrypted, "expires_at": batch["expires_at"]})
        return True

    async def refresh_daily(self, *, limit: int = 100) -> dict[str, int]:
        await self.store.cleanup()
        refreshed = failed = 0
        # Rotate through the stable scope list using durable last-attempt time;
        # disabled/inactive records cannot starve later eligible accounts.
        records = await self.repository.scopes()
        records.sort(key=lambda record: int(record.get("last_attempt_at") or 0))
        scopes = [record["scope_hash"] for record in records]
        attempted = 0
        for scope in scopes:
            if attempted >= limit:
                break
            try:
                prior_attempt = (await self.repository.get(scope) or {}).get("attempt_id")
                changed = await self.refresh_scope(scope)
                refreshed += int(changed)
                current_attempt = (await self.repository.get(scope) or {}).get("attempt_id")
                attempted += int(current_attempt != prior_attempt)
            except Exception:
                failed += 1
                attempted += 1
                # Do not serialize exception text/tracebacks containing parameters.
                logger.warning("Private Apps daily refresh failed")
        return {"refreshed": refreshed, "failed": failed}
