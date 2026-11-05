"""Engineering/tooling contracts for disk-owned version-fenced Task waits."""
import json
import pytest
from scripts import codex_task_adapter as adapter

OWNER = "00000000-0000-0000-0000-000000000001"


def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "state_root", lambda: tmp_path)
    snapshot_path = tmp_path / "snapshot.json"
    task = {"task_id": "task", "status": "in_progress", "version": 5,
            "external_chat": {"provider": "codex", "id": OWNER}, "encrypted": {"version": 5}}
    snapshot = {"connection": "connected", "account_scope": ["server", "account", "personal"],
                "project_id": "project", "tasks": [task]}
    snapshot_path.write_text(json.dumps(snapshot))
    return adapter.empty_state(), {**task, "snapshot_path": str(snapshot_path)}, {"id": "request", "state": "waiting"}


def deliveries(tmp_path):
    return list((tmp_path / "task-command-delivery").glob("*/*.json"))


def acknowledge(tmp_path):
    for path in deliveries(tmp_path):
        data = json.loads(path.read_text())
        data["state"] = "acknowledged"
        path.write_text(json.dumps(data))


def refresh(task):
    path = adapter.Path(task["snapshot_path"])
    snapshot = json.loads(path.read_text())
    snapshot["tasks"] = [{k: v for k, v in task.items() if k != "snapshot_path"}]
    path.write_text(json.dumps(snapshot))


# contract-test: tooling
def test_block_restore_is_version_fenced_and_waits_for_durable_ack(tmp_path, monkeypatch):
    state, task, row = setup(tmp_path, monkeypatch)
    saves = []
    assert not adapter.sync_disk_task(state, row, task, lambda: saves.append(True))
    assert saves
    assert len(deliveries(tmp_path)) == 2
    assert all(json.loads(p.read_text())["task"]["version"] == 5 for p in deliveries(tmp_path))
    task.update(status="blocked", version=6)
    refresh(task)
    row["state"] = "granted"
    assert not adapter.sync_disk_task(state, row, task, lambda: None)
    assert len(deliveries(tmp_path)) == 2  # Pending or uncertain block is never restored.
    acknowledge(tmp_path)
    assert not adapter.sync_disk_task(state, row, task, lambda: None)
    restores = [json.loads(p.read_text()) for p in deliveries(tmp_path) if json.loads(p.read_text())["operation"].get("status") == "in_progress"]
    assert len(restores) == 1 and restores[0]["task"]["version"] == 6
    # Simulate publication followed by a crash before the adapter state save.
    del state["disk_task_waits"]["request"]["restore_delivery"]
    task.update(status="in_progress", version=7)
    refresh(task)
    assert not adapter.sync_disk_task(state, row, task, lambda: None)
    acknowledge(tmp_path)
    assert adapter.sync_disk_task(state, row, task, lambda: None)


# contract-test: tooling
@pytest.mark.parametrize("change", ["version", "reason", "owner"])
def test_competing_task_edits_require_review_and_never_clear_user_blocker(tmp_path, monkeypatch, change):
    state, task, row = setup(tmp_path, monkeypatch)
    adapter.sync_disk_task(state, row, task, lambda: None)
    acknowledge(tmp_path)
    task.update(status="blocked", version=6)
    if change == "version":
        task["version"] = 8
    elif change == "reason":
        task["blocked_reason"] = "Waiting for the user"
    else:
        task["external_chat"] = {"provider": "codex", "id": "another"}
    refresh(task)
    row["state"] = "granted"
    assert not adapter.sync_disk_task(state, row, task, lambda: None)
    assert state["disk_task_waits"]["request"]["state"] == "needs_review"
    assert len(deliveries(tmp_path)) == 2


# contract-test: tooling
def test_preexisting_user_blocker_has_no_status_or_activity_mutation(tmp_path, monkeypatch):
    state, task, row = setup(tmp_path, monkeypatch)
    task["blocked_reason_code"] = "needs_user_input"
    assert not adapter.sync_disk_task(state, row, task, lambda: None)
    assert not deliveries(tmp_path)


# contract-test: tooling
def test_wait_replay_keeps_original_snapshot_and_stable_activity_id(tmp_path, monkeypatch):
    state, task, row = setup(tmp_path, monkeypatch)
    adapter.sync_disk_task(state, row, task, lambda: None)
    first = {p.name: p.read_text() for p in deliveries(tmp_path)}
    adapter.sync_disk_task(state, row, task, lambda: None)
    assert first == {p.name: p.read_text() for p in deliveries(tmp_path)}


# contract-test: tooling
def test_concurrent_same_task_waits_share_status_fence_and_serialize_grants(tmp_path, monkeypatch):
    class Ledger:
        def __init__(self):
            self.rows = [{"id": "request", "thread": OWNER, "task_id": "task", "operation": "build", "state": "waiting", "grant_id": "", "expires_at": 9999999999}]
        def requests(self, repository):
            return [dict(row) for row in self.rows]
        def valid_grant(self, request_id, grant_id):
            return any(row["id"] == request_id and row["grant_id"] == grant_id and row["state"] == "granted" for row in self.rows)
        def defer(self, request_id):
            raise AssertionError("eligible group grant must not be deferred")
    state, task, _row = setup(tmp_path, monkeypatch)
    ledger = Ledger()
    ledger.rows[0]["state"] = "waiting"
    ledger.rows.append({**ledger.rows[0], "id": "second", "operation": "test"})
    tasks = {"task": task}
    def observe():
        adapter.observe_disk(tmp_path, state, tasks, {OWNER}, ledger)
    observe()
    assert len(deliveries(tmp_path)) == 2
    assert len(state["disk_task_waits"]) == 1
    acknowledge(tmp_path)
    task.update(status="blocked", version=6)
    refresh(task)
    ledger.rows[0].update(state="granted", grant_id="one")
    observe()
    assert len(deliveries(tmp_path)) == 3  # One live grant permits serialized progress.
    assert not state["deliveries"]
    acknowledge(tmp_path)
    task.update(status="in_progress", version=7)
    refresh(task)
    observe()
    assert len(state["deliveries"]) == 1
    assert next(iter(state["deliveries"].values()))["data"]["id"] == "request"
    ledger.rows[1].update(state="granted", grant_id="two")
    observe()
    assert len(state["deliveries"]) == 1  # Oldest unclaimed grant fences later wake.
    ledger.rows[0]["state"] = "claimed"
    observe()
    assert len(state["deliveries"]) == 2
    assert len(deliveries(tmp_path)) == 3  # No additional Task edits or activities.
    assert all(item["data"]["task_wait_id"] == "request" for item in state["deliveries"].values())


# contract-test: tooling
def test_waiting_block_receipts_are_refreshed_before_capacity_is_granted(tmp_path, monkeypatch):
    state, task, row = setup(tmp_path, monkeypatch)
    adapter.sync_disk_task(state, row, task, lambda: None)
    acknowledge(tmp_path)
    task.update(status="blocked", version=6)
    refresh(task)
    assert not adapter.sync_disk_task(state, row, task, lambda: None)
    wait = state["disk_task_waits"][row["id"]]
    assert wait["block_state"] == "acknowledged"
    assert wait["activity_state"] == "acknowledged"
    assert len(deliveries(tmp_path)) == 2


# contract-test: tooling
def test_replacement_request_adopts_exact_acknowledged_disk_status_owner(tmp_path, monkeypatch):
    state, task, row = setup(tmp_path, monkeypatch)
    adapter.sync_disk_task(state, row, task, lambda: None)
    acknowledge(tmp_path)
    adapter.refresh_disk_wait_receipts(state)
    task.update(status="blocked", version=6)
    assert adapter.prior_disk_status_owner(state, task, OWNER) == "request"
    task["version"] = 7
    assert adapter.prior_disk_status_owner(state, task, OWNER) is None
    task["version"] = 6
    task["blocked_reason_code"] = "needs_user_input"
    assert adapter.prior_disk_status_owner(state, task, OWNER) is None


# contract-test: tooling
def test_granted_replacement_request_restores_original_disk_owned_status_fence(tmp_path, monkeypatch):
    from types import SimpleNamespace
    state, task, row = setup(tmp_path, monkeypatch)
    adapter.sync_disk_task(state, row, task, lambda: None)
    acknowledge(tmp_path)
    task.update(status="blocked", version=6)
    refresh(task)
    replacement = {"id": "replacement", "thread": OWNER, "task_id": "task", "operation": "workspace:fixture",
                   "state": "granted", "grant_id": "fresh-grant", "expires_at": 9999999999}
    ledger = SimpleNamespace(requests=lambda _: [dict(replacement)], valid_grant=lambda *_: True)
    adapter.observe_disk(tmp_path, state, {"task": task}, {OWNER}, ledger)
    assert len(deliveries(tmp_path)) == 3
    assert len(state["disk_task_waits"]) == 1
    assert state["disk_task_waits"]["request"]["state"] == "restoring"
    acknowledge(tmp_path)
    task.update(status="in_progress", version=7)
    refresh(task)
    adapter.observe_disk(tmp_path, state, {"task": task}, {OWNER}, ledger)
    event = next(iter(state["deliveries"].values()))
    assert event["data"]["id"] == "replacement"
    assert event["data"]["task_wait_id"] == "request"
