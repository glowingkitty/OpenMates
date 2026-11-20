# contract-test-file: tooling
"""Dev deploy and restart lock while a real test runs on dev (TASK-8552)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import claude_chat_waiters as waiters  # noqa: E402 - scripts/ is the import root for tooling tests
import dev_test_lock as lock  # noqa: E402

CHAT = "4508e325-8a99-4839-ac02-7c5ef40a759c"
OTHER = "39bfb863-0000-4000-8000-000000000000"


@pytest.fixture
def state(tmp_path):
    return tmp_path


def _registered(state: Path) -> dict:
    return waiters._read_json(state / "registered.json")


def test_free_dev_lets_deploy_through(state, monkeypatch):
    monkeypatch.setattr(lock, "state_dir", lambda: state)
    lock.gate("deploy", "7469", CHAT)  # returns: nothing holds dev
    assert _registered(state) == {}


def test_held_lock_stops_deploy_and_registers_a_waiter_for_the_chat(state, monkeypatch, capsys):
    monkeypatch.setattr(lock, "state_dir", lambda: state)
    lock.take("voice-call", "voice_call_web_real_test.py", chat=OTHER, session="c2f1", state=state)
    with pytest.raises(SystemExit) as stop:
        lock.gate("deploy", "7469", CHAT)
    assert stop.value.code == lock.LOCKED_EXIT
    err = capsys.readouterr().err
    assert "deploy waits: nothing was done" in err and "real voice call test" in err
    assert "chat 39bfb863" in err and "session c2f1" in err and "Keep coding" in err
    entry = _registered(state)[lock.WAITER_PREFIX + CHAT[:8]]
    assert entry["chat_id"] == CHAT and entry["kind"] == "handoff" and not entry.get("fired_at")
    assert "deploy --session 7469" in entry["on"]


def test_release_of_the_last_holder_wakes_every_waiting_chat(state, monkeypatch):
    monkeypatch.setattr(lock, "state_dir", lambda: state)
    first = lock.take("real-inference", "a", state=state)
    second = lock.take("ai-test-users", "b", state=state)
    for chat in (CHAT, OTHER):
        with pytest.raises(SystemExit):
            lock.gate("docker restart", "s1", chat)
    assert lock.release(first, state=state) == []  # one test still runs
    assert sorted(lock.release(second, state=state)) == sorted([CHAT, OTHER])
    found = waiters.registered_waiters(state)
    assert {w.chat_id for w in found if w.ready} == {CHAT, OTHER}
    assert all("AI test user run ended" in w.ready_text for w in found)


def test_lock_expires_after_45_minutes_and_the_lifecycle_sweep_wakes_waiters(state, monkeypatch):
    monkeypatch.setattr(lock, "state_dir", lambda: state)
    lock.take("voice-call", state=state, now=1000.0, minutes=600)  # asks for more than the cap
    assert lock.holders(state, now=1000.0 + 44 * 60)
    waiters.add(state, CHAT, "handoff", "dev test lock", key=lock.WAITER_PREFIX + CHAT[:8])
    assert lock.holders(state, now=1000.0 + 45 * 60 + 1) == {}
    ready = [w for w in waiters.registered_waiters(state) if w.ready]
    assert [w.chat_id for w in ready] == [CHAT] and "expired after 45 minutes" in ready[0].ready_text


def test_holder_whose_process_is_gone_no_longer_locks_dev(state):
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    lock.take("real-inference", pid=dead.pid, state=state)
    assert lock.holders(state) == {}
    lock.take("real-inference", pid=os.getpid(), state=state)
    assert len(lock.holders(state)) == 1


def test_other_waiters_are_not_fired(state):
    waiters.add(state, CHAT, "handoff", "another chat's answer", key="answer-1")
    lock.take("real-inference", state=state)
    lock.release(everyone=True, state=state)
    assert not _registered(state)["answer-1"].get("fired_at")


def test_run_holds_the_lock_while_the_command_runs(state, monkeypatch):
    monkeypatch.setattr(lock, "state_dir", lambda: state)
    probe = f"import sys; sys.path.insert(0, {str(Path(lock.__file__).parent)!r}); import dev_test_lock as l; " \
            f"from pathlib import Path; sys.exit(0 if l.holders(Path({str(state)!r})) else 3)"
    assert lock.main(["run", "--kind", "voice-call", "--", sys.executable, "-c", probe]) == 0
    assert lock.holders(state) == {}


def test_status_lists_holder_and_since(state, monkeypatch, capsys):
    monkeypatch.setattr(lock, "state_dir", lambda: state)
    lock.main(["status"])
    assert "Dev is free" in capsys.readouterr().out
    lock.take("ai-test-users", "AI test users run 20261120-170000", chat=OTHER, state=state)
    lock.main(["status"])
    out = capsys.readouterr().out
    assert "AI test user run (AI test users run 20261120-170000, chat 39bfb863) since" in out
    assert "Berlin, expires" in out


def test_unknown_kind_is_refused(state):
    with pytest.raises(ValueError):
        lock.take("unit-tests", state=state)


def test_sessions_docker_restart_does_nothing_while_dev_is_locked(state, monkeypatch, capsys):
    import argparse

    import sessions

    state = Path(os.environ["OPENMATES_CHAT_LIFECYCLE_DIR"])  # sessions.py imports scripts.dev_test_lock
    monkeypatch.setattr(sessions, "_load_sessions", lambda: {"sessions": {}})
    monkeypatch.setattr(sessions, "request_docker_restart", lambda *a: pytest.fail("restart was requested"))
    monkeypatch.setattr(sessions, "available_docker_services", lambda root: {"api"})
    monkeypatch.setattr(sessions, "_docker_checkout_root", lambda sid: state)
    lock.take("voice-call", "voice_call_web_real_test.py", state=state)
    with pytest.raises(SystemExit) as stop:
        sessions.cmd_docker_restart(argparse.Namespace(session="ab12", service=["api"]))
    assert stop.value.code == lock.LOCKED_EXIT
    assert "docker restart waits" in capsys.readouterr().err
