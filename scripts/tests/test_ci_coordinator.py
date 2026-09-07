# contract-test-file: tooling
"""Exercise CI admission against a deterministic GitHub transport.

These tests verify concurrency, process recovery and ambiguous network sends.
No requests are sent and no shared Docker resources are read or changed.
The queue is shared by all Codex callers rather than polled per task.
See docs/plans/isolated-github-tests/plan.yml.
"""

from concurrent.futures import ThreadPoolExecutor
from scripts.ci_coordinator import Queue, GitHubError


class Remote:
    def __init__(self):
        self.sent = []
        self.visible = []
        self.remaining = 5000
        self.fail = False

    def budget(self):
        return {"remaining": self.remaining, "reset": 500}

    def runs(self):
        return self.visible

    def dispatch(self, job):
        self.sent.append(job)
        if self.fail:
            raise GitHubError("ambiguous send", 100)


def test_concurrent_enqueue_is_idempotent(tmp_path):
    q = Queue(tmp_path / "queue.db")
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(
            pool.map(lambda _: q.enqueue("a", "a" * 40, ["x.spec.ts"])["id"], range(16))
        )
    assert len(set(ids)) == 1
    assert len(q.status()) == 1


def test_four_slots_and_completion_release(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.ci_coordinator.time.sleep", lambda _: None)
    q = Queue(tmp_path / "queue.db")
    remote = Remote()
    for n in range(6):
        q.enqueue(str(n), "a" * 40, ["x.spec.ts"])
    q.tick(remote, 100)
    assert len(remote.sent) == 4
    job = remote.sent[0]
    remote.visible = [
        dict(
            display_title=job["token"],
            status="completed",
            conclusion="success",
            id=7,
            html_url="https://example.test/7",
        )
    ]
    Queue(q.path).tick(remote, 140)
    assert len(remote.sent) == 5
    assert q.status(job["id"])[0]["state"] == "success"


def test_uncertain_dispatch_is_never_resent(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.ci_coordinator.time.sleep", lambda _: None)
    q = Queue(tmp_path / "queue.db")
    remote = Remote()
    remote.fail = True
    job = q.enqueue("a", "a" * 40, ["x.spec.ts"])
    q.tick(remote, 100)
    Queue(q.path).tick(remote, 800)
    assert len(remote.sent) == 1
    assert q.status(job["id"])[0]["state"] == "attention"


def test_rate_reserve_and_cached_poll(tmp_path):
    q = Queue(tmp_path / "queue.db")
    remote = Remote()
    remote.remaining = 101
    q.enqueue("a", "a" * 40, ["x.spec.ts"])
    q.tick(remote, 100)
    remote.remaining = 5000
    q.tick(remote, 499)
    assert not remote.sent
