#!/usr/bin/env python3
"""Durable response-media queue contracts."""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_sessions():
    spec = importlib.util.spec_from_file_location("openmates_sessions_media", ROOT / "scripts/sessions.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def isolated_state(monkeypatch, sessions):
    state = {"sessions": {"repo": {"opencode_session_id": "ses_test"}}}

    def mutate(callback):
        return callback(state)

    monkeypatch.setattr(sessions, "_mutate_sessions", mutate)
    return state


def test_media_delivery_is_idempotent_and_acknowledged_once(monkeypatch) -> None:
    sessions = load_sessions()
    state = isolated_state(monkeypatch, sessions)
    snippet = '<video controls src="https://example/proof.mp4"></video>'

    first = sessions._record_session_media("ses_test", artifact_type="video", snippet=snippet, run_id="run-1")
    repeated = sessions._record_session_media("ses_test", artifact_type="video", snippet=snippet, run_id="run-1")
    claimed = sessions._claim_session_media("ses_test")
    delivered = sessions._finish_session_media("ses_test", claimed["artifact_key"], delivered=True)

    assert first == repeated
    assert claimed["attempts"] == 1
    assert delivered["status"] == "delivered"
    assert sessions._claim_session_media("ses_test") is None
    assert len(state["sessions"]["repo"]["response_media"]) == 1


def test_interrupted_delivery_retries_once_then_stops(monkeypatch) -> None:
    sessions = load_sessions()
    isolated_state(monkeypatch, sessions)
    record = sessions._record_session_media("repo", artifact_type="video", snippet="<video>one</video>")

    first = sessions._claim_session_media("repo")
    sessions._finish_session_media("repo", record["artifact_key"], delivered=False)
    second = sessions._claim_session_media("repo")
    failed = sessions._finish_session_media("repo", record["artifact_key"], delivered=False)

    assert first["message_id"] != second["message_id"]
    assert failed["status"] == "failed"
    assert sessions._claim_session_media("repo") is None


def test_uploaded_figma_image_upgrades_pending_export(monkeypatch) -> None:
    sessions = load_sessions()
    isolated_state(monkeypatch, sessions)
    key = "frame-settings"
    sessions._record_session_media(
        "repo", artifact_type="figma_export", artifact_key=key, snippet="upload the exported frame"
    )
    upgraded = sessions._record_session_media(
        "repo",
        artifact_type="figma_image",
        artifact_key=key,
        snippet="![Figma](https://example/frame.png)",
    )

    assert upgraded["artifact_type"] == "figma_image"
    assert upgraded["snippet"].startswith("![Figma]")
    assert upgraded["status"] == "pending"
