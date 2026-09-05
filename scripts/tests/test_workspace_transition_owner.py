"""Workspace lifecycle owner contracts for development tooling.

Synthetic state proves duplicate coalescing and rejection of stale writers.
Existing Git integration fixtures separately cover source preservation.
No live worktree, chat, or deployment is modified by this test file.
See docs/architecture/agent-workflow-decisions.md for the migration contract.
"""

# contract-test-file: tooling
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sessions


def test_duplicate_transition_is_coalesced_and_stale_generation_rejected(
    monkeypatch, tmp_path
):
    data = {"sessions": {"abcd": {"worktree": {"base_commit": "base"}}}}
    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda fn: fn(data))
    monkeypatch.setattr(sessions, "WORKTREE_CHECKPOINT_LOCKS_DIR", tmp_path / "locks")
    calls = []

    def operation():
        calls.append("write")
        return {"status": "ok"}

    def run(generation, key):
        return sessions._run_workspace_transition(
            "abcd", "repair", operation, expected_generation=generation, operation_id=key
        )
    assert run(0, "request-1")["status"] == "ok"
    assert run(0, "request-1")["status"] == "ok"
    assert calls == ["write"]
    with pytest.raises(RuntimeError, match="generation"):
        run(0, "stale-request")
    assert run(1, "request-2")["status"] == "ok"
    assert calls == ["write", "write"]


def test_normal_reads_do_not_enter_lifecycle_or_repair():
    hook = (
        Path(__file__).resolve().parents[2] / ".opencode/plugins/openmates-hooks.js"
    ).read_text()
    assert "await recordWorktreeRouting(" not in hook


def test_actual_session_temporary_path_is_excluded():
    import subprocess

    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", ".claude/sessions.tmp"],
        cwd=root,
        capture_output=True,
    )
    assert result.returncode == 0


def test_two_processes_share_one_transition_result(monkeypatch, tmp_path):
    import json
    import multiprocessing

    state = tmp_path / "sessions.json"
    state.write_text(
        json.dumps({"sessions": {"abcd": {"worktree": {"base_commit": "base"}}}})
    )
    marker = tmp_path / "writes.txt"
    monkeypatch.setattr(sessions, "WORKTREE_CHECKPOINT_LOCKS_DIR", tmp_path / "locks")
    monkeypatch.setattr(
        sessions, "_load_sessions", lambda: json.loads(state.read_text())
    )

    def mutate(fn):
        data = json.loads(state.read_text())
        result = fn(data)
        state.write_text(json.dumps(data))
        return result

    monkeypatch.setattr(sessions, "_mutate_sessions", mutate)
    ctx = multiprocessing.get_context("fork")
    queue = ctx.Queue()

    def worker():
        def operation():
            with marker.open("a") as handle:
                handle.write("write\n")
            return {"status": "ok"}

        queue.put(
            sessions._run_workspace_transition(
                "abcd",
                "repair",
                operation,
                expected_generation=0,
                operation_id="same-request",
            )
        )

    children = [ctx.Process(target=worker) for _ in range(2)]
    for child in children:
        child.start()
    for child in children:
        child.join(10)
        assert child.exitcode == 0
    assert [queue.get(timeout=2) for _ in children] == [
        {"status": "ok"},
        {"status": "ok"},
    ]
    assert marker.read_text() == "write\n"
