"""Engineering/tooling contracts: disk ledger to durable Codex event delivery."""
import copy
import pytest
from scripts import codex_task_adapter as adapter
from scripts.codex_cached_context import render_event

OWNER = "00000000-0000-0000-0000-000000000001"


class Ledger:
    def __init__(self):
        self.rows = [{"id": "request", "thread": OWNER, "task_id": "task", "repository": "/repo",
                      "operation": "build", "state": "granted", "grant_id": "grant", "expires_at": 9999999999,
                      "amount": 1024, "reason": "capacity"}]
        self.acks = []
        self.deferrals = []
        self.reads = 0
        self.valid = True
        self.cancellations = []
        self.bindings = []

    def requests(self, repository):
        self.reads += 1
        return copy.deepcopy(self.rows)

    def available(self):
        return True

    def valid_grant(self, request_id, grant_id):
        return self.valid and any(r["id"] == request_id and r["grant_id"] == grant_id and r["state"] == "granted" for r in self.rows)

    def defer(self, request_id):
        self.deferrals.append(request_id)

    def bind_task(self, request_id, thread, task_id):
        self.bindings.append((request_id, thread, task_id))
        for row in self.rows:
            if row["id"] == request_id and row["thread"] == thread and row["state"] in {"waiting", "granted"} and row.get("task_id") in {"", None, task_id}:
                row["task_id"] = task_id
                return True
        return False

    def cancel(self, request_id, reason):
        self.cancellations.append((request_id, reason))
        for row in self.rows:
            if row["id"] == request_id:
                row["state"] = "cancelled"

    def acknowledge(self, request_id, grant_id):
        self.acks.append((request_id, grant_id))


class RPC:
    def __init__(self, active=False):
        self.starts = []
        self.active = active

    def call(self, method, params):
        if method == "thread/read":
            return {"thread": {"status": {"type": "active" if self.active else "idle"}}}
        if method == "turn/start":
            self.starts.append(params)
            return {"turn": {"id": "turn"}}
        if method == "thread/items/list":
            return {"data": []}
        raise AssertionError(method)


def setup():
    return adapter.empty_state(), Ledger(), {"task": {"task_id": "task", "status": "in_progress", "external_chat": {"provider": "codex", "id": OWNER}}}


def observe(state, ledger, tasks):
    from pathlib import Path
    adapter.observe_disk(Path("/repo"), state, tasks, {OWNER}, ledger)


# contract-test: tooling
def test_snapshot_deduplicates_grant_and_acknowledges_without_claiming():
    state, ledger, tasks = setup()
    observe(state, ledger, tasks)
    observe(state, ledger, tasks)
    assert ledger.reads == 2
    assert len(state["deliveries"]) == 1
    rpc = RPC()
    adapter.deliver(state, rpc, {OWNER}, True, lambda: None, tasks, ledger)
    assert len(rpc.starts) == 1
    assert ledger.acks == [("request", "grant")]
    assert ledger.rows[0]["state"] == "granted"


# contract-test: tooling
def test_rollout_cutoff_retains_old_context_and_allows_new_same_owner_event():
    state, ledger, tasks = setup()
    adapter.queue(state, OWNER, "ci_result", "historical", {})
    old = next(iter(state["deliveries"].values()))
    old["created_at"] = 10
    observe(state, ledger, tasks)
    ready = next(item for item in state["deliveries"].values() if item["kind"] == "disk_ready")
    ready["created_at"] = 30
    rpc = RPC()
    adapter.deliver(state, rpc, {OWNER}, True, lambda: None, tasks, ledger,
                    execution_not_before=20)
    assert len(rpc.starts) == 1
    assert old["state"] == "pending"
    assert ready["state"] == "accepted"


# contract-test: tooling
def test_rollout_cutoff_keeps_uncertain_start_reconciliation():
    state, ledger, tasks = setup()
    adapter.queue(state, OWNER, "ci_result", "historical", {})
    old = next(iter(state["deliveries"].values()))
    old.update(created_at=10, state="uncertain")
    rpc = RPC()
    adapter.deliver(state, rpc, {OWNER}, True, lambda: None, tasks, ledger,
                    execution_not_before=20)
    assert not rpc.starts
    assert old["state"] == "needs_review"


# contract-test: tooling
@pytest.mark.parametrize("flag", ["paused", "deleted", "archived"])
def test_human_control_is_preserved_and_grant_deferred(flag):
    state, ledger, tasks = setup()
    state["threads"][OWNER] = {flag: True}
    observe(state, ledger, tasks)
    assert state["threads"][OWNER][flag]
    assert state["threads"][OWNER]["resource_waiting"]
    assert ledger.deferrals == ["request"]
    assert not state["deliveries"]


# contract-test: tooling
def test_active_chat_context_receipt_acknowledges_reservation_without_start():
    state, ledger, tasks = setup()
    observe(state, ledger, tasks)
    rpc = RPC(active=True)
    adapter.deliver(state, rpc, {OWNER}, True, lambda: None, tasks, ledger)
    assert not rpc.starts
    item = next(iter(state["deliveries"].values()))
    adapter.acknowledge_context(state, {"adapter_events": [item["id"]]}, OWNER, ledger, tasks, {OWNER})
    assert item["state"] == "provided_in_context"
    assert ledger.acks == [("request", "grant")]


# contract-test: tooling
def test_other_events_cannot_wake_waiting_chat():
    state, ledger, tasks = setup()
    ledger.rows[0]["state"] = "waiting"
    observe(state, ledger, tasks)
    adapter.queue(state, OWNER, "ci_result", "ci", {})
    rpc = RPC()
    adapter.deliver(state, rpc, {OWNER}, True, lambda: None, tasks, ledger)
    assert not rpc.starts


# contract-test: tooling
def test_fresh_grant_is_fenced_by_uncertain_expired_grant():
    state, ledger, tasks = setup()
    observe(state, ledger, tasks)
    old = next(iter(state["deliveries"].values()))
    old["state"] = "uncertain"
    ledger.rows[0]["grant_id"] = "new-grant"
    observe(state, ledger, tasks)
    assert old["state"] == "uncertain"
    assert len(state["deliveries"]) == 2
    rpc = RPC()
    adapter.deliver(state, rpc, {OWNER}, True, lambda: None, tasks, ledger)
    assert old["state"] == "needs_review"
    adapter.deliver(state, rpc, {OWNER}, True, lambda: None, tasks, ledger)
    assert not rpc.starts
    assert not ledger.acks


# contract-test: tooling
@pytest.mark.parametrize("change", ["pause", "done", "unregister", "expired"])
def test_final_start_guard_rechecks_owner_and_grant(change):
    state, ledger, tasks = setup()
    observe(state, ledger, tasks)
    def revalidate():
        if change == "pause":
            state["threads"][OWNER]["paused"] = True
        if change == "done":
            tasks["task"]["status"] = "done"
        if change == "expired":
            ledger.valid = False
        return (set() if change == "unregister" else {OWNER}), tasks
    rpc = RPC()
    adapter.deliver(state, rpc, {OWNER}, True, lambda: None, tasks, ledger, revalidate)
    assert not rpc.starts


# contract-test: tooling
def test_missing_task_identity_requires_unique_active_owned_task():
    state, ledger, tasks = setup()
    ledger.rows[0]["task_id"] = None
    tasks["other"] = {**tasks["task"], "task_id": "other"}
    observe(state, ledger, tasks)
    assert not state["deliveries"]
    assert state["disk_requests"]
    tasks["other"]["status"] = "done"
    observe(state, ledger, tasks)
    assert len(state["deliveries"]) == 1


# contract-test: tooling
def test_disk_context_clearly_distinguishes_wait_and_reserved_ready():
    assert "Waiting for disk" in render_event({"kind": "disk_wait", "data": {"id": "request"}})
    assert "must claim" in render_event({"kind": "disk_ready", "data": {"id": "request", "grant_id": "grant"}})


# contract-test: tooling
def test_anonymous_request_cannot_infer_task_or_wake_single_registered_chat():
    state, ledger, tasks = setup()
    ledger.rows[0]["thread"] = ""
    ledger.rows[0]["task_id"] = ""
    observe(state, ledger, tasks)
    assert state["disk_requests"]
    assert not state["deliveries"]
    assert not state.get("disk_task_waits")
    rpc = RPC()
    adapter.deliver(state, rpc, {OWNER}, True, lambda: None, tasks, ledger)
    assert not rpc.starts


# contract-test: tooling
def test_adapter_selects_custom_repository_ledger(tmp_path):
    from scripts.disk_coordinator import _atomic, marker
    root = tmp_path / "repository"
    root.mkdir()
    custom = tmp_path / "custom-private-ledger"
    _atomic(marker(root), {"enabled": True, "state_root": str(custom)})
    assert adapter.disk_ledger(root).root == custom


# contract-test: tooling
@pytest.mark.parametrize("revocation", ["repository", "thread", "snapshot", "auto_wake"])
def test_final_start_reloads_repository_opt_in_after_thread_read(tmp_path, monkeypatch, revocation):
    import json
    from datetime import datetime, timezone
    state, ledger, tasks = setup()
    monkeypatch.setattr(adapter, "state_root", lambda: tmp_path)
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"connection": "connected", "synced_at": datetime.now(timezone.utc).isoformat(),
                                    "account_scope": ["api", "account", "personal"], "tasks": list(tasks.values())}))
    config = {"enabled": True, "auto_wake": True, "threads": [OWNER],
              "execution_hosts": {OWNER: adapter.socket.gethostname()}, "snapshots": [str(snapshot)]}
    path = tmp_path / "codex-adapter.json"
    def save_config():
        path.write_text(json.dumps({"repositories": {str(tmp_path): config}}))
    save_config()
    observe(state, ledger, tasks)
    class RevokedDuringRead(RPC):
        def call(self, method, params):
            if method == "thread/read":
                if revocation == "repository":
                    config["enabled"] = False
                elif revocation == "thread":
                    config["threads"] = []
                elif revocation == "snapshot":
                    config["snapshots"] = []
                else:
                    config["auto_wake"] = False
                save_config()
            return super().call(method, params)
    rpc = RevokedDuringRead()
    adapter.deliver(state, rpc, {OWNER}, True, lambda: None, tasks, ledger,
                    lambda: adapter.refresh_disk_authorization(tmp_path, state))
    assert not rpc.starts


# contract-test: tooling
def test_inferred_task_binding_survives_later_same_chat_task_replacement():
    state, ledger, tasks = setup()
    ledger.rows[0]["task_id"] = ""
    observe(state, ledger, tasks)
    assert ledger.bindings == [("request", OWNER, "task")]
    assert ledger.rows[0]["task_id"] == "task"
    tasks["task"]["status"] = "done"
    tasks["replacement"] = {**tasks["task"], "task_id": "replacement", "status": "in_progress"}
    observe(state, ledger, tasks)
    assert ledger.rows[0]["state"] == "cancelled"
    assert len(ledger.cancellations) == 1
    assert all(item["state"] == "superseded" for item in state["deliveries"].values())
    assert not any(item["data"]["task_id"] == "replacement" for item in state["deliveries"].values())


# contract-test: tooling
@pytest.mark.parametrize("change", ["done", "owner", "unlinked"])
def test_bound_task_cancellation_preserves_uncertain_start_and_supersedes_unsent(change):
    state, ledger, tasks = setup()
    observe(state, ledger, tasks)
    item = next(iter(state["deliveries"].values()))
    uncertain = {**copy.deepcopy(item), "id": "uncertain-original", "state": "uncertain"}
    state["deliveries"][uncertain["id"]] = uncertain
    if change == "done":
        tasks["task"]["status"] = "done"
    elif change == "owner":
        tasks["task"]["external_chat"] = {"provider": "codex", "id": "another"}
    else:
        tasks["task"]["external_chat"] = None
    observe(state, ledger, tasks)
    assert ledger.rows[0]["state"] == "cancelled"
    assert item["state"] == "superseded"
    assert uncertain["state"] == "uncertain"


# contract-test: tooling
def test_binding_race_never_creates_disk_status_or_ready_intents(monkeypatch):
    state, ledger, tasks = setup()
    ledger.rows[0]["task_id"] = ""
    monkeypatch.setattr(ledger, "bind_task", lambda *_: False)
    observe(state, ledger, tasks)
    assert not state["deliveries"]
    assert not state.get("disk_task_waits")
