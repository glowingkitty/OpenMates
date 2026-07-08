#!/usr/bin/env python3
"""Static guard for Apple sync/decryption startup parity.

These tests keep the native startup path aligned with the web app's bounded
decryption model: connect sync before sidebar metadata decrypt, keep REST
fallbacks visible-only, and reserve eager all-chat metadata decrypt for the
bounded Phase 1a startup shell.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAIN_APP_VIEW = ROOT / "apple/OpenMates/Sources/App/MainAppView.swift"


def read_main_app_view() -> str:
    return MAIN_APP_VIEW.read_text(encoding="utf-8")


def function_body(source: str, name: str) -> str:
    marker = f"private func {name}"
    start = source.index(marker)
    brace_start = source.index("{", start)
    depth = 0
    for index in range(brace_start, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[brace_start + 1:index]
    raise AssertionError(f"Could not parse function body for {name}")


def test_authenticated_bootstrap_connects_before_offline_metadata_decrypt() -> None:
    body = function_body(read_main_app_view(), "bootstrapAuthenticatedSession")

    connect_index = body.index("connectWebSocket()")
    decrypt_index = body.index('decryptVisibleChatMetadata(reason: "offlineColdLoad")')

    assert connect_index < decrypt_index
    assert 'await decryptVisibleChatMetadata(reason: "offlineColdLoad")\n\n        Task' not in body


def test_rest_initial_load_uses_visible_only_metadata_decryption() -> None:
    body = function_body(read_main_app_view(), "loadInitialData")

    assert "metadataDecryption: .visibleOnly" in body
    assert "metadataDecryption: .all" not in body


def test_only_phase1a_uses_all_metadata_decryption() -> None:
    source = read_main_app_view()
    all_count = source.count("metadataDecryption: .all")
    phase1_body = function_body(source, "processSyncEvent")

    assert all_count == 1
    assert "phase_1_last_chat_ready" in phase1_body
    assert "metadataDecryption: .all" in phase1_body
    assert "decrypt=deferred" in phase1_body
