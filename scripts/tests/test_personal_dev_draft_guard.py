"""Tooling test: the personal-dev leftover-draft guard fails runs that leave drafts."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import personal_dev_draft_guard as guard  # noqa: E402 - import after adding scripts/ to sys.path


# contract-test: tooling
def test_parse_rejects_unexpected_shapes() -> None:
    assert guard.parse_draft_chat_ids({"drafts": [{"chatId": "a"}, {"chatId": "b"}]}) == {"a", "b"}
    for payload in ({}, {"drafts": None}, {"drafts": [{"markdown": "x"}]}, []):
        with pytest.raises(guard.DraftGuardError):
            guard.parse_draft_chat_ids(payload)


# contract-test: tooling
def test_only_drafts_new_since_the_baseline_are_leftovers() -> None:
    assert guard.leftover_drafts({"keep"}, {"keep"}) == []
    assert guard.leftover_drafts({"keep", "cleared"}, {"keep", "new-2", "new-1"}) == ["new-1", "new-2"]


# contract-test: tooling
def test_receipt_fails_on_leftovers_and_on_unreadable_inventory() -> None:
    clean = {"status": "passed", "cleanup": {}}
    guard.record_leftovers(clean, guard.DraftGuard(frozenset({"a"}), lambda: {"a"}))
    assert clean == {"status": "passed", "cleanup": {"drafts": "clean"}}

    dirty = {"status": "passed", "cleanup": {}}
    guard.record_leftovers(dirty, guard.DraftGuard(frozenset(), lambda: {"x"}))
    assert dirty["status"] == "failed"
    assert dirty["leftover_draft_chat_ids"] == ["x"]
    assert dirty["error_code"] == "leftover_drafts"

    def unreadable() -> set[str]:
        raise guard.DraftGuardError("draft_list_failed")

    broken = {"status": "passed", "cleanup": {}}
    guard.record_leftovers(broken, guard.DraftGuard(frozenset(), unreadable))
    assert broken["status"] == "failed"
    assert broken["cleanup"]["drafts"] == "check_failed"


# contract-test: tooling
def test_check_command_exits_nonzero_on_leftovers(tmp_path, monkeypatch, capsys) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"draft_chat_ids": ["keep"]}))
    monkeypatch.setattr(guard, "list_draft_chat_ids", lambda cli, api_url, **_: {"keep", "left"})
    assert guard.main(["check", "--baseline", str(baseline)]) == 1
    assert "left" in capsys.readouterr().err
    monkeypatch.setattr(guard, "list_draft_chat_ids", lambda cli, api_url, **_: {"keep"})
    assert guard.main(["check", "--baseline", str(baseline)]) == 0
