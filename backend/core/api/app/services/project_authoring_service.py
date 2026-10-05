"""Click-triggered Project authoring with privacy-safe job state.

Chat history lives only in the running task. Focus drafts are short-lived client
encryption handoffs. Durable definitions remain in their existing encrypted
stores; neither job metadata nor notifications contain private authoring text.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from dataclasses import asdict, is_dataclass
from typing import Any, Literal

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from backend.shared.python_schemas.app_metadata_schemas import FocusPhaseDefinition

from backend.core.api.app.services.notification_event_service import NotificationEvent, NotificationEventService
from backend.core.api.app.services.project_recommendation_service import (
    ProjectAuthoringAccess, ProjectRecommendationService, RECOMMENDATION_TTL, require_authoring_budget,
)
from backend.core.api.app.services.project_write_authorization_service import ProjectWriteAuthorizationError
from backend.core.api.app.services.project_file_operation_service import ProjectFileOperationService
from backend.core.api.app.services.workflow_authoring_billing import GEMINI_MODEL, WorkflowAuthoringBilling, WorkflowAuthoringBillingError
from backend.core.api.app.services.team_billing_service import TeamBillingService
from backend.core.api.app.services.workflow_gemini_authoring import GOOGLE_SECRET_PATH

JOB_TTL = 7 * 24 * 60 * 60
HISTORY_MAX_CHARS = 12_000
FOCUS_AUTHOR_INSTRUCTIONS = (
    "Author one private reusable Project Focus. Return only the requested structured document. "
    "Use the authorized conversation as evidence for reusable guidance; do not copy its transcript, secrets or incidental personal data. "
    "Create a non-overlapping specialist Focus or improve only the given existing Focus. "
    "Preserve compatible phase identifiers and unrelated instructions when editing. "
    "Include a concise name, description, when_to_use and full instructions. Add ordered phases only when useful; "
    "phased documents must use phases_version 1 and each phase needs id, title, instructions and semantic requirements. "
    "Instructions may guide later conversation but grant no file, account, execution or tool authority. "
    "If essential requirements are unclear return needs_input with a concise question and document null."
)
WORKFLOW_AUTHOR_INSTRUCTIONS = (
    "Update only the selected existing Project Workflow using the conversation's reusable requirements. "
    "Preserve unrelated graph behavior, configured Checks, delivery settings and the current enabled state. "
    "Use the existing supported capabilities and typed references. Do not execute or enable anything, "
    "create copies or change other Workflows. Do not include the conversation transcript in saved instructions. "
    "Ask for clarification if the useful edit cannot be determined."
)


class ProjectFocusPhase(BaseModel):
    """Only for validation of already saved, unversioned Focus documents."""
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=120)
    instructions: str = Field(min_length=1, max_length=16_000)


class LegacyProjectFocusDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2_000)
    when_to_use: str = Field(min_length=1, max_length=2_000)
    instructions: str = Field(min_length=1, max_length=64_000)
    phases: list[ProjectFocusPhase] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def validate_legacy_document(self) -> LegacyProjectFocusDocument:
        if any(not value.strip() for value in (self.name, self.description, self.when_to_use, self.instructions)):
            raise ValueError("Focus content must not be blank")
        if len({phase.id for phase in self.phases}) != len(self.phases):
            raise ValueError("Focus phase ids must be unique")
        return self


class ProjectFocusDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2_000)
    when_to_use: str = Field(min_length=1, max_length=2_000)
    instructions: str = Field(min_length=1, max_length=64_000)
    phases_version: Literal[1] | None = None
    phases: list[FocusPhaseDefinition] = Field(default_factory=list, max_length=16)

    @field_validator("phases_version", mode="before")
    @classmethod
    def reject_boolean_phase_version(cls, value):
        if isinstance(value, bool):
            raise ValueError("phases_version must be the integer 1")
        return value

    @model_validator(mode="after")
    def validate_document(self) -> ProjectFocusDocument:
        if any(not value.strip() for value in (self.name, self.description, self.when_to_use, self.instructions)):
            raise ValueError("Focus content must not be blank")
        if len({phase.id for phase in self.phases}) != len(self.phases):
            raise ValueError("Focus phase ids must be unique")
        if bool(self.phases) != (self.phases_version == 1):
            raise ValueError("Focus phases require phases_version 1")
        return self

    def markdown(self) -> str:
        metadata = self.model_dump(exclude={"instructions", "phases_version", "phases"})
        if self.phases:
            metadata["phases_version"] = 1
            metadata["phases"] = [phase.model_dump() for phase in self.phases]
        metadata["preprocessor_hint"] = metadata.pop("when_to_use")
        return "---\n" + yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True) + "---\n\n" + self.instructions + "\n"


class FocusAuthorResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["authored", "needs_input"]
    document: ProjectFocusDocument | None
    question: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def require_result(self) -> FocusAuthorResult:
        if self.status == "authored" and self.document is None:
            raise ValueError("Focus author omitted the document")
        if self.status == "needs_input" and (self.document is not None or not self.question or not self.question.strip()):
            raise ValueError("Focus clarification requires a question without a document")
        return self


class ProjectFocusAuthor:
    """A bounded, metered Focus document author; no tools or chat creation."""
    def __init__(self, secrets_manager: Any, directus_service: Any = None) -> None:
        self.secrets = secrets_manager
        self.directus = directus_service

    async def author(self, *, user_id: str, job_id: str, history: list[dict[str, str]],
                     target: dict[str, Any] | None, team_id: str | None = None) -> FocusAuthorResult:
        async def team_precheck(team_id: str, actor: str) -> None:
            if self.directus is None:
                raise WorkflowAuthoringBillingError("WORKFLOW_AUTHORING_BILLING_UNAVAILABLE")
            account = await TeamBillingService(self.directus).get_billing_summary(team_id, actor)
            if int(account.get("balance_credits") or 0) < 1:
                raise WorkflowAuthoringBillingError("INSUFFICIENT_CREDITS")
        billing = WorkflowAuthoringBilling(user_id=user_id, session_id=job_id,
                                           app_id="ai", skill_id="project-focus-author",
                                           team_id=team_id, team_precheck=team_precheck)
        await billing.precheck(model=GEMINI_MODEL)
        key = await self.secrets.get_secret(secret_path=GOOGLE_SECRET_PATH, secret_key="api_key")
        if not key:
            raise ProjectWriteAuthorizationError("PROJECT_AUTHORING_PROVIDER_UNAVAILABLE", status_code=503)
        body = {"systemInstruction": {"parts": [{"text": FOCUS_AUTHOR_INSTRUCTIONS}]},
            "contents": [{"role": "user", "parts": [{"text": json.dumps({"history": history, "target": target})}]}],
            "generationConfig": {"responseMimeType": "application/json", "responseJsonSchema": FocusAuthorResult.model_json_schema(),
                                 "maxOutputTokens": 8192, "temperature": 1.0}}
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent",
                headers={"x-goog-api-key": key}, json=body)
            response.raise_for_status()
            if len(response.content) > 128 * 1024:
                raise ValueError("Focus author response exceeded its limit")
            value = response.json()
        usage = value.get("usageMetadata") or {}
        await billing.settle(model=GEMINI_MODEL, provider_step="focus-author", usage={
            "input_tokens": usage.get("promptTokenCount"),
            "output_tokens": usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0)})
        parts = value.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        result = "".join(part.get("text", "") for part in parts if not part.get("thought"))
        try:
            return FocusAuthorResult.model_validate_json(result)
        except ValidationError:
            raise ProjectWriteAuthorizationError("PROJECT_FOCUS_AUTHORING_INVALID_DOCUMENT", status_code=422) from None


def validate_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
    if len(history) > 60 or sum(len(row.get("content", "")) for row in history) > HISTORY_MAX_CHARS:
        raise ProjectWriteAuthorizationError("PROJECT_AUTHORING_CONTEXT_TOO_LARGE", status_code=422)
    if not history or any(row.get("role") not in {"user", "assistant"} or not isinstance(row.get("content"), str)
                          or not row["content"].strip() for row in history):
        raise ProjectWriteAuthorizationError("INVALID_PROJECT_AUTHORING_HISTORY", status_code=422)
    return [{"role": row["role"], "content": row["content"]} for row in history]


class ProjectAuthoringService:
    def __init__(self, *, access: ProjectAuthoringAccess, cache: Any, workflow_input: Any,
                 focus_author: Any, notifications: Any = None, remote_files: Any = None) -> None:
        self.access, self.cache = access, cache
        self.workflow_input, self.focus_author = workflow_input, focus_author
        self.notifications = notifications or NotificationEventService(cache)
        self.remote_files = remote_files
        self._tasks: set[asyncio.Task[Any]] = set()

    @staticmethod
    def key(user_id: str, job_id: str) -> str:
        return f"project-authoring:job:{hashlib.sha256(user_id.encode()).hexdigest()}:{job_id}"

    async def start(self, *, user_id: str, project_id: str, recommendation_id: str,
                    expected_revision: str | None, history: list[dict[str, str]],
                    target: dict[str, Any] | None = None, vault_key_id: str | None = None,
                    remote_binding: Any = None, source_write_context: dict[str, Any] | None = None,
                    timezone: str | None = None) -> dict[str, Any]:
        history = validate_history(history)
        pending = await self.cache.get(ProjectRecommendationService.key(user_id, recommendation_id))
        if (not isinstance(pending, dict) or pending.get("user_id") != user_id
                or pending.get("project_id") != project_id or pending.get("action") not in {"create", "update"}
                or pending.get("expires_at", 0) <= time.time()):
            raise ProjectWriteAuthorizationError("PROJECT_RECOMMENDATION_EXPIRED", status_code=409)
        await self.access.require_context(user_id, pending["chat_id"], project_id, pending.get("team_id"), write=True)
        job_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"project-authoring:{user_id}:{recommendation_id}"))
        existing = await self.cache.get(self.key(user_id, job_id))
        if isinstance(existing, dict):
            return self.public(existing)
        await require_authoring_budget(self.cache, user_id, "click", 5)
        if expected_revision != pending.get("expected_revision"):
            raise ProjectWriteAuthorizationError("PROJECT_AUTHORING_REVISION_CONFLICT", status_code=409)
        if pending["action"] == "update":
            revision, owned = await self.access.require_target(user_id=user_id, project_id=project_id,
                kind=pending["kind"], target_id=pending["target_id"], team_id=pending.get("team_id"), vault_key_id=vault_key_id)
            if revision != expected_revision:
                raise ProjectWriteAuthorizationError("PROJECT_AUTHORING_REVISION_CONFLICT", status_code=409)
            if pending["kind"] == "focus":
                target = ProjectFocusDocument.model_validate(target).model_dump()
                embeds = await self.access.directus.embed.get_embeds_by_hashed_embed_ids([owned["target_id_hash"]])
                if len(embeds) != 1 or not isinstance(embeds[0].get("version_number"), int):
                    raise ProjectWriteAuthorizationError("PROJECT_AUTHORING_RESULT_UNAVAILABLE", status_code=409)
                base_embed_revision = embeds[0]["version_number"]
            else:
                target_hash = hashlib.sha256(pending["target_id"].encode()).hexdigest()
                items = await self.access.require_context(user_id, pending["chat_id"], project_id, pending.get("team_id"), write=True)
                project_item = next((row for row in items if row.get("item_type") == "workflow"
                                     and row.get("target_id_hash") == target_hash), None)
        elif pending["kind"] != "focus" or target is not None:
            raise ProjectWriteAuthorizationError("INVALID_PROJECT_AUTHORING_TARGET", status_code=422)
        if remote_binding is not None and remote_binding.project_id != project_id:
            raise ProjectWriteAuthorizationError("PROJECT_AUTHORING_REMOTE_SCOPE_MISMATCH")
        job = {**pending, "job_id": job_id, "status": "running", "created_at": int(time.time()),
               "updated_at": int(time.time()), "result_id": None, "result_revision": None,
               "error_code": None, "notification_sent": False, "remote_required": remote_binding is not None}
        if pending["kind"] == "focus":
            job["base_embed_revision"] = base_embed_revision if pending["action"] == "update" else 0
            job["save_operation_id"] = "project-authoring:" + job_id
        elif remote_binding is not None:
            if project_item is None:
                raise ProjectWriteAuthorizationError("PROJECT_WORKFLOW_NOT_FOUND", status_code=404)
            from backend.core.api.app.services.project_recommendation_service import project_item_revision
            job["project_item_id"] = project_item["project_item_id"]
            job["expected_item_revision"] = project_item_revision(project_item)
        client = await self.cache.client
        if client is None:
            raise ProjectWriteAuthorizationError("PROJECT_AUTHORING_CACHE_UNAVAILABLE", status_code=503)
        claimed = await client.set(self.key(user_id, job_id) + ":claim", "1", nx=True, ex=JOB_TTL)
        if not claimed:
            existing = await self.cache.get(self.key(user_id, job_id))
            if not isinstance(existing, dict):
                raise ProjectWriteAuthorizationError("PROJECT_AUTHORING_START_IN_PROGRESS", status_code=409)
            return self.public(existing)
        await self._save(job)
        task = asyncio.create_task(self._run(job, history=history, target=target, vault_key_id=vault_key_id,
            remote_binding=remote_binding, source_write_context=source_write_context, timezone=timezone))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return self.public(job)

    async def _run(self, job: dict[str, Any], *, history: list[dict[str, str]], target: Any,
                   vault_key_id: str | None, remote_binding: Any, source_write_context: Any,
                   timezone: str | None) -> None:
        try:
            await self.access.require_context(job["user_id"], job["chat_id"], job["project_id"], job.get("team_id"), write=True)
            if job["kind"] == "focus":
                authored = await self.focus_author.author(user_id=job["user_id"], job_id=job["job_id"], history=history,
                    target=target, team_id=job.get("team_id"))
                authored = authored if isinstance(authored, FocusAuthorResult) else FocusAuthorResult.model_validate(authored)
                if authored.status == "needs_input":
                    job["status"] = "needs_input"
                    draft = {"question": authored.question}
                else:
                    job["status"] = "needs_save"
                    stable_id = job.get("target_id") or str(uuid.uuid5(uuid.NAMESPACE_URL, f"project-focus:{job['job_id']}"))
                    job["result_id"] = stable_id
                    draft = {"document": authored.document.model_dump(), "markdown": authored.document.markdown(),
                             "path": f".openmates/focuses/{stable_id}/SKILL.md",
                             "save_operation_id": job["save_operation_id"],
                             "expected_embed_revision": job["base_embed_revision"]}
                if not await self.cache.set(self.key(job["user_id"], job["job_id"]) + ":draft", draft, ttl=RECOMMENDATION_TTL):
                    raise ProjectWriteAuthorizationError("PROJECT_AUTHORING_CACHE_UNAVAILABLE", status_code=503)
            else:
                loop = asyncio.get_running_loop()
                def authorize_commit() -> None:
                    asyncio.run_coroutine_threadsafe(self.access.require_context(job["user_id"], job["chat_id"],
                        job["project_id"], job.get("team_id"), write=True), loop).result(timeout=30)
                result = await asyncio.to_thread(self.workflow_input.start,
                    user_id=job["user_id"], text=WORKFLOW_AUTHOR_INSTRUCTIONS,
                    selected_workflow_id=job["target_id"], selected_project_id=job["project_id"],
                    vault_key_id=vault_key_id, timezone=timezone, idempotency_key=job["job_id"],
                    expected_workflow_version=int(job["expected_revision"]),
                    transient_context={"history": history, "_authorize_commit": authorize_commit})
                job["input_session_id"] = result.session_id
                if result.status in {"needs_clarification", "draft"}:
                    job["status"] = "needs_input"
                    await self.cache.set(self.key(job["user_id"], job["job_id"]) + ":draft",
                                         {"question": result.message or "Please clarify the requested Workflow update."}, ttl=RECOMMENDATION_TTL)
                elif result.partial_reason or result.status != "executed" or result.workflow is None:
                    job["status"] = "partial" if result.partial_reason else "failed"
                    job["error_code"] = result.error_code or ("PROJECT_WORKFLOW_PARTIAL" if result.partial_reason else "PROJECT_WORKFLOW_NOT_SAVED")
                else:
                    if result.workflow.id != job["target_id"]:
                        raise ProjectWriteAuthorizationError("PROJECT_AUTHORING_TARGET_MISMATCH")
                    job["result_id"], job["result_revision"] = result.workflow.id, str(result.workflow.version)
                    job["workflow_version_id"] = result.workflow.current_version_id
                    if remote_binding is not None:
                        job["remote_source_id"] = remote_binding.source_id
                        if self.remote_files is None:
                            job["status"] = "pending_file"
                        else:
                            job["status"] = "pending_file"
                            job["file_operation_id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, f"project-authoring-file:{job['job_id']}"))
                            await self._save(job)
                            saved = await self.remote_files.persist(user_id=job["user_id"], workflow_id=result.workflow.id,
                                expected_workflow_version_id=result.workflow.current_version_id, binding=remote_binding,
                                source_write_context={**(source_write_context or {}), "chat_id": job["chat_id"],
                                    "user_id": job["user_id"], "job_id": job["job_id"], "team_id": job.get("team_id")},
                                vault_key_id=vault_key_id)
                            job["status"] = "saved" if saved["status"] == "saved" else "pending_file" if saved["status"] == "pending" else saved["status"]
                            job["file_operation_id"] = saved.get("operation_id")
                            proposed = saved.get("proposed_binding") or (saved.get("binding") if saved["status"] == "saved" else None)
                            if proposed is not None:
                                binding_value = asdict(proposed) if is_dataclass(proposed) else dict(proposed)
                                binding_value["workflow_version_id"] = result.workflow.current_version_id
                                await self.cache.set(self.key(job["user_id"], job["job_id"]) + ":draft",
                                    {"remote_binding": binding_value}, ttl=RECOMMENDATION_TTL)
                            if saved["status"] == "saved":
                                job["status"] = "needs_binding_save"
                    else:
                        job["status"] = "saved"
                    if job["status"] == "saved":
                        await self._ready(job, vault_key_id=vault_key_id)
        except BaseException as exc:
            job["status"] = "failed"
            job["error_code"] = getattr(exc, "code", "PROJECT_AUTHORING_FAILED")
            # Provider bodies, history and exception text must never enter jobs.
        finally:
            await self._save(job, preserve_completion=True)

    async def execute_source_operation(self, operation: str, arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """Dispatch actual YAML through the existing client Project file executor."""
        await self.access.require_context(context["user_id"], context["chat_id"], context["project_id"], context.get("team_id"), write=True)
        focus = await self.access.authorization.get_active_focus(user_id=context["user_id"], chat_id=context["chat_id"])
        if not focus or focus.get("project_id") != context["project_id"] or focus.get("team_id") != context.get("team_id"):
            raise ProjectWriteAuthorizationError("PROJECT_FOCUS_REQUIRED")
        source = await self.access.directus.project.get_source(context["project_id"], context["user_id"],
                                                              context["source_id"], team_id=context.get("team_id"))
        if not source or source.get("status") == "revoked" or "write_request" not in (source.get("capabilities") or []):
            raise ProjectWriteAuthorizationError("PROJECT_SOURCE_UNAVAILABLE")
        operation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"project-authoring-file:{context['job_id']}"))
        proposed = context.get("_proposed_binding")
        if proposed is None:
            raise ProjectWriteAuthorizationError("PROJECT_WORKFLOW_FILE_BINDING_UNAVAILABLE", status_code=409)
        await self.cache.set(self.key(context["user_id"], context["job_id"]) + ":draft",
            {"remote_binding": asdict(proposed) if is_dataclass(proposed) else dict(proposed)}, ttl=RECOMMENDATION_TTL)
        service = ProjectFileOperationService(self.cache)
        queued = await service.create_operation(user_id=context["user_id"], chat_id=context["chat_id"],
            project_focus={**focus, "source_id": context["source_id"]}, operation=operation, arguments=arguments,
            continuation_task_id="project-authoring:" + context["job_id"], operation_id=operation_id, publish=False)
        operation_job = await service.get_job(user_id=context["user_id"], operation_id=operation_id)
        from backend.core.api.app.tasks.project_file_operation_tasks import schedule_project_file_operation_deadlines
        schedule_project_file_operation_deadlines(user_id=context["user_id"], operation_id=operation_id,
                                                  episode_id=str(operation_job["episode_id"]))
        await service.publish_available(operation_job)
        return {"status": "queued", "operation_id": queued["operation_id"]}

    async def settle_file_operation(self, *, user_id: str, operation_id: str) -> dict[str, Any]:
        """Called by the existing authenticated source-operation settlement path."""
        operation = await ProjectFileOperationService(self.cache).get_job(user_id=user_id, operation_id=operation_id)
        continuation = str(operation.get("continuation_task_id") or "")
        if not continuation.startswith("project-authoring:"):
            raise ProjectWriteAuthorizationError("PROJECT_AUTHORING_TARGET_MISMATCH")
        job_id = continuation.split(":", 1)[1]
        job = await self._require_job(user_id, operation["project_id"], job_id, write=True)
        if job["status"] == "ready":
            return self.public(job)
        if (job["kind"] != "workflow" or job["status"] != "pending_file"
                or job.get("file_operation_id") != operation_id or job.get("remote_source_id") != operation.get("source_id")):
            raise ProjectWriteAuthorizationError("PROJECT_AUTHORING_TARGET_MISMATCH")
        if operation.get("state") != "COMPLETED":
            return self.public(job)
        if operation.get("result_status") == "completed":
            # Version and Project membership are rechecked by _ready; the
            # leased client executor already enforced exact file-base guards.
            try:
                revision, detail = await self.access.require_target(user_id=user_id, project_id=job["project_id"],
                    kind="workflow", target_id=job["result_id"], team_id=job.get("team_id"))
                if revision != job["result_revision"] or detail.current_version_id != job["workflow_version_id"]:
                    raise ProjectWriteAuthorizationError("PROJECT_AUTHORING_REVISION_CONFLICT", status_code=409)
                job["status"] = "needs_binding_save"
            except ProjectWriteAuthorizationError as exc:
                job["status"], job["error_code"] = "conflict", exc.code
        else:
            job["status"] = "conflict" if operation.get("result_status") == "conflict" else "failed"
            job["error_code"] = "PROJECT_WORKFLOW_FILE_NOT_SAVED"
        await self._save(job)
        return self.public(job)

    async def acknowledge_workflow_binding(self, *, user_id: str, project_id: str, job_id: str,
                                            project_item_id: str, saved_item_revision: str,
                                            workflow_version_id: str, vault_key_id: str | None = None) -> dict[str, Any]:
        job = await self._require_job(user_id, project_id, job_id, write=True)
        if job["status"] == "ready":
            return self.public(job)
        if (job["kind"] != "workflow" or job["status"] != "needs_binding_save"
                or job.get("project_item_id") != project_item_id or job.get("workflow_version_id") != workflow_version_id):
            raise ProjectWriteAuthorizationError("INVALID_PROJECT_AUTHORING_SAVE", status_code=409)
        draft = await self.cache.get(self.key(user_id, job_id) + ":draft")
        if not isinstance(draft, dict) or not draft.get("remote_binding"):
            raise ProjectWriteAuthorizationError("PROJECT_AUTHORING_DRAFT_EXPIRED", status_code=409)
        from backend.core.api.app.services.project_recommendation_service import project_item_revision
        item = await self.access.directus.project.get_item(project_id, project_item_id, user_id, team_id=job.get("team_id"))
        if (not item or not item.get("encrypted_metadata") or project_item_revision(item) != saved_item_revision
                or saved_item_revision == job["expected_item_revision"]):
            raise ProjectWriteAuthorizationError("PROJECT_AUTHORING_REVISION_CONFLICT", status_code=409)
        await self._ready(job, vault_key_id=vault_key_id)
        await self._save(job)
        await self.cache.delete(self.key(user_id, job_id) + ":draft")
        return self.public(job)

    async def get(self, *, user_id: str, project_id: str, job_id: str) -> dict[str, Any]:
        job = await self._require_job(user_id, project_id, job_id)
        result = self.public(job)
        if job["status"] in {"needs_save", "needs_input", "pending_file", "needs_binding_save"}:
            draft = await self.cache.get(self.key(user_id, job_id) + ":draft")
            if isinstance(draft, dict):
                result["draft"] = draft
            elif job["status"] != "pending_file":
                job["status"], job["error_code"] = "failed", "PROJECT_AUTHORING_DRAFT_EXPIRED"
                await self._save(job)
                result = self.public(job)
        return result

    async def acknowledge_focus_save(self, *, user_id: str, project_id: str, job_id: str,
                                     project_item_id: str, embed_id: str, saved_revision: str,
                                     expected_revision: str | None, save_operation_id: str) -> dict[str, Any]:
        job = await self._require_job(user_id, project_id, job_id, write=True)
        if job["status"] == "ready":
            return self.public(job)
        if (job["kind"] != "focus" or job["status"] != "needs_save"
                or job["action"] == "update" and project_item_id != job["result_id"]):
            raise ProjectWriteAuthorizationError("INVALID_PROJECT_AUTHORING_SAVE", status_code=409)
        if expected_revision != job["expected_revision"]:
            raise ProjectWriteAuthorizationError("PROJECT_AUTHORING_REVISION_CONFLICT", status_code=409)
        if save_operation_id != job["save_operation_id"]:
            raise ProjectWriteAuthorizationError("PROJECT_AUTHORING_SAVE_PROOF_REQUIRED", status_code=409)
        revision, item = await self.access.require_target(user_id=user_id, project_id=project_id,
            kind="focus", target_id=project_item_id, team_id=job.get("team_id"))
        if revision != saved_revision or revision == expected_revision or item.get("target_id_hash") != hashlib.sha256(embed_id.encode()).hexdigest():
            raise ProjectWriteAuthorizationError("PROJECT_AUTHORING_REVISION_CONFLICT", status_code=409)
        embed = await self.access.directus.embed.get_embed_by_id(embed_id)
        if not embed or not embed.get("encrypted_content"):
            raise ProjectWriteAuthorizationError("PROJECT_AUTHORING_RESULT_UNAVAILABLE", status_code=409)
        commit_identity = hashlib.sha256((embed_id + "\0" + save_operation_id).encode()).hexdigest()
        receipts = await self.access.directus.get_items("embed_version_commits", params={
            "filter[commit_identity][_eq]": commit_identity,
            "fields": "operation_id,embed_id,committed_revision,expected_revision,actor_user_hash,hashed_project_id,hashed_chat_id,hashed_team_id,created_at",
            "limit": 1}, no_cache=True, admin_required=True)
        saved_embed_revision = job["base_embed_revision"] + 1
        if (not isinstance(receipts, list) or len(receipts) != 1
                or receipts[0].get("operation_id") != save_operation_id or receipts[0].get("embed_id") != embed_id
                or receipts[0].get("committed_revision") != saved_embed_revision
                or receipts[0].get("expected_revision") != job["base_embed_revision"]
                or receipts[0].get("actor_user_hash") != hashlib.sha256(user_id.encode()).hexdigest()
                or receipts[0].get("hashed_project_id") != hashlib.sha256(project_id.encode()).hexdigest()
                or receipts[0].get("hashed_chat_id") != hashlib.sha256(job["chat_id"].encode()).hexdigest()
                or receipts[0].get("hashed_team_id") != (hashlib.sha256(job["team_id"].encode()).hexdigest() if job.get("team_id") else None)
                or int(receipts[0].get("created_at") or 0) < job["created_at"]
                or embed.get("version_number") != saved_embed_revision):
            raise ProjectWriteAuthorizationError("PROJECT_AUTHORING_SAVE_PROOF_REQUIRED", status_code=409)
        # The existing client Project file write owns encryption and base CAS;
        # this endpoint only acknowledges its saved reachable result.
        job["result_id"], job["result_revision"], job["embed_id"] = project_item_id, revision, embed_id
        await self._ready(job)
        await self._save(job)
        await self.cache.delete(self.key(user_id, job_id) + ":draft")
        return self.public(job)

    async def _ready(self, job: dict[str, Any], *, vault_key_id: str | None = None) -> None:
        await self.access.require_context(job["user_id"], job["chat_id"], job["project_id"], job.get("team_id"), write=True)
        revision, _ = await self.access.require_target(user_id=job["user_id"], project_id=job["project_id"],
            kind=job["kind"], target_id=job["result_id"], team_id=job.get("team_id"), vault_key_id=vault_key_id)
        if revision != job["result_revision"]:
            raise ProjectWriteAuthorizationError("PROJECT_AUTHORING_REVISION_CONFLICT", status_code=409)
        event = NotificationEvent(id="project_authoring_" + job["job_id"], user_id=job["user_id"],
            type="project.authoring_ready", safe_title_key="apps.openmates", safe_body_key="notifications.project_authoring.ready",
            routing={"project_id": job["project_id"], "result_kind": job["kind"], "result_id": job["result_id"],
                     "embed_id": job.get("embed_id"), "job_id": job["job_id"], "team_id": job.get("team_id")}, metadata={"status": "ready"})
        if not job["notification_sent"]:
            client = await self.cache.client
            if client is None:
                raise ProjectWriteAuthorizationError("PROJECT_AUTHORING_CACHE_UNAVAILABLE", status_code=503)
            notification_key = self.key(job["user_id"], job["job_id"]) + ":notification"
            if await client.set(notification_key, "pending", nx=True, ex=30):
                try:
                    await self.notifications.store_and_publish(event)
                    await client.set(notification_key, "sent", ex=JOB_TTL)
                except Exception:
                    await client.delete(notification_key)
                    raise
            elif await client.get(notification_key) not in {"sent", b"sent"}:
                raise ProjectWriteAuthorizationError("PROJECT_AUTHORING_NOTIFICATION_PENDING", status_code=409)
            job["notification_sent"] = True
        job["status"] = "ready"

    async def _require_job(self, user_id: str, project_id: str, job_id: str, *, write: bool = False) -> dict[str, Any]:
        job = await self.cache.get(self.key(user_id, job_id))
        if not isinstance(job, dict) or job.get("user_id") != user_id or job.get("project_id") != project_id:
            raise ProjectWriteAuthorizationError("PROJECT_AUTHORING_JOB_NOT_FOUND", status_code=404)
        await self.access.require_context(user_id, job["chat_id"], project_id, job.get("team_id"), write=write)
        if job["status"] == "running" and time.time() - job["created_at"] > RECOMMENDATION_TTL:
            job["status"], job["error_code"] = "failed", "PROJECT_AUTHORING_INTERRUPTED"
            await self._save(job)
        return job

    async def _save(self, job: dict[str, Any], *, preserve_completion: bool = False) -> None:
        if preserve_completion and job["status"] == "pending_file":
            current = await self.cache.get(self.key(job["user_id"], job["job_id"]))
            if isinstance(current, dict) and current.get("status") in {"needs_binding_save", "ready", "conflict", "failed"}:
                job.update(current)
        job["updated_at"] = int(time.time())
        if not await self.cache.set(self.key(job["user_id"], job["job_id"]), job, ttl=JOB_TTL):
            raise ProjectWriteAuthorizationError("PROJECT_AUTHORING_CACHE_UNAVAILABLE", status_code=503)

    @staticmethod
    def public(job: dict[str, Any]) -> dict[str, Any]:
        allowed = {"job_id", "recommendation_id", "status", "project_id", "chat_id", "kind", "action", "target_id", "expected_revision",
                   "result_id", "result_revision", "embed_id", "workflow_version_id", "input_session_id",
                   "error_code", "file_operation_id", "created_at", "updated_at"}
        allowed.update({"project_item_id", "expected_item_revision"})
        return {key: value for key, value in job.items() if key in allowed}
