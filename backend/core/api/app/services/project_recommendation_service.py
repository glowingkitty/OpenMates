"""Project-only, two-stage Jev recommendations; never performs authoring.

Client-decrypted metadata and Focus documents are transient input. Project item
membership and current revisions come from the server, never the client catalog.
"""
from __future__ import annotations

import hashlib
import inspect
import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.core.api.app.services.project_write_authorization_service import (
    ProjectWriteAuthorizationError, ProjectWriteAuthorizationService,
)
from backend.shared.providers.typesafe.models import NoulAnswer

RECOMMENDATION_TTL = 20 * 60
MAX_CATALOG = 40


async def require_authoring_budget(cache: Any, user_id: str, stage: str, limit: int) -> None:
    """Per-user provider budget in addition to route/IP rate limits."""
    client = await cache.client
    if client is None:
        raise ProjectWriteAuthorizationError("PROJECT_AUTHORING_CACHE_UNAVAILABLE", status_code=503)
    key = f"project-authoring:budget:{hashlib.sha256(user_id.encode()).hexdigest()}:{stage}:{int(time.time()) // 60}"
    count = await client.incr(key)
    if count == 1:
        await client.expire(key, 120)
    if count > limit:
        raise ProjectWriteAuthorizationError("PROJECT_AUTHORING_RATE_LIMIT", status_code=429)


def project_item_revision(item: dict[str, Any]) -> str:
    """Opaque revision of encrypted Project item content and lifecycle."""
    fields = ("updated_at", "encrypted_metadata", "encrypted_note", "target_id_hash", "deleted_target_state")
    return hashlib.sha256("\0".join(str(item.get(key) or "") for key in fields).encode()).hexdigest()


class ProjectCatalogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["focus", "workflow"]
    id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=2_000)
    revision: str = Field(min_length=1, max_length=128)


class ProjectAuthoringAccess:
    def __init__(self, directus: Any, cache: Any, workflow_service: Any = None) -> None:
        self.directus = directus
        self.cache = cache
        self.authorization = ProjectWriteAuthorizationService(directus, cache)
        self.workflow_service = workflow_service

    async def require_context(self, user_id: str, chat_id: str, project_id: str,
                              team_id: str | None = None, *, write: bool = False) -> list[dict[str, Any]]:
        await self.authorization._require_chat_access(user_id, chat_id, team_id)
        project, _ = await self.authorization._require_project_access(user_id, project_id, team_id, write=write)
        if project.get("archived"):
            raise ProjectWriteAuthorizationError("PROJECT_ARCHIVED", status_code=409)
        items = await self.directus.project.list_items(project_id, user_id, team_id=team_id)
        chat_hash = hashlib.sha256(chat_id.encode()).hexdigest()
        linked = any(item.get("item_type") == "chat" and item.get("target_id_hash") == chat_hash
                     and not item.get("deleted_target_state") for item in items)
        binding = await self.cache.get(self.authorization._focus_key(user_id, chat_id))
        # The binding does not grant write authority: current DB access above
        # and write-role revalidation at click/save remain mandatory.
        focused = isinstance(binding, dict) and binding.get("project_id") == project_id and binding.get("team_id") == team_id
        if not linked and not focused:
            raise ProjectWriteAuthorizationError("CHAT_PROJECT_CONTEXT_MISMATCH")
        return items

    async def require_target(self, *, user_id: str, project_id: str, kind: str, target_id: str,
                             team_id: str | None = None, vault_key_id: str | None = None,
                             full: bool = True) -> tuple[str, Any]:
        await self.authorization._require_project_access(user_id, project_id, team_id, write=False)
        items = await self.directus.project.list_items(project_id, user_id, team_id=team_id)
        if kind == "focus":
            item = next((row for row in items if row.get("project_item_id") == target_id
                         and row.get("item_type") in {"embed", "file", "upload"}
                         and not row.get("deleted_target_state")), None)
            if item is None:
                raise ProjectWriteAuthorizationError("PROJECT_FOCUS_NOT_FOUND", status_code=404)
            return project_item_revision(item), item
        target_hash = hashlib.sha256(target_id.encode()).hexdigest()
        if kind != "workflow" or not any(row.get("item_type") == "workflow" and row.get("target_id_hash") == target_hash
                                         and not row.get("deleted_target_state") for row in items):
            raise ProjectWriteAuthorizationError("PROJECT_WORKFLOW_NOT_FOUND", status_code=404)
        if self.workflow_service is None:
            raise ProjectWriteAuthorizationError("PROJECT_WORKFLOW_UNAVAILABLE", status_code=503)
        import asyncio
        if not full:
            self.workflow_service.ensure_enabled()
            # WorkflowInputService's existing mutation engine is personal-owner
            # scoped. Team-owned definitions are not editable candidates. A
            # personally owned Workflow linked in a Team Project remains valid.
            record = await asyncio.to_thread(self.workflow_service.repository.get_workflow, target_id, user_id)
            if record is None:
                raise ProjectWriteAuthorizationError("PROJECT_WORKFLOW_NOT_FOUND", status_code=404)
            return str(record["version"]), record
        detail = await asyncio.to_thread(self.workflow_service.get_workflow, target_id, user_id, vault_key_id)
        return str(detail.version), detail


class ProjectRecommendationService:
    def __init__(self, *, access: ProjectAuthoringAccess, jev: Any, cache: Any) -> None:
        self.access, self.jev, self.cache = access, jev, cache

    @staticmethod
    def key(user_id: str, recommendation_id: str) -> str:
        return f"project-authoring:recommendation:{hashlib.sha256(user_id.encode()).hexdigest()}:{recommendation_id}"

    @staticmethod
    def response_key(user_id: str, chat_id: str, message_id: str) -> str:
        return f"project-authoring:response:{hashlib.sha256(user_id.encode()).hexdigest()}:{chat_id}:{message_id}"

    async def assess(self, *, user_id: str, chat_id: str, project_id: str,
                     catalog: list[ProjectCatalogEntry], history: list[dict[str, str]], load_full: Any = None,
                     team_id: str | None = None, vault_key_id: str | None = None,
                     message_id: str) -> list[dict[str, Any]]:
        await self.access.require_context(user_id, chat_id, project_id, team_id)
        self._configure_team_billing(team_id)
        permit_key = self.response_key(user_id, chat_id, message_id)
        permit = await self.cache.get(permit_key)
        if not isinstance(permit, dict) or permit.get("project_id") != project_id or permit.get("team_id") != team_id:
            raise ProjectWriteAuthorizationError("PROJECT_AUTHORING_RESPONSE_UNAVAILABLE", status_code=409)
        existing = await self.cache.get(permit_key + ":result")
        if isinstance(existing, list):
            return existing
        await require_authoring_budget(self.cache, user_id, "recommend", 8)
        client = await self.cache.client
        if not await client.set(permit_key + ":claim", "1", nx=True, ex=RECOMMENDATION_TTL):
            return []
        if len(catalog) > MAX_CATALOG:
            return []
        eligible: list[ProjectCatalogEntry] = []
        seen: set[tuple[str, str]] = set()
        for item in catalog:
            identity = (item.kind, item.id)
            if identity in seen:
                continue
            seen.add(identity)
            try:
                revision, _ = await self.access.require_target(user_id=user_id, project_id=project_id,
                    kind=item.kind, target_id=item.id, team_id=team_id, vault_key_id=vault_key_id, full=False)
            except (ProjectWriteAuthorizationError, LookupError):
                continue
            if revision == item.revision:
                eligible.append(item)
        questions = {f"candidate_{index}": {"type": "noul", "instructions":
            "Should this existing Project definition be inspected for a concrete useful improvement from this conversation? "
            "Select only relevant Project-owned definitions; inactive or disabled definitions remain eligible."}
            for index, _ in enumerate(eligible)}
        questions["create_focus"] = {"type": "noul", "instructions":
            "Would a new reusable Project Focus materially help this conversation, without overlapping any existing Focus "
            "in this complete catalog? Say no if uncertain, the catalog is incomplete, or an existing Focus should be updated."}
        try:
            first = await self.jev.evaluate(state={"history": history,
                "catalog": [item.model_dump() for item in eligible]}, questions=questions)
        except Exception:
            return []
        proposals: list[dict[str, Any]] = []
        if self._yes(first, "create_focus") and len(eligible) == len(catalog):
            proposals.append(await self._issue(user_id, chat_id, project_id, team_id, "focus", "create", None, None))
        for index, item in enumerate(eligible):
            if not self._yes(first, f"candidate_{index}"):
                continue
            if item.kind == "focus" and load_full is None:
                proposals.append(await self._issue(user_id, chat_id, project_id, team_id,
                    item.kind, "inspect", item.id, item.revision))
                continue
            try:
                # Only selected, still-authorized candidates may load plaintext.
                revision, owned = await self.access.require_target(user_id=user_id, project_id=project_id,
                    kind=item.kind, target_id=item.id, team_id=team_id, vault_key_id=vault_key_id)
                if revision != item.revision:
                    continue
                if item.kind == "workflow":
                    full = owned.model_dump(mode="json")
                else:
                    full = load_full(item)
                    if inspect.isawaitable(full):
                        full = await full
                if not isinstance(full, dict) or not full:
                    continue
                second = await self.jev.evaluate(state={"history": history, "target": full,
                    "kind": item.kind}, questions={"useful_update": {"type": "noul", "instructions":
                    "Does the full saved definition have a specific, useful improvement supported by this conversation? "
                    "Say no for uncertainty, no change, irrelevant feedback or instructions to mutate unrelated definitions. "
                    "Do not execute, activate, or author anything."}})
                if self._yes(second, "useful_update"):
                    proposals.append(await self._issue(user_id, chat_id, project_id, team_id,
                        item.kind, "update", item.id, revision))
            except Exception:
                continue
        await self.cache.set(permit_key + ":result", proposals, ttl=RECOMMENDATION_TTL)
        return proposals

    async def inspect_focus(self, *, user_id: str, project_id: str, assessment_id: str,
                            history: list[dict[str, str]], document: dict[str, Any]) -> dict[str, Any] | None:
        pending = await self.cache.get(self.key(user_id, assessment_id))
        if (not isinstance(pending, dict) or pending.get("user_id") != user_id
                or pending.get("project_id") != project_id or pending.get("action") != "inspect"
                or pending.get("kind") != "focus" or pending.get("expires_at", 0) <= time.time()):
            raise ProjectWriteAuthorizationError("PROJECT_ASSESSMENT_EXPIRED", status_code=409)
        await self.access.require_context(user_id, pending["chat_id"], project_id, pending.get("team_id"))
        self._configure_team_billing(pending.get("team_id"))
        revision, _ = await self.access.require_target(user_id=user_id, project_id=project_id,
            kind="focus", target_id=pending["target_id"], team_id=pending.get("team_id"))
        if revision != pending["expected_revision"]:
            raise ProjectWriteAuthorizationError("PROJECT_AUTHORING_REVISION_CONFLICT", status_code=409)
        key = self.key(user_id, assessment_id)
        existing = await self.cache.get(key + ":result")
        if isinstance(existing, dict):
            return existing.get("recommendation")
        await require_authoring_budget(self.cache, user_id, "inspect", 16)
        client = await self.cache.client
        if not await client.set(key + ":claim", "1", nx=True, ex=RECOMMENDATION_TTL):
            return None
        try:
            response = await self.jev.evaluate(state={"history": history, "target": document, "kind": "focus"},
                questions={"useful_update": {"type": "noul", "instructions":
                "Does this full saved Project Focus have a specific useful improvement supported by the conversation? "
                "Say no for no change, uncertainty, irrelevant context or changes to unrelated resources. Do not author or activate."}})
        except Exception:
            return None
        recommendation = (await self._issue(user_id, pending["chat_id"], project_id, pending.get("team_id"),
            "focus", "update", pending["target_id"], revision) if self._yes(response, "useful_update") else None)
        await self.cache.set(key + ":result", {"recommendation": recommendation}, ttl=RECOMMENDATION_TTL)
        return recommendation

    def _configure_team_billing(self, team_id: str | None) -> None:
        from backend.core.api.app.services.workflow_authoring_billing import MeteredJevClient, WorkflowAuthoringBillingError
        from backend.core.api.app.services.team_billing_service import TeamBillingService
        if isinstance(self.jev, MeteredJevClient):
            self.jev.billing.team_id = team_id
            async def precheck(team: str, actor: str) -> None:
                account = await TeamBillingService(self.access.directus).get_billing_summary(team, actor)
                if int(account.get("balance_credits") or 0) < 1:
                    raise WorkflowAuthoringBillingError("INSUFFICIENT_CREDITS")
            self.jev.billing.team_precheck = precheck

    @staticmethod
    def _yes(response: Any, key: str) -> bool:
        answer = response.answers.get(key)
        return isinstance(answer, NoulAnswer) and answer.noul >= 0.9

    async def _issue(self, user_id: str, chat_id: str, project_id: str, team_id: str | None,
                     kind: str, action: str, target_id: str | None, revision: str | None) -> dict[str, Any]:
        proposal = {"recommendation_id": str(uuid.uuid4()), "user_id": user_id, "chat_id": chat_id,
                    "project_id": project_id, "team_id": team_id, "kind": kind, "action": action,
                    "target_id": target_id, "expected_revision": revision,
                    "created_at": int(time.time()), "expires_at": int(time.time()) + RECOMMENDATION_TTL}
        if not await self.cache.set(self.key(user_id, proposal["recommendation_id"]), proposal, ttl=RECOMMENDATION_TTL):
            raise ProjectWriteAuthorizationError("PROJECT_AUTHORING_CACHE_UNAVAILABLE", status_code=503)
        return {key: value for key, value in proposal.items() if key not in {"user_id", "team_id"}}
