# backend/core/api/app/services/workflow_capability_registry.py
#
# Metadata-derived Workflow app-skill capability registry.
# App metadata declares the Workflow contract; the in-process SkillRegistry
# proves that the app and its skill class are actually available in this
# process. Missing or incomplete classification fails closed with a stable
# reason rather than inferring that a public skill is safe to automate.
#
# Spec: docs/specs/workflows-cli-runtime/spec.yml

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Any

import yaml

from backend.core.api.app.services.workflow_models import WorkflowCapability
from backend.core.api.app.services.workflow_runtime_values import resolve_workflow_runtime_values


WORKFLOW_CONTROL_CAPABILITIES = (
    WorkflowCapability(type="node", id="check.ai.options", title="AI Check: options", metadata={
        "node_type": "check", "mode": "ai", "result_type": "options",
        "selection_modes": ["single", "multiple"], "min_options": 2, "max_options": 10,
        "branches": ["option:<id>", "no_match", "unsure"],
        "outputs": ["selected_options", "selected_labels", "selected_count", "matches", "decision"],
    }),
    WorkflowCapability(type="node", id="for_each", title="For each", metadata={
        "node_type": "for_each", "items_type": "typed_array_reference",
        "max_items": {"default": 100, "minimum": 1, "maximum": 100},
        "max_duration_seconds": {"default": 300, "minimum": 1, "maximum": 3600},
        "max_credits": {"default": 100, "minimum": 1, "maximum": 1000},
        "per_item_timeout_seconds": {"default": 60, "minimum": 1, "maximum": 3600},
        "branches": ["body", "default"],
        "outputs": ["item_count", "completed_count", "results"],
        "nested": False,
    }),
)
if TYPE_CHECKING:
    from backend.core.api.app.services.skill_registry import SkillRegistry


WORKFLOW_CLASSIFICATION_REQUIRED = "WORKFLOW_CLASSIFICATION_REQUIRED"
WORKFLOW_INTERNAL_SKILL = "WORKFLOW_INTERNAL_SKILL"
WORKFLOW_SKILL_NOT_IMPLEMENTED = "WORKFLOW_SKILL_NOT_IMPLEMENTED"
WORKFLOW_SKILL_NOT_REGISTERED = "WORKFLOW_SKILL_NOT_REGISTERED"
WORKFLOW_APP_NOT_REGISTERED = "WORKFLOW_APP_NOT_REGISTERED"
WORKFLOW_METADATA_INVALID = "WORKFLOW_METADATA_INVALID"
WORKFLOW_EXECUTION_MODE_UNSUPPORTED = "WORKFLOW_EXECUTION_MODE_UNSUPPORTED"
WORKFLOW_EFFECT_UNSUPPORTED = "WORKFLOW_EFFECT_UNSUPPORTED"
WORKFLOW_TEST_EXAMPLE_REQUIRED = "WORKFLOW_TEST_EXAMPLE_REQUIRED"
WORKFLOW_CONNECTED_ACCOUNT_REQUIRED = "WORKFLOW_CONNECTED_ACCOUNT_REQUIRED"
WORKFLOW_CLIENT_ENCRYPTED_DATA_REQUIRED = "WORKFLOW_CLIENT_ENCRYPTED_DATA_REQUIRED"
WORKFLOW_FILE_OR_EMBED_INPUT_REQUIRED = "WORKFLOW_FILE_OR_EMBED_INPUT_REQUIRED"
WORKFLOW_RUNTIME_UNSUPPORTED = "WORKFLOW_RUNTIME_UNSUPPORTED"

_EXECUTION_MODES = {"sync", "workflow_ai", "async_job", "sandbox"}
_EFFECTS = {"read", "notify", "chat_write", "generate", "compute", "code_execution"}
_APPROVALS = {"never", "side_effect_confirmation", "always"}
_BINDING_REQUIREMENTS = {
    "none",
    "location",
    "provider_account",
    "connected_account_or_csv",
    "notification_preferences",
    "chat_owner",
}
_UNAVAILABLE_REASONS = {
    WORKFLOW_CLASSIFICATION_REQUIRED,
    WORKFLOW_INTERNAL_SKILL,
    WORKFLOW_SKILL_NOT_IMPLEMENTED,
    WORKFLOW_SKILL_NOT_REGISTERED,
    WORKFLOW_APP_NOT_REGISTERED,
    WORKFLOW_METADATA_INVALID,
    WORKFLOW_EXECUTION_MODE_UNSUPPORTED,
    WORKFLOW_EFFECT_UNSUPPORTED,
    WORKFLOW_TEST_EXAMPLE_REQUIRED,
    WORKFLOW_CONNECTED_ACCOUNT_REQUIRED,
    WORKFLOW_CLIENT_ENCRYPTED_DATA_REQUIRED,
    WORKFLOW_FILE_OR_EMBED_INPUT_REQUIRED,
    WORKFLOW_RUNTIME_UNSUPPORTED,
}
WORKFLOW_CLASSIFICATION_FILE = Path(__file__).resolve().parent / "workflow_capabilities.yml"
_metadata_cache_lock = RLock()
_classification_cache: tuple[Path, tuple[int, int] | None, dict[str, Any]] | None = None
_filesystem_cache: dict[Path, tuple[tuple[tuple[str, int, int], ...], dict[str, dict[str, Any]]]] = {}


def workflow_runtime_unavailable_reason(workflow: Mapping[str, Any]) -> str | None:
    """Keep incomplete execution/approval lifecycles out of workflow dispatch.

    Queued generation/rendering jobs settle billing in their worker and cannot
    yet resume dependent workflow nodes with a completed result. Per-run skill
    approval is also not implemented. Declaring an input/output schema alone
    must not enable either path, including for previously saved workflow graphs.
    """
    if workflow.get("execution_mode") in {"async_job", "sandbox"}:
        return WORKFLOW_RUNTIME_UNSUPPORTED
    if workflow.get("approval") == "always" or workflow.get("unattended") is False:
        return WORKFLOW_RUNTIME_UNSUPPORTED
    return None


def _file_version(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return stat.st_mtime_ns, stat.st_size


class WorkflowCapabilityRegistry:
    """Expose app-skill Workflow capabilities from registered app metadata."""

    def __init__(self, skill_registry: "SkillRegistry | None" = None) -> None:
        self.skill_registry = skill_registry
        self._workflow_classifications = _load_workflow_classifications()

    def list_capabilities(self, user_id: str | None = None) -> list[WorkflowCapability]:
        """Return every discoverable app skill with explicit Workflow availability."""
        del user_id  # Owner and provider checks belong to the execution boundary.
        registry = self._registry()
        capabilities: list[WorkflowCapability] = []
        for app_id, app_metadata in sorted(registry.all_metadata().items()):
            for skill in _value(app_metadata, "skills", default=[]):
                capabilities.append(self._capability_for_skill(registry, app_id, skill))
        return capabilities

    def list_control_capabilities(self) -> list[WorkflowCapability]:
        """Describe bounded graph controls without mixing them into app-skill selection."""
        return [capability.model_copy(deep=True) for capability in WORKFLOW_CONTROL_CAPABILITIES]

    def get_capability(self, capability_id: str) -> WorkflowCapability:
        """Resolve ``app.skill`` and retain a precise reason when it is unavailable."""
        app_id, separator, skill_id = capability_id.partition(".")
        if not separator or not app_id or not skill_id:
            return _unavailable_capability(
                capability_id,
                "Unknown Workflow capability identifier",
                WORKFLOW_METADATA_INVALID,
            )

        registry = self._registry()
        app_metadata = registry.get_metadata(app_id)
        if app_metadata is None:
            return _unavailable_capability(
                capability_id,
                capability_id,
                WORKFLOW_APP_NOT_REGISTERED,
                app_id=app_id,
                skill_id=skill_id,
            )

        for skill in _value(app_metadata, "skills", default=[]):
            if _value(skill, "id") == skill_id:
                return self._capability_for_skill(registry, app_id, skill)
        return _unavailable_capability(
            capability_id,
            capability_id,
            WORKFLOW_SKILL_NOT_REGISTERED,
            app_id=app_id,
            skill_id=skill_id,
        )

    def _registry(self) -> Any:
        if self.skill_registry is not None:
            return self.skill_registry
        try:
            from backend.core.api.app.services.skill_registry import get_global_registry

            registry = get_global_registry()
            if registry.all_metadata():
                return registry
            return _FilesystemWorkflowMetadataRegistry()
        except ModuleNotFoundError as exc:
            if exc.name != "celery":
                raise
            return _FilesystemWorkflowMetadataRegistry()

    def _capability_for_skill(
        self,
        registry: Any,
        app_id: str,
        skill: Any,
    ) -> WorkflowCapability:
        skill_id = _value(skill, "id")
        capability_id = f"{app_id}.{skill_id}"
        input_schema = _as_mapping(_value(skill, "tool_schema"))
        metadata = {
            "app_id": app_id,
            "skill_id": skill_id,
            "input_schema": input_schema,
            "description": str(_value(skill, "preprocessor_hint") or ""),
            "cost": _dump_value(_value(skill, "pricing")),
        }
        if _value(skill, "internal", default=False):
            return _unavailable_capability(
                capability_id, capability_id, WORKFLOW_INTERNAL_SKILL, metadata
            )
        if not _value(skill, "class_path"):
            return _unavailable_capability(
                capability_id, capability_id, WORKFLOW_SKILL_NOT_IMPLEMENTED, metadata
            )
        if not registry.is_skill_available(app_id, skill_id):
            return _unavailable_capability(
                capability_id, capability_id, WORKFLOW_SKILL_NOT_REGISTERED, metadata
            )

        workflow = _as_mapping(_value(skill, "workflow"))
        if workflow is None:
            workflow = _as_mapping(self._workflow_classifications.get(capability_id))
        if workflow is None:
            return _unavailable_capability(
                capability_id,
                capability_id,
                WORKFLOW_CLASSIFICATION_REQUIRED,
                metadata,
            )

        metadata["workflow"] = dict(workflow)
        metadata["workflow_source"] = "app.yml" if _value(skill, "workflow") is not None else "workflow_capabilities.yml"
        metadata["output_schema"] = workflow.get("output_schema")
        reason = _workflow_metadata_reason(workflow, metadata["input_schema"])
        if reason is not None:
            return _unavailable_capability(capability_id, capability_id, reason, metadata)
        if workflow["available"] is False:
            return _unavailable_capability(
                capability_id,
                capability_id,
                str(workflow.get("unavailable_reason") or WORKFLOW_CLASSIFICATION_REQUIRED),
                metadata,
            )

        runtime_reason = workflow_runtime_unavailable_reason(workflow)
        if runtime_reason is not None:
            return _unavailable_capability(capability_id, capability_id, runtime_reason, metadata)

        return WorkflowCapability(
            type="app_skill",
            id=capability_id,
            title=capability_id,
            metadata=metadata,
        )


def _workflow_metadata_reason(workflow: Mapping[str, Any], input_schema: Any) -> str | None:
    available = workflow.get("available")
    if not isinstance(available, bool):
        return WORKFLOW_METADATA_INVALID
    if available is False:
        reason = workflow.get("unavailable_reason")
        if reason not in _UNAVAILABLE_REASONS:
            return WORKFLOW_METADATA_INVALID
        return None
    if not isinstance(input_schema, Mapping):
        return WORKFLOW_METADATA_INVALID
    if workflow.get("execution_mode") not in _EXECUTION_MODES:
        return WORKFLOW_EXECUTION_MODE_UNSUPPORTED
    if workflow.get("effect") not in _EFFECTS:
        return WORKFLOW_EFFECT_UNSUPPORTED
    if not isinstance(workflow.get("unattended"), bool):
        return WORKFLOW_METADATA_INVALID
    if workflow.get("approval") not in _APPROVALS:
        return WORKFLOW_METADATA_INVALID
    requirements = workflow.get("binding_requirements")
    if not isinstance(requirements, list) or not set(requirements).issubset(_BINDING_REQUIREMENTS):
        return WORKFLOW_METADATA_INVALID
    if not isinstance(workflow.get("output_schema"), Mapping):
        return WORKFLOW_METADATA_INVALID
    if not isinstance(workflow.get("test_allowed"), bool):
        return WORKFLOW_METADATA_INVALID
    if workflow["test_allowed"] and not _valid_example(workflow.get("test_example_input"), input_schema):
        return WORKFLOW_TEST_EXAMPLE_REQUIRED
    return None


def _valid_example(value: Any, schema: Mapping[str, Any]) -> bool:
    """Validate the bounded JSON Schema subset used for safe test examples."""
    try:
        resolved_value = resolve_workflow_runtime_values(value)
    except (TypeError, ValueError):
        return False
    return _valid_resolved_example(resolved_value, schema)


def _valid_resolved_example(value: Any, schema: Mapping[str, Any]) -> bool:
    if not isinstance(value, Mapping) or schema.get("type") != "object":
        return False
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return False
    required = schema.get("required", [])
    if not isinstance(required, list) or any(key not in value for key in required):
        return False
    return all(
        key in properties and _matches_schema(item, properties[key])
        for key, item in value.items()
    )


def _matches_schema(value: Any, schema: Any) -> bool:
    if not isinstance(schema, Mapping):
        return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    variants = schema.get("anyOf")
    if variants is not None:
        if not isinstance(variants, list) or not variants or not any(
            _matches_schema(value, variant) for variant in variants
        ):
            return False
        if "type" not in schema:
            return True
    schema_type = schema.get("type")
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if schema_type == "boolean":
        return isinstance(value, bool)
    if schema_type == "array":
        items = schema.get("items")
        return isinstance(value, list) and all(_matches_schema(item, items) for item in value)
    if schema_type == "object":
        return _valid_resolved_example(value, schema)
    return False


def _unavailable_capability(
    capability_id: str,
    title: str,
    reason: str,
    metadata: dict[str, Any] | None = None,
    *,
    app_id: str | None = None,
    skill_id: str | None = None,
) -> WorkflowCapability:
    capability_metadata = metadata or {}
    if app_id is not None:
        capability_metadata["app_id"] = app_id
    if skill_id is not None:
        capability_metadata["skill_id"] = skill_id
    return WorkflowCapability(
        type="app_skill",
        id=capability_id,
        title=title,
        enabled=False,
        reason=reason,
        metadata=capability_metadata,
    )


def _value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dumped
    return None


def _dump_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _load_workflow_classifications() -> dict[str, Any]:
    global _classification_cache
    with _metadata_cache_lock:
        version = _file_version(WORKFLOW_CLASSIFICATION_FILE)
        if _classification_cache is not None and _classification_cache[:2] == (WORKFLOW_CLASSIFICATION_FILE, version):
            return _classification_cache[2]
        if version is None:
            classifications: dict[str, Any] = {}
        else:
            with WORKFLOW_CLASSIFICATION_FILE.open("r", encoding="utf-8") as handle:
                payload = yaml.safe_load(handle) or {}
            capabilities = payload.get("capabilities") if isinstance(payload, Mapping) else None
            classifications = dict(capabilities) if isinstance(capabilities, Mapping) else {}
        _classification_cache = (WORKFLOW_CLASSIFICATION_FILE, version, classifications)
        return classifications


class _FilesystemWorkflowMetadataRegistry:
    """Lightweight app.yml reader for unit environments without Celery installed."""

    def __init__(self, apps_root: Path | None = None) -> None:
        apps_root = apps_root or Path(__file__).resolve().parents[4] / "apps"
        with _metadata_cache_lock:
            app_files = sorted(apps_root.glob("*/app.yml"))
            version = tuple((str(path), *(_file_version(path) or (0, 0))) for path in app_files)
            cached = _filesystem_cache.get(apps_root)
            if cached is None or cached[0] != version:
                metadata_by_id: dict[str, dict[str, Any]] = {}
                for app_file in app_files:
                    with app_file.open("r", encoding="utf-8") as handle:
                        metadata = yaml.safe_load(handle) or {}
                    if isinstance(metadata, dict):
                        metadata_by_id[str(metadata.get("id") or app_file.parent.name)] = metadata
                _filesystem_cache[apps_root] = (version, metadata_by_id)
            self._metadata = _filesystem_cache[apps_root][1]

    def all_metadata(self) -> dict[str, dict[str, Any]]:
        return self._metadata

    def get_metadata(self, app_id: str) -> dict[str, Any] | None:
        return self._metadata.get(app_id)

    def is_skill_available(self, app_id: str, skill_id: str) -> bool:
        app_metadata = self._metadata.get(app_id) or {}
        return any(
            isinstance(skill, dict)
            and skill.get("id") == skill_id
            and isinstance(skill.get("class_path"), str)
            and bool(skill.get("class_path", "").strip())
            for skill in app_metadata.get("skills") or []
        )
