# backend/tests/test_apple_ui_contracts.py
#
# Unit coverage for the Apple UI contract/audit script. These tests build small
# temporary web/native source trees so deterministic parity checks can be
# verified without depending on generated fixtures in the working tree.
# Architecture context: scripts/apple_ui_contracts.py

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import apple_ui_contracts  # noqa: E402


def _write_repo_fixture(tmp_path: Path, registry_keys: list[str], *, content_cases: list[str]) -> None:
    registry_entries = "\n".join(f'  "{key}": "Demo.svelte",' for key in registry_keys)
    registry_path = tmp_path / "frontend/packages/ui/src/data/embedRegistry.generated.ts"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        "export const EMBED_PREVIEW_COMPONENTS: Record<string, string> = {\n"
        f"{registry_entries}\n"
        "};\n"
        "export const EMBED_FULLSCREEN_COMPONENTS: Record<string, string> = {\n"
        f"{registry_entries}\n"
        "};\n",
        encoding="utf-8",
    )

    apps = sorted(apple_ui_contracts.REQUIRED_EMBED_SHOWCASE_APPS)
    showcase_path = tmp_path / "frontend/apps/web_app/src/routes/dev/preview/embeds/[app]/+page.svelte"
    showcase_path.parent.mkdir(parents=True)
    showcase_path.write_text(
        "<script>\n"
        f"const ALL_APPS = [{', '.join(repr(app) for app in apps)}];\n"
        "</script>\n",
        encoding="utf-8",
    )

    enum_cases = {
        "app:images:generate_draft": "imagesGenerateDraft",
        "app:travel:search_connections": "travelConnections",
        "app:travel:search_stays": "travelStays",
        "app:travel:get_flight": "travelFlight",
        "focus-mode-activation": "focusModeActivation",
        "image": "image",
        "images-image-result": "imagesImageResult",
        "maps-place": "mapsPlace",
        "app:demo:unknown": "demoUnknown",
    }
    embed_model_cases = "\n".join(f'    case {enum_cases[key]} = "{key}"' for key in registry_keys)
    embed_models_path = tmp_path / "apple/OpenMates/Sources/Core/Models/EmbedModels.swift"
    embed_models_path.parent.mkdir(parents=True)
    embed_models_path.write_text(
        "enum EmbedType: String {\n"
        f"{embed_model_cases}\n"
        "}\n",
        encoding="utf-8",
    )

    app_cases = "\n".join(
        f'    case {apple_ui_contracts._swift_case_name_for_app(app)} = "{app}"'
        if "_" in app
        else f"    case {app}"
        for app in apps
    )
    switch_cases = "\n".join(f"        case .{apple_ui_contracts._swift_case_name_for_app(app)}: return []" for app in apps)
    fixture_ids = [
        "images-generate",
        "travel-search",
        "travel-stays",
        "travel-get-flight",
        "images-upload",
        "images-result",
        "images-search",
        "maps-search",
    ]
    fixture_returns = "\n".join(f'func fixture_{index}() {{ return skill(id: "{fixture_id}") }}' for index, fixture_id in enumerate(fixture_ids))
    fixtures_path = tmp_path / "apple/OpenMates/Sources/DevPreview/DevEmbedPreviewFixtures.swift"
    fixtures_path.parent.mkdir(parents=True)
    fixtures_path.write_text(
        "enum DevEmbedPreviewApp: String {\n"
        f"{app_cases}\n"
        "}\n"
        "func skills(for app: DevEmbedPreviewApp) -> [String] {\n"
        "    switch app {\n"
        f"{switch_cases}\n"
        "    }\n"
        "}\n"
        f"{fixture_returns}\n",
        encoding="utf-8",
    )

    content_path = tmp_path / "apple/OpenMates/Sources/Features/Embeds/Views/EmbedContentView.swift"
    content_path.parent.mkdir(parents=True)
    content_path.write_text("\n".join(f"case .{case}" for case in content_cases), encoding="utf-8")


def test_embed_audit_allows_explicit_fixture_aliases_and_renderer_only_keys(tmp_path, monkeypatch) -> None:
    """Known equivalent fixture IDs should not produce drift warnings."""

    registry_keys = [
        "app:images:generate_draft",
        "app:travel:search_connections",
        "app:travel:search_stays",
        "app:travel:get_flight",
        "focus-mode-activation",
        "image",
        "images-image-result",
        "maps-place",
    ]
    _write_repo_fixture(tmp_path, registry_keys, content_cases=["focusModeActivation"])
    monkeypatch.setattr(apple_ui_contracts, "REPO_ROOT", tmp_path)

    errors, warnings = apple_ui_contracts.audit_embeds()

    assert errors == []
    assert warnings == ["visual/style contract checks are agent-reviewed for embeds until specific surfaces are promoted"]


def test_embed_audit_warns_for_unclassified_registry_key(tmp_path, monkeypatch) -> None:
    """New registry keys need a fixture alias or explicit renderer-only coverage."""

    _write_repo_fixture(tmp_path, ["app:demo:unknown"], content_cases=[])
    monkeypatch.setattr(apple_ui_contracts, "REPO_ROOT", tmp_path)

    errors, warnings = apple_ui_contracts.audit_embeds()

    assert errors == []
    assert "no direct Apple debug fixture id found for registry key: app:demo:unknown" in warnings
