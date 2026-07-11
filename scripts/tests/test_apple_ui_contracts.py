"""Focused tests for Apple web-contract source coverage.

The contract audit must scan canonical component files rather than forcing
accessibility identifiers into unrelated views. These tests use repository
paths only and do not access private runtime or simulator data.
"""

from scripts import apple_ui_contracts


def test_message_input_audit_scans_canonical_composer_component() -> None:
    paths = apple_ui_contracts.swift_files_for_message_input()

    assert any(path.name == "MessageComposerView.swift" for path in paths)
