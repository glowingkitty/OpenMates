"""Tests for the dev-only admin issue -> Claude chat queue writer."""

import json
import os
import stat

import pytest

from backend.core.api.app.utils import claude_issue_dispatch as dispatch

ISSUE_ID = "0b6f5c1e-8a3b-4b8e-9d55-2f1f0c1d2e3f"


# contract-test: supporting surface=gui.web assertions=issue-reporting.automation.admin-dev-claude-chat
def test_queue_writes_identifier_only_request(tmp_path):
    result = dispatch.queue_issue_for_claude_chat(issue_id=ISSUE_ID, short_issue_id="ABCDE", queue_dir=str(tmp_path))
    assert result.status == "queued"
    path = tmp_path / "issue-ABCDE.json"
    assert json.loads(path.read_text()).keys() == {"kind", "issue_id", "short_issue_id", "queued_at"}
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o644
    assert not list(tmp_path.glob(".*.tmp"))


# contract-test: supporting surface=gui.web assertions=issue-reporting.automation.admin-dev-claude-chat
def test_queue_unavailable_without_configured_directory(monkeypatch, tmp_path):
    monkeypatch.delenv(dispatch.QUEUE_DIR_ENV, raising=False)
    assert dispatch.queue_issue_for_claude_chat(issue_id=ISSUE_ID, short_issue_id="ABCDE").status == "unavailable"
    missing = tmp_path / "missing"
    assert dispatch.queue_issue_for_claude_chat(issue_id=ISSUE_ID, short_issue_id="ABCDE", queue_dir=str(missing)).status == "unavailable"


# contract-test: supporting surface=gui.web assertions=issue-reporting.automation.admin-dev-claude-chat
@pytest.mark.parametrize("issue_id,short_id", [("not-a-uuid", "ABCDE"), (ISSUE_ID, "abc"), (ISSUE_ID, "AB1DE")])
def test_queue_rejects_invalid_identifiers(tmp_path, issue_id, short_id):
    with pytest.raises(ValueError):
        dispatch.queue_issue_for_claude_chat(issue_id=issue_id, short_issue_id=short_id, queue_dir=str(tmp_path))


# contract-test: supporting surface=gui.web assertions=issue-reporting.automation.admin-dev-claude-chat
@pytest.mark.parametrize("value,expected", [("development", True), ("production", False), ("", False)])
def test_development_detection_fails_closed(monkeypatch, value, expected):
    monkeypatch.setenv("SERVER_ENVIRONMENT", value)
    assert dispatch.is_development_server() is expected


@pytest.mark.parametrize(
    "requested,is_admin,environment",
    [(False, True, "development"), (True, False, "development"), (True, True, "production")],
)
# contract-test: supporting surface=gui.web assertions=issue-reporting.automation.admin-dev-claude-chat
def test_handoff_gate_never_queues_outside_admin_dev(monkeypatch, tmp_path, requested, is_admin, environment):
    monkeypatch.setenv("SERVER_ENVIRONMENT", environment)
    monkeypatch.setenv(dispatch.QUEUE_DIR_ENV, str(tmp_path))
    assert dispatch.handoff_admin_issue(
        requested=requested, is_admin=is_admin, issue_id=ISSUE_ID, short_issue_id="ABCDE",
    ) is None
    assert not list(tmp_path.iterdir())


# contract-test: supporting surface=gui.web assertions=issue-reporting.automation.admin-dev-claude-chat
def test_handoff_gate_queues_for_admin_on_dev(monkeypatch, tmp_path):
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.setenv(dispatch.QUEUE_DIR_ENV, str(tmp_path))
    result = dispatch.handoff_admin_issue(requested=True, is_admin=True, issue_id=ISSUE_ID, short_issue_id="ABCDE")
    assert result is not None and result.status == "queued"
    assert (tmp_path / "issue-ABCDE.json").exists()
