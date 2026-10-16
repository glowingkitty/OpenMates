"""Task event routing contracts using isolated snapshots and a synthetic daemon.

No live thread or account is created. Lost acceptance must never become a second
start, and routine Task activity must never become a coordinator wakeup.
Real app-server behavior remains an explicit opt-in runtime pilot gate.
"""

import json
import io
import pytest
from scripts import codex_task_adapter as adapter
from scripts import codex_orchestration as legacy
from scripts.ci_coordinator import Queue

OWNER = "00000000-0000-0000-0000-000000000001"
PARENT = "00000000-0000-0000-0000-000000000002"


def ci_fixture(root):
    """Use the existing queue and the receipt shape written by ci_results.fetch."""
    sessions = root / ".claude/sessions.json"
    sessions.parent.mkdir()
    sessions.write_text(
        json.dumps(
            {
                "sessions": {
                    "worker": {
                        "codex_host": adapter.socket.gethostname(),
                        "codex_task_id": OWNER,
                    },
                    "other-device": {
                        "codex_host": "other-host.invalid",
                        "codex_task_id": OWNER,
                    },
                    "unregistered": {
                        "codex_host": adapter.socket.gethostname(),
                        "codex_task_id": PARENT,
                    },
                }
            }
        )
    )
    coordinator = Queue(root / "logs/ci-coordinator/queue.sqlite3")
    jobs = []
    for owner in ("worker", "other-device", "unregistered"):
        job = coordinator.enqueue(
            owner, "a" * 40, ["tasks-flow.spec.ts"], proof_profile="web-phone"
        )
        with coordinator.connect() as db:
            db.execute(
                "UPDATE jobs SET state='success', run_id=123 WHERE id=?", (job["id"],)
            )
        jobs.append(job)
    receipt = {
        "id": jobs[0]["id"],
        "source_commit": "a" * 40,
        "run_id": 123,
        "state": "success",
        "harness_commit": "b" * 40,
        "report": {
            "source_commit": "a" * 40,
            "run_id": 123,
            "harness_commit": "b" * 40,
            "proof_profile": "web-phone",
        },
    }
    path = root / "test-results/ci-runs" / jobs[0]["id"] / "receipt.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(receipt))
    return path, receipt


# contract-test: tooling
def test_ci_receipt_uses_nested_profile_and_routes_once_only_to_registered_local_owner(
    tmp_path,
):
    ci_fixture(tmp_path)
    state = adapter.empty_state()
    adapter.observe_ci(tmp_path, {"activated_at": 0}, state, {OWNER})
    adapter.observe_ci(tmp_path, {"activated_at": 0}, state, {OWNER})
    assert len(state["deliveries"]) == 1
    event = next(iter(state["deliveries"].values()))
    assert event["owner"] == OWNER
    assert event["kind"] == "ci_result"
    assert event["data"]["receipt_state"] == "available"
    assert event["data"]["harness_commit"] == "b" * 40


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_commit", "c" * 40),
        ("run_id", 124),
        ("harness_commit", "c" * 40),
        ("proof_profile", "web-laptop"),
    ],
)
# contract-test: tooling
def test_ci_rejects_mismatched_nested_proof_identity(tmp_path, field, value):
    path, receipt = ci_fixture(tmp_path)
    receipt["report"][field] = value
    path.write_text(json.dumps(receipt))
    state = adapter.empty_state()
    adapter.observe_ci(tmp_path, {"activated_at": 0}, state, {OWNER})
    event = next(iter(state["deliveries"].values()))
    assert event["data"]["receipt_state"].startswith("identity_mismatch")
    assert "receipt" not in event["data"]


def task(status="blocked", version=1):
    return {
        "task_id": "task",
        "title": "Header",
        "status": status,
        "version": version,
        "blocked_reason_code": "external_dependency" if status == "blocked" else None,
        "blocked_reason": "",
        "external_chat": {"provider": "codex", "id": OWNER},
        "scope": ["api", "account", "personal"],
        "dependencies": [{"target_kind": "task", "target_status": "done"}],
    }


class RPC:
    def __init__(self, active=False, lost=False):
        self.calls = []
        self.active = active
        self.lost = lost

    def call(self, method, params):
        self.calls.append((method, params))
        if method == "thread/read":
            return {"thread": {"status": {"type": "active" if self.active else "idle"}}}
        if method == "thread/items/list":
            return {"data": [], "nextCursor": None}
        if self.lost:
            raise TimeoutError("response lost")
        return {"turn": {"id": "accepted-turn"}}


def ready_state():
    state = adapter.empty_state()
    adapter.observe_tasks(state, {"key": task()}, {OWNER})
    tasks = {"key": task("todo", 2)}
    adapter.observe_tasks(state, tasks, {OWNER})
    return state, tasks


# contract-test: tooling
def test_routine_activity_is_silent_and_ready_event_is_owner_bound_and_deduplicated():
    state, tasks = ready_state()
    adapter.observe_tasks(state, tasks, {OWNER})
    assert len(state["deliveries"]) == 1
    event = next(iter(state["deliveries"].values()))
    assert event["owner"] == OWNER and event["kind"] == "dependency_ready"
    tasks["key"]["latest_activity"] = "still reviewing"
    adapter.observe_tasks(state, tasks, {OWNER})
    assert len(state["deliveries"]) == 1


# contract-test: tooling
def test_active_or_paused_worker_does_not_start_another_turn():
    state, tasks = ready_state()
    rpc = RPC(active=True)
    adapter.deliver(state, rpc, {OWNER}, True, lambda: None, tasks)
    assert [method for method, _ in rpc.calls] == ["thread/read"]
    state["threads"][OWNER]["paused"] = True
    rpc.calls.clear()
    adapter.deliver(state, rpc, {OWNER}, True, lambda: None, tasks)
    assert rpc.calls == []


# contract-test: tooling
def test_lost_start_response_is_reconciled_without_retrying_start():
    state, tasks = ready_state()
    rpc = RPC(lost=True)
    saved = []
    with pytest.raises(TimeoutError):
        adapter.deliver(
            state,
            rpc,
            {OWNER},
            True,
            lambda: saved.append(json.loads(json.dumps(state))),
            tasks,
        )
    assert next(iter(saved[-1]["deliveries"].values()))["state"] == "uncertain"
    adapter.deliver(state, rpc, {OWNER}, True, lambda: None, tasks)
    assert len([m for m, _ in rpc.calls if m == "turn/start"]) == 1
    assert next(iter(state["deliveries"].values()))["state"] == "needs_review"


# contract-test: tooling
def test_superseded_ownership_or_status_cannot_resume_old_work():
    state, tasks = ready_state()
    tasks["key"]["status"] = "done"
    rpc = RPC()
    adapter.deliver(state, rpc, {OWNER}, True, lambda: None, tasks)
    assert rpc.calls == []
    assert next(iter(state["deliveries"].values()))["state"] == "superseded"


# contract-test: tooling
def test_parent_only_receives_completed_work_not_each_worker_turn():
    state = adapter.empty_state()
    message = {
        "method": "turn/completed",
        "params": {"threadId": OWNER, "turn": {"id": "turn", "status": "completed"}},
    }
    adapter.observe_notification(
        state, message, {OWNER, PARENT}, {OWNER: PARENT}, {"key": task("in_progress")}
    )
    assert not state["deliveries"]
    adapter.observe_notification(
        state, message, {OWNER, PARENT}, {OWNER: PARENT}, {"key": task("done")}
    )
    assert next(iter(state["deliveries"].values()))["owner"] == PARENT


# contract-test: tooling
def test_only_confirmed_delete_of_registered_chat_enqueues_unlink():
    state = adapter.empty_state()
    adapter.observe_tasks(state, {"key": task()}, {OWNER})
    for method in ["thread/archived", "thread/unloaded", "thread/status/changed"]:
        adapter.observe_notification(
            state, {"method": method, "params": {"threadId": OWNER}}, {OWNER}, {}, {}
        )
    assert not state["deliveries"]
    adapter.observe_notification(
        state,
        {"method": "thread/deleted", "params": {"threadId": PARENT}},
        {OWNER},
        {},
        {},
    )
    assert not state["deliveries"]
    adapter.observe_notification(
        state,
        {"method": "thread/deleted", "params": {"threadId": OWNER}},
        {OWNER},
        {},
        {},
    )
    assert next(iter(state["deliveries"].values()))["kind"] == "chat_deleted"
    assert state["threads"][OWNER]["paused"]


# contract-test: tooling
def test_migrated_old_observer_cannot_read_or_start_threads(tmp_path):
    path = tmp_path / "state.json"
    with legacy.transaction(path) as state:
        state.update(enabled=True, adapter_mode="task_cache", coordinator=PARENT)
    rpc = RPC()
    legacy.observe_tick(path, rpc)
    legacy.deliver(path, rpc)
    assert rpc.calls == []


# contract-test: tooling
def test_all_chat_context_does_not_let_another_device_execute_the_same_task(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(adapter.socket, "gethostname", lambda: "dev-server")
    path = tmp_path / ".claude/sessions.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps(
            {
                "sessions": {
                    "local": {
                        "codex_task_id": OWNER,
                        "codex_host": "dev-server",
                        "worktree": {
                            "path": str(tmp_path / "worker"),
                            "status": "active",
                        },
                    },
                    "remote": {
                        "codex_task_id": PARENT,
                        "codex_host": "laptop",
                        "worktree": {
                            "path": str(tmp_path / "other"),
                            "status": "active",
                        },
                    },
                }
            }
        )
    )
    assert adapter.execution_threads(tmp_path, {"all_threads": True}) == {OWNER}
    assert adapter.execution_threads(tmp_path, {}) == set()


# contract-test: tooling
def test_parent_completion_survives_task_sync_arriving_after_turn_event():
    state = adapter.empty_state()
    message = {
        "method": "turn/completed",
        "params": {"threadId": OWNER, "turn": {"id": "turn", "status": "completed"}},
    }
    adapter.observe_notification(
        state, message, {OWNER, PARENT}, {OWNER: PARENT}, {"key": task("in_progress")}
    )
    assert not state["deliveries"]
    tasks = {"key": task("done", 2)}
    adapter.observe_worker_completion(state, {OWNER: PARENT}, tasks, {OWNER, PARENT})
    assert len(state["deliveries"]) == 1
    tasks["key"]["title"] = "Minor title edit"
    tasks["key"]["version"] = 3
    adapter.observe_worker_completion(state, {OWNER: PARENT}, tasks, {OWNER, PARENT})
    assert len(state["deliveries"]) == 1


# contract-test: tooling
def test_subscription_batches_metadata_and_recovers_interruption_without_inference():
    class ResumeRPC:
        def __init__(self):
            self.calls = []

        def call(self, method, params):
            self.calls.append((method, params))
            return {
                "thread": {"status": {"type": "idle"}},
                "initialTurnsPage": {
                    "data": [
                        {"id": "turn", "status": "interrupted", "completedAt": 100}
                    ]
                },
            }

    rpc = ResumeRPC()
    state = adapter.empty_state()
    adapter.subscribe_thread(rpc, state, OWNER)
    assert [method for method, _ in rpc.calls] == ["thread/resume"]
    assert rpc.calls[0][1]["excludeTurns"] is True
    assert rpc.calls[0][1]["initialTurnsPage"]["itemsView"] == "notLoaded"
    assert state["threads"][OWNER]["paused"]


# contract-test: tooling
def test_new_active_turn_cannot_reuse_previous_completion_to_wake_parent():
    state = adapter.empty_state()
    adapter.observe_notification(
        state,
        {
            "method": "turn/completed",
            "params": {"threadId": OWNER, "turn": {"id": "old", "status": "completed"}},
        },
        {OWNER, PARENT},
        {OWNER: PARENT},
        {"key": task("in_progress")},
    )
    adapter.observe_notification(
        state,
        {
            "method": "thread/status/changed",
            "params": {"threadId": OWNER, "status": {"type": "active"}},
        },
        {OWNER, PARENT},
        {OWNER: PARENT},
        {},
    )
    adapter.observe_worker_completion(
        state, {OWNER: PARENT}, {"key": task("done", 2)}, {OWNER, PARENT}
    )
    assert not state["deliveries"]


# contract-test: tooling
def test_title_edit_does_not_discard_still_ready_dependency():
    state, tasks = ready_state()
    tasks["key"]["version"] += 1
    tasks["key"]["title"] = "Clearer title"
    rpc = RPC()
    adapter.deliver(state, rpc, {OWNER}, True, lambda: None, tasks)
    assert len([method for method, _ in rpc.calls if method == "turn/start"]) == 1


# contract-test: tooling
def test_native_codex_worktree_is_recognized_by_repository_metadata(tmp_path):
    root = tmp_path / "repository"
    checkout = tmp_path / "codex-worktrees" / "native"
    metadata = root / ".git/worktrees/native"
    metadata.mkdir(parents=True)
    checkout.mkdir(parents=True)
    (checkout / ".git").write_text("gitdir: " + str(metadata))
    (metadata / "commondir").write_text("../..")
    assert adapter.repository_checkout(root, str(checkout))
    (metadata / "commondir").write_text(str(tmp_path / "unrelated/.git"))
    assert not adapter.repository_checkout(root, str(checkout))
    assert not adapter.repository_checkout(root, str(tmp_path / "unknown"))


# contract-test: tooling
def test_visible_peer_presence_does_not_grant_event_delivery_or_wake(tmp_path):
    state, tasks = ready_state()
    state["presence"] = {
        "schema_version": 1,
        "connection": "connected",
        "complete": True,
        "threads": {PARENT: {"project_ids": ["project"], "status": "idle"}},
    }
    rpc = RPC()
    adapter.deliver(state, rpc, {OWNER}, True, lambda: None, tasks)
    assert [method for method, _ in rpc.calls] == ["thread/read", "turn/start"]
    assert all(params.get("threadId") != PARENT for _, params in rpc.calls)
    adapter.observe_notification(state, {"method": "thread/status/changed",
        "params": {"threadId": PARENT, "status": {"type": "active"}}},
        {OWNER}, {}, tasks)
    assert PARENT not in state["threads"]


@pytest.mark.parametrize("cause", ["eof", "disabled"])
# contract-test: tooling
def test_clean_shutdown_marks_presence_unavailable_and_preserves_deliveries(
    tmp_path, monkeypatch, cause
):
    root = tmp_path / "repository"
    root.mkdir()
    monkeypatch.setattr(adapter, "state_root", lambda: tmp_path)
    state_path = adapter.adapter_path(root)
    state_path.parent.mkdir(parents=True)
    original = adapter.empty_state()
    original["presence"] = {"schema_version": 1, "threads": {OWNER: {
        "project_ids": ["project"], "title": "Peer", "status": "active",
        "workspace": str(root), "files": [], "parent_id": None,
        "checked_at": "2026-01-01T00:00:00+00:00"}}}
    original["deliveries"]["pending-id"] = {"owner": OWNER, "state": "pending"}
    state_path.write_text(json.dumps(original))
    monkeypatch.setattr(adapter.sys, "stdin", io.StringIO(""))
    monkeypatch.setattr(adapter.select, "select", lambda *_: (
        [adapter.sys.stdin] if cause == "eof" else [], [], []
    ))
    if cause == "disabled":
        (tmp_path / "codex-adapter.json").write_text(json.dumps({
            "repositories": {str(root): {"enabled": False}}
        }))
    adapter.run(root, {})
    saved = json.loads(state_path.read_text())
    assert saved["presence"]["connection"] == "unavailable"
    assert saved["presence"]["threads"][OWNER]["status"] == "unknown"
    assert saved["connection"]["state"] == "stopped"
    assert saved["deliveries"] == original["deliveries"]


# contract-test: tooling
def test_inventory_deadline_reconnects_before_task_delivery(monkeypatch, tmp_path):
    class RPCConnection:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    old = RPCConnection()
    replacement = RPCConnection()
    monkeypatch.setattr(adapter, "CodexRPC", lambda: replacement)
    monkeypatch.setattr(adapter.presence, "collect_once", lambda *_: {
        "schema_version": 1, "connection": "unavailable", "complete": False,
        "threads": {}, "reason": "Codex inventory deadline exceeded"
    })
    state = adapter.empty_state()
    rpc, reset = adapter.refresh_presence(old, tmp_path, {}, state)
    assert old.closed and rpc is replacement and reset
    assert state["presence"]["connection"] == "unavailable"


# contract-test: tooling
def test_disabled_presence_skips_inventory_and_status_updates_but_delivers(monkeypatch, tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    monkeypatch.setattr(adapter, "state_root", lambda: tmp_path)
    (tmp_path / "codex-adapter.json").write_text(json.dumps({
        "repositories": {str(root): {"enabled": True, "presence_enabled": False}}
    }))
    monkeypatch.setattr(adapter.sys, "stdin", io.StringIO(""))
    passes = [0]

    def ready(*_):
        passes[0] += 1
        return ([adapter.sys.stdin] if passes[0] > 1 else [], [], [])

    monkeypatch.setattr(adapter.select, "select", ready)

    class QuietRPC:
        socket = object()

        def poll_notifications(self, _timeout):
            return [{"method": "thread/status/changed", "params": {
                "threadId": PARENT, "status": {"type": "active"}}}]

        def close(self):
            pass

    monkeypatch.setattr(adapter, "CodexRPC", QuietRPC)
    monkeypatch.setattr(adapter, "refresh_presence", lambda *_: pytest.fail(
        "disabled presence must not inventory chats"))
    monkeypatch.setattr(adapter.presence, "observe_notification", lambda *_: pytest.fail(
        "disabled presence must not update peer status"))
    delivered = []
    monkeypatch.setattr(adapter, "deliver", lambda *_: delivered.append(True))
    adapter.run(root, {})
    assert delivered == [True]
