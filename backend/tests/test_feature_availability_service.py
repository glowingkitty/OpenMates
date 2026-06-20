# backend/tests/test_feature_availability_service.py
#
# Contract tests for the simplified feature availability model. Features are
# enabled by default unless metadata explicitly marks them off or an admin
# override disables them.
#
# Spec: docs/specs/simplified-feature-availability/spec.yml

from backend.core.api.app.services.feature_availability_service import (
    FeatureAvailabilityService,
    FeatureDefinition,
    migrate_legacy_disabled_apps,
)
from backend.core.api.app.routes.features import _definitions_from_raw_manifests


def test_features_are_enabled_by_default() -> None:
    service = FeatureAvailabilityService(
        definitions=[FeatureDefinition(id="skill:web:search", kind="skill")],
        config={},
    )

    assert service.is_enabled("skill:web:search") is True
    assert service.explain("skill:web:search").effective_enabled is True


def test_default_enabled_false_requires_admin_enable() -> None:
    feature = FeatureDefinition(id="embed:code:application", kind="embed", default_enabled=False)

    disabled_service = FeatureAvailabilityService(definitions=[feature], config={})
    enabled_service = FeatureAvailabilityService(
        definitions=[feature],
        config={"feature_overrides": {"enabled": ["embed:code:application"], "disabled": []}},
    )

    assert disabled_service.is_enabled("embed:code:application") is False
    assert enabled_service.is_enabled("embed:code:application") is True


def test_disabled_parent_disables_children_unless_child_explicitly_enabled() -> None:
    definitions = [
        FeatureDefinition(id="app:videos", kind="app"),
        FeatureDefinition(id="skill:videos:create", kind="skill", parent_id="app:videos"),
        FeatureDefinition(id="embed:videos:video", kind="embed", parent_id="app:videos"),
    ]
    service = FeatureAvailabilityService(
        definitions=definitions,
        config={
            "feature_overrides": {
                "enabled": ["skill:videos:create"],
                "disabled": ["app:videos"],
            }
        },
    )

    assert service.is_enabled("app:videos") is False
    assert service.is_enabled("skill:videos:create") is True
    assert service.is_enabled("embed:videos:video") is False


def test_legacy_disabled_apps_migrate_to_feature_overrides() -> None:
    config = {"disabled_apps": ["images", "videos"], "feature_overrides": {"disabled": ["app:web"]}}

    migrated = migrate_legacy_disabled_apps(config)

    assert migrated["feature_overrides"]["disabled"] == ["app:web", "app:images", "app:videos"]
    assert "disabled_apps" not in migrated


def test_raw_manifest_definitions_include_default_disabled_embeds(tmp_path) -> None:
    app_dir = tmp_path / "code"
    app_dir.mkdir()
    (app_dir / "app.yml").write_text(
        """
name_translation_key: code
description_translation_key: code.description
embed_types:
  - id: application
    default_enabled: false
    frontend_type: code-application
    backend_type: application
""".strip(),
        encoding="utf-8",
    )

    definitions = _definitions_from_raw_manifests(str(tmp_path))

    application = next(definition for definition in definitions if definition.id == "embed:code:application")
    assert application.default_enabled is False
