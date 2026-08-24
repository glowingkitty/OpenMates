"""Focused Linux-safe tests for simulator notification harness behavior.

These tests cover generic payload privacy, profile/device compatibility, and
malformed request rejection without requiring Xcode or a simulator. They do
not exercise APNs provider delivery, account credentials, or private chats.
"""

# contract-test-file: infrastructure

import importlib.util
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest


SCRIPT_PATH = Path(__file__).parents[1] / "apple_background_notification_simulator_test.py"
SPEC = importlib.util.spec_from_file_location("apple_background_notification_simulator_test", SCRIPT_PATH)
assert SPEC and SPEC.loader
HARNESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HARNESS)


def test_payload_is_generic_and_uses_only_routing_metadata(tmp_path: Path) -> None:
    payload_path = tmp_path / "push.apns"
    HARNESS.write_payload(
        payload_path,
        {"request_id": "request-1", "scenario": "warm_tap", "chat_id": "opaque-chat-id"},
    )

    payload = json.loads(payload_path.read_text(encoding="utf-8"))

    assert payload["aps"]["alert"] == {"title": "OpenMates", "body": "New message received"}
    assert payload["aps"]["badge"] == 1
    assert payload["chat_id"] == "opaque-chat-id"
    assert "request_id" not in payload
    assert "scenario" not in payload


def test_recording_profile_must_match_simulator_family() -> None:
    HARNESS.validate_profile("iPhone 17", "apple-iphone-portrait")
    HARNESS.validate_profile("iPad Pro 13-inch (M5)", "apple-ipad-landscape")

    with pytest.raises(ValueError, match="requires an iphone simulator"):
        HARNESS.validate_profile("iPad Pro 13-inch (M5)", "apple-iphone-portrait")


def test_request_validation_rejects_partial_or_invalid_json(tmp_path: Path) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text("not-json", encoding="utf-8")
    assert HARNESS.read_request(request_path) is None

    request_path.write_text(json.dumps({"request_id": "one"}), encoding="utf-8")
    assert HARNESS.read_request(request_path) is None


def test_uninstall_ignores_only_known_missing_app_result() -> None:
    result = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="An error occurred: No such app"
    )
    with patch.object(HARNESS.subprocess, "run", return_value=result) as run:
        HARNESS.run_uninstall()

    assert run.call_args.kwargs["env"]["DEVELOPER_DIR"] == HARNESS.DEVELOPER_DIR
    assert run.call_args.kwargs["capture_output"] is True


def test_uninstall_surfaces_unexpected_failure_without_output(capsys: pytest.CaptureFixture[str]) -> None:
    result = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="private simulator output", stderr="unexpected failure"
    )
    with patch.object(HARNESS.subprocess, "run", return_value=result):
        with pytest.raises(RuntimeError, match="simctl uninstall failed"):
            HARNESS.run_uninstall()

    assert capsys.readouterr().out == ""
    assert capsys.readouterr().err == ""


def test_xcode_subprocesses_pin_developer_dir(tmp_path: Path) -> None:
    result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    with patch.object(HARNESS.subprocess, "run", return_value=result) as run:
        assert HARNESS.inject_push(tmp_path / "push.apns")
        assert HARNESS.run_xcodebuild(
            "iPhone 17", tmp_path / "request.json", tmp_path / "response.json", "auto", None
        ) == 0

    assert all(call.kwargs["env"]["DEVELOPER_DIR"] == HARNESS.DEVELOPER_DIR for call in run.call_args_list)
