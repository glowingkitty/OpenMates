# contract-test-file: tooling
"""Exercise CI admission against a deterministic GitHub transport.

These tests verify concurrency, process recovery and ambiguous network sends.
No requests are sent and no shared Docker resources are read or changed.
The queue is shared by all Codex callers rather than polled per task.
See docs/plans/isolated-github-tests/plan.yml.
"""

from concurrent.futures import ThreadPoolExecutor
import datetime as dt

from scripts.ci_coordinator import Queue, GitHub, GitHubError, enqueue_submission


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


def test_e2e_submission_splits_specs_into_independent_jobs(tmp_path):
    import json
    import pytest

    queue = Queue(tmp_path / "queue.db")
    jobs = enqueue_submission(
        queue,
        "owner",
        "a" * 40,
        ["second.spec.ts", "first.spec.ts", "first.spec.ts"],
        "e2e",
    )
    assert [json.loads(job["specs"]) for job in jobs] == [
        ["first.spec.ts"],
        ["second.spec.ts"],
    ]
    with pytest.raises(ValueError, match="exactly one spec"):
        queue.enqueue(
            "owner", "a" * 40, ["first.spec.ts", "second.spec.ts"], "e2e"
        )
    with pytest.raises(ValueError, match="explicit specs"):
        enqueue_submission(queue, "owner", "a" * 40, [], "e2e")


def test_component_submission_is_one_spec_per_github_job(tmp_path):
    import json

    queue = Queue(tmp_path / "queue.db")
    jobs = enqueue_submission(
        queue,
        "owner",
        "a" * 40,
        ["components/a.spec.ts", "components/b.spec.ts"],
        "component",
    )
    assert [json.loads(job["specs"]) for job in jobs] == [
        ["components/a.spec.ts"],
        ["components/b.spec.ts"],
    ]


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


def test_known_run_outside_listing_uses_persisted_id(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.ci_coordinator.time.sleep", lambda _: None)
    q = Queue(tmp_path / "queue.db")
    remote = Remote()
    job = q.enqueue("a", "a" * 40, ["x.spec.ts"])
    q.tick(remote, 100)
    with q.connect() as db:
        db.execute("UPDATE jobs SET run_id=7, state='running'")
    remote.run = lambda run_id: dict(
        id=run_id,
        display_title=job["token"],
        status="completed",
        conclusion="success",
        html_url="https://example.test/7",
    )
    q.tick(remote, 140)
    assert q.status(job["id"])[0]["state"] == "success"
    assert len(remote.sent) == 1


def test_result_rate_reserve_and_cached_receipt(tmp_path):
    import json
    import pytest

    q = Queue(tmp_path / "queue.db")
    remote = Remote()
    remote.remaining = 100
    job = q.enqueue("a", "a" * 40, ["x.spec.ts"])
    fetched = []
    with pytest.raises(GitHubError):
        q.result(remote, job["id"], tmp_path, lambda *args: fetched.append(args))
    assert not fetched
    receipt = tmp_path / "test-results/ci-runs" / job["id"] / "receipt.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({"cached": True}))
    remote.budget = lambda: pytest.fail("Cached evidence must not query GitHub")
    def validate_cached(github, selected, root):
        assert selected["id"] == job["id"]
        return {**json.loads(receipt.read_text()), "validated": True}
    assert q.result(remote, job["id"], tmp_path, validate_cached) == {"cached": True, "validated": True}


def test_proof_profiles_have_distinct_idempotent_requests(tmp_path):
    q = Queue(tmp_path / "queue.db")
    ordinary = q.enqueue("a", "a" * 40, ["x.spec.ts"])
    phone = q.enqueue("a", "a" * 40, ["x.spec.ts"], proof_profile="web-phone")
    laptop = q.enqueue("a", "a" * 40, ["x.spec.ts"], proof_profile="web-laptop")
    assert len({ordinary["id"], phone["id"], laptop["id"]}) == 3
    assert (
        q.enqueue("a", "a" * 40, ["x.spec.ts"], proof_profile="web-phone")["id"]
        == phone["id"]
    )


def test_owned_prerequisite_runs_first_without_exceeding_four_slots(tmp_path):
    import pytest
    queue = Queue(tmp_path / "queue.db")
    jobs = [queue.enqueue("owner", "a" * 40, [f"{n}.spec.ts"]) for n in range(6)]
    with pytest.raises(ValueError, match="owned queued"):
        queue.prioritize(jobs[-1]["id"], "other", "repair")
    queue.prioritize(jobs[-1]["id"], "owner", "verify framework repair")
    with pytest.raises(ValueError, match="still pending"):
        queue.prioritize(jobs[-2]["id"], "owner", "another repair")
    remote = Remote()
    queue.tick(remote, 100)
    assert len(remote.sent) == 4
    assert remote.sent[0]["id"] == jobs[-1]["id"]
    assert queue.status(jobs[-1]["id"])[0]["source"] == "a" * 40


def test_candidate_identity_is_persisted_and_dispatched_from_base(tmp_path, monkeypatch):
    queue = Queue(tmp_path / "queue.db")
    candidate = {
        "source": "c" * 40,
        "base": "b" * 40,
        "tree": "d" * 40,
        "session": "owner",
        "patch_sha256": "e" * 64,
        "patch_url": "https://nbg1.your-objectstorage.com/private.patch?signature=test",
        "artifact_expires_at": (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat(),
    }
    job = queue.enqueue("owner", "c" * 40, ["x.spec.ts"], candidate=candidate)
    assert job["candidate_base"] == "b" * 40
    github = GitHub.__new__(GitHub)
    github.repo = "example/repo"
    requests = []
    github.request = lambda endpoint, payload=None: requests.append((endpoint, payload))
    github.dispatch(job)
    inputs = requests[0][1]["inputs"]
    assert inputs["checkout_ref"] == "b" * 40
    assert inputs["source_commit"] == "c" * 40
    assert inputs["candidate_patch_sha256"] == "e" * 64


def test_json_receipts_redact_presigned_candidate_url(capsys):
    from scripts.ci_coordinator import print_receipt

    print_receipt({"candidate_patch_url": "https://secret", "source": "a" * 40}, as_json=True)
    value = __import__("json").loads(capsys.readouterr().out)
    assert value["candidate_patch_url"] == "<redacted>"
    assert value["source"] == "a" * 40
