"""Focused tests for Apple web-contract source coverage.

The contract audit must scan canonical component files rather than forcing
accessibility identifiers into unrelated views. These tests use repository
paths only and do not access private runtime or simulator data.
"""

import copy

from scripts import apple_ui_contracts


# contract-test: tooling
def test_message_input_audit_scans_canonical_composer_component() -> None:
    paths = apple_ui_contracts.swift_files_for_message_input()

    assert any(path.name == "MessageComposerView.swift" for path in paths)
    assert any(path.name == "ComposerAttachmentActionRow.swift" for path in paths)


# contract-test: tooling
def test_embed_showcase_apps_read_current_slug_registry() -> None:
    source = "export const EMBED_APP_SLUGS = ['code', 'web'] as const;"
    assert apple_ui_contracts._extract_showcase_apps(source) == {"code", "web"}


# contract-test: tooling
def test_attachment_icons_must_exist_in_web_source_assets() -> None:
    assert apple_ui_contracts.missing_attachment_icons(
        'Icon("add"); Icon("plus"); item("missing", label, "files", action)', {"plus"}
    ) == {"add", "missing"}


def _embed_contract() -> dict:
    return {
        "schemaVersion": 1,
        "surface": "embeds",
        "dimension": {"id": "iphone-light-ltr"},
        "apps": [{"appId": app} for app in sorted(apple_ui_contracts.REQUIRED_EMBED_SHOWCASE_APPS)],
        "surfaces": [
            {
                "key": "web:search:1",
                "appId": "web",
                "sources": {"preview": True, "fullscreen": True},
                "previews": [{"capture": {"visibleText": "Example"}}],
                "fullscreen": {"visibleText": "Example"},
            }
        ],
        "registrySurfaces": [
            {
                "registryKey": "example",
                "surface": surface,
                "exists": True,
                "renderError": False,
                "capture": {"visibleText": "Example", "computedStyle": {"width": "300px"}},
                "screenshotPath": f"iphone-light-ltr/registry/example-{surface}.png",
            }
            for surface in ("preview", "fullscreen")
        ],
    }


# contract-test: tooling
def test_embed_registry_contract_requires_each_rendered_surface(monkeypatch) -> None:
    monkeypatch.setattr(apple_ui_contracts, "_extract_ts_object_keys", lambda *_: {"example"})
    contract = _embed_contract()
    assert apple_ui_contracts.validate_embeds_contract(contract) == []

    missing = copy.deepcopy(contract)
    missing["registrySurfaces"].pop()
    assert any("missing 1 registry surfaces" in error for error in apple_ui_contracts.validate_embeds_contract(missing))

    duplicate = copy.deepcopy(contract)
    duplicate["registrySurfaces"].append(copy.deepcopy(duplicate["registrySurfaces"][0]))
    assert any("duplicate registry surface" in error for error in apple_ui_contracts.validate_embeds_contract(duplicate))


# contract-test: tooling
def test_embed_registry_contract_rejects_uncaptured_or_private_artifacts(monkeypatch) -> None:
    monkeypatch.setattr(apple_ui_contracts, "_extract_ts_object_keys", lambda *_: {"example"})
    contract = _embed_contract()
    contract["registrySurfaces"][0]["capture"] = None
    contract["registrySurfaces"][1]["screenshotPath"] = "/Users/example/private.png"
    errors = apple_ui_contracts.validate_embeds_contract(contract)
    assert any("missing rendered capture" in error for error in errors)
    assert any("screenshot must be relative" in error for error in errors)
