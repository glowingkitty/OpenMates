"""Dev deploy freeze: refuses deploys and pushes to dev from its start until cleared (owner, 2026-11-22)."""

from datetime import datetime, timezone

import pytest

import scripts.deploy_freeze as freeze

START = "2026-11-23T08:00:00+01:00"


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    path = tmp_path / "deploy-freeze.json"
    monkeypatch.setenv("OPENMATES_DEPLOY_FREEZE_FILE", str(path))
    return path


# contract-test: tooling
def test_freeze_is_inactive_before_its_start_and_active_after():
    freeze.main(["set", "--from", START, "--reason", "release PR first"])
    assert freeze.active_reason(datetime(2026, 11, 23, 6, 59, tzinfo=timezone.utc)) == ""
    reason = freeze.active_reason(datetime(2026, 11, 23, 7, 0, tzinfo=timezone.utc))
    assert "release PR first" in reason and "owner" in reason


# contract-test: tooling
def test_check_exits_nonzero_while_frozen_and_clear_ends_it(monkeypatch):
    freeze.main(["set", "--from", "2020-01-01T00:00:00+00:00", "--reason", "release"])
    assert freeze.main(["check", "--ref", "refs/heads/dev"]) == 1
    with pytest.raises(SystemExit):
        freeze.refuse_if_frozen()
    freeze.main(["clear", "--approved-by", "owner go"])
    assert freeze.main(["check", "--ref", "refs/heads/dev"]) == 0
    assert freeze.load()["cleared_by"] == "owner go"
    freeze.refuse_if_frozen()  # no exit


# contract-test: tooling
def test_no_freeze_recorded_allows_deploys():
    assert freeze.active_reason() == ""
    assert freeze.main(["check"]) == 0
