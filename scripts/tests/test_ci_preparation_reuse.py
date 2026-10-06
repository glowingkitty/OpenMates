# contract-test-file: tooling
"""Exercise preparation reuse across independent requests and private tickets."""

from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import json

import pytest

from scripts.ci_coordinator import Queue, enqueue_submission
from scripts import ci_preparation_transport as transport


SOURCE = "a" * 40
PREPARATION = {"key": "b" * 64, "harness_commit": "c" * 40, "cli": True, "upload": False}


@pytest.fixture
def queue(tmp_path):
    return Queue(tmp_path / "logs/ci-coordinator/queue.sqlite3")


def producer(queue, attempt="first", **kwargs):
    return queue.enqueue(kwargs.pop("owner", "owner"), kwargs.pop("source", SOURCE),
                         [], "prepare", attempt,
                         preparation=kwargs.pop("preparation", PREPARATION), **kwargs)


def candidate(**kwargs):
    return {"source": SOURCE, "base": "d" * 40, "tree": "e" * 40, "session": "owner",
            "patch_sha256": "f" * 64,
            "patch_url": "https://nbg1.your-objectstorage.com/private.patch?signature=first",
            "artifact_expires_at": (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)).isoformat(),
            **kwargs}


def successful_ticket(queue, job, *, remaining=48 * 60 * 60):
    def sign(objects, expires):
        return {name: {verb: f"https://nbg1.your-objectstorage.com/{transport.BUCKET_NAME}/{key}?signature=test"
                       for verb in ("put_url", "get_url")} for name, key in objects.items()}
    now = dt.datetime.now(dt.timezone.utc)
    transport.get_or_create_ticket(queue.path.parents[2], job["id"], job["source"], job["preparation_key"],
                                   now=now - dt.timedelta(seconds=48 * 60 * 60 - remaining), presign=sign)
    with queue.connect() as db:
        db.execute("UPDATE jobs SET state='success',run_id=42 WHERE id=?", (job["id"],))
    return queue.path.parent / "preparations" / f"{job['id']}.json"


def test_concurrent_attempts_have_one_preparation_and_separate_consumers(queue, monkeypatch, tmp_path):
    monkeypatch.setattr("scripts.ci_coordinator.subprocess.check_output",
                        lambda *a, **kw: '{"groups":{"uploads":{"specs":[]}}}')
    monkeypatch.setattr("scripts.ci_coordinator.harness_commit", lambda _: "c" * 40)
    def submit(n):
        return enqueue_submission(queue, "owner", SOURCE, ["first.spec.ts"], "e2e", str(n),
                                  candidate=candidate(), source_root=tmp_path, prepared_builds=True)[0]
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = list(pool.map(submit, range(16)))
    assert len({job["id"] for job in jobs}) == 16
    assert len({job["preparation_id"] for job in jobs}) == 1
    assert len([job for job in queue.status() if job["mode"] == "prepare"]) == 1


@pytest.mark.parametrize("state", ["queued", "dispatching", "submitted", "running", "attention"])
def test_pending_preparation_is_shared_without_resending_or_rewriting_intent(queue, state):
    first = producer(queue, candidate=candidate())
    with queue.connect() as db:
        db.execute("UPDATE jobs SET state=?,sent=? WHERE id=?", (state, None if state == "queued" else 100, first["id"]))
    refreshed = candidate(patch_url="https://nbg1.your-objectstorage.com/private.patch?signature=new")
    second = producer(queue, "second", candidate=refreshed)
    assert second["id"] == first["id"]
    assert second["state"] == state
    assert second["candidate_patch_url"] == (refreshed["patch_url"] if state == "queued" else first["candidate_patch_url"])
    assert second["sent"] == (None if state == "queued" else 100)


def test_completed_preparation_reused_after_queue_reopen(queue):
    first = producer(queue)
    path = successful_ticket(queue, first)
    before = path.read_bytes()
    second = producer(Queue(queue.path), "second")
    assert second["id"] == first["id"]
    assert second["run_id"] == 42
    assert path.read_bytes() == before  # No renewal or additional write capability.


@pytest.mark.parametrize("state", ["failure", "cancelled"])
def test_failed_preparation_retry_gets_new_history_and_object_namespace(queue, state):
    first = producer(queue)
    with queue.connect() as db:
        db.execute("UPDATE jobs SET state=? WHERE id=?", (state, first["id"]))
    second = producer(queue)  # Even reusing the exact attempt string is safe.
    assert second["id"] != first["id"]
    assert second["state"] == "queued"
    assert queue.status(first["id"])[0]["state"] == state
    assert producer(queue, "third")["id"] == second["id"]


@pytest.mark.parametrize("invalid", ["missing", "expired", "near-expiry", "malformed", "identity", "permissions", "no-run"])
def test_unavailable_completed_preparation_is_not_reused_or_renewed(queue, invalid):
    first = producer(queue)
    path = successful_ticket(queue, first, remaining={"expired": -1, "near-expiry": 60}.get(invalid, 48 * 60 * 60))
    if invalid == "missing":
        path.unlink()
    elif invalid == "malformed":
        path.write_text("not-json")
    elif invalid == "identity":
        ticket = json.loads(path.read_text())
        ticket["source"] = "0" * 40
        path.write_text(json.dumps(ticket))
    elif invalid == "permissions":
        path.chmod(0o644)
    elif invalid == "no-run":
        with queue.connect() as db:
            db.execute("UPDATE jobs SET run_id=NULL WHERE id=?", (first["id"],))
    before = path.read_bytes() if path.exists() else None
    second = producer(queue)
    assert second["id"] != first["id"]
    assert second["state"] == "queued"
    assert (path.read_bytes() if path.exists() else None) == before


@pytest.mark.parametrize("change", ["source", "owner", "base", "tree", "patch", "key", "harness", "cli", "upload"])
def test_changed_preparation_inputs_require_new_producer(queue, change):
    first = producer(queue, candidate=candidate())
    changed = candidate()
    prep = dict(PREPARATION)
    owner, source = "owner", SOURCE
    if change == "source":
        source = changed["source"] = "1" * 40
    elif change == "owner":
        owner = changed["session"] = "other"
    elif change in ("base", "tree"):
        changed[change] = "1" * 40
    elif change == "patch":
        changed["patch_sha256"] = "1" * 64
    elif change == "key":
        prep["key"] = "1" * 64
    elif change == "harness":
        prep["harness_commit"] = "1" * 40
    else:
        prep[change] = not prep[change]
    second = producer(queue, "second", owner=owner, source=source, candidate=changed, preparation=prep)
    assert second["id"] != first["id"]


def test_disabling_reuse_preserves_per_attempt_producers(queue, monkeypatch):
    first = producer(queue)
    monkeypatch.setenv("OPENMATES_CI_REUSE_PREPARATION", "0")
    assert producer(queue, "second")["id"] != first["id"]


def test_reuse_can_find_pre_rollout_queued_producer(queue, monkeypatch):
    monkeypatch.setenv("OPENMATES_CI_REUSE_PREPARATION", "0")
    first = producer(queue)
    monkeypatch.delenv("OPENMATES_CI_REUSE_PREPARATION")
    assert producer(queue, "second")["id"] == first["id"]


def test_cancelled_consumer_does_not_remove_shared_preparation(queue, monkeypatch):
    monkeypatch.setattr("scripts.ci_coordinator.time.sleep", lambda _: None)
    first = producer(queue)
    one = queue.enqueue("owner", SOURCE, ["first.spec.ts"], nonce="one", preparation={**PREPARATION, "id": first["id"]})
    two = queue.enqueue("owner", SOURCE, ["first.spec.ts"], nonce="two", preparation={**PREPARATION, "id": first["id"]})
    with queue.connect() as db:
        db.execute("UPDATE jobs SET state='cancelled' WHERE id=?", (one["id"],))
    successful_ticket(queue, first)
    class Remote:
        def __init__(self): self.sent = []
        def budget(self): return {"remaining": 5000, "reset": 500}
        def runs(self): return []
        def dispatch(self, job): self.sent.append(job)
    remote = Remote()
    queue.tick(remote)
    assert [job["id"] for job in remote.sent] == [two["id"]]
    assert remote.sent[0]["prepared_run_id"] == 42
    assert queue.status(first["id"])[0]["state"] == "success"
