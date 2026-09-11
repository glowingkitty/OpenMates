"""Exercise the Codex coordinator with fake time and isolated state.

No live threads, tasks, schedulers or shared services are modified.
Progress is outcome evidence rather than runtime activity.
See docs/architecture/codex-orchestration.md for the state machine.
"""

# contract-test-file: tooling
from scripts import codex_orchestration as co


def worker():
    return co.new_worker("00000000-0000-0000-0000-000000000001", "TASK-1", "Render", 0)


def test_adaptive_cadence():
    assert [co.next_review(0, t) for t in (0, 60, 120, 180, 780, 1380, 1980, 9180)] == [
        60,
        120,
        180,
        780,
        1380,
        1980,
        3180,
        10980,
    ]


def test_activity_does_not_reset_progress_and_parking_has_no_clock_cutoff():
    w = worker()
    co.observe(w, {"status": {"type": "active"}, "updatedAt": 1799}, 1799)
    assert w["progress_at"] == 0
    co.observe(w, {"status": {"type": "active"}, "updatedAt": 1800}, 1800)
    assert w["parked"] and w["status"] == "active"


def test_duplicate_progress_cannot_keep_worker_alive():
    w = worker()
    co.progress(w, "verification", "run:123:passed", 100)
    co.progress(w, "verification", "run:123:passed", 1700)
    assert w["progress_at"] == 100


def test_job_watch_survives_parking_but_not_explicit_stop():
    w = worker()
    w["jobs"] = {"job1": "running"}
    co.observe(w, {"status": {"type": "idle"}, "updatedAt": 0}, 1801)
    assert w["parked"] and co.needs_observation(w)
    w["stopped"] = True
    assert not co.needs_observation(w)


def test_human_instruction_only_resets_affected_worker():
    a, b = worker(), worker()
    co.user_instruction(a, "human-message-1", 1200)
    co.user_instruction(a, "human-message-1", 1600)
    assert a["cadence_at"] == 1200 and b["cadence_at"] == 0
    assert a["progress_at"] == 0


def test_linked_table_escapes_quotes_and_no_fake_freshness():
    w = worker()
    w["quote"] = "A | B\nC"
    w["checked_at"] = 123
    text = co.render_table({"workers": {w["thread"]: w}})
    assert "codex://threads/" in text and "A \\| B C" in text
    assert "1970-01-01T00:02:03" in text


class RPC:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def call(self, method, params):
        self.calls.append((method, params))
        if method == "thread/read":
            return {"thread": {"status": {"type": "idle"}, "updatedAt": 1}}
        if self.fail:
            raise TimeoutError("uncertain acceptance")
        return {"turn": {"id": "accepted-turn"}}


def state_file(tmp_path):
    path = tmp_path / "state.json"
    w = worker()
    with co.transaction(path) as state:
        state.update(
            enabled=True,
            coordinator="00000000-0000-0000-0000-000000000002",
            workers={w["thread"]: w},
        )
    return path


def test_parked_workers_are_not_reread_and_summary_delivered_once(tmp_path):
    path = state_file(tmp_path)
    rpc = RPC()
    co.observe_tick(path, rpc, now=1801)
    co.deliver(path, rpc)
    before = len(rpc.calls)
    co.observe_tick(path, rpc, now=2000)
    co.deliver(path, rpc)
    assert len(rpc.calls) == before


def test_restart_after_uncertain_delivery_never_resubmits(tmp_path):
    import pytest
    import json

    path = state_file(tmp_path)
    rpc = RPC(fail=True)
    with co.transaction(path) as state:
        co.queue_review(state, 1, {"event": "completed"})
    with pytest.raises(TimeoutError):
        co.deliver(path, rpc)
    second = RPC()
    co.deliver(path, second)
    assert second.calls == []
    assert {v["status"] for v in json.loads(path.read_text())["outbox"].values()} == {
        "uncertain"
    }


def test_explicit_stop_prevents_wakeup(tmp_path):
    path = state_file(tmp_path)
    rpc = RPC()
    with co.transaction(path) as state:
        co.queue_review(state, 1, {"event": "completed"})
        state["enabled"] = False
    co.observe_tick(path, rpc, now=2000)
    co.deliver(path, rpc)
    assert rpc.calls == []


def test_no_repeated_instruction_without_observed_outcome():
    import pytest

    w = worker()
    co.instruction(
        w, "drift", "worker-message:1", "Return to the assigned verification", 10
    )
    with pytest.raises(ValueError, match="previous"):
        co.instruction(w, "new_evidence", "run:2", "Check result", 20)
    w["last_instruction"]["effect"] = "unchanged"
    with pytest.raises(ValueError, match="Identical"):
        co.instruction(
            w, "drift", "worker-message:1", "Return to the assigned verification", 30
        )


def test_stop_formatter_only_coordinator_and_one_retry(tmp_path):
    w = worker()
    sid = "abc"
    path = co.state_path(tmp_path, sid)
    with co.transaction(path) as state:
        state.update(coordinator="owner", workers={w["thread"]: w})
    payload = {"turn_id": "turn", "last_assistant_message": "Done"}
    assert co.output_guard(tmp_path, sid, "worker", payload) == {}
    assert co.output_guard(tmp_path, sid, "owner", payload)["decision"] == "block"
    assert co.output_guard(tmp_path, sid, "owner", payload) == {}


def test_external_job_completion_rearms_only_affected_parked_worker(tmp_path):
    from scripts.ci_coordinator import Queue
    import json

    path = state_file(tmp_path)
    db = Queue(tmp_path / "logs/ci-coordinator/queue.sqlite3")
    job = db.enqueue("test", "a" * 40, ["chat.spec.ts"], "e2e", "")
    with co.transaction(path) as state:
        w = next(iter(state["workers"].values()))
        w.update(parked=True, jobs={job["id"]: "running"})
    with db.connect() as conn:
        conn.execute("UPDATE jobs SET state=? WHERE id=?", ("failure", job["id"]))
    rpc = RPC()
    co.observe_tick(path, rpc, now=2700, root=tmp_path)
    w = next(iter(json.loads(path.read_text())["workers"].values()))
    assert not w["parked"] and w["progress_at"] == 2700
    assert rpc.calls == []  # Only the external cache was read while parked.


def test_wakeup_is_tool_output_not_a_synthetic_user_instruction(tmp_path):
    import json

    path = state_file(tmp_path)
    rpc = RPC()
    with co.transaction(path) as state:
        co.queue_review(state, 1, {"event": "completed"})
    co.deliver(path, rpc)
    params = next(p for method, p in rpc.calls if method == "turn/start")
    assert params["input"] == []
    assert params["toolOutput"]["name"] == "orchestration_checkpoint"
    output = json.loads(params["toolOutput"]["output"])
    assert output["delivery_id"] == params["clientUserMessageId"]
    assert "not a human instruction or approval" in output["checkpoint"]
