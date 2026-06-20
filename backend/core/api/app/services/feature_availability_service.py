# backend/core/api/app/services/feature_availability_service.py
#
# Computes effective availability for OpenMates features. The product contract is
# intentionally simple: implemented features are enabled by default, except when
# metadata declares default_enabled: false or an admin override disables them.
#
# Spec: docs/specs/simplified-feature-availability/spec.yml

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal


FeatureKind = Literal["app", "skill", "embed", "focus", "memory", "platform"]


@dataclass(frozen=True)
class FeatureDefinition:
    """Static metadata for a feature discovered from app config or platform config."""

    id: str
    kind: FeatureKind
    default_enabled: bool = True
    parent_id: str | None = None
    app_id: str | None = None
    source: str | None = None


@dataclass(frozen=True)
class FeatureExplanation:
    """Human-readable state used by CLI explain/list commands."""

    id: str
    kind: str
    default_enabled: bool
    effective_enabled: bool
    override: str | None
    parent_id: str | None
    source: str | None


def _normalize_feature_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in (str(raw).strip() for raw in value) if item]


def migrate_legacy_disabled_apps(config: dict[str, Any]) -> dict[str, Any]:
    """Return a config copy with legacy disabled_apps folded into feature overrides."""

    migrated = dict(config)
    legacy_apps = _normalize_feature_list(migrated.pop("disabled_apps", []))
    overrides = dict(migrated.get("feature_overrides") or {})
    disabled = _normalize_feature_list(overrides.get("disabled"))

    for app_id in legacy_apps:
        feature_id = app_id if app_id.startswith("app:") else f"app:{app_id}"
        if feature_id not in disabled:
            disabled.append(feature_id)

    overrides["disabled"] = disabled
    overrides["enabled"] = _normalize_feature_list(overrides.get("enabled"))
    migrated["feature_overrides"] = overrides
    return migrated


class FeatureAvailabilityService:
    """Compute effective feature state from metadata defaults and admin overrides."""

    def __init__(self, definitions: Iterable[FeatureDefinition], config: dict[str, Any]) -> None:
        self._definitions = {definition.id: definition for definition in definitions}
        migrated_config = migrate_legacy_disabled_apps(config)
        overrides = migrated_config.get("feature_overrides") or {}
        self._enabled_overrides = set(_normalize_feature_list(overrides.get("enabled")))
        self._disabled_overrides = set(_normalize_feature_list(overrides.get("disabled")))

    @property
    def definitions(self) -> dict[str, FeatureDefinition]:
        return dict(self._definitions)

    @property
    def enabled_overrides(self) -> set[str]:
        return set(self._enabled_overrides)

    @property
    def disabled_overrides(self) -> set[str]:
        return set(self._disabled_overrides)

    def is_enabled(self, feature_id: str) -> bool:
        if feature_id in self._enabled_overrides:
            return True
        if feature_id in self._disabled_overrides:
            return False

        definition = self._definitions.get(feature_id)
        if definition is None:
            return True
        if not definition.default_enabled:
            return False
        if definition.parent_id:
            return self.is_enabled(definition.parent_id)
        return True

    def explain(self, feature_id: str) -> FeatureExplanation:
        definition = self._definitions.get(feature_id)
        if definition is None:
            definition = FeatureDefinition(id=feature_id, kind="platform", source="admin_config")
        override = None
        if feature_id in self._enabled_overrides:
            override = "enabled"
        elif feature_id in self._disabled_overrides:
            override = "disabled"
        return FeatureExplanation(
            id=feature_id,
            kind=definition.kind,
            default_enabled=definition.default_enabled,
            effective_enabled=self.is_enabled(feature_id),
            override=override,
            parent_id=definition.parent_id,
            source=definition.source,
        )

    def list_features(self) -> list[FeatureExplanation]:
        ids = set(self._definitions) | self._enabled_overrides | self._disabled_overrides
        return [self.explain(feature_id) for feature_id in sorted(ids)]

    def list_disabled_feature_ids(self) -> list[str]:
        """Return the sparse client-facing disabled feature list.

        This intentionally lists only feature IDs that are directly inactive via
        metadata defaults or admin overrides. Children inherited from a disabled
        parent are not expanded, keeping the client contract small: clients treat
        everything not listed here as enabled by default.
        """

        disabled = set(self._disabled_overrides)
        for feature_id, definition in self._definitions.items():
            if not definition.default_enabled and feature_id not in self._enabled_overrides:
                disabled.add(feature_id)
        return sorted(disabled - self._enabled_overrides)


def app_feature_id(app_id: str) -> str:
    return f"app:{app_id}"


def skill_feature_id(app_id: str, skill_id: str) -> str:
    return f"skill:{app_id}:{skill_id}"


def embed_feature_id(app_id: str, embed_id: str) -> str:
    return f"embed:{app_id}:{embed_id}"


def focus_feature_id(app_id: str, focus_id: str) -> str:
    return f"focus:{app_id}:{focus_id}"


def memory_feature_id(app_id: str, memory_id: str) -> str:
    return f"memory:{app_id}:{memory_id}"


def platform_feature_id(feature_id: str) -> str:
    return f"platform:{feature_id}"


PLATFORM_FEATURES: tuple[FeatureDefinition, ...] = (
    FeatureDefinition(id=platform_feature_id("projects"), kind="platform", default_enabled=False, source="platform"),
    FeatureDefinition(id=platform_feature_id("workflows"), kind="platform", default_enabled=False, source="platform"),
    FeatureDefinition(id=platform_feature_id("tasks"), kind="platform", default_enabled=False, source="platform"),
)


def is_sparse_default_enabled_false(raw: dict[str, Any]) -> bool:
    return raw.get("default_enabled") is False


def collect_feature_definitions_from_app_config(
    app_id: str,
    raw_config: dict[str, Any],
    source: str | None = None,
) -> list[FeatureDefinition]:
    """Build feature definitions for implemented metadata in one app.yml file."""

    app_definition = FeatureDefinition(
        id=app_feature_id(app_id),
        kind="app",
        default_enabled=not is_sparse_default_enabled_false(raw_config),
        app_id=app_id,
        source=source,
    )
    definitions: list[FeatureDefinition] = [app_definition]
    app_parent_id = app_definition.id

    for skill in raw_config.get("skills") or []:
        if not isinstance(skill, dict) or not skill.get("class_path"):
            continue
        skill_id = str(skill.get("id") or "").strip()
        if not skill_id:
            continue
        definitions.append(
            FeatureDefinition(
                id=skill_feature_id(app_id, skill_id),
                kind="skill",
                default_enabled=not is_sparse_default_enabled_false(skill),
                parent_id=app_parent_id,
                app_id=app_id,
                source=source,
            )
        )

    for embed in raw_config.get("embed_types") or []:
        if not isinstance(embed, dict):
            continue
        embed_id = str(embed.get("id") or "").strip()
        if not embed_id:
            continue
        definitions.append(
            FeatureDefinition(
                id=embed_feature_id(app_id, embed_id),
                kind="embed",
                default_enabled=not is_sparse_default_enabled_false(embed),
                parent_id=app_parent_id,
                app_id=app_id,
                source=source,
            )
        )

    for focus in (raw_config.get("focuses") or raw_config.get("focus_modes") or []):
        if not isinstance(focus, dict) or not (focus.get("system_prompt") or focus.get("systemprompt") or focus.get("systemprompt_translation_key")):
            continue
        focus_id = str(focus.get("id") or "").strip()
        if not focus_id:
            continue
        definitions.append(
            FeatureDefinition(
                id=focus_feature_id(app_id, focus_id),
                kind="focus",
                default_enabled=not is_sparse_default_enabled_false(focus),
                parent_id=app_parent_id,
                app_id=app_id,
                source=source,
            )
        )

    for memory in (raw_config.get("settings_and_memories") or raw_config.get("memory_fields") or raw_config.get("memory") or []):
        if not isinstance(memory, dict) or not memory.get("schema"):
            continue
        memory_id = str(memory.get("id") or "").strip()
        if not memory_id:
            continue
        definitions.append(
            FeatureDefinition(
                id=memory_feature_id(app_id, memory_id),
                kind="memory",
                default_enabled=not is_sparse_default_enabled_false(memory),
                parent_id=app_parent_id,
                app_id=app_id,
                source=source,
            )
        )

    return definitions
