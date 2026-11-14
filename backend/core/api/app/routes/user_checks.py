"""First-party reusable mixed-source Checks (client-encrypted, never public API).

Session and approved paired-device callers only; excluded from public API docs.
Titles, definitions and result detail are opaque client ciphertext.
"""

from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user_or_api_key
from backend.core.api.app.services.directus.team_methods import TeamPermissionError
from backend.core.api.app.services.feature_availability_guards import ensure_projects_enabled
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.services.user_check_ai_evaluator import (
    DEFAULT_THRESHOLD, MAX_EVIDENCE_CHARS, MAX_QUESTION_CHARS, AiEvaluationError, evaluate_check_source,
)
from backend.core.api.app.services.user_check_service import CheckError, UserCheckService

router = APIRouter(prefix="/v1/user-checks", tags=["User Checks"], dependencies=[Depends(ensure_projects_enabled)])
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
SourceKind = Literal["e2e", "unit", "integration", "static_analysis", "deterministic_audit",
                     "ai_evaluation", "human_confirmation"]


class SourceBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_binding_id: str = Field(min_length=1, max_length=128)
    source_kind: SourceKind
    role: Literal["required", "supporting"]


class RevisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision_id: UUID
    definition_hash: Hash
    requires_deterministic: bool = False
    sources: list[SourceBinding] = Field(min_length=1, max_length=50)
    encrypted_definition: str = Field(min_length=1, max_length=4 * 1024 * 1024)


class KeyWrapper(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key_type: Literal["master", "project", "team"]
    encrypted_check_key: str = Field(min_length=1, max_length=16384)
    hashed_project_id: Hash | None = None
    hashed_team_id: Hash | None = None
    team_key_epoch: int | None = Field(default=None, ge=1)


class CheckCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    check_id: UUID
    project_id: UUID
    status: Literal["draft", "ready"] = "draft"
    linked_project_hashes: list[Hash] = Field(default_factory=list, max_length=50)
    encrypted_title: str = Field(min_length=1, max_length=16384)
    encrypted_description: str | None = Field(default=None, max_length=65536)
    key_wrappers: list[KeyWrapper] = Field(min_length=1, max_length=20)
    revision: RevisionInput


class CheckReviseInput(RevisionInput):
    base_revision_id: UUID
    status: Literal["draft", "ready", "archived"] | None = None
    encrypted_title: str | None = Field(default=None, min_length=1, max_length=16384)
    encrypted_description: str | None = Field(default=None, max_length=65536)


class RunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject_revision: str | None = Field(default=None, max_length=255)
    encrypted_summary: str | None = Field(default=None, max_length=65536)


class SourceResultInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_kind: SourceKind
    status: Literal["pending", "running", "passed", "failed", "error", "blocked", "skipped", "cancelled", "waived"]
    test_result_embed_id: str | None = Field(default=None, max_length=255)
    ai_score: float | None = None
    ai_threshold: float | None = None
    encrypted_result: str | None = Field(default=None, max_length=1024 * 1024)


class AiEvaluateInput(BaseModel):
    """Plaintext question and evidence are transient: used for one model call, never stored."""
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    evidence: str = Field(min_length=1, max_length=MAX_EVIDENCE_CHARS)
    threshold: int = Field(default=DEFAULT_THRESHOLD, ge=0, le=100)
    encrypted_result: str | None = Field(default=None, max_length=1024 * 1024)

class ConfirmInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["confirmed", "rejected", "blocked", "waived"]
    encrypted_result: str | None = Field(default=None, max_length=1024 * 1024)


class PlanLinkInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str = Field(min_length=1, max_length=128)
    required: bool = True
    criterion_id: str | None = Field(default=None, max_length=128)


async def _service(request: Request, user: User, team_id: str | None, *, write: bool = False) -> UserCheckService:
    directus = request.app.state.directus_service
    if team_id:
        roles = {"owner", "admin", "member"} if write else {"owner", "admin", "member", "viewer"}
        try:
            await directus.team.require_team_role(team_id, user.id, roles)
        except TeamPermissionError as exc:
            raise HTTPException(status_code=403, detail={"error": "team_permission_denied"}) from exc
    return UserCheckService(directus)


def _error(exc: CheckError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"error": exc.code})


@router.post("", status_code=201)
@limiter.limit("30/minute")
async def create_check(request: Request, body: CheckCreateInput, team_id: str | None = None,
                       user: User = Depends(get_current_user_or_api_key)):
    service = await _service(request, user, team_id, write=True)
    try:
        return await service.create_check(user.id, body.model_dump(mode="json", exclude_none=True), team_id=team_id)
    except CheckError as exc:
        raise _error(exc) from exc


@router.get("")
@limiter.limit("60/minute")
async def list_checks(request: Request, project_hash: Hash | None = None, plan_id: str | None = None,
                      team_id: str | None = None, limit: int = Query(50, ge=1, le=100),
                      user: User = Depends(get_current_user_or_api_key)):
    service = await _service(request, user, team_id)
    try:
        return await service.list_checks(user.id, team_id=team_id, project_hash=project_hash,
                                         plan_id=plan_id, limit=limit)
    except CheckError as exc:
        raise _error(exc) from exc


@router.post("/runs/{run_id}/sources/{binding_id}/result")
@limiter.limit("120/minute")
async def record_source_result(request: Request, run_id: UUID, binding_id: str, body: SourceResultInput,
                               team_id: str | None = None, user: User = Depends(get_current_user_or_api_key)):
    service = await _service(request, user, team_id, write=True)
    try:
        return await service.record_result(str(run_id), binding_id, user.id, body.model_dump(mode="json"), team_id=team_id)
    except CheckError as exc:
        raise _error(exc) from exc


async def _bill_ai_evaluation(user_id: str, run_id: str, binding_id: str) -> None:
    """Prepay one normal AI credit through the Workflow AI Check billing path."""
    from backend.core.api.app.services.workflow_app_skill_adapter import WorkflowSkillBillingError
    from backend.core.api.app.services.workflow_runner import _charge_workflow_ai_check, _precheck_workflow_ai_check
    try:
        await _precheck_workflow_ai_check(user_id)
        await _charge_workflow_ai_check(
            user_id=user_id, context={"workflow": {"workflow_id": "user-check", "run_id": run_id}},
            node_id=binding_id, operation_id=str(uuid4()), source_override="user_check",
            skill_id="user-check-ai-evaluation")
    except WorkflowSkillBillingError as exc:
        status = 402 if getattr(exc, "code", "") == "INSUFFICIENT_CREDITS" else 503
        raise HTTPException(status_code=status, detail={"error": getattr(exc, "code", "billing_unavailable")}) from exc

@router.post("/runs/{run_id}/sources/{binding_id}/ai-evaluate")
@limiter.limit("30/minute")
async def ai_evaluate_source(request: Request, run_id: UUID, binding_id: str, body: AiEvaluateInput,
                             team_id: str | None = None, user: User = Depends(get_current_user_or_api_key)):
    """Judge the question against the evidence and store passed/failed/error for an ai_evaluation source."""
    service = await _service(request, user, team_id, write=True)
    payload = {"source_kind": "ai_evaluation", "ai_threshold": body.threshold,
               "encrypted_result": body.encrypted_result}
    try:
        await service.require_binding(str(run_id), binding_id, "ai_evaluation", user.id, team_id=team_id)
        await _bill_ai_evaluation(user.id, str(run_id), binding_id)
        evaluation = await evaluate_check_source(
            body.question, body.evidence, threshold=body.threshold,
            secrets_manager=getattr(request.app.state, "secrets_manager", None))
    except AiEvaluationError:
        try:
            stored = await service.record_result(str(run_id), binding_id, user.id,
                                                 {**payload, "status": "error"}, team_id=team_id)
        except CheckError as exc:
            raise _error(exc) from exc
        return {**stored, "verdict": "error", "score": None, "feedback": None}
    except CheckError as exc:
        raise _error(exc) from exc
    try:
        stored = await service.record_result(str(run_id), binding_id, user.id, {
            **payload, "status": "passed" if evaluation.verdict == "pass" else "failed",
            "ai_score": evaluation.score}, team_id=team_id)
    except CheckError as exc:
        raise _error(exc) from exc
    return {**stored, "verdict": evaluation.verdict, "score": evaluation.score, "feedback": evaluation.feedback}

@router.post("/runs/{run_id}/sources/{binding_id}/confirm")
@limiter.limit("60/minute")
async def confirm_source(request: Request, run_id: UUID, binding_id: str, body: ConfirmInput,
                         team_id: str | None = None, user: User = Depends(get_current_user_or_api_key)):
    service = await _service(request, user, team_id, write=True)
    try:
        return await service.confirm(str(run_id), binding_id, user.id, body.model_dump(mode="json"), team_id=team_id)
    except CheckError as exc:
        raise _error(exc) from exc


@router.get("/{check_id}")
@limiter.limit("60/minute")
async def get_check(request: Request, check_id: UUID, team_id: str | None = None,
                    user: User = Depends(get_current_user_or_api_key)):
    service = await _service(request, user, team_id)
    try:
        return await service.get_check(str(check_id), user.id, team_id=team_id)
    except CheckError as exc:
        raise _error(exc) from exc


@router.get("/{check_id}/revisions")
@limiter.limit("60/minute")
async def list_revisions(request: Request, check_id: UUID, team_id: str | None = None,
                         limit: int = Query(50, ge=1, le=100), user: User = Depends(get_current_user_or_api_key)):
    service = await _service(request, user, team_id)
    try:
        return await service.list_revisions(str(check_id), user.id, team_id=team_id, limit=limit)
    except CheckError as exc:
        raise _error(exc) from exc


@router.post("/{check_id}/revisions")
@limiter.limit("30/minute")
async def revise_check(request: Request, check_id: UUID, body: CheckReviseInput, team_id: str | None = None,
                       user: User = Depends(get_current_user_or_api_key)):
    service = await _service(request, user, team_id, write=True)
    try:
        return await service.revise(str(check_id), user.id, body.model_dump(mode="json"), team_id=team_id)
    except CheckError as exc:
        raise _error(exc) from exc


@router.post("/{check_id}/runs", status_code=201)
@limiter.limit("60/minute")
async def start_run(request: Request, check_id: UUID, body: RunInput, team_id: str | None = None,
                    user: User = Depends(get_current_user_or_api_key)):
    service = await _service(request, user, team_id, write=True)
    try:
        return await service.start_run(str(check_id), user.id, body.model_dump(mode="json"), team_id=team_id)
    except CheckError as exc:
        raise _error(exc) from exc


@router.get("/{check_id}/runs")
@limiter.limit("60/minute")
async def list_runs(request: Request, check_id: UUID, team_id: str | None = None,
                    limit: int = Query(20, ge=1, le=100), user: User = Depends(get_current_user_or_api_key)):
    service = await _service(request, user, team_id)
    try:
        return await service.list_runs(str(check_id), user.id, team_id=team_id, limit=limit)
    except CheckError as exc:
        raise _error(exc) from exc


@router.post("/{check_id}/plan-links")
@limiter.limit("60/minute")
async def link_plan(request: Request, check_id: UUID, body: PlanLinkInput, team_id: str | None = None,
                    user: User = Depends(get_current_user_or_api_key)):
    service = await _service(request, user, team_id, write=True)
    try:
        return await service.link_plan(str(check_id), user.id, body.model_dump(mode="json"), team_id=team_id)
    except CheckError as exc:
        raise _error(exc) from exc


@router.delete("/{check_id}/plan-links/{plan_id}")
@limiter.limit("60/minute")
async def unlink_plan(request: Request, check_id: UUID, plan_id: str, team_id: str | None = None,
                      user: User = Depends(get_current_user_or_api_key)):
    service = await _service(request, user, team_id, write=True)
    try:
        return await service.unlink_plan(str(check_id), plan_id, user.id, team_id=team_id)
    except CheckError as exc:
        raise _error(exc) from exc
