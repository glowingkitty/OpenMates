# contract-test-file: tooling
"""Worktree WIP safety (scripts/worktree_wip.py), the lifecycle's finish wake and the readiness verdict.

Real Git repositories in tmp_path; nothing touches the host's worktrees or chats.
Run: python3 -m pytest scripts/tests/test_worktree_wip.py
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import claude_idle_chats as lc  # noqa: E402  (path set above)
import worktree_wip as wip  # noqa: E402

NOW = 1_800_000_000.0


def git(path: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """One lane worktree whose HEAD is also origin/dev, registered as session s1 of chat c1."""
    path = tmp_path / "agent-s1"
    path.mkdir()
    git(path, "init", "-q", "-b", "dev")
    git(path, "config", "user.email", "test@example.org")
    git(path, "config", "user.name", "Test")
    (path / ".gitignore").write_text("ignored.log\n")
    (path / "app.py").write_text("print('v1')\n")
    git(path, "add", ".gitignore", "app.py")
    git(path, "commit", "-q", "-m", "base")
    git(path, "update-ref", "refs/remotes/origin/dev", "HEAD")
    sessions = tmp_path / "sessions.json"
    sessions.write_text(json.dumps({"sessions": {"s1": {
        "agent_task_id": "c1", "task": "Fix the thing", "worktree": {"path": str(path)}}}}))
    monkeypatch.setenv("OPENMATES_SESSIONS_FILE", str(sessions))
    monkeypatch.setenv("OPENMATES_WORKTREE_WIP_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / "claude"))
    monkeypatch.delenv("OPENMATES_WIP_REMOTE", raising=False)
    return path


def row(path: Path) -> dict:
    return {"session_id": "s1", "chat_id": "c1", "task": "Fix the thing", "path": str(path)}


def test_snapshot_commits_tracked_and_untracked_work_without_touching_the_worktree(repo):
    (repo / "app.py").write_text("print('v2')\n")
    (repo / "new.py").write_text("x = 1\n")
    (repo / "ignored.log").write_text("noise\n")
    head, status = git(repo, "rev-parse", "HEAD"), git(repo, "status", "--porcelain")

    saved = wip.snapshot(row(repo), "turn-end")

    assert saved["state"] == "saved" and saved["ref"] == "refs/openmates/wip/s1"
    assert git(repo, "show", "refs/openmates/wip/s1:app.py") == "print('v2')"
    assert git(repo, "show", "refs/openmates/wip/s1:new.py") == "x = 1"
    assert "ignored.log" not in git(repo, "ls-tree", "--name-only", "refs/openmates/wip/s1")
    assert git(repo, "rev-parse", "HEAD") == head and git(repo, "status", "--porcelain") == status
    assert wip.snapshot(row(repo), "turn-end")["state"] == "unchanged"
    (repo / "new.py").write_text("x = 2\n")
    again = wip.snapshot(row(repo), "turn-end")
    assert again["state"] == "saved"
    assert git(repo, "rev-parse", "refs/openmates/wip/s1^2") == saved["commit"]  # history kept


def test_clean_worktree_gets_no_snapshot(repo):
    assert wip.snapshot(row(repo), "turn-end")["state"] == "clean"
    assert subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", "refs/openmates/wip/s1"],
                          capture_output=True).returncode != 0


def test_unfinished_ignores_files_already_on_dev_and_generated_outputs(repo):
    (repo / "specifications" / "generated").mkdir(parents=True)
    (repo / "specifications" / "generated" / "registry.yml").write_text("x\n")
    (repo / "landed.py").write_text("same\n")
    git(repo, "add", "landed.py")
    git(repo, "commit", "-q", "-m", "landed elsewhere")
    git(repo, "update-ref", "refs/remotes/origin/dev", "HEAD")
    git(repo, "reset", "-q", "--soft", "HEAD~1")  # the lane still holds the file uncommitted
    assert wip.unfinished_files(repo) == []
    (repo / "app.py").write_text("print('unfinished')\n")
    assert wip.unfinished_files(repo) == ["app.py"]
    assert [entry["session_id"] for entry in wip.unfinished()] == ["s1"]


def test_park_holds_until_the_worktree_changes(repo):
    (repo / "app.py").write_text("print('waits for an answer')\n")
    wip.park("s1", "waits on the owner's answers to 8 questions")
    assert wip.unfinished()[0]["parked"]["reason"].startswith("waits on the owner")
    (repo / "app.py").write_text("print('changed after parking')\n")
    assert wip.unfinished()[0]["parked"] is None


def test_push_refuses_the_public_origin(repo, monkeypatch):
    git(repo, "remote", "add", "origin", "https://github.com/example/public.git")
    git(repo, "remote", "add", "mirror", "git@github.com:example/public.git")
    monkeypatch.setenv("OPENMATES_WIP_REMOTE", "mirror")
    (repo / "app.py").write_text("print('secret wip')\n")
    assert wip.snapshot(row(repo), "turn-end")["pushed"].startswith("refused")


def test_push_reaches_a_private_remote(repo, tmp_path, monkeypatch):
    private = tmp_path / "private.git"
    subprocess.run(["git", "init", "-q", "--bare", str(private)], check=True)
    monkeypatch.setenv("OPENMATES_WIP_REMOTE", str(private))
    (repo / "app.py").write_text("print('wip')\n")
    saved = wip.snapshot(row(repo), "turn-end")
    assert saved["pushed"] == "pushed"
    assert git(private, "rev-parse", "refs/openmates/wip/s1") == saved["commit"]


def status_with(*entries: dict) -> dict:
    return {"unfinished": [{"session_id": "s1", "chat_id": "c1", "task": "Fix", "worktree": "agent-s1", "files": 3,
                            "sample": ["app.py"], "parked": None, "error": "", "snapshot": {"tree": "t1"},
                            **entry} for entry in entries]}


def test_worktree_recovery_retries_a_stopped_owner_every_half_hour():
    marks, calls = {}, []

    def launch(chat_id, prompt):
        calls.append((chat_id, prompt))
        return "ok"

    status = status_with({"parked": {"reason": "waiting for the CI worker"}})
    def run(now):
        return wip.periodic_owners(status, set(), set(), set(), now, marks, launch, lambda _: True)

    assert run(1000)[0]["state"] == "resumed"
    assert "session s1 (agent-s1: 3 files not on dev" in calls[0][1]
    assert run(2799)[0]["state"] == "retry due"
    assert run(2800)[0]["state"] == "resumed"
    assert len(calls) == 2


@pytest.mark.parametrize(("running", "protected", "held", "history", "reason"), [
    ({"c1"}, set(), set(), True, "the owning chat is open"),
    (set(), {"c1"}, set(), True, "waiting for Marco"),
    (set(), set(), {"c1"}, True, "parked or withdrawn by Marco"),
    (set(), set(), set(), False, "the chat history is unavailable"),
])
def test_recovery_leaves_protected_and_running_owners_alone(running, protected, held, history, reason):
    outcome = wip.periodic_owners(status_with({}), running, protected, held, 1000, {},
                                 lambda *_: pytest.fail("unexpected wake"), lambda _: history)
    assert outcome[0]["note"] == reason


def test_briefing_lists_unfinished_and_parked_work(tmp_path):
    report = tmp_path / "readiness.json"
    report.write_text(json.dumps({"at": "2026-11-15T02:30:00Z", "readiness": {"ready": False, "blocking": ["s1"]},
                                  **status_with({}, {"session_id": "s2", "parked": {"reason": "owner answers"}}),
                                  "wakes": [{"chat_id": "c1", "state": "resumed"}]}))
    lines = wip.briefing_lines(report)
    assert "NOT ready; 1 blocking worktrees, 1 with unfinished work, 1 parked" in lines[0]
    assert any("`s1`" in line and "resumed" in line for line in lines)
    assert any("`s2`" in line and ("owner answers" in line or "resumed" in line) for line in lines)


# --- the chat lifecycle's finish wake (claude_idle_chats.guard_unfinished) ---------------------------

def pane_chat(**overrides) -> lc.Chat:
    values = dict(pid=1, session_id="c1", name="openmates-aa", status="idle", kind="pane",
                  last_activity=NOW - 7200, last_speaker="assistant", last_text="Done for now.")
    values.update(overrides)
    return lc.Chat(**values)


@pytest.fixture()
def dirty(repo):
    (repo / "app.py").write_text("print('unfinished')\n")
    return repo


def test_lifecycle_wakes_a_pane_chat_with_unfinished_work_once_then_stops_it_after_the_grace(dirty, tmp_path,
                                                                                            monkeypatch):
    woken = []
    monkeypatch.setattr(lc, "wake", lambda chat, text="": woken.append(text) or True)
    monkeypatch.setattr(lc, "log_event", lambda *_args: None)
    plan = [(pane_chat(), lc.Decision("stop", "idle 120 min"))]
    state = tmp_path / "lifecycle"

    kept, flagged = lc.guard_unfinished(plan, state, NOW, pressure=False, dry_run=False)
    assert kept == [] and flagged == [] and "Done means committed, tested and deployed" in woken[0]
    assert git(dirty, "show", "refs/openmates/wip/s1:app.py") == "print('unfinished')"

    kept, _ = lc.guard_unfinished(plan, state, NOW + 30 * 60, pressure=False, dry_run=False)
    assert kept == [] and len(woken) == 1  # within the grace: kept, not woken again

    kept, flagged = lc.guard_unfinished(plan, state, NOW + 61 * 60, pressure=False, dry_run=False)
    assert [chat.session_id for chat, _ in kept] == ["c1"]
    assert flagged[0]["why"] == "no reply within the grace period" and flagged[0]["worktree"] == "s1"
    assert "unfinished work snapshotted" in kept[0][1].reason


@pytest.mark.parametrize(("overrides", "pressure", "why"), [
    ({"kind": "rc_worker"}, False, "cannot be woken here (no zellij pane)"),
    ({}, True, "host short on memory"),
])
def test_lifecycle_snapshots_and_flags_when_it_cannot_wait(dirty, tmp_path, monkeypatch, overrides, pressure, why):
    monkeypatch.setattr(lc, "wake", lambda *_args: pytest.fail("must not wake"))
    monkeypatch.setattr(lc, "log_event", lambda *_args: None)
    kept, flagged = lc.guard_unfinished([(pane_chat(**overrides), lc.Decision("stop", "idle"))], tmp_path / "lc",
                                        NOW, pressure=pressure, dry_run=False)
    assert len(kept) == 1 and flagged[0]["why"] == why
    assert flagged[0]["wip_ref"] == "refs/openmates/wip/s1"


def test_lifecycle_stops_chats_without_unfinished_work_unchanged(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(lc, "wake", lambda *_args: pytest.fail("must not wake"))
    plan = [(pane_chat(), lc.Decision("stop", "idle")), (pane_chat(session_id="other"), lc.Decision("done", "idle"))]
    assert lc.guard_unfinished(plan, tmp_path / "lc", NOW, pressure=False, dry_run=False) == (plan, [])


def test_stopped_chat_with_unfinished_work_is_listed_as_stalled():
    registry = {"c1": {"state": "stopped", "title": "Fix", "kind": "pane", "last_activity": "2026-11-15T01:00:00Z",
                       "resume": "claude --resume c1"}}
    stalled = lc.unfinished_stalled(registry, status_with({}, {"session_id": "s2", "chat_id": "c2"}))
    assert [entry["unfinished_session"] for entry in stalled] == ["s1"]
    assert "stopped with unfinished work in session s1 (3 files not on dev" in stalled[0]["reason"]


# --- the release-readiness verdict (sessions._readiness_verdict) -------------------------------------

def load_sessions():
    import importlib.util

    spec = importlib.util.spec_from_file_location("sessions_for_wip_test",
                                                  Path(__file__).resolve().parents[1] / "sessions.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_readiness_blocks_only_on_unfinished_unparked_work(repo):
    sessions = load_sessions()
    item = {"session_id": "s1", "path": str(repo), "classification": "unique_stale", "reason_code": "unique_changes"}
    assert sessions._readiness_verdict({**item, "classification": "integrated"}) == "ok"
    assert sessions._readiness_verdict(item) == "ok"  # clean: nothing unfinished
    (repo / "app.py").write_text("print('unfinished')\n")
    assert sessions._readiness_verdict(item) == "blocking"
    wip.park("s1", "waits on the owner")
    assert sessions._readiness_verdict(item) == "parked"
    residue = {"session_id": "integration-s1", "classification": "unique_stale", "reason_code": "integration_has_changes"}
    assert sessions._readiness_verdict({**residue, "idle_hours": 3}) == "ok"
    assert sessions._readiness_verdict({**residue, "idle_hours": 0.5}) == "blocking"
    assert sessions._readiness_verdict({"session_id": "x", "classification": "orphaned_git_metadata"}) == "blocking"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", *os.environ.get("PYTEST_ARGS", "").split()]))
