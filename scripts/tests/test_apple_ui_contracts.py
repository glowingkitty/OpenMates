"""Focused tests for Apple web-contract source coverage.

The contract audit must scan canonical component files rather than forcing
accessibility identifiers into unrelated views. These tests use repository
paths only and do not access private runtime or simulator data.
"""

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
