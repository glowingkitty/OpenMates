"""Presence inventory stays read-only, scoped, and honest about coverage."""

# contract-test-file: tooling
import json
import socket
import pytest

from scripts import codex_chat_presence as presence


ALPHA = "00000000-0000-0000-0000-000000000001"
BETA = "00000000-0000-0000-0000-000000000002"
GAMMA = "00000000-0000-0000-0000-000000000003"


class RPC:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def call(self, method, params, *, timeout=None):
        self.calls.append((method, params, timeout))
        page = self.pages[len(self.calls) - 1]
        if isinstance(page, Exception):
            raise page
        return page


def row(thread, cwd, status="idle", **extra):
    return {"id": thread, "cwd": str(cwd), "status": {"type": status}, **extra}


def snapshot(path, project, tasks, connection="connected"):
    path.write_text(json.dumps({"schema_version": 1, "project_id": project,
                                "connection": connection, "tasks": tasks}))
    return str(path)


def linked_task(thread, status="in_progress"):
    return {"task_id": "task-1", "title": "Build header", "status": status,
            "external_chat": {"provider": "codex", "id": thread}}


def worktree(root, path, label="peer"):
    metadata = root / ".git/worktrees" / label
    metadata.mkdir(parents=True)
    path.mkdir(parents=True)
    (path / ".git").write_text(f"gitdir: {metadata}")
    (metadata / "commondir").write_text("../..")


# contract-test: tooling
def test_linked_and_unlinked_project_membership_uses_runtime_status(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    a = snapshot(tmp_path / "a.json", "project-a", [linked_task(ALPHA)], "unavailable")
    b = snapshot(tmp_path / "b.json", "project-b", [linked_task(BETA)])
    rpc = RPC([{"data": [row(ALPHA, root, "idle", name="Alpha", preview="secret"),
                         row(BETA, root, "active", name="Beta"),
                         row(GAMMA, root, "notLoaded", preview="private")]}])
    result = presence.collect_once(rpc, root, {"snapshots": [a, b],
                                            "presence_project_id": "project-a"})
    assert result["complete"] and result["connection"] == "connected"
    assert result["threads"][ALPHA]["project_ids"] == ["project-a"]
    assert result["threads"][BETA]["project_ids"] == ["project-b"]
    assert result["threads"][GAMMA]["project_ids"] == ["project-a"]
    assert result["threads"][ALPHA]["status"] == "idle"
    assert result["threads"][ALPHA]["tasks"] == [
        {"project_id": "project-a", "task_id": "task-1", "title": "Build header",
         "status": "in_progress"}]
    assert result["threads"][GAMMA]["title"] == ""
    assert [method for method, _, _ in rpc.calls] == ["thread/list"]
    assert rpc.calls[0][1]["useStateDbOnly"] is True
    assert 0 < rpc.calls[0][2] <= presence.INVENTORY_TIMEOUT


# contract-test: tooling
def test_legacy_single_project_default_and_explicit_override(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    source = snapshot(tmp_path / "single.json", "project-a", [linked_task(ALPHA)])
    rpc = RPC([{"data": [row(ALPHA, root), row(BETA, root), row(GAMMA, root)]}])
    result = presence.collect_once(rpc, root, {"snapshots": [source],
        "thread_projects": {ALPHA: ["project-c"], BETA: []}})
    assert result["threads"][ALPHA]["project_ids"] == ["project-c"]
    assert "tasks" not in result["threads"][ALPHA]
    assert BETA not in result["threads"]
    assert result["threads"][GAMMA]["project_ids"] == ["project-a"]


# contract-test: tooling
def test_cross_project_task_summaries_follow_selected_association(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    a = snapshot(tmp_path / "a.json", "project-a", [linked_task(ALPHA)])
    b = snapshot(tmp_path / "b.json", "project-b", [linked_task(ALPHA, "todo")])
    rpc = RPC([{"data": [row(ALPHA, root, "active")]}])
    result = presence.collect_once(rpc, root, {"snapshots": [a, b],
        "thread_projects": {ALPHA: ["project-b"]}})
    assert result["threads"][ALPHA]["project_ids"] == ["project-b"]
    assert result["threads"][ALPHA]["tasks"] == [{
        "project_id": "project-b", "task_id": "task-1",
        "title": "Build header", "status": "todo"}]


# contract-test: tooling
def test_complete_pagination_clears_absent_old_threads(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    previous = presence.collect_once(RPC([{"data": [row(GAMMA, root, "active")]}]),
                                     root, {"presence_project_id": "project-a"})
    rpc = RPC([{"data": [row(ALPHA, root, "idle")], "nextCursor": "second"},
               {"data": [row(BETA, root, "active")]}])
    result = presence.collect_once(rpc, root, {"presence_project_id": "project-a"}, previous)
    assert result["complete"] and result["connection"] == "connected"
    assert set(result["threads"]) == {ALPHA, BETA}
    assert rpc.calls[1][1]["cursor"] == "second"
    assert all(params["useStateDbOnly"] is True for _, params, _ in rpc.calls)


# contract-test: tooling
def test_inventory_rejects_other_checkout_and_reads_bounded_session_claims(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    checkout = tmp_path / "peer"
    worktree(root, checkout)
    other = tmp_path / "other"
    other.mkdir()
    sessions = root / ".claude/sessions.json"
    sessions.parent.mkdir()
    sessions.write_text(json.dumps({"sessions": {"bound": {
        "codex_task_id": ALPHA, "codex_host": socket.gethostname(),
        "worktree": {"path": str(checkout), "status": "active"},
        "modified_files": ["src/main.py", "../outside", "src/main.py"],
        "writing": "src/current.py"}},
        "edit_leases": {"src/lease.py": {"session_id": "bound"},
                        "src/foreign.py": {"session_id": "other"}}}))
    rpc = RPC([{"data": [row(ALPHA, checkout / "src", "active",
                         forkedFromId=BETA), row(BETA, other, "active")]}])
    result = presence.collect_once(rpc, root, {
        "presence_project_id": "project-a", "thread_projects": {BETA: ["project-a"]}
    })
    assert set(result["threads"]) == {ALPHA}
    assert result["threads"][ALPHA]["files"] == ["src/main.py", "src/current.py", "src/lease.py"]
    assert result["threads"][ALPHA]["parent_id"] == BETA


# contract-test: tooling
def test_canonical_rpc_cwd_uses_latest_valid_bound_worktree_and_claims(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    older = tmp_path / "older"
    current = tmp_path / "current"
    worktree(root, older, "older")
    worktree(root, current, "current")
    sessions = root / ".claude/sessions.json"
    sessions.parent.mkdir()
    # Newer binding appears first to prove selection uses timestamps.
    sessions.write_text(json.dumps({"sessions": {
        "current": {"codex_task_id": ALPHA, "codex_host": socket.gethostname(),
                    "last_active": "2026-10-12T12:00:00Z",
                    "worktree": {"path": str(current), "status": "merged"},
                    "modified_files": ["src/current.py"], "writing": "src/claim.py"},
        "older": {"codex_task_id": ALPHA, "codex_host": socket.gethostname(),
                  "last_active": "2026-10-01T12:00:00Z",
                  "worktree": {"path": str(older), "status": "active"},
                  "modified_files": ["src/old.py"]}},
        "edit_leases": {"src/lease.py": {"session_id": "current"}}}))
    rpc = RPC([{"data": [row(ALPHA, root, "active")]}])
    result = presence.collect_once(rpc, root, {"presence_project_id": "project-a"})
    assert result["threads"][ALPHA]["workspace"] == str(current)
    assert result["threads"][ALPHA]["files"] == [
        "src/current.py", "src/claim.py", "src/lease.py"]


# contract-test: tooling
def test_explicit_rpc_worktree_preserves_its_matching_binding(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    explicit = tmp_path / "explicit"
    newer = tmp_path / "newer"
    worktree(root, explicit, "explicit")
    worktree(root, newer, "newer")
    sessions = root / ".claude/sessions.json"
    sessions.parent.mkdir()
    sessions.write_text(json.dumps({"sessions": {
        "newer": {"codex_task_id": ALPHA, "codex_host": socket.gethostname(),
                  "last_active": "2026-10-12T12:00:00Z",
                  "worktree": {"path": str(newer), "status": "active"},
                  "modified_files": ["newer.py"]},
        "explicit": {"codex_task_id": ALPHA, "codex_host": socket.gethostname(),
                     "last_active": "2026-10-11T12:00:00Z",
                     "worktree": {"path": str(explicit), "status": "active"},
                     "modified_files": ["explicit.py"]}}}))
    rpc = RPC([{"data": [row(ALPHA, explicit / "src", "active")]}])
    result = presence.collect_once(rpc, root, {"presence_project_id": "project-a"})
    assert result["threads"][ALPHA]["workspace"] == str(explicit)
    assert result["threads"][ALPHA]["files"] == ["explicit.py"]


# contract-test: tooling
def test_pagination_truncation_and_repeated_cursor_keep_old_rows_unknown(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    old = presence.collect_once(RPC([{"data": [row(ALPHA, root, "active")]}]), root,
                                {"presence_project_id": "project-a"})
    monkeypatch.setattr(presence, "MAX_PAGES", 2)
    rpc = RPC([{"data": [row(BETA, root, "idle")], "nextCursor": "one"},
               {"data": [], "nextCursor": "two"}])
    result = presence.collect_once(rpc, root, {"presence_project_id": "project-a"}, old)
    assert not result["complete"] and "truncated" in result["reason"]
    assert result["threads"][ALPHA]["status"] == "unknown"
    assert result["threads"][ALPHA]["checked_at"] == old["threads"][ALPHA]["checked_at"]
    assert result["threads"][BETA]["status"] == "idle"
    assert rpc.calls[1][1]["cursor"] == "one"
    repeated = presence.collect_once(RPC([{"data": [], "nextCursor": "x"},
                                           {"data": [], "nextCursor": "x"}]), root,
                                     {"presence_project_id": "project-a"}, old)
    assert not repeated["complete"] and "cursor repeated" in repeated["reason"]


# contract-test: tooling
def test_failure_retains_metadata_as_unknown_and_successful_deletion_clears_it(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    previous = presence.collect_once(RPC([{"data": [row(ALPHA, root, "active", name="Alpha")]}]),
                                     root, {"presence_project_id": "project-a"})
    failed = presence.collect_once(RPC([RuntimeError("private daemon detail")]), root,
                                   {"presence_project_id": "project-a"}, previous)
    assert failed["connection"] == "unavailable" and not failed["complete"]
    assert failed["threads"][ALPHA]["title"] == "Alpha"
    assert failed["threads"][ALPHA]["status"] == "unknown"
    assert "private" not in failed["reason"]
    presence.observe_notification(failed, {"method": "thread/status/changed",
        "params": {"threadId": ALPHA, "status": {"type": "active"}}})
    assert failed["threads"][ALPHA]["status"] == "active"
    presence.observe_notification(failed, {"method": "thread/deleted",
        "params": {"threadId": ALPHA}})
    assert not failed["threads"]
    complete = presence.collect_once(RPC([{"data": []}]), root,
                                     {"presence_project_id": "project-a"}, previous)
    assert complete["complete"] and not complete["threads"]


# contract-test: tooling
def test_missing_snapshot_marks_coverage_incomplete_without_claiming_task_status(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    result = presence.collect_once(RPC([{"data": [row(ALPHA, root, "active")]}]), root,
        {"presence_project_id": "project-a", "snapshots": [str(tmp_path / "missing.json")]})
    assert result["connection"] == "connected" and not result["complete"]
    assert "snapshot unavailable" in result["reason"]
    assert result["threads"][ALPHA]["status"] == "active"


@pytest.mark.parametrize("previous", [None, [], "bad", {"threads": None},
                                      {"threads": []}, {"threads": "bad"}])
# contract-test: tooling
def test_corrupt_previous_presence_is_recovered_without_reusing_it(tmp_path, previous):
    root = tmp_path / "repo"
    root.mkdir()
    failed = presence.collect_once(RPC([RuntimeError("daemon")]), root,
        {"presence_project_id": "project-a"}, previous)
    assert failed["threads"] == {} and not failed["complete"]
    assert presence.unavailable(previous)["threads"] == {}


# contract-test: tooling
def test_corrupt_retained_rows_are_normalized(tmp_path):
    previous = {"threads": {ALPHA: {"project_ids": ["project-a"], "title": "Alpha",
        "status": "active", "files": "wrong", "tasks": [{"title": "no project"}]},
        BETA: "wrong", GAMMA: {"project_ids": "wrong"}}}
    result = presence.unavailable(previous)
    assert set(result["threads"]) == {ALPHA}
    assert result["threads"][ALPHA]["status"] == "unknown"
    assert result["threads"][ALPHA]["files"] == []
    assert "tasks" not in result["threads"][ALPHA]


# contract-test: tooling
def test_inventory_deadline_bounds_all_pages_and_keeps_partial_coverage(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    moment = [0.0]
    monkeypatch.setattr(presence.time, "monotonic", lambda: moment[0])

    class SlowRPC(RPC):
        def call(self, method, params, *, timeout=None):
            result = super().call(method, params, timeout=timeout)
            moment[0] += 3
            return result

    rpc = SlowRPC([{"data": [row(ALPHA, root)], "nextCursor": "two"},
                   {"data": [row(BETA, root)], "nextCursor": "three"}])
    result = presence.collect_once(rpc, root, {"presence_project_id": "project-a"})
    assert result["connection"] == "unavailable" and not result["complete"]
    assert result["reason"] == "Codex inventory deadline exceeded"
    assert set(result["threads"]) == {ALPHA, BETA}
    assert [timeout for _, _, timeout in rpc.calls] == [5.0, 2.0]
