"""Resource admission tests for isolated Codex test environments.

Only synthetic host measurements and in-memory durable documents are used.
Cover accounting races, retry identity, retention and safe release semantics.
Persistence adapters must run these transitions under one host transaction.
See docs/plans/codex-session-runtime-isolation/plan.yml.
"""

# contract-test-file: infrastructure
import copy
import pytest
from backend.engineering_control_plane import runtime_capacity as capacity

G = 1024**3


def host(**overrides):
    value = dict(
        memory_available=20 * G,
        memory_total=30 * G,
        disk_available={"root": 68 * G},
        disk_total={"root": 300 * G},
        memory_floor=4 * G,
        build_memory=4 * G,
        build_disk={"root": 10 * G},
        max_environments=2,
        enforcement_verified=True,
    )
    value.update(overrides)
    return value


def request(key):
    return dict(
        key=key,
        owner=key,
        memory_limit=6 * G,
        disk_limits={"root": 10 * G},
        source="a" * 40,
        profile="basic",
    )


def test_fifo_budget_and_retry():
    state = capacity.empty_state()
    for key in ["a", "b", "c"]:
        capacity.enqueue(state, request(key))
    capacity.reconcile(state, host())
    assert [r["state"] for r in state["requests"]] == ["admitted", "admitted", "queued"]
    assert capacity.enqueue(state, request("a"))["state"] == "admitted"
    assert len(state["requests"]) == 3
    wrong = request("a")
    wrong["source"] = "b" * 40
    with pytest.raises(ValueError, match="identity"):
        capacity.enqueue(state, wrong)


def test_restart_preserves_outstanding_growth_without_double_counting():
    state = capacity.empty_state()
    capacity.enqueue(state, request("a"))
    capacity.reconcile(state, host())
    capacity.observe(
        state, "a", memory_used=2 * G, disk_used={"root": 4 * G}, live=True
    )
    state = copy.deepcopy(state)
    capacity.enqueue(state, request("b"))
    capacity.reconcile(
        state, host(memory_available=18 * G, disk_available={"root": 64 * G})
    )
    assert state["requests"][1]["state"] == "admitted"
    assert capacity.outstanding(state)["disk"]["root"] == 16 * G


def test_retention_charges_disk_and_live_test_cannot_release():
    state = capacity.empty_state()
    capacity.enqueue(state, request("a"))
    capacity.reconcile(state, host())
    capacity.observe(state, "a", memory_used=G, disk_used={"root": 3 * G}, live=True)
    with pytest.raises(ValueError, match="live"):
        capacity.release(state, "a", owner="a", evidence_saved=True, removed=True)
    capacity.observe(state, "a", memory_used=0, disk_used={"root": 3 * G}, live=False)
    capacity.retain(state, "a", owner="a", evidence_saved=True)
    assert state["requests"][0]["state"] == "retained"
    assert capacity.outstanding(state)["memory"] == 0
    assert capacity.outstanding(state)["disk"]["root"] == 0
    # Used bytes are already excluded from statvfs available bytes, never refunded.
    capacity.release(state, "a", owner="a", evidence_saved=True, removed=False)
    assert state["requests"][0]["state"] == "releasing"


def test_limits_fail_closed_and_impossible_request_does_not_block_queue():
    state = capacity.empty_state()
    huge = request("huge")
    huge["memory_limit"] = 100 * G
    capacity.enqueue(state, huge)
    capacity.enqueue(state, request("normal"))
    capacity.reconcile(state, host(enforcement_verified=False))
    assert all(r["state"] == "queued" for r in state["requests"])
    capacity.reconcile(state, host())
    assert state["requests"][0]["state"] == "blocked"
    assert state["requests"][1]["state"] == "admitted"


def test_missing_filesystem_and_negative_measurement_rejected():
    state = capacity.empty_state()
    r = request("a")
    r["disk_limits"] = {"unknown": G}
    capacity.enqueue(state, r)
    capacity.reconcile(state, host())
    assert state["requests"][0]["state"] == "blocked"
    with pytest.raises(ValueError):
        capacity.reconcile(state, host(memory_available=-1))


@pytest.mark.parametrize(
    "available,expected", [(50 * G - 1, "queued"), (50 * G, "admitted")]
)
def test_disk_floor_includes_build_and_runtime_growth(available, expected):
    state = capacity.empty_state()
    capacity.enqueue(state, request("a"))
    capacity.reconcile(state, host(disk_available={"root": available}))
    assert state["requests"][0]["state"] == expected
    if expected == "queued":
        assert state["requests"][0]["reason"] == "disk_reserve"


def test_all_filesystems_preserve_floor_including_reserved_growth():
    state = capacity.empty_state()
    for key in ("a", "b"):
        item = request(key)
        item["disk_limits"] = {"root": G, "data": 10 * G}
        capacity.enqueue(state, item)
    snapshot = host(
        disk_available={"root": 68 * G, "data": 50 * G - 1},
        disk_total={"root": 300 * G, "data": 100 * G},
        build_disk={"root": 10 * G, "data": 0},
    )
    capacity.reconcile(state, snapshot)
    assert [row["state"] for row in state["requests"]] == ["admitted", "queued"]
    assert state["requests"][1]["reason"] == "disk_reserve"
