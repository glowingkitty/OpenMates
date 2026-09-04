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
    monkeypatch.setattr(sessions, "MEDIA_AUTOMATION_ENABLED", True)
    return state


def test_recovery_quarantines_all_undelivered_media_without_deleting_records(monkeypatch) -> None:
    sessions = load_sessions()
    state = {
        "sessions": {
            "one": {
                "opencode_session_id": "ses_one",
                "response_media": {
                    "pending": {"artifact_key": "pending", "status": "pending"},
                    "delivering": {"artifact_key": "delivering", "status": "delivering"},
                    "delivered": {"artifact_key": "delivered", "status": "delivered"},
                },
            },
            "two": {
                "opencode_session_id": "ses_two",
                "response_media": {"failed": {"artifact_key": "failed", "status": "failed"}},
            },
        }
    }

    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(state))
    result = sessions._quarantine_session_media(reason="recovery test")

    assert result["quarantined"] == 2
    assert result["sessions_changed"] == 1
    assert state["sessions"]["one"]["response_media"]["pending"]["status"] == "quarantined"
    assert state["sessions"]["one"]["response_media"]["delivering"]["status"] == "quarantined"
    assert state["sessions"]["one"]["response_media"]["delivered"]["status"] == "delivered"
    assert state["sessions"]["two"]["response_media"]["failed"]["status"] == "failed"


def test_disabled_automation_never_claims_or_creates_pending_media(monkeypatch) -> None:
    sessions = load_sessions()
    state = isolated_state(monkeypatch, sessions)
    monkeypatch.setattr(sessions, "MEDIA_AUTOMATION_ENABLED", False)

    record = sessions._record_session_media("repo", artifact_type="video", snippet="<video></video>")

    assert record["status"] == "quarantined"
    assert sessions._claim_session_media("repo") is None
    assert state["sessions"]["repo"]["response_media"][record["artifact_key"]]["status"] == "quarantined"


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
    assert first["message_id"][4:16] != "000000000000"
    assert second["message_id"][4:16] != "000000000000"
    assert failed["status"] == "failed"
    assert sessions._claim_session_media("repo") is None


def test_uploaded_figma_image_upgrades_pending_export(monkeypatch) -> None:
    sessions = load_sessions()
    isolated_state(monkeypatch, sessions)
    key = "frame-settings"
    sessions._record_session_media(
        "repo",
        artifact_type="figma_export",
        artifact_key=key,
        artifact_path="/tmp/frame.png",
        snippet="upload the exported frame",
    )
    upgraded = sessions._record_session_media(
        "repo",
        artifact_type="figma_image",
        artifact_key=key,
        artifact_path="/tmp/frame.png",
        snippet="![Figma](https://example/frame.png)",
    )

    assert upgraded["artifact_type"] == "figma_image"
    assert upgraded["artifact_path"] == "/tmp/frame.png"
    assert upgraded["snippet"].startswith("![Figma]")
    assert upgraded["status"] == "pending"


def test_media_fail_retires_undeliverable_artifact(monkeypatch) -> None:
    sessions = load_sessions()
    isolated_state(monkeypatch, sessions)
    record = sessions._record_session_media(
        "repo",
        artifact_type="figma_export",
        artifact_key="missing-frame",
        artifact_path="/tmp/missing.png",
        snippet="Figma export pending upload: /tmp/missing.png",
    )

    failed = sessions._fail_session_media("repo", record["artifact_key"], reason="missing file")

    assert failed["status"] == "failed"
    assert failed["failure_reason"] == "missing file"
    assert sessions._claim_session_media("repo") is None


def test_media_claim_retires_duplicate_video_after_delivery(monkeypatch) -> None:
    sessions = load_sessions()
    state = isolated_state(monkeypatch, sessions)
    normal = '<video controls crossorigin="anonymous"><source src="https://example/video.webm?x=1&amp;y=2"></video>'
    escaped = '<video controls crossorigin=\\"anonymous\\"><source src=\\"https://example/video.webm?x=1&amp;y=2\\"></video>'
    first = sessions._record_session_media("repo", artifact_type="video", artifact_key="normal", snippet=normal)
    sessions._record_session_media("repo", artifact_type="video", artifact_key="escaped", snippet=escaped)

    claimed = sessions._claim_session_media("repo")
    sessions._finish_session_media("repo", claimed["artifact_key"], delivered=True)
    duplicate_claim = sessions._claim_session_media("repo")
    duplicate_key = "escaped" if claimed["artifact_key"] == first["artifact_key"] else first["artifact_key"]
    duplicate = state["sessions"]["repo"]["response_media"][duplicate_key]

    assert claimed["artifact_key"] in {"normal", "escaped"}
    assert duplicate_claim is None
    assert duplicate["status"] == "failed"
    assert duplicate["failure_reason"] == "duplicate response-media artifact"
