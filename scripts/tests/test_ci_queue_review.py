# contract-test-file: tooling
"""Queued-only review controls preserve immutable subjects and dispatch safety.

All mutations use disposable SQLite databases and a deterministic fake remote.
Tests exercise the existing coordinator lock, transaction rollback, owner and
priority boundaries, and exact coverage conservation across split replacements.
No live queue, GitHub request, account or Docker runtime is touched.
"""

import json

import pytest

from scripts.ci_coordinator import Queue
from test_ci_coordinator import Remote


@pytest.fixture
def setup(tmp_path):
    queue = Queue(tmp_path / "queue.db")
    job = queue.enqueue("daily", "a" * 40, ["affected.spec.ts", "other.spec.ts"])
    manifest = dict(
        version=1,
        action="hold",
        reason="Known old-source fixture blocker",
        entries=[
            dict(
                id=job["id"], source=job["source"], affected_specs=["affected.spec.ts"]
            )
        ],
    )
    return queue, job, manifest


def test_default_inspection_does_not_change_database(setup):
    queue, job, manifest = setup
    before = queue.path.read_bytes()
    report = Queue(queue.path, read_only=True).review_queued(manifest, "daily")
    assert queue.path.read_bytes() == before
    assert report["applied"] is False
    assert report["requests"][0]["preserved_other_specs"] == ["other.spec.ts"]
    assert queue.status(job["id"])[0] == job


def test_hold_preserves_identity_and_appends_audit(setup):
    queue, job, manifest = setup
    queue.review_queued(manifest, "daily", apply=True)
    held = queue.status(job["id"])[0]
    for key in set(job) - {"state", "updated"}:
        assert held[key] == job[key]
    assert held["state"] == "held"
    with queue.connect() as db:
        audit = json.loads(queue.metadata(db, "queued_review:" + job["id"]))
    assert audit[0]["source"] == job["source"]
    assert audit[0]["reason"] == manifest["reason"]


@pytest.mark.parametrize(
    "state",
    [
        "dispatching",
        "submitted",
        "running",
        "attention",
        "success",
        "failure",
        "cancelled",
    ],
)
def test_dispatched_or_terminal_work_cannot_be_held(setup, state):
    queue, job, manifest = setup
    with queue.connect() as db:
        db.execute("UPDATE jobs SET state=? WHERE id=?", (state, job["id"]))
    with pytest.raises(ValueError, match="never-dispatched"):
        queue.review_queued(manifest, "daily", apply=True)


def test_prioritized_task_and_owner_are_protected(setup):
    queue, job, manifest = setup
    with pytest.raises(ValueError, match="owner/source"):
        queue.review_queued(manifest, "other-owner", apply=True)
    queue.prioritize(job["id"], "daily", "Task prerequisite")
    with pytest.raises(ValueError, match="priority"):
        queue.review_queued(manifest, "daily", apply=True)
    with queue.connect() as db:
        assert queue.metadata(db, "prerequisite_request") == job["id"]


def test_stale_source_and_partial_multi_request_apply_roll_back(setup):
    queue, job, manifest = setup
    second = queue.enqueue("daily", "b" * 40, ["third.spec.ts"])
    manifest["entries"].append(dict(id=second["id"], source="c" * 40))
    with pytest.raises(ValueError, match="owner/source"):
        queue.review_queued(manifest, "daily", apply=True)
    assert queue.status(job["id"])[0]["state"] == "queued"
    with queue.connect() as db:
        assert queue.metadata(db, "queued_review:" + job["id"], "missing") == "missing"


def test_supersede_requires_every_sibling_and_preserves_history(setup):
    queue, job, manifest = setup
    queue.review_queued(manifest, "daily", apply=True)
    fixed = queue.enqueue("daily", "b" * 40, ["affected.spec.ts"])
    manifest["action"] = "supersede"
    manifest["entries"][0]["replacement_ids"] = [fixed["id"]]
    with pytest.raises(ValueError, match="EVERY original spec"):
        queue.review_queued(manifest, "daily", apply=True)
    sibling = queue.enqueue("daily", "b" * 40, ["other.spec.ts"])
    manifest["entries"][0]["replacement_ids"].append(sibling["id"])
    queue.review_queued(manifest, "daily", apply=True)
    old = queue.status(job["id"])[0]
    assert old["source"] == job["source"] and old["specs"] == job["specs"]
    assert old["state"] == "superseded"
    with queue.connect() as db:
        history = json.loads(queue.metadata(db, "queued_review:" + job["id"]))
    assert [entry["to_state"] for entry in history] == ["held", "superseded"]
    assert queue.status(sibling["id"])[0]["state"] == "queued"


def test_replacement_owner_mode_source_and_duplicate_coverage_rejected(setup):
    queue, job, manifest = setup
    manifest["action"] = "supersede"
    for owner, source, mode in [
        ("other", "b" * 40, "e2e"),
        ("daily", "a" * 40, "e2e"),
        ("daily", "b" * 40, "artifact"),
    ]:
        replacement = queue.enqueue(
            owner, source, json.loads(job["specs"]), mode, nonce=owner + mode
        )
        manifest["entries"][0]["replacement_ids"] = [replacement["id"]]
        with pytest.raises(ValueError, match="Replacement"):
            queue.review_queued(manifest, "daily", apply=True)
    first = queue.enqueue("daily", "b" * 40, json.loads(job["specs"]))
    duplicate = queue.enqueue("daily", "c" * 40, ["other.spec.ts"])
    manifest["entries"][0]["replacement_ids"] = [first["id"], duplicate["id"]]
    with pytest.raises(ValueError, match="EVERY original spec"):
        queue.review_queued(manifest, "daily", apply=True)


def test_tick_ignores_held_and_keeps_four_slots(setup, monkeypatch):
    queue, job, manifest = setup
    queue.review_queued(manifest, "daily", apply=True)
    for n in range(5):
        queue.enqueue(str(n), "b" * 40, ["x.spec.ts"])
    monkeypatch.setattr("scripts.ci_coordinator.time.sleep", lambda _: None)
    remote = Remote()
    queue.tick(remote, 100)
    assert len(remote.sent) == 4
    assert job["id"] not in [item["id"] for item in remote.sent]
    assert queue.status(job["id"])[0]["state"] == "held"


def test_dispatch_lock_and_inspect_apply_race_are_rejected(setup, monkeypatch):
    queue, job, manifest = setup
    queue.review_queued(manifest, "daily")

    class RacingRemote(Remote):
        def dispatch(self, item):
            with pytest.raises(RuntimeError, match="Coordinator busy"):
                queue.review_queued(manifest, "daily", apply=True)
            super().dispatch(item)

    monkeypatch.setattr("scripts.ci_coordinator.time.sleep", lambda _: None)
    remote = RacingRemote()
    queue.tick(remote, 100)
    with pytest.raises(ValueError, match="never-dispatched"):
        queue.review_queued(manifest, "daily", apply=True)
    assert len(remote.sent) == 1
    assert queue.status(job["id"])[0]["state"] == "submitted"


def test_sent_receipt_even_with_queued_state_is_protected(setup):
    queue, job, manifest = setup
    with queue.connect() as db:
        db.execute("UPDATE jobs SET sent=1 WHERE id=?", (job["id"],))
    with pytest.raises(ValueError, match="never-dispatched"):
        queue.review_queued(manifest, "daily", apply=True)
