# backend/core/api/app/routes/user_plans.py
#
# Authenticated Plans V1 product API. Plans are durable coordination records for
# complex chat/project work and link to user-facing tasks and verification items.
#
# Spec: docs/specs/plans-v1/spec.yml

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user_or_api_key
from backend.core.api.app.services.directus.team_methods import TeamPermissionError
from backend.core.api.app.services.feature_availability_guards import ensure_plans_enabled
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.services.team_workspace_service import move_workspace_record_to_team
from backend.core.api.app.services.user_plan_service import (
    UserPlanConflictError,
    UserPlanNotFoundError,
    UserPlanService,
)
from backend.core.api.app.services.user_task_service import UserTaskService


router = APIRouter(prefix="/v1/user-plans", tags=["User Plans"], dependencies=[Depends(ensure_plans_enabled)])

PlanStatus = Literal["draft", "checking_assumptions", "awaiting_confirmation", "active", "executing", "running_checks", "blocked", "completed", "archived"]
CriterionStatus = Literal["pending", "satisfied", "failed", "waived"]
VerificationStatus = Literal["proposed", "pending", "passed", "failed", "passed_unexpectedly", "skipped", "skipped_with_reason", "not_applicable", "waived"]
KeyWrapperType = Literal["master", "chat", "project"]


class UserPlanKeyWrapperRequest(BaseModel):
    key_type: KeyWrapperType
    encrypted_plan_key: str = Field(min_length=1)
    hashed_chat_id: str | None = None
    hashed_project_id: str | None = None
    created_at: int
    expires_at: int | None = None


class PlanVerificationTaskKeyWrapperRequest(BaseModel):
    key_type: KeyWrapperType
    encrypted_task_key: str = Field(min_length=1)
    hashed_chat_id: str | None = None
    hashed_project_id: str | None = None
    created_at: int
    expires_at: int | None = None


class UserPlanCreateRequest(BaseModel):
    plan_id: str = Field(min_length=1)
    encrypted_plan_key: str | None = None
    encrypted_title: str = Field(min_length=1)
    encrypted_summary: str | None = None
    encrypted_goal: str | None = None
    encrypted_scope_in: str | None = None
    encrypted_scope_out: str | None = None
    encrypted_user_flows: str | None = None
    encrypted_current_focus: str | None = None
    encrypted_linked_project_ids: str | None = None
    encrypted_assumptions: str | None = None
    encrypted_open_questions: str | None = None
    encrypted_constraints: str | None = None
    encrypted_decisions: str | None = None
    encrypted_risks: str | None = None
    encrypted_reference_patterns: str | None = None
    encrypted_context: str | None = None
    encrypted_continuation_policy: str | None = None
    status: PlanStatus = "draft"
    primary_chat_id: str | None = None
    linked_project_ids: list[str] = Field(default_factory=list)
    current_phase_id: str | None = None
    current_step_id: str | None = None
    current_task_id: str | None = None
    continuation_state: str | None = None
    approval_state: str | None = None
    planner_focus_id: str | None = None
    created_at: int
    updated_at: int
    key_wrappers: list[UserPlanKeyWrapperRequest] = Field(default_factory=list)


class UserPlanUpdateRequest(BaseModel):
    encrypted_plan_key: str | None = None
    encrypted_title: str | None = None
    encrypted_summary: str | None = None
    encrypted_goal: str | None = None
    encrypted_scope_in: str | None = None
    encrypted_scope_out: str | None = None
    encrypted_user_flows: str | None = None
    encrypted_current_focus: str | None = None
    encrypted_linked_project_ids: str | None = None
    encrypted_assumptions: str | None = None
    encrypted_open_questions: str | None = None
    encrypted_constraints: str | None = None
    encrypted_decisions: str | None = None
    encrypted_risks: str | None = None
    encrypted_reference_patterns: str | None = None
    encrypted_context: str | None = None
    encrypted_continuation_policy: str | None = None
    status: PlanStatus | None = None
    primary_chat_id: str | None = None
    linked_project_ids: list[str] | None = None
    current_phase_id: str | None = None
    current_step_id: str | None = None
    current_task_id: str | None = None
    continuation_state: str | None = None
    approval_state: str | None = None
    planner_focus_id: str | None = None
    updated_at: int | None = None
    version: int | None = None
    key_wrappers: list[UserPlanKeyWrapperRequest] | None = None


class UserPlanMoveRequest(BaseModel):
    team_id: str
    confirmed: bool
    moved_at: int | None = None


class PlanActivationRequest(BaseModel):
    chat_id: str | None = None
    current_step_id: str | None = None
    current_task_id: str | None = None
    updated_at: int | None = None
    version: int | None = None


class PlanCompletionRequest(BaseModel):
    updated_at: int | None = None
    completion_note: str | None = None
    version: int | None = None


class PlanCriterionRequest(BaseModel):
    criterion_id: str = Field(min_length=1)
    encrypted_text: str = Field(min_length=1)
    type: str = "functional"
    status: CriterionStatus = "pending"
    required: bool = True
    linked_step_ids: list[str] = Field(default_factory=list)
    linked_task_ids: list[str] = Field(default_factory=list)
    verification_ids: list[str] = Field(default_factory=list)
    coverage_status: str = "uncovered"
    verification_scope: str | None = None
    created_at: int
    updated_at: int | None = None


class PlanCriterionUpdateRequest(BaseModel):
    status: CriterionStatus | None = None
    encrypted_evidence: str | None = None
    encrypted_coverage_note: str | None = None
    encrypted_waiver_reason: str | None = None
    verification_ids: list[str] | None = None
    coverage_status: str | None = None
    verification_scope: str | None = None
    updated_at: int | None = None
    version: int | None = None


class PlanVerificationRequest(BaseModel):
    verification_id: str = Field(min_length=1)
    kind: str
    phase: str = "final"
    status: VerificationStatus = "pending"
    lifecycle_status: str | None = None
    required_for_done: bool = True
    covers: list[str] = Field(default_factory=list)
    source_hash: str | None = None
    threshold: int | None = None
    score: int | None = None
    confidence: str | None = None
    assigned_to: str | None = None
    linked_sub_chat_id: str | None = None
    source_embed_id: str | None = None
    runner_kind: str | None = None
    create_task: bool = False
    task_id: str | None = None
    encrypted_task_key: str | None = None
    task_key_wrappers: list[PlanVerificationTaskKeyWrapperRequest] = Field(default_factory=list)
    encrypted_linked_project_ids: str | None = None
    encrypted_title: str | None = None
    encrypted_description: str | None = None
    encrypted_command: str | None = None
    encrypted_evaluation_prompt: str | None = None
    encrypted_evaluator_instructions: str | None = None
    encrypted_expected_result: str | None = None
    encrypted_source_path: str | None = None
    encrypted_red_phase_reason: str | None = None
    primary_chat_id: str | None = None
    linked_project_ids: list[str] = Field(default_factory=list)
    plan_step_id: str | None = None
    assignee_type: str = "user"
    created_at: int
    updated_at: int | None = None


class PlanVerificationEvidenceRequest(BaseModel):
    status: VerificationStatus
    score: int | None = None
    threshold: int | None = None
    confidence: str | None = None
    run_id: str | None = None
    encrypted_result_summary: str | None = None
    encrypted_required_fixes: str | None = None
    updated_at: int | None = None


class PlanDriftCheckRequest(BaseModel):
    drift_score: int = Field(ge=0, le=100)
    correction_message: str | None = None
    active_task_id: str | None = None


class UserPlanKeyWrappersRequest(BaseModel):
    key_wrappers: list[UserPlanKeyWrapperRequest] = Field(min_length=1)


class PlanAssumptionRequest(BaseModel):
    assumption_id: str = Field(min_length=1)
    encrypted_text: str = Field(min_length=1)
    category: str = "other"
    status: str = "unchecked"
    required_before: str = "implementation"
    linked_sub_chat_id: str | None = None
    linked_task_id: str | None = None
    linked_step_ids: list[str] = Field(default_factory=list)
    linked_criterion_ids: list[str] = Field(default_factory=list)
    source_count: int = 0
    encrypted_corrected_text: str | None = None
    encrypted_evidence_summary: str | None = None
    encrypted_blocker_reason: str | None = None
    encrypted_waiver_reason: str | None = None
    encrypted_sources: str | None = None
    created_at: int
    updated_at: int | None = None


class PlanAssumptionUpdateRequest(BaseModel):
    status: str | None = None
    required_before: str | None = None
    linked_sub_chat_id: str | None = None
    linked_task_id: str | None = None
    source_count: int | None = None
    encrypted_corrected_text: str | None = None
    encrypted_evidence_summary: str | None = None
    encrypted_blocker_reason: str | None = None
    encrypted_waiver_reason: str | None = None
    encrypted_sources: str | None = None
    updated_at: int | None = None


class PlanReferencePatternRequest(BaseModel):
    pattern_id: str = Field(min_length=1)
    encrypted_title: str = Field(min_length=1)
    encrypted_description: str | None = None
    category: str = "other"
    status: str = "proposed"
    required_before: str = "implementation"
    source_count: int = 0
    linked_task_ids: list[str] = Field(default_factory=list)
    linked_check_ids: list[str] = Field(default_factory=list)
    encrypted_sources: str | None = None
    encrypted_match_rules: str | None = None
    encrypted_anti_patterns: str | None = None
    encrypted_evidence_summary: str | None = None
    encrypted_waiver_reason: str | None = None
    created_at: int
    updated_at: int | None = None


class PlanReferencePatternUpdateRequest(BaseModel):
    status: str | None = None
    required_before: str | None = None
    source_count: int | None = None
    linked_task_ids: list[str] | None = None
    linked_check_ids: list[str] | None = None
    encrypted_description: str | None = None
    encrypted_sources: str | None = None
    encrypted_match_rules: str | None = None
    encrypted_anti_patterns: str | None = None
    encrypted_evidence_summary: str | None = None
    encrypted_waiver_reason: str | None = None
    updated_at: int | None = None


class PlanExecutionContextRequest(BaseModel):
    vault_encrypted_context: str = Field(min_length=1)
    expires_at: int
    context_version: int = 1
    created_at: int | None = None


class PlanVerificationRunRequest(BaseModel):
    run_id: str = Field(min_length=1)
    runner_kind: str
    status: str = "queued"
    exit_code: int | None = None
    source_embed_id: str | None = None
    started_at: int | None = None
    finished_at: int | None = None
    duration_ms: int | None = None
    artifact_count: int = 0
    created_at: int
    encrypted_command: str | None = None
    encrypted_summary: str | None = None
    encrypted_step_timeline: str | None = None
    encrypted_stdout: str | None = None
    encrypted_stderr: str | None = None
    encrypted_environment: str | None = None


def get_user_plan_service(request: Request) -> UserPlanService:
    task_service = UserTaskService(request.app.state.directus_service.user_task, cache_service=request.app.state.cache_service)
    return UserPlanService(request.app.state.directus_service.user_plan, task_service=task_service)


async def _current_user(request: Request, response: Response) -> User:
    return await get_current_user_or_api_key(
        request=request,
        response=response,
        directus_service=request.app.state.directus_service,
        cache_service=request.app.state.cache_service,
        refresh_token=request.cookies.get("auth_refresh_token"),
    )


def _handle_plan_error(exc: Exception) -> None:
    if isinstance(exc, TeamPermissionError):
        raise HTTPException(status_code=403, detail="TEAM_PERMISSION_DENIED") from exc
    if isinstance(exc, UserPlanConflictError):
        raise HTTPException(status_code=409, detail="PLAN_VERSION_CONFLICT") from exc
    if isinstance(exc, UserPlanNotFoundError):
        raise HTTPException(status_code=404, detail="Plan not found") from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise exc


@router.get("")
@limiter.limit("60/minute")
async def list_user_plans(
    request: Request,
    response: Response,
    status: PlanStatus | None = None,
    project_id: str | None = None,
    chat_id: str | None = None,
    active_only: bool = False,
    team_id: str | None = None,
    limit: int = 100,
    service: UserPlanService = Depends(get_user_plan_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        if team_id:
            await request.app.state.directus_service.team.require_team_role(team_id, current_user.id, {"owner", "admin", "member", "viewer"})
    except Exception as exc:
        _handle_plan_error(exc)
    plans = await service.list_plans(current_user.id, status=status, project_id=project_id, chat_id=chat_id, active_only=active_only, team_id=team_id, limit=limit)
    return {"plans": plans}


@router.post("")
@limiter.limit("30/minute")
async def create_user_plan(
    request: Request,
    response: Response,
    body: UserPlanCreateRequest,
    service: UserPlanService = Depends(get_user_plan_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        plan = await service.create_plan(current_user.id, body.model_dump())
        return {"plan": plan}
    except Exception as exc:
        _handle_plan_error(exc)


@router.patch("/{plan_id}")
@limiter.limit("30/minute")
async def update_user_plan(
    request: Request,
    response: Response,
    plan_id: str,
    body: UserPlanUpdateRequest,
    service: UserPlanService = Depends(get_user_plan_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        plan = await service.update_plan(plan_id, current_user.id, body.model_dump(exclude_unset=True))
        return {"plan": plan}
    except Exception as exc:
        _handle_plan_error(exc)


@router.post("/{plan_id}/move")
@limiter.limit("20/minute")
async def move_user_plan_to_team(
    request: Request,
    response: Response,
    plan_id: str,
    body: UserPlanMoveRequest,
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        plan = await move_workspace_record_to_team(
            directus_service=request.app.state.directus_service,
            actor_user_id=current_user.id,
            team_id=body.team_id,
            workspace_type="plan",
            object_id=plan_id,
            confirmed=body.confirmed,
            moved_at=body.moved_at,
        )
        return {"plan": plan}
    except Exception as exc:
        _handle_plan_error(exc)


@router.post("/{plan_id}/key-wrappers")
@limiter.limit("20/minute")
async def add_user_plan_key_wrappers(
    request: Request,
    response: Response,
    plan_id: str,
    body: UserPlanKeyWrappersRequest,
    service: UserPlanService = Depends(get_user_plan_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    existing = await service.plan_methods.get_plan(plan_id, current_user.id)
    if not existing:
        raise HTTPException(status_code=404, detail="Plan not found")
    created = await service.plan_methods.replace_plan_key_wrappers(
        current_user.id,
        plan_id,
        [wrapper.model_dump() for wrapper in body.key_wrappers],
    )
    if created is None:
        raise HTTPException(status_code=400, detail="Invalid plan key wrappers")
    return {"key_wrappers": created}


@router.get("/{plan_id}/key-wrappers")
@limiter.limit("60/minute")
async def list_user_plan_key_wrappers(
    request: Request,
    response: Response,
    plan_id: str,
    service: UserPlanService = Depends(get_user_plan_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    existing = await service.plan_methods.get_plan(plan_id, current_user.id)
    if not existing:
        raise HTTPException(status_code=404, detail="Plan not found")
    return {"key_wrappers": await service.plan_methods.list_plan_key_wrappers(current_user.id, plan_id)}


@router.post("/{plan_id}/activate")
@limiter.limit("30/minute")
async def activate_user_plan(
    request: Request,
    response: Response,
    plan_id: str,
    body: PlanActivationRequest,
    service: UserPlanService = Depends(get_user_plan_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    patch = body.model_dump(exclude_unset=True)
    if body.chat_id is not None:
        patch["primary_chat_id"] = body.chat_id
        patch.pop("chat_id", None)
    try:
        plan = await service.activate_plan(plan_id, current_user.id, patch)
        return {"plan": plan}
    except Exception as exc:
        _handle_plan_error(exc)


@router.get("/active-context")
@limiter.limit("60/minute")
async def get_active_plan_context(
    request: Request,
    response: Response,
    chat_id: str,
    now: int | None = None,
    service: UserPlanService = Depends(get_user_plan_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        import time

        return await service.active_context(current_user.id, chat_id, now or int(time.time()))
    except Exception as exc:
        _handle_plan_error(exc)


@router.post("/{plan_id}/complete")
@limiter.limit("20/minute")
async def complete_user_plan(
    request: Request,
    response: Response,
    plan_id: str,
    body: PlanCompletionRequest,
    service: UserPlanService = Depends(get_user_plan_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        return await service.complete_plan(plan_id, current_user.id, body.model_dump(exclude_unset=True))
    except Exception as exc:
        _handle_plan_error(exc)


@router.post("/{plan_id}/criteria")
@limiter.limit("60/minute")
async def create_plan_criterion(
    request: Request,
    response: Response,
    plan_id: str,
    body: PlanCriterionRequest,
    service: UserPlanService = Depends(get_user_plan_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        criterion = await service.create_criterion(plan_id, current_user.id, body.model_dump())
        return {"criterion": criterion}
    except Exception as exc:
        _handle_plan_error(exc)


@router.get("/{plan_id}/criteria")
@limiter.limit("60/minute")
async def list_plan_criteria(
    request: Request,
    response: Response,
    plan_id: str,
    service: UserPlanService = Depends(get_user_plan_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        await service.ensure_plan_owner(plan_id, current_user.id)
        return {"criteria": await service.plan_methods.list_criteria(plan_id)}
    except Exception as exc:
        _handle_plan_error(exc)


@router.patch("/{plan_id}/criteria/{criterion_id}")
@limiter.limit("60/minute")
async def update_plan_criterion(
    request: Request,
    response: Response,
    plan_id: str,
    criterion_id: str,
    body: PlanCriterionUpdateRequest,
    service: UserPlanService = Depends(get_user_plan_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        criterion = await service.update_criterion(plan_id, current_user.id, criterion_id, body.model_dump(exclude_unset=True))
        return {"criterion": criterion}
    except Exception as exc:
        _handle_plan_error(exc)


@router.post("/{plan_id}/verification")
@limiter.limit("60/minute")
async def create_plan_verification(
    request: Request,
    response: Response,
    plan_id: str,
    body: PlanVerificationRequest,
    service: UserPlanService = Depends(get_user_plan_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        return await service.create_verification(plan_id, current_user.id, body.model_dump(exclude_unset=True))
    except Exception as exc:
        _handle_plan_error(exc)


@router.get("/{plan_id}/verification")
@limiter.limit("60/minute")
async def list_plan_verifications(
    request: Request,
    response: Response,
    plan_id: str,
    service: UserPlanService = Depends(get_user_plan_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        await service.ensure_plan_owner(plan_id, current_user.id)
        return {"verifications": await service.plan_methods.list_verifications(plan_id)}
    except Exception as exc:
        _handle_plan_error(exc)


@router.post("/{plan_id}/assumptions")
@limiter.limit("60/minute")
async def create_plan_assumption(
    request: Request,
    response: Response,
    plan_id: str,
    body: PlanAssumptionRequest,
    service: UserPlanService = Depends(get_user_plan_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        assumption = await service.create_assumption(plan_id, current_user.id, body.model_dump())
        return {"assumption": assumption}
    except Exception as exc:
        _handle_plan_error(exc)


@router.get("/{plan_id}/assumptions")
@limiter.limit("60/minute")
async def list_plan_assumptions(
    request: Request,
    response: Response,
    plan_id: str,
    service: UserPlanService = Depends(get_user_plan_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        await service.ensure_plan_owner(plan_id, current_user.id)
        return {"assumptions": await service.plan_methods.list_assumptions(plan_id)}
    except Exception as exc:
        _handle_plan_error(exc)


@router.patch("/{plan_id}/assumptions/{assumption_id}")
@limiter.limit("60/minute")
async def update_plan_assumption(
    request: Request,
    response: Response,
    plan_id: str,
    assumption_id: str,
    body: PlanAssumptionUpdateRequest,
    service: UserPlanService = Depends(get_user_plan_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        assumption = await service.update_assumption(plan_id, current_user.id, assumption_id, body.model_dump(exclude_unset=True))
        return {"assumption": assumption}
    except Exception as exc:
        _handle_plan_error(exc)


@router.post("/{plan_id}/reference-patterns")
@limiter.limit("60/minute")
async def create_plan_reference_pattern(
    request: Request,
    response: Response,
    plan_id: str,
    body: PlanReferencePatternRequest,
    service: UserPlanService = Depends(get_user_plan_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        pattern = await service.create_reference_pattern(plan_id, current_user.id, body.model_dump())
        return {"reference_pattern": pattern}
    except Exception as exc:
        _handle_plan_error(exc)


@router.get("/{plan_id}/reference-patterns")
@limiter.limit("60/minute")
async def list_plan_reference_patterns(
    request: Request,
    response: Response,
    plan_id: str,
    service: UserPlanService = Depends(get_user_plan_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        await service.ensure_plan_owner(plan_id, current_user.id)
        return {"reference_patterns": await service.plan_methods.list_reference_patterns(plan_id)}
    except Exception as exc:
        _handle_plan_error(exc)


@router.patch("/{plan_id}/reference-patterns/{pattern_id}")
@limiter.limit("60/minute")
async def update_plan_reference_pattern(
    request: Request,
    response: Response,
    plan_id: str,
    pattern_id: str,
    body: PlanReferencePatternUpdateRequest,
    service: UserPlanService = Depends(get_user_plan_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        pattern = await service.update_reference_pattern(plan_id, current_user.id, pattern_id, body.model_dump(exclude_unset=True))
        return {"reference_pattern": pattern}
    except Exception as exc:
        _handle_plan_error(exc)


@router.post("/{plan_id}/verification/{verification_id}/evidence")
@limiter.limit("60/minute")
async def add_plan_verification_evidence(
    request: Request,
    response: Response,
    plan_id: str,
    verification_id: str,
    body: PlanVerificationEvidenceRequest,
    service: UserPlanService = Depends(get_user_plan_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        verification = await service.add_verification_evidence(plan_id, current_user.id, verification_id, body.model_dump(exclude_unset=True))
        return {"verification": verification}
    except Exception as exc:
        _handle_plan_error(exc)


@router.post("/{plan_id}/verification/{verification_id}/runs")
@limiter.limit("60/minute")
async def create_plan_verification_run(
    request: Request,
    response: Response,
    plan_id: str,
    verification_id: str,
    body: PlanVerificationRunRequest,
    service: UserPlanService = Depends(get_user_plan_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        run = await service.create_verification_run(plan_id, current_user.id, verification_id, body.model_dump(exclude_unset=True))
        return {"run": run}
    except Exception as exc:
        _handle_plan_error(exc)


@router.get("/{plan_id}/verification/{verification_id}/runs/{run_id}")
@limiter.limit("60/minute")
async def get_plan_verification_run(
    request: Request,
    response: Response,
    plan_id: str,
    verification_id: str,
    run_id: str,
    service: UserPlanService = Depends(get_user_plan_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        return await service.get_verification_run(plan_id, current_user.id, verification_id, run_id)
    except Exception as exc:
        _handle_plan_error(exc)


@router.post("/{plan_id}/execution-context")
@limiter.limit("30/minute")
async def save_plan_execution_context(
    request: Request,
    response: Response,
    plan_id: str,
    body: PlanExecutionContextRequest,
    service: UserPlanService = Depends(get_user_plan_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    try:
        return await service.save_execution_context(plan_id, current_user.id, body.model_dump(exclude_unset=True))
    except Exception as exc:
        _handle_plan_error(exc)


@router.post("/{plan_id}/drift-check")
@limiter.limit("60/minute")
async def plan_drift_check(
    request: Request,
    response: Response,
    plan_id: str,
    body: PlanDriftCheckRequest,
    service: UserPlanService = Depends(get_user_plan_service),
) -> dict[str, Any]:
    current_user = await _current_user(request, response)
    await service.ensure_plan_owner(plan_id, current_user.id)
    message = body.correction_message or "Return to the active plan and current task."
    return service.build_correction_message(plan_id, body.drift_score, message, task_id=body.active_task_id)
