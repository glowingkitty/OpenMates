"""Regression coverage for compact outputs, exact identity and bounded waits."""
# contract-test-file: tooling
import copy
import json
import multiprocessing
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import sessions
from scripts.ci_coordinator import print_receipt, wait_for_job
from scripts.deploy_admission import admission_lock
from scripts.deployment_wait import wait_deploy
from scripts.session_binding import resolve_session


def test_session_binding_is_exact_host_scoped_and_never_falls_back_on_wrong_task(tmp_path):
    state = {"sessions": {"one": {"codex_task_id": "thread", "codex_host": "host",
                                  "worktree": {"path": str(tmp_path)}},
                          "two": {"codex_task_id": "thread", "codex_host": "other"}}}
    assert resolve_session(state, thread_id="thread", host="host") == "one"
    assert resolve_session(state, cwd=tmp_path) == "one"
    with pytest.raises(RuntimeError, match="No session"):
        resolve_session(state, thread_id="wrong", host="host", cwd=tmp_path)
    assert resolve_session(state, session_id="two") == "two"
    state["sessions"]["duplicate"] = copy.deepcopy(state["sessions"]["one"])
    with pytest.raises(RuntimeError, match="Ambiguous"):
        resolve_session(state, thread_id="thread", host="host")


def test_status_json_is_scoped_and_does_not_write_or_prune(monkeypatch, capsys, tmp_path):
    state = {"sessions": {"one": {"task": "mine", "worktree": {"path": str(tmp_path)}},
                          "two": {"task": "unrelated-private-title"}}, "locks": {}, "edit_leases": {}}
    before = copy.deepcopy(state)
    monkeypatch.setattr(sessions, "_load_sessions", lambda: state)
    def forbidden(*args, **kwargs):
        raise AssertionError("status must remain read-only")
    monkeypatch.setattr(sessions, "_save_sessions", forbidden)
    monkeypatch.setattr(sessions, "_prune_stale", forbidden)
    sessions.cmd_status(SimpleNamespace(session="one", all=False, json=True))
    result = json.loads(capsys.readouterr().out)
    assert list(result["sessions"]) == ["one"]
    assert state == before


class Clock:
    now = 0
    def __call__(self):
        return self.now
    def sleep(self, seconds):
        self.now += seconds


def test_ci_wait_uses_cached_status_and_stops_on_terminal_or_attention():
    for terminal in ("success", "failure", "cancelled", "attention"):
        states = iter(["queued", "running", terminal])
        clock = Clock()
        queue = SimpleNamespace(status=lambda key: [{"id": key, "state": next(states)}])
        assert wait_for_job(queue, "job", clock=clock, sleep=clock.sleep)["state"] == terminal


def test_ci_wait_timeout_is_not_success_and_invalid_job_fails():
    clock = Clock()
    queue = SimpleNamespace(status=lambda key: [{"id": key, "state": "queued"}])
    result = wait_for_job(queue, "job", timeout=3, poll=2, clock=clock, sleep=clock.sleep)
    assert result["state"] == "timeout" and result["last_state"] == "queued"
    assert clock.now == 3
    with pytest.raises(ValueError, match="Unknown"):
        wait_for_job(SimpleNamespace(status=lambda key: []), "missing")


def test_ci_text_omits_large_inputs_json_preserves_them(capsys):
    row = {"id": "job", "state": "running", "specs": "large input" * 1000}
    print_receipt(row)
    assert len(capsys.readouterr().out) < 100
    print_receipt(row, as_json=True)
    assert json.loads(capsys.readouterr().out) == row


def test_deploy_wait_ignores_unrelated_status_and_uses_latest_per_context(tmp_path):
    clock = Clock()
    reads = iter([{"statuses": [{"context": "tests", "state": "success"}]},
                  {"statuses": [{"context": "Vercel", "state": "success", "target_url": "https://example.test"},
                                {"context": "Vercel", "state": "failure"}]}])
    result = wait_deploy(tmp_path, "a" * 40, read=lambda: next(reads), clock=clock, sleep=clock.sleep)
    assert result["state"] == "success"
    assert clock.now > 0 and result["commit"] == "a" * 40


def test_deploy_wait_timeout_and_invalid_commit(tmp_path):
    clock = Clock()
    result = wait_deploy(tmp_path, "a" * 40, timeout=3, poll=2, read=lambda: {"statuses": []}, clock=clock, sleep=clock.sleep)
    assert result["state"] == "timeout" and clock.now == 3
    with pytest.raises(ValueError, match="40-character"):
        wait_deploy(tmp_path, "latest")


def _try_admission(path, results):
    try:
        with admission_lock(Path(path), timeout=0.1, poll=0.01):
            results.put("acquired")
    except RuntimeError:
        results.put("timeout")


def test_deploy_admission_serializes_processes_and_releases_after_error(tmp_path):
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    path = tmp_path / "admission.lock"
    with pytest.raises(ValueError):
        with admission_lock(path):
            worker = context.Process(target=_try_admission, args=(str(path), queue))
            worker.start()
            worker.join(10)
            assert worker.exitcode == 0
            assert queue.get(timeout=1) == "timeout"
            raise ValueError("preparation failed")
    with admission_lock(path, timeout=0.1):
        pass


def test_routine_feature_does_not_require_video_but_explicit_scope_does():
    files = ["frontend/packages/ui/src/components/Test.svelte"]
    assert not sessions._requires_proof_video({"mode": "feature"}, files)
    assert sessions._requires_proof_video({"proof_video_required": True}, files)


def test_start_reuses_workspace_with_short_text_and_explicit_json(monkeypatch, capsys, tmp_path):
    data = {"sessions": {"one": {"task": "Existing", "worktree": {"path": str(tmp_path)}}}}
    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    monkeypatch.setattr(sessions, "_resolve_repo_id", lambda value: "openmates")
    monkeypatch.setattr(sessions, "_repo_metadata", lambda value: {"repo_id": value, "repo_kind": "control_plane"})
    monkeypatch.setattr(sessions, "_validate_session_repo", lambda repo: None)
    monkeypatch.setattr(sessions, "_codex_task_identity", lambda: "")
    monkeypatch.setattr(sessions, "_resolve_session_id", lambda state: "one")
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "ensure_session_worktree", lambda sid: data["sessions"][sid]["worktree"])
    monkeypatch.setattr(sessions, "_session_checkout_root", lambda record: tmp_path)
    args = SimpleNamespace(mode="feature", task="Existing", full=False, json=False)
    sessions.cmd_start(args)
    assert len(capsys.readouterr().out.splitlines()) == 3
    args.json = True
    sessions.cmd_start(args)
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["session_id"] == "one" and receipt["created"] is False
    assert receipt["workspace"] == str(tmp_path)
    assert list(data["sessions"]) == ["one"]


def test_long_diagnostics_keep_complete_evidence(tmp_path):
    from scripts.agent_output import diagnostic
    original = "first error\n" + "detail " * 2000 + "\nlast error"
    shown = diagnostic(original, tmp_path)
    assert len(shown) < 4500
    assert "first error" in shown and "last error" in shown
    retained = list(tmp_path.glob("*.log"))
    assert len(retained) == 1 and retained[0].read_text() == original
    assert retained[0].stat().st_mode & 0o777 == 0o600


def test_task_binding_is_scoped_to_repository():
    state = {"sessions": {"one": {"codex_task_id": "thread", "codex_host": "host", "repo_id": "openmates"},
                          "two": {"codex_task_id": "thread", "codex_host": "host", "repo_id": "openmatescloud"}}}
    assert resolve_session(state, thread_id="thread", host="host", repo_id="openmates") == "one"
    assert resolve_session(state, thread_id="thread", host="host", repo_id="openmatescloud") == "two"
