# backend/core/api/app/services/workflow_yaml_compiler.py
#
# Authoritative, bounded YAML authoring compiler for Workflow drafts. It accepts
# only safe YAML values and a deliberately small subset that translates to the
# existing typed WorkflowGraph while later slices add capabilities and runtime.
#
# Spec: docs/specs/workflows-cli-runtime/spec.yml

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

import yaml
from pydantic import ValidationError
from yaml.events import AliasEvent

from backend.core.api.app.services.workflow_capability_registry import WorkflowCapabilityRegistry
from backend.core.api.app.services.workflow_models import (
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
    WorkflowNodeType,
)


MAX_WORKFLOW_YAML_BYTES = 64 * 1024
MAX_WORKFLOW_YAML_DEPTH = 20
MAX_WORKFLOW_YAML_COLLECTION_ITEMS = 200
AUTHORING_VERSION = 1
DEFAULT_RUN_CONTENT_RETENTION = "last_5"
ALLOWED_TOP_LEVEL_FIELDS = {
    "title",
    "description",
    "start_when",
    "steps",
    "run_content_retention",
}
ALLOWED_START_WHEN_FIELDS = {"schedule", "manual"}
ALLOWED_SCHEDULE_FIELDS = {"type", "time", "timezone", "at", "cron"}
ALLOWED_MANUAL_FIELDS = {"input_schema"}
ALLOWED_APP_SKILL_STEP_FIELDS = {"id", "use_app_skill", "input"}
ALLOWED_NOTIFICATION_STEP_FIELDS = {"id", "send_notification"}
ALLOWED_CHAT_STEP_FIELDS = {"id", "send_chat_message"}
ALLOWED_ASK_USER_STEP_FIELDS = {"id", "ask_for_user_input"}
ALLOWED_WAIT_STEP_FIELDS = {"id", "wait"}
ALLOWED_FOR_EVERY_STEP_FIELDS = {"id", "for_every"}
ALLOWED_REPEAT_UNTIL_STEP_FIELDS = {"id", "repeat_until"}
ALLOWED_IF_STEP_FIELDS = {"id", "if", "if_true", "if_false"}
SUPPORTED_STEP_FORMS = {
    "use_app_skill",
    "send_notification",
    "send_chat_message",
    "ask_for_user_input",
    "wait",
    "for_every",
    "repeat_until",
    "if",
}
APP_SKILL_IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*\.[a-z][a-z0-9_-]*$")


class WorkflowYamlParseError(ValueError):
    """Raised when an authoring document cannot be safely parsed."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class WorkflowYamlCompilationError(ValueError):
    """Raised when YAML is not structurally valid enough to compile."""

    def __init__(self, diagnostics: list["WorkflowYamlDiagnostic"]) -> None:
        self.diagnostics = diagnostics
        super().__init__("; ".join(f"{item.code} at {item.path}: {item.message}" for item in diagnostics))


@dataclass(frozen=True)
class WorkflowYamlDiagnostic:
    code: str
    path: str
    message: str
    step_id: str | None = None
    field: str | None = None
    expected_type: str | None = None
    help_command: str | None = None


@dataclass(frozen=True)
class WorkflowYamlValidationResult:
    draft_valid: bool
    enable_ready: bool
    diagnostics: list[WorkflowYamlDiagnostic] = field(default_factory=list)
    graph: WorkflowGraph | None = None


@dataclass(frozen=True)
class WorkflowYamlCompilation:
    title: str
    description: str | None
    run_content_retention: str
    graph: WorkflowGraph
    validation: WorkflowYamlValidationResult


class _WorkflowYamlLoader(yaml.SafeLoader):
    """SafeLoader with anchors and duplicate-key shadowing explicitly forbidden."""

    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(AliasEvent):
            raise WorkflowYamlParseError("YAML_ANCHORS_DISABLED", "YAML aliases are not supported")
        event = self.peek_event()
        if event.anchor is not None:
            raise WorkflowYamlParseError("YAML_ANCHORS_DISABLED", "YAML anchors are not supported")
        return super().compose_node(parent, index)

    def construct_mapping(self, node: Any, deep: bool = False) -> dict[str, Any]:
        mapping: dict[str, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise WorkflowYamlParseError("YAML_KEY_TYPE", "Workflow YAML mapping keys must be strings")
            if key in mapping:
                raise WorkflowYamlParseError("YAML_DUPLICATE_KEY", f"Duplicate YAML key: {key}")
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def parse_workflow_yaml(source: str) -> dict[str, Any]:
    """Parse one bounded workflow document without aliases, custom tags, or duplicate keys."""
    if not isinstance(source, str):
        raise WorkflowYamlParseError("YAML_SOURCE_TYPE", "Workflow YAML source must be a string")
    if len(source.encode("utf-8")) > MAX_WORKFLOW_YAML_BYTES:
        raise WorkflowYamlParseError("YAML_DOCUMENT_TOO_LARGE", "Workflow YAML exceeds the maximum document size")

    try:
        document = yaml.load(source, Loader=_WorkflowYamlLoader)
    except WorkflowYamlParseError:
        raise
    except yaml.YAMLError as error:
        raise WorkflowYamlParseError("YAML_PARSE_ERROR", "Workflow YAML must use safe YAML syntax") from error

    _validate_safe_yaml_value(document)
    if not isinstance(document, dict):
        raise WorkflowYamlParseError("YAML_DOCUMENT_TYPE", "Workflow YAML must be a mapping")
    return document


def validate_workflow_yaml(source: str, capability_registry: Any | None = None) -> WorkflowYamlValidationResult:
    """Validate draft structure and readiness without persisting or executing a workflow."""
    try:
        document = parse_workflow_yaml(source)
    except WorkflowYamlParseError as error:
        return WorkflowYamlValidationResult(
            draft_valid=False,
            enable_ready=False,
            diagnostics=[WorkflowYamlDiagnostic(code=error.code, path="$", message=str(error).split(": ", 1)[-1])],
        )

    diagnostics = _validate_document_structure(document)
    if diagnostics:
        return WorkflowYamlValidationResult(draft_valid=False, enable_ready=False, diagnostics=diagnostics)

    try:
        graph = _compile_graph(document)
    except ValidationError:
        return WorkflowYamlValidationResult(
            draft_valid=False,
            enable_ready=False,
            diagnostics=[
                WorkflowYamlDiagnostic(
                    code="WORKFLOW_GRAPH_INVALID",
                    path="$",
                    message="Workflow definition is not supported by the current runtime",
                )
            ],
        )

    readiness_diagnostics = _validate_enable_readiness(document, capability_registry)
    return WorkflowYamlValidationResult(
        draft_valid=True,
        enable_ready=not readiness_diagnostics,
        diagnostics=readiness_diagnostics,
        graph=graph,
    )


def compile_workflow_yaml(source: str, capability_registry: Any | None = None) -> WorkflowYamlCompilation:
    """Compile a structurally valid YAML draft into the immutable runtime graph shape."""
    document = parse_workflow_yaml(source)
    validation = validate_workflow_yaml(source, capability_registry)
    if not validation.draft_valid or validation.graph is None:
        raise WorkflowYamlCompilationError(validation.diagnostics)

    return WorkflowYamlCompilation(
        title=document["title"].strip(),
        description=document.get("description"),
        run_content_retention=document.get("run_content_retention", DEFAULT_RUN_CONTENT_RETENTION),
        graph=validation.graph,
        validation=validation,
    )


def _validate_safe_yaml_value(value: Any, path: str = "$", depth: int = 0) -> None:
    if depth > MAX_WORKFLOW_YAML_DEPTH:
        raise WorkflowYamlParseError("YAML_MAX_DEPTH", "Workflow YAML exceeds the maximum nesting depth")
    if value is None or isinstance(value, (str, bool, int, float)):
        return
    if isinstance(value, list):
        if len(value) > MAX_WORKFLOW_YAML_COLLECTION_ITEMS:
            raise WorkflowYamlParseError("YAML_LIST_TOO_LONG", f"Workflow YAML list at {path} exceeds the item limit")
        for index, child in enumerate(value):
            _validate_safe_yaml_value(child, f"{path}[{index}]", depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > MAX_WORKFLOW_YAML_COLLECTION_ITEMS:
            raise WorkflowYamlParseError("YAML_MAPPING_TOO_LARGE", f"Workflow YAML mapping at {path} exceeds the item limit")
        for key, child in value.items():
            if not isinstance(key, str):
                raise WorkflowYamlParseError("YAML_KEY_TYPE", f"Workflow YAML key at {path} must be a string")
            _validate_safe_yaml_value(child, f"{path}.{key}", depth + 1)
        return
    raise WorkflowYamlParseError("YAML_UNSAFE_VALUE", f"Workflow YAML value at {path} has an unsupported scalar type")


def _validate_document_structure(document: dict[str, Any]) -> list[WorkflowYamlDiagnostic]:
    diagnostics: list[WorkflowYamlDiagnostic] = []
    diagnostics.extend(_unknown_field_diagnostics(document, ALLOWED_TOP_LEVEL_FIELDS, ""))
    title = document.get("title")
    if not isinstance(title, str) or not title.strip():
        diagnostics.append(WorkflowYamlDiagnostic("TITLE_REQUIRED", "title", "title must be a non-empty string"))
    if "description" in document and not isinstance(document["description"], str):
        diagnostics.append(WorkflowYamlDiagnostic("FIELD_TYPE", "description", "description must be a string", expected_type="string"))
    if document.get("run_content_retention", DEFAULT_RUN_CONTENT_RETENTION) not in {"last_5", "none"}:
        diagnostics.append(WorkflowYamlDiagnostic("FIELD_VALUE", "run_content_retention", "run_content_retention must be last_5 or none"))
    diagnostics.extend(_validate_start_when(document.get("start_when")))
    diagnostics.extend(_validate_steps(document.get("steps"), "steps", set()))
    return diagnostics


def _validate_start_when(value: Any) -> list[WorkflowYamlDiagnostic]:
    if not isinstance(value, dict):
        return [WorkflowYamlDiagnostic("START_WHEN_REQUIRED", "start_when", "start_when must define one supported trigger")]

    diagnostics = _unknown_field_diagnostics(value, ALLOWED_START_WHEN_FIELDS, "start_when")
    trigger_names = [name for name in ALLOWED_START_WHEN_FIELDS if name in value]
    if len(trigger_names) != 1:
        diagnostics.append(WorkflowYamlDiagnostic("TRIGGER_COUNT", "start_when", "exactly one supported trigger is required"))
        return diagnostics

    trigger_name = trigger_names[0]
    config = value[trigger_name]
    if not isinstance(config, dict):
        diagnostics.append(WorkflowYamlDiagnostic("FIELD_TYPE", f"start_when.{trigger_name}", "trigger configuration must be a mapping", expected_type="object"))
        return diagnostics
    if trigger_name == "schedule":
        diagnostics.extend(_unknown_field_diagnostics(config, ALLOWED_SCHEDULE_FIELDS, "start_when.schedule"))
        if not isinstance(config.get("type"), str) or not config["type"].strip():
            diagnostics.append(WorkflowYamlDiagnostic("SCHEDULE_TYPE_REQUIRED", "start_when.schedule.type", "schedule.type must be a non-empty string"))
    else:
        diagnostics.extend(_unknown_field_diagnostics(config, ALLOWED_MANUAL_FIELDS, "start_when.manual"))
        if "input_schema" in config and not isinstance(config["input_schema"], dict):
            diagnostics.append(WorkflowYamlDiagnostic("FIELD_TYPE", "start_when.manual.input_schema", "input_schema must be a mapping", expected_type="object"))
    return diagnostics


def _validate_steps(value: Any, path: str, step_ids: set[str], *, allow_empty: bool = False) -> list[WorkflowYamlDiagnostic]:
    if not isinstance(value, list) or (not value and not allow_empty):
        return [WorkflowYamlDiagnostic("STEPS_REQUIRED", path, "steps must be a non-empty list")]

    diagnostics: list[WorkflowYamlDiagnostic] = []
    for index, step in enumerate(value):
        step_path = f"{path}[{index}]"
        if not isinstance(step, dict):
            diagnostics.append(WorkflowYamlDiagnostic("STEP_TYPE", step_path, "each step must be a mapping", expected_type="object"))
            continue
        step_id = step.get("id")
        if not isinstance(step_id, str) or not step_id.strip():
            diagnostics.append(WorkflowYamlDiagnostic("STEP_ID_REQUIRED", f"{step_path}.id", "step id must be a non-empty string"))
        elif step_id in step_ids:
            diagnostics.append(WorkflowYamlDiagnostic("DUPLICATE_STEP_ID", f"{step_path}.id", f"step id {step_id!r} is already used", step_id=step_id))
        else:
            step_ids.add(step_id)

        forms = [form for form in SUPPORTED_STEP_FORMS if form in step]
        if len(forms) != 1:
            diagnostics.append(WorkflowYamlDiagnostic("STEP_FORM", step_path, "each step must contain exactly one supported action or control form", step_id=step_id if isinstance(step_id, str) else None))
            continue
        form = forms[0]
        allowed_fields = {
            "use_app_skill": ALLOWED_APP_SKILL_STEP_FIELDS,
            "send_notification": ALLOWED_NOTIFICATION_STEP_FIELDS,
            "send_chat_message": ALLOWED_CHAT_STEP_FIELDS,
            "ask_for_user_input": ALLOWED_ASK_USER_STEP_FIELDS,
            "wait": ALLOWED_WAIT_STEP_FIELDS,
            "for_every": ALLOWED_FOR_EVERY_STEP_FIELDS,
            "repeat_until": ALLOWED_REPEAT_UNTIL_STEP_FIELDS,
            "if": ALLOWED_IF_STEP_FIELDS,
        }[form]
        diagnostics.extend(_unknown_field_diagnostics(step, allowed_fields, step_path))
        if form == "use_app_skill":
            diagnostics.extend(_validate_app_skill_step(step, step_path, step_id))
        elif form == "send_notification":
            diagnostics.extend(_validate_notification_step(step, step_path, step_id))
        elif form == "send_chat_message":
            diagnostics.extend(_validate_chat_step(step, step_path, step_id))
        elif form == "ask_for_user_input":
            diagnostics.extend(_validate_ask_user_step(step, step_path, step_id))
        elif form == "wait":
            diagnostics.extend(_validate_wait_step(step, step_path, step_id))
        elif form in {"for_every", "repeat_until"}:
            diagnostics.extend(_validate_repeat_step(step, step_path, step_id, step_ids, form))
        else:
            diagnostics.extend(_validate_if_step(step, step_path, step_id, step_ids))
    return diagnostics


def _validate_app_skill_step(step: dict[str, Any], path: str, step_id: Any) -> list[WorkflowYamlDiagnostic]:
    diagnostics: list[WorkflowYamlDiagnostic] = []
    identifier = step.get("use_app_skill")
    if not isinstance(identifier, str) or not APP_SKILL_IDENTIFIER_PATTERN.fullmatch(identifier):
        diagnostics.append(WorkflowYamlDiagnostic("APP_SKILL_IDENTIFIER", f"{path}.use_app_skill", "use_app_skill must be an app-id.skill-id identifier", step_id=step_id if isinstance(step_id, str) else None))
    if "input" in step and not isinstance(step["input"], dict):
        diagnostics.append(WorkflowYamlDiagnostic("FIELD_TYPE", f"{path}.input", "input must be a mapping", step_id=step_id if isinstance(step_id, str) else None, expected_type="object"))
    return diagnostics


def _validate_notification_step(step: dict[str, Any], path: str, step_id: Any) -> list[WorkflowYamlDiagnostic]:
    value = step.get("send_notification")
    if not isinstance(value, dict):
        return [WorkflowYamlDiagnostic("FIELD_TYPE", f"{path}.send_notification", "send_notification must be a mapping", step_id=step_id if isinstance(step_id, str) else None, expected_type="object")]
    diagnostics = _unknown_field_diagnostics(value, {"title", "body", "link"}, f"{path}.send_notification")
    for field_name in ("title", "body"):
        if not isinstance(value.get(field_name), str) or not value[field_name].strip():
            diagnostics.append(WorkflowYamlDiagnostic("FIELD_REQUIRED", f"{path}.send_notification.{field_name}", f"{field_name} must be a non-empty string", step_id=step_id if isinstance(step_id, str) else None))
    if "link" in value and not isinstance(value["link"], str):
        diagnostics.append(WorkflowYamlDiagnostic("FIELD_TYPE", f"{path}.send_notification.link", "link must be a string", step_id=step_id if isinstance(step_id, str) else None, expected_type="string"))
    return diagnostics


def _validate_if_step(step: dict[str, Any], path: str, step_id: Any, step_ids: set[str]) -> list[WorkflowYamlDiagnostic]:
    diagnostics: list[WorkflowYamlDiagnostic] = []
    if not isinstance(step.get("if"), dict):
        diagnostics.append(WorkflowYamlDiagnostic("FIELD_TYPE", f"{path}.if", "if must be a structured comparison", step_id=step_id if isinstance(step_id, str) else None, expected_type="object"))
    for branch in ("if_true", "if_false"):
        if branch in step and not isinstance(step[branch], list):
            diagnostics.append(WorkflowYamlDiagnostic("FIELD_TYPE", f"{path}.{branch}", f"{branch} must be a list of steps", step_id=step_id if isinstance(step_id, str) else None, expected_type="array"))
        elif isinstance(step.get(branch), list):
            diagnostics.extend(_validate_steps(step[branch], f"{path}.{branch}", step_ids, allow_empty=True))
    return diagnostics


def _validate_chat_step(step: dict[str, Any], path: str, step_id: Any) -> list[WorkflowYamlDiagnostic]:
    value = step.get("send_chat_message")
    if not isinstance(value, dict):
        return [WorkflowYamlDiagnostic("FIELD_TYPE", f"{path}.send_chat_message", "send_chat_message must be a mapping", step_id=step_id if isinstance(step_id, str) else None, expected_type="object")]
    diagnostics = _unknown_field_diagnostics(value, {"title", "message", "chat_id"}, f"{path}.send_chat_message")
    for field_name in ("title", "message"):
        if not isinstance(value.get(field_name), str) or not value[field_name].strip():
            diagnostics.append(WorkflowYamlDiagnostic("FIELD_REQUIRED", f"{path}.send_chat_message.{field_name}", f"{field_name} must be a non-empty string", step_id=step_id if isinstance(step_id, str) else None))
    if "chat_id" in value and not isinstance(value["chat_id"], str):
        diagnostics.append(WorkflowYamlDiagnostic("FIELD_TYPE", f"{path}.send_chat_message.chat_id", "chat_id must be a string", step_id=step_id if isinstance(step_id, str) else None, expected_type="string"))
    return diagnostics


def _validate_ask_user_step(step: dict[str, Any], path: str, step_id: Any) -> list[WorkflowYamlDiagnostic]:
    value = step.get("ask_for_user_input")
    if not isinstance(value, dict):
        return [WorkflowYamlDiagnostic("FIELD_TYPE", f"{path}.ask_for_user_input", "ask_for_user_input must be a mapping", step_id=step_id if isinstance(step_id, str) else None, expected_type="object")]
    diagnostics = _unknown_field_diagnostics(value, {"prompt", "input_schema", "timeout_seconds"}, f"{path}.ask_for_user_input")
    if not isinstance(value.get("prompt"), str) or not value["prompt"].strip():
        diagnostics.append(WorkflowYamlDiagnostic("FIELD_REQUIRED", f"{path}.ask_for_user_input.prompt", "prompt must be a non-empty string", step_id=step_id if isinstance(step_id, str) else None))
    if "input_schema" in value and not isinstance(value["input_schema"], dict):
        diagnostics.append(WorkflowYamlDiagnostic("FIELD_TYPE", f"{path}.ask_for_user_input.input_schema", "input_schema must be a mapping", step_id=step_id if isinstance(step_id, str) else None, expected_type="object"))
    if "timeout_seconds" in value and (not isinstance(value["timeout_seconds"], int) or value["timeout_seconds"] <= 0):
        diagnostics.append(WorkflowYamlDiagnostic("FIELD_TYPE", f"{path}.ask_for_user_input.timeout_seconds", "timeout_seconds must be a positive integer", step_id=step_id if isinstance(step_id, str) else None, expected_type="integer"))
    return diagnostics


def _validate_wait_step(step: dict[str, Any], path: str, step_id: Any) -> list[WorkflowYamlDiagnostic]:
    value = step.get("wait")
    if not isinstance(value, dict):
        return [WorkflowYamlDiagnostic("FIELD_TYPE", f"{path}.wait", "wait must be a mapping", step_id=step_id if isinstance(step_id, str) else None, expected_type="object")]
    diagnostics = _unknown_field_diagnostics(value, {"seconds", "until"}, f"{path}.wait")
    if "seconds" not in value and "until" not in value:
        diagnostics.append(WorkflowYamlDiagnostic("FIELD_REQUIRED", f"{path}.wait", "wait requires seconds or until", step_id=step_id if isinstance(step_id, str) else None))
    if "seconds" in value and (not isinstance(value["seconds"], int) or value["seconds"] <= 0):
        diagnostics.append(WorkflowYamlDiagnostic("FIELD_TYPE", f"{path}.wait.seconds", "seconds must be a positive integer", step_id=step_id if isinstance(step_id, str) else None, expected_type="integer"))
    if "until" in value and not isinstance(value["until"], str):
        diagnostics.append(WorkflowYamlDiagnostic("FIELD_TYPE", f"{path}.wait.until", "until must be a string", step_id=step_id if isinstance(step_id, str) else None, expected_type="string"))
    return diagnostics


def _validate_repeat_step(step: dict[str, Any], path: str, step_id: Any, step_ids: set[str], form: str) -> list[WorkflowYamlDiagnostic]:
    value = step.get(form)
    if not isinstance(value, dict):
        return [WorkflowYamlDiagnostic("FIELD_TYPE", f"{path}.{form}", f"{form} must be a mapping", step_id=step_id if isinstance(step_id, str) else None, expected_type="object")]
    allowed = {"items", "as", "do", "max_iterations"} if form == "for_every" else {"condition", "do", "max_iterations"}
    diagnostics = _unknown_field_diagnostics(value, allowed, f"{path}.{form}")
    if not isinstance(value.get("do"), list) or not value["do"]:
        diagnostics.append(WorkflowYamlDiagnostic("FIELD_REQUIRED", f"{path}.{form}.do", "do must be a non-empty list of steps", step_id=step_id if isinstance(step_id, str) else None, expected_type="array"))
    else:
        diagnostics.extend(_validate_steps(value["do"], f"{path}.{form}.do", step_ids))
    if form == "for_every":
        if "items" not in value:
            diagnostics.append(WorkflowYamlDiagnostic("FIELD_REQUIRED", f"{path}.for_every.items", "for_every requires items", step_id=step_id if isinstance(step_id, str) else None))
    elif not isinstance(value.get("condition"), dict):
        diagnostics.append(WorkflowYamlDiagnostic("FIELD_REQUIRED", f"{path}.repeat_until.condition", "repeat_until requires a structured condition", step_id=step_id if isinstance(step_id, str) else None, expected_type="object"))
    max_iterations = value.get("max_iterations", 10)
    if not isinstance(max_iterations, int) or max_iterations <= 0:
        diagnostics.append(WorkflowYamlDiagnostic("FIELD_TYPE", f"{path}.{form}.max_iterations", "max_iterations must be a positive integer", step_id=step_id if isinstance(step_id, str) else None, expected_type="integer"))
    return diagnostics


def _validate_enable_readiness(document: dict[str, Any], capability_registry: Any | None = None) -> list[WorkflowYamlDiagnostic]:
    diagnostics: list[WorkflowYamlDiagnostic] = []
    registry = capability_registry or WorkflowCapabilityRegistry()
    for step, path in _walk_steps(document["steps"], "steps"):
        identifier = step.get("use_app_skill")
        if not isinstance(identifier, str) or "." not in identifier:
            continue
        capability = registry.get_capability(identifier)
        if not capability.enabled:
            diagnostics.append(
                WorkflowYamlDiagnostic(
                    "WORKFLOW_CAPABILITY_UNAVAILABLE",
                    f"{path}.use_app_skill",
                    f"{identifier} is not available for workflows: {capability.reason}",
                    step_id=step["id"],
                    help_command=f"openmates workflows help-app {identifier}",
                )
            )
            continue
        input_value = step.get("input", {})
        input_schema = capability.metadata.get("input_schema")
        if not isinstance(input_schema, dict):
            continue
        for field_name in _required_schema_fields(input_schema):
            if input_value.get(field_name) in (None, ""):
                diagnostics.append(
                    WorkflowYamlDiagnostic(
                        "REQUIRED_RUNTIME_INPUT",
                        f"{path}.input.{field_name}",
                        f"{identifier} requires {field_name} before enablement",
                        step_id=step["id"],
                        field=field_name,
                        expected_type=_schema_field_type(input_schema, field_name),
                        help_command=f"openmates workflows help-app {identifier}",
                    )
                )
    return diagnostics


def _required_schema_fields(schema: dict[str, Any]) -> tuple[str, ...]:
    required = schema.get("required")
    if not isinstance(required, list):
        return ()
    return tuple(field_name for field_name in required if isinstance(field_name, str))


def _schema_field_type(schema: dict[str, Any], field_name: str) -> str | None:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return None
    field_schema = properties.get(field_name)
    if not isinstance(field_schema, dict):
        return None
    schema_type = field_schema.get("type")
    return schema_type if isinstance(schema_type, str) else None


def _walk_steps(steps: list[dict[str, Any]], path: str):
    for index, step in enumerate(steps):
        step_path = f"{path}[{index}]"
        yield step, step_path
        if "if" in step:
            yield from _walk_steps(step.get("if_true", []), f"{step_path}.if_true")
            yield from _walk_steps(step.get("if_false", []), f"{step_path}.if_false")
        if isinstance(step.get("for_every"), dict):
            yield from _walk_steps(step["for_every"].get("do", []), f"{step_path}.for_every.do")
        if isinstance(step.get("repeat_until"), dict):
            yield from _walk_steps(step["repeat_until"].get("do", []), f"{step_path}.repeat_until.do")


def _compile_graph(document: dict[str, Any]) -> WorkflowGraph:
    trigger = _compile_trigger(document["start_when"])
    nodes = [trigger]
    edges: list[WorkflowEdge] = []
    _compile_steps(document["steps"], [(trigger.id, None)], nodes, edges)
    return WorkflowGraph(
        version=AUTHORING_VERSION,
        trigger_node_id=trigger.id,
        nodes=nodes,
        edges=edges,
    )


def _compile_trigger(start_when: dict[str, Any]) -> WorkflowNode:
    if "schedule" in start_when:
        return WorkflowNode(id="trigger", type=WorkflowNodeType.SCHEDULE_TRIGGER, config={"schedule": dict(start_when["schedule"])})
    manual = start_when["manual"]
    config: dict[str, Any] = {}
    if "input_schema" in manual:
        config["required_start_input_schema"] = manual["input_schema"]
    return WorkflowNode(id="trigger", type=WorkflowNodeType.MANUAL_TRIGGER, config=config)


def _compile_steps(
    steps: list[dict[str, Any]],
    incoming: list[tuple[str, str | None]],
    nodes: list[WorkflowNode],
    edges: list[WorkflowEdge],
) -> list[tuple[str, str | None]]:
    previous = incoming
    for step in steps:
        node = _compile_step_node(step)
        nodes.append(node)
        for source_id, branch in previous:
            edges.append(WorkflowEdge(**{"from": source_id, "to": node.id, "branch": branch}))
        if "if" not in step:
            previous = [(node.id, None)]
            continue
        true_endpoints = _compile_steps(step.get("if_true", []), [(node.id, "true")], nodes, edges)
        false_endpoints = _compile_steps(step.get("if_false", []), [(node.id, "false")], nodes, edges)
        previous = true_endpoints + false_endpoints
    return previous


def _compile_step_node(step: dict[str, Any]) -> WorkflowNode:
    if "use_app_skill" in step:
        app_id, skill_id = step["use_app_skill"].split(".", 1)
        return WorkflowNode(
            id=step["id"],
            type=WorkflowNodeType.APP_SKILL_ACTION,
            config={"app_id": app_id, "skill_id": skill_id, "input": dict(step.get("input", {}))},
        )
    if "send_notification" in step:
        return WorkflowNode(id=step["id"], type=WorkflowNodeType.SEND_NOTIFICATION, config=dict(step["send_notification"]))
    if "send_chat_message" in step:
        return WorkflowNode(id=step["id"], type=WorkflowNodeType.START_NEW_CHAT, config=dict(step["send_chat_message"]))
    if "ask_for_user_input" in step:
        return WorkflowNode(id=step["id"], type=WorkflowNodeType.ASK_USER, config=dict(step["ask_for_user_input"]))
    if "wait" in step:
        return WorkflowNode(id=step["id"], type=WorkflowNodeType.WAIT, config=dict(step["wait"]))
    if "for_every" in step:
        config = dict(step["for_every"])
        config.setdefault("mode", "for_every")
        config.setdefault("max_iterations", 10)
        config.setdefault("max_duration_seconds", 300)
        config.setdefault("max_credits", 100)
        config.setdefault("per_iteration_timeout_seconds", 60)
        return WorkflowNode(id=step["id"], type=WorkflowNodeType.REPEAT, config=config)
    if "repeat_until" in step:
        config = dict(step["repeat_until"])
        config.setdefault("mode", "repeat_until")
        config.setdefault("max_iterations", 10)
        config.setdefault("max_duration_seconds", 300)
        config.setdefault("max_credits", 100)
        config.setdefault("per_iteration_timeout_seconds", 60)
        return WorkflowNode(id=step["id"], type=WorkflowNodeType.REPEAT, config=config)
    return WorkflowNode(id=step["id"], type=WorkflowNodeType.DECISION, config={"predicate": _normalize_predicate(dict(step["if"]))})


def _normalize_predicate(predicate: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(predicate)
    if "left" in normalized:
        normalized["left"] = _normalize_template_reference(normalized["left"])
    if "right" in normalized:
        normalized["right"] = _normalize_template_reference(normalized["right"])
    if "conditions" in normalized and isinstance(normalized["conditions"], list):
        normalized["conditions"] = [
            _normalize_predicate(item) if isinstance(item, dict) else item
            for item in normalized["conditions"]
        ]
    if "condition" in normalized and isinstance(normalized["condition"], dict):
        normalized["condition"] = _normalize_predicate(normalized["condition"])
    return normalized


def _normalize_template_reference(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    match = re.fullmatch(r"\{\{\s*steps\.([a-zA-Z0-9_-]+)\.([a-zA-Z0-9_.-]+)\s*\}\}", value)
    if match is None:
        return value
    step_id, path = match.groups()
    return f"$nodes.{step_id}.output.{path}"


def _unknown_field_diagnostics(value: dict[str, Any], allowed_fields: set[str], path: str) -> list[WorkflowYamlDiagnostic]:
    return [
        WorkflowYamlDiagnostic("UNKNOWN_FIELD", f"{path}.{field_name}".lstrip("."), f"Unknown field: {field_name}")
        for field_name in value
        if field_name not in allowed_fields
    ]
