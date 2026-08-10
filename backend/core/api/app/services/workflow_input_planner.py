"""Strict, isolated planning boundary for workflow input.

This module accepts sanitized user-owned evidence plus compact server-owned
context and turns provider output into validated workflow commands. It does not
call chat processing or execute workflow mutations.

Spec: docs/specs/workflows-v1/spec.yml
"""

from __future__ import annotations

from typing import Annotated, Literal, Protocol, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from backend.core.api.app.services.workflow_input_security import (
    sanitize_workflow_input_text,
)
from backend.core.api.app.services.workflow_models import WorkflowGraph


MAX_PLANNER_TEXT_LENGTH = 20_000
MAX_EVIDENCE_ITEMS = 12
MAX_EVIDENCE_TEXT_LENGTH = 12_000
MAX_CONTEXT_ITEMS = 100
MAX_TITLE_LENGTH = 200
MAX_CLARIFICATION_LENGTH = 2_000
WORKFLOW_INPUT_PLANNER_PROVIDER_UNAVAILABLE = (
    "WORKFLOW_INPUT_PLANNER_PROVIDER_UNAVAILABLE"
)


class WorkflowInputPlannerUnavailableError(RuntimeError):
    """Raised when no approved workflow-input planning provider is configured."""

    def __init__(self) -> None:
        self.code = WORKFLOW_INPUT_PLANNER_PROVIDER_UNAVAILABLE
        super().__init__("Structured workflow planning is not available.")


class WorkflowInputPlannerValidationError(ValueError):
    """Raised when a provider command violates the workflow-input contract."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class WorkflowInputEvidence(_StrictModel):
    """A user-supplied source that is always treated as untrusted evidence."""

    source: Literal["attachment", "external", "location", "paste"]
    label: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    text: str = Field(min_length=1, max_length=MAX_EVIDENCE_TEXT_LENGTH)


class WorkflowPlannerInput(_StrictModel):
    """Raw workflow-input text received from a trusted workflow-input boundary."""

    text: str | None = Field(
        default=None, min_length=1, max_length=MAX_PLANNER_TEXT_LENGTH
    )
    transcript: str | None = Field(
        default=None, min_length=1, max_length=MAX_PLANNER_TEXT_LENGTH
    )
    evidence: list[WorkflowInputEvidence] = Field(
        default_factory=list, max_length=MAX_EVIDENCE_ITEMS
    )

    @model_validator(mode="after")
    def require_content(self) -> WorkflowPlannerInput:
        if self.text is None and self.transcript is None and not self.evidence:
            raise ValueError(
                "workflow planner input requires text, transcript, or evidence"
            )
        return self


class SanitizedWorkflowInputEvidence(_StrictModel):
    """Untrusted evidence after deterministic input sanitization."""

    source: Literal["attachment", "external", "location", "paste"]
    label: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    text: str = Field(min_length=1, max_length=MAX_EVIDENCE_TEXT_LENGTH)


class SanitizedWorkflowPlannerInput(_StrictModel):
    """Provider-safe input preserving evidence provenance without instruction authority."""

    text: str | None = Field(
        default=None, min_length=1, max_length=MAX_PLANNER_TEXT_LENGTH
    )
    transcript: str | None = Field(
        default=None, min_length=1, max_length=MAX_PLANNER_TEXT_LENGTH
    )
    evidence: list[SanitizedWorkflowInputEvidence] = Field(
        default_factory=list, max_length=MAX_EVIDENCE_ITEMS
    )

    @model_validator(mode="after")
    def require_content(self) -> SanitizedWorkflowPlannerInput:
        if self.text is None and self.transcript is None and not self.evidence:
            raise ValueError("sanitized workflow planner input must not be empty")
        return self


class WorkflowPlannerWorkflowContext(_StrictModel):
    """Minimal owner-scoped workflow metadata available to the planner."""

    id: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)


class WorkflowPlannerProjectContext(_StrictModel):
    """Minimal owner-scoped project metadata available to the planner."""

    id: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)


class WorkflowPlannerCapabilityContext(_StrictModel):
    """A server-registered capability that may be referenced by a workflow graph."""

    id: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)


class ServerWorkflowPlannerContext(_StrictModel):
    """Compact server-loaded context; callers must never fill this from client records."""

    workflows: list[WorkflowPlannerWorkflowContext] = Field(
        default_factory=list, max_length=MAX_CONTEXT_ITEMS
    )
    projects: list[WorkflowPlannerProjectContext] = Field(
        default_factory=list, max_length=MAX_CONTEXT_ITEMS
    )
    capabilities: list[WorkflowPlannerCapabilityContext] = Field(
        default_factory=list, max_length=MAX_CONTEXT_ITEMS
    )
    selected_workflow_id: str | None = Field(
        default=None, min_length=1, max_length=MAX_TITLE_LENGTH
    )
    selected_project_id: str | None = Field(
        default=None, min_length=1, max_length=MAX_TITLE_LENGTH
    )

    @model_validator(mode="after")
    def validate_selected_targets(self) -> ServerWorkflowPlannerContext:
        workflow_ids = {workflow.id for workflow in self.workflows}
        project_ids = {project.id for project in self.projects}
        if (
            self.selected_workflow_id is not None
            and self.selected_workflow_id not in workflow_ids
        ):
            raise ValueError(
                "selected_workflow_id must be owner-scoped workflow context"
            )
        if (
            self.selected_project_id is not None
            and self.selected_project_id not in project_ids
        ):
            raise ValueError("selected_project_id must be owner-scoped project context")
        return self


class WorkflowPlannerProviderRequest(_StrictModel):
    """Typed provider request with untrusted evidence explicitly separated from context."""

    input: SanitizedWorkflowPlannerInput
    context: ServerWorkflowPlannerContext


class NeedsClarificationCommand(_StrictModel):
    action: Literal["needs_clarification"]
    message: str = Field(min_length=1, max_length=MAX_CLARIFICATION_LENGTH)


class DraftWorkflowCommand(_StrictModel):
    action: Literal["draft"]
    draft_graph: WorkflowGraph


class CreateWorkflowCommand(_StrictModel):
    action: Literal["create_workflow"]
    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    graph: WorkflowGraph
    enabled: bool = False
    assumptions: list[str] = Field(default_factory=list, max_length=20)


class UpdateWorkflowCommand(_StrictModel):
    action: Literal["update_workflow"]
    workflow_id: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    title: str | None = Field(default=None, min_length=1, max_length=MAX_TITLE_LENGTH)
    graph: WorkflowGraph | None = None

    @model_validator(mode="after")
    def require_change(self) -> UpdateWorkflowCommand:
        if self.title is None and self.graph is None:
            raise ValueError("update_workflow requires title or graph")
        return self


class DeleteWorkflowCommand(_StrictModel):
    action: Literal["delete_workflow"]
    workflow_id: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)


class LinkWorkflowToProjectCommand(_StrictModel):
    action: Literal["link_workflow_to_project"]
    workflow_id: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    project_id: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    display_name: str | None = Field(
        default=None, min_length=1, max_length=MAX_TITLE_LENGTH
    )


WorkflowMutationCommand: TypeAlias = Annotated[
    CreateWorkflowCommand
    | UpdateWorkflowCommand
    | DeleteWorkflowCommand
    | LinkWorkflowToProjectCommand,
    Field(discriminator="action"),
]


class ConfirmationRequiredCommand(_StrictModel):
    """A mutation that an executor must not apply until the user confirms it."""

    action: Literal["confirmation_required"]
    message: str = Field(min_length=1, max_length=MAX_CLARIFICATION_LENGTH)
    proposed_command: WorkflowMutationCommand


WorkflowInputPlannerCommand: TypeAlias = Annotated[
    NeedsClarificationCommand | DraftWorkflowCommand | ConfirmationRequiredCommand,
    Field(discriminator="action"),
]
WORKFLOW_INPUT_PLANNER_COMMAND_ADAPTER = TypeAdapter(WorkflowInputPlannerCommand)


class WorkflowInputPlannerProvider(Protocol):
    """Injectable adapter for an approved structured-output provider."""

    def plan(self, request: WorkflowPlannerProviderRequest) -> object:
        """Return a JSON-compatible command candidate; it is always validated locally."""


class UnavailableWorkflowInputPlannerProvider:
    """Fail-closed default until an approved provider adapter is explicitly injected."""

    def plan(self, request: WorkflowPlannerProviderRequest) -> object:
        del request
        raise WorkflowInputPlannerUnavailableError()


class WorkflowInputPlanner:
    """Sanitize input and validate provider output without executing any command."""

    def __init__(self, provider: WorkflowInputPlannerProvider | None = None) -> None:
        self.provider = provider or UnavailableWorkflowInputPlannerProvider()

    def plan(
        self,
        *,
        input: WorkflowPlannerInput,
        context: ServerWorkflowPlannerContext,
    ) -> WorkflowInputPlannerCommand:
        request = WorkflowPlannerProviderRequest(
            input=_sanitize_input(input), context=context
        )
        return self.validate_command(self.provider.plan(request), context=context)

    @staticmethod
    def validate_command(
        candidate: object, *, context: ServerWorkflowPlannerContext
    ) -> WorkflowInputPlannerCommand:
        """Reject arbitrary provider output before any caller can observe a command."""
        if not isinstance(candidate, dict):
            raise WorkflowInputPlannerValidationError(
                "provider must return a JSON object command"
            )
        try:
            # Command models are strict; WorkflowGraph owns JSON-to-enum parsing and graph validation.
            command = WORKFLOW_INPUT_PLANNER_COMMAND_ADAPTER.validate_python(candidate)
        except ValidationError as exc:
            raise WorkflowInputPlannerValidationError(
                "provider returned an invalid workflow command"
            ) from exc
        _validate_command_targets(command, context)
        return command


def _sanitize_input(input: WorkflowPlannerInput) -> SanitizedWorkflowPlannerInput:
    return SanitizedWorkflowPlannerInput(
        text=_sanitize_optional_text(input.text, "text"),
        transcript=_sanitize_optional_text(input.transcript, "transcript"),
        evidence=[
            SanitizedWorkflowInputEvidence(
                source=evidence.source,
                label=_sanitize_required_text(evidence.label, "evidence label"),
                text=_sanitize_required_text(evidence.text, "evidence"),
            )
            for evidence in input.evidence
        ],
    )


def _sanitize_optional_text(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    return _sanitize_required_text(value, field_name)


def _sanitize_required_text(value: str, field_name: str) -> str:
    sanitized, _stats = sanitize_workflow_input_text(value)
    if not sanitized.strip():
        raise WorkflowInputPlannerValidationError(
            f"sanitized {field_name} must not be empty"
        )
    return sanitized


def _validate_command_targets(
    command: WorkflowInputPlannerCommand, context: ServerWorkflowPlannerContext
) -> None:
    if not isinstance(command, ConfirmationRequiredCommand):
        return
    proposed = command.proposed_command
    workflow_ids = {workflow.id for workflow in context.workflows}
    if isinstance(
        proposed,
        (UpdateWorkflowCommand, DeleteWorkflowCommand, LinkWorkflowToProjectCommand),
    ):
        if proposed.workflow_id not in workflow_ids:
            raise WorkflowInputPlannerValidationError(
                "workflow command target is not in server-owned context"
            )
    if isinstance(proposed, LinkWorkflowToProjectCommand):
        project_ids = {project.id for project in context.projects}
        if proposed.project_id not in project_ids:
            raise WorkflowInputPlannerValidationError(
                "project command target is not in server-owned context"
            )
