"""
Tests for scripts/sessions.py session-identity resolution.

Bug history this test suite guards against:
- 2026-04-06 (OPE-338 follow-up): the auto-track hook permanently attached
  backend Celery files to a UI-tokens session because cmd_track's fallback
  used `max(last_active)` to pick the "current" session, which is racy
  whenever >1 sessions.py session exists in parallel. Files were never
  removed (no prune logic anywhere), so collision warnings fired forever.
  The fix: capture $ZELLIJ_SESSION_NAME at session start and resolve
  identity from it; silent exit on no match instead of guessing wrong.
  Commits: see scripts/sessions.py `_resolve_session_from_zellij` and
  `cmd_untrack`.

These tests run as plain unit tests (no docker, no network, no DB). They
import sessions.py as a module and monkeypatch SESSIONS_FILE to a
tmp_path so the real .claude/sessions.json is untouched.
"""

import importlib.util
import json
import sys
from argparse import Namespace
from pathlib import Path

import pytest

# scripts/sessions.py is not a package — load it via importlib.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SESSIONS_PY = _REPO_ROOT / "scripts" / "sessions.py"


@pytest.fixture
def sessions_module(tmp_path, monkeypatch):
    """Load scripts/sessions.py with SESSIONS_FILE pointing at tmp_path."""
    spec = importlib.util.spec_from_file_location(
        "sessions_under_test", str(_SESSIONS_PY)
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sessions_under_test"] = mod
    spec.loader.exec_module(mod)

    # Redirect persistent state to a tmp file
    fake_sessions_file = tmp_path / "sessions.json"
    fake_sessions_file.write_text(json.dumps({"sessions": {}, "locks": {}}))
    monkeypatch.setattr(mod, "SESSIONS_FILE", fake_sessions_file)

    yield mod


def _seed(mod, sessions_dict):
    """Write a sessions dict into the test sessions.json."""
    mod.SESSIONS_FILE.write_text(
        json.dumps({"sessions": sessions_dict, "locks": {}})
    )


def _read_files(mod, sid):
    return json.loads(mod.SESSIONS_FILE.read_text())["sessions"][sid].get(
        "modified_files", []
    )


# ---------------------------------------------------------------------------
# _resolve_session_from_zellij
# ---------------------------------------------------------------------------


def test_resolver_returns_single_match(sessions_module, monkeypatch):
    monkeypatch.setenv("ZELLIJ_SESSION_NAME", "claude3")
    sessions = {
        "aaaa": {"zellij_session": "claude3", "task": "ui work"},
        "bbbb": {"zellij_session": "claude5", "task": "backend work"},
    }
    assert sessions_module._resolve_session_from_zellij(sessions) == "aaaa"


def test_resolver_returns_none_when_env_unset(sessions_module, monkeypatch):
    monkeypatch.delenv("ZELLIJ_SESSION_NAME", raising=False)
    sessions = {"aaaa": {"zellij_session": "claude3"}}
    assert sessions_module._resolve_session_from_zellij(sessions) is None


def test_resolver_returns_none_when_no_match(sessions_module, monkeypatch):
    monkeypatch.setenv("ZELLIJ_SESSION_NAME", "claude9")
    sessions = {
        "aaaa": {"zellij_session": "claude3"},
        "bbbb": {"zellij_session": "claude5"},
    }
    assert sessions_module._resolve_session_from_zellij(sessions) is None


def test_resolver_returns_none_on_ambiguous_match(sessions_module, monkeypatch):
    """Two sessions sharing a Zellij tab → refuse to guess."""
    monkeypatch.setenv("ZELLIJ_SESSION_NAME", "claude3")
    sessions = {
        "aaaa": {"zellij_session": "claude3"},
        "bbbb": {"zellij_session": "claude3"},
    }
    assert sessions_module._resolve_session_from_zellij(sessions) is None


def test_resolver_ignores_sessions_with_null_zellij(sessions_module, monkeypatch):
    """Pre-fix sessions have zellij_session=None and must be invisible."""
    monkeypatch.setenv("ZELLIJ_SESSION_NAME", "claude3")
    sessions = {
        "aaaa": {"zellij_session": None, "task": "legacy"},
        "bbbb": {"zellij_session": "claude3", "task": "post-fix"},
    }
    assert sessions_module._resolve_session_from_zellij(sessions) == "bbbb"


# ---------------------------------------------------------------------------
# cmd_track end-to-end with the new identity resolver
# ---------------------------------------------------------------------------


def test_cmd_track_uses_zellij_identity(sessions_module, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("ZELLIJ_SESSION_NAME", "claude3")
    _seed(sessions_module, {
        "aaaa": {"zellij_session": "claude3", "task": "right session", "modified_files": []},
        "bbbb": {"zellij_session": "claude5", "task": "wrong session", "modified_files": []},
    })

    args = Namespace(session=None, file=["scripts/sessions.py"])
    sessions_module.cmd_track(args)

    assert "scripts/sessions.py" in _read_files(sessions_module, "aaaa")
    assert "scripts/sessions.py" not in _read_files(sessions_module, "bbbb")


def test_cmd_track_silent_exit_when_zellij_unset(sessions_module, monkeypatch, capsys):
    """No env var → no auto-track. Better than the old race-prone guess."""
    monkeypatch.delenv("ZELLIJ_SESSION_NAME", raising=False)
    _seed(sessions_module, {
        "aaaa": {"zellij_session": "claude3", "modified_files": []},
        "bbbb": {"zellij_session": "claude5", "modified_files": []},
    })

    args = Namespace(session=None, file=["scripts/sessions.py"])
    sessions_module.cmd_track(args)  # must not raise, must not track

    assert _read_files(sessions_module, "aaaa") == []
    assert _read_files(sessions_module, "bbbb") == []


def test_cmd_track_warns_on_ambiguous_zellij(sessions_module, monkeypatch, capsys):
    monkeypatch.setenv("ZELLIJ_SESSION_NAME", "claude3")
    _seed(sessions_module, {
        "aaaa": {"zellij_session": "claude3", "modified_files": []},
        "bbbb": {"zellij_session": "claude3", "modified_files": []},
    })

    args = Namespace(session=None, file=["scripts/sessions.py"])
    sessions_module.cmd_track(args)

    captured = capsys.readouterr()
    assert "ambiguous Zellij tab" in captured.err
    # No file should have been tracked
    assert _read_files(sessions_module, "aaaa") == []
    assert _read_files(sessions_module, "bbbb") == []


def test_cmd_track_explicit_session_bypasses_identity(sessions_module, monkeypatch):
    """An explicit --session always wins, even if zellij doesn't match."""
    monkeypatch.delenv("ZELLIJ_SESSION_NAME", raising=False)
    _seed(sessions_module, {
        "aaaa": {"zellij_session": "claude3", "modified_files": []},
    })

    args = Namespace(session="aaaa", file=["scripts/sessions.py"])
    sessions_module.cmd_track(args)
    assert "scripts/sessions.py" in _read_files(sessions_module, "aaaa")


# ---------------------------------------------------------------------------
# cmd_untrack
# ---------------------------------------------------------------------------


def test_cmd_untrack_removes_specific_files(sessions_module):
    _seed(sessions_module, {
        "aaaa": {
            "zellij_session": "claude3",
            "modified_files": ["foo.py", "bar.py", "baz.py"],
        },
    })

    args = Namespace(session="aaaa", file=["foo.py", "baz.py"], all_ghosts=False)
    sessions_module.cmd_untrack(args)

    assert _read_files(sessions_module, "aaaa") == ["bar.py"]


def test_cmd_untrack_all_ghosts_removes_only_recognized_overlap(sessions_module):
    """--all-ghosts cleans up files that another *recognized* session also tracks."""
    _seed(sessions_module, {
        "ghost-host": {
            "zellij_session": None,  # legacy session, NOT recognized
            "modified_files": ["legacy-only.py", "shared.py", "real-owner.py"],
        },
        "real-owner-sess": {
            "zellij_session": "claude5",  # recognized
            "modified_files": ["shared.py", "real-owner.py"],
        },
    })

    args = Namespace(session="ghost-host", file=None, all_ghosts=True)
    sessions_module.cmd_untrack(args)

    # Files also tracked by a recognized session → removed.
    # Files unique to the legacy session → retained.
    assert _read_files(sessions_module, "ghost-host") == ["legacy-only.py"]
    # The real owner is untouched.
    assert _read_files(sessions_module, "real-owner-sess") == [
        "shared.py", "real-owner.py",
    ]


def test_cmd_untrack_missing_session_exits_nonzero(sessions_module):
    _seed(sessions_module, {})
    args = Namespace(session="nope", file=["foo.py"], all_ghosts=False)
    with pytest.raises(SystemExit):
        sessions_module.cmd_untrack(args)


def test_cmd_untrack_no_args_exits_nonzero(sessions_module):
    _seed(sessions_module, {
        "aaaa": {"zellij_session": "claude3", "modified_files": ["foo.py"]},
    })
    args = Namespace(session="aaaa", file=None, all_ghosts=False)
    with pytest.raises(SystemExit):
        sessions_module.cmd_untrack(args)


# ---------------------------------------------------------------------------
# Regression: cmd_start populates zellij_session
# ---------------------------------------------------------------------------


def test_cmd_start_captures_zellij_session_name(sessions_module, monkeypatch):
    """The whole fix hinges on cmd_start writing zellij_session into the record."""
    monkeypatch.setenv("ZELLIJ_SESSION_NAME", "claude7")
    _seed(sessions_module, {})

    # Stub out the Linear and Zellij side effects so cmd_start is just a write.
    monkeypatch.setattr(
        sessions_module, "_linear_start_integration", lambda *a, **kw: None
    )

    # cmd_start does a lot — print contexts, lookup tags, etc. We only need
    # it to reach the session_record dict creation. The simplest way is to
    # invoke it with a minimal Namespace and accept whatever it prints.
    args = Namespace(
        mode="bug",
        task="test fixture session",
        tags=None,
        debug=False,
        embed=None,
        logs=None,
        user=None,
        debug_id=None,
        vercel=False,
        run_id=None,
        since_last_deploy=False,
        chat=None,
        issue=None,
        task_id=None,
        linear_issue=None,
    )
    try:
        sessions_module.cmd_start(args)
    except SystemExit:
        pass  # cmd_start may sys.exit at end

    data = json.loads(sessions_module.SESSIONS_FILE.read_text())
    sessions = data.get("sessions", {})
    assert sessions, "cmd_start did not create any session"
    # The single new session must have zellij_session populated
    new_session = next(iter(sessions.values()))
    assert new_session.get("zellij_session") == "claude7"
