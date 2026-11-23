# contract-test-file: tooling
"""sessions.py wiring of the small-fix change scope (TASK-8809)."""
import pytest

import scripts.sessions as sessions


def test_deploy_refuses_oversized_small_fix_session(monkeypatch, capsys):
    monkeypatch.setattr(sessions, "_change_scope_stats", lambda s, f: ([(f"a{i}.py", 1, 0, False) for i in range(9)], []))
    with pytest.raises(SystemExit):
        sessions._enforce_change_scope({"change_scope": "small-fix"}, ["a"])
    assert "Small-fix scope (AI test-user report): this change is too large" in capsys.readouterr().err


def test_deploy_allows_small_fix_and_unscoped(monkeypatch):
    monkeypatch.setattr(sessions, "_change_scope_stats", lambda s, f: ([("a.py", 3, 1, False)], []))
    sessions._enforce_change_scope({"change_scope": "small-fix"}, ["a.py"])
    monkeypatch.setattr(sessions, "_change_scope_stats", lambda s, f: pytest.fail("unscoped must not inspect"))
    sessions._enforce_change_scope({}, ["a.py"])


def test_unknown_scope_env_rejected(monkeypatch):
    monkeypatch.setenv("OPENMATES_CHANGE_SCOPE", "big")
    with pytest.raises(SystemExit):
        sessions._requested_change_scope()
    monkeypatch.setenv("OPENMATES_CHANGE_SCOPE", "small-fix")
    assert sessions._requested_change_scope() == "small-fix"
