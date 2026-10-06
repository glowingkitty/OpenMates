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


def test_focused_vitest_submission_admits_only_unit_paths(tmp_path):
    import json
    import pytest

    queue = Queue(tmp_path / "queue.db")
    targets = [
        "frontend/packages/ui/src/services/db/__tests__/messageEmbedBundleJournal.test.ts",
        "frontend/apps/web_app/src/lib/selected.test.tsx",
        "frontend/packages/openmates-cli/tests/embedCreatorDurability.test.ts",
    ]
    jobs = enqueue_submission(queue, "owner", "a" * 40, targets, "vitest")
    assert len(jobs) == 1
    assert json.loads(jobs[0]["specs"]) == sorted(targets)
    for rejected in (
        "frontend/apps/web_app/tests/storage-capacity-replay.spec.ts",
        "frontend/packages/openmates-cli/tests/unsupported.test.tsx",
        "frontend/packages/ui/src/../../outside.test.ts",
        "/frontend/packages/ui/src/absolute.test.ts",
    ):
        with pytest.raises(ValueError, match="Invalid spec path"):
            queue.enqueue("owner", "a" * 40, [rejected], "vitest")
    with pytest.raises(ValueError, match="Invalid spec path"):
        queue.enqueue("owner", "a" * 40, [targets[0]], "e2e")


def test_four_slots_and_completion_release(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.ci_coordinator.time.sleep", lambda _: None)
    q = Queue(tmp_path / "queue.db", max_active=4, lightweight_reserve=0)
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
    Queue(q.path, max_active=4, lightweight_reserve=0).tick(remote, 140)
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
    queue = Queue(tmp_path / "queue.db", max_active=4, lightweight_reserve=0)
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


def test_text_receipts_expose_retained_evidence_and_upload_action(tmp_path, capsys):
    from scripts.ci_coordinator import print_receipt
    from scripts.ci_results import attach_visual_evidence

    receipt = attach_visual_evidence({
        "id": "check", "state": "success", "source_commit": "a" * 40,
        "run_id": 9, "selected_specs": ["chat.spec.ts"],
        "directory": str(tmp_path),
        "candidate_patch_url": "https://private.example.test/source",
    }, tmp_path)
    print_receipt(receipt)
    output = capsys.readouterr().out
    assert f"directory: {tmp_path}" in output
    assert f"codex_evidence: {tmp_path / 'codex-evidence.json'}" in output
    assert f"codex_evidence_command: python3 scripts/codex_evidence.py {tmp_path} --upload" in output
    assert "private.example.test" not in output


def test_failed_wait_exposes_recording_retrieval_without_changing_verdict(tmp_path, monkeypatch, capsys):
    import sys
    from scripts import ci_coordinator as coordinator

    queue = Queue(tmp_path / "queue.db")
    job = queue.enqueue("owner", "a" * 40, ["chat.spec.ts"])
    monkeypatch.setattr(coordinator, "canonical_root", lambda path: tmp_path)
    monkeypatch.setattr(coordinator, "Queue", lambda path: queue)
    # Evidence retrieval stays explicit, so missing artifacts cannot hide the
    # original failure and waiting does not consume extra GitHub calls.
    monkeypatch.setattr(coordinator, "GitHub", lambda root: (_ for _ in ()).throw(AssertionError("unexpected network access")))
    for state in ("failure", "cancelled"):
        monkeypatch.setattr(coordinator, "wait_for_job", lambda *a, **kw: {**job, "state": state, "run_id": 9})
        monkeypatch.setattr(sys, "argv", ["ci_coordinator.py", "wait", job["id"]])
        assert coordinator.main() == 1
        output = capsys.readouterr().out
        assert f"{job['id']}: {state}" in output
        assert f"result_command: python3 scripts/ci_coordinator.py result {job['id']}" in output

    monkeypatch.setattr(coordinator, "wait_for_job", lambda *a, **kw: {**job, "state": "cancelled", "run_id": None})
    assert coordinator.main() == 1
    assert "result_command:" not in capsys.readouterr().out


def test_json_receipts_redact_presigned_candidate_url(capsys):
    from scripts.ci_coordinator import print_receipt

    print_receipt({"candidate_patch_url": "https://secret", "source": "a" * 40}, as_json=True)
    value = __import__("json").loads(capsys.readouterr().out)
    assert value["candidate_patch_url"] == "<redacted>"
    assert value["source"] == "a" * 40


def test_preparation_dispatch_uses_private_capability_ticket(tmp_path, monkeypatch):
    import sys
    import types

    queue = Queue(tmp_path / "queue.db")
    job = queue.enqueue(
        "owner",
        "a" * 40,
        [],
        "prepare",
        preparation={"key": "f" * 64, "harness_commit": "b" * 40},
    )
    signed = []
    ticket = '{"private":"capability-not-for-status"}'
    def dispatch_ticket(root, request):
        signed.append((root, request["id"]))
        return ticket
    monkeypatch.setitem(sys.modules, "scripts.ci_preparation_transport", types.SimpleNamespace(dispatch_ticket=dispatch_ticket))
    github = GitHub.__new__(GitHub)
    github.root = tmp_path
    github.repo = "example/repo"
    requests = []
    github.request = lambda endpoint, payload=None: requests.append(payload)
    github.dispatch(job)
    assert signed == [(tmp_path, job["id"])]
    assert requests[0]["inputs"]["preparation_transport"] == ticket
    assert requests[0]["inputs"]["harness_commit"] == "b" * 40
    assert all("preparation_transport" not in row for row in queue.status())


def test_private_transport_failure_is_before_intent_and_does_not_stop_queue(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.ci_coordinator.time.sleep", lambda _: None)
    queue = Queue(tmp_path / "queue.db")
    producer = queue.enqueue(
        "owner",
        "a" * 40,
        [],
        "prepare",
        preparation={"key": "f" * 64, "harness_commit": "b" * 40},
    )
    light = queue.enqueue("other", "b" * 40, ["components/x.spec.ts"], "component")
    remote = Remote()
    def prepare_dispatch(job):
        if job["mode"] == "prepare":
            raise RuntimeError("do-not-log-private-capability")
        return job
    remote.prepare_dispatch = prepare_dispatch
    queue.tick(remote, 100)
    failed = queue.status(producer["id"])[0]
    assert failed["state"] == "failure"
    assert failed["sent"] is None
    assert "do-not-log" not in failed["error"]
    assert [job["id"] for job in remote.sent] == [light["id"]]


def test_unpublished_candidate_shares_private_preparation(tmp_path, monkeypatch):
    queue = Queue(tmp_path / "queue.db")
    candidate = {
        "source": "c" * 40, "base": "b" * 40, "tree": "d" * 40, "session": "owner",
        "patch_sha256": "e" * 64,
        "patch_url": "https://nbg1.your-objectstorage.com/private.patch?signature=test",
        "artifact_expires_at": (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat(),
    }
    monkeypatch.setattr(
        "scripts.ci_coordinator.subprocess.check_output",
        lambda *args, **kwargs: '{"groups":{"uploads":{"specs":[]}}}',
    )
    monkeypatch.setattr("scripts.ci_coordinator.harness_commit", lambda _: "a" * 40)
    jobs = enqueue_submission(
        queue, "owner", "c" * 40, ["first.spec.ts", "second.spec.ts"], "e2e",
        candidate=candidate, source_root=tmp_path, prepared_builds=True,
    )
    assert len(jobs) == 2
    assert len(queue.status()) == 3
    assert jobs[0]["preparation_id"] == jobs[1]["preparation_id"]
    producer = queue.status(jobs[0]["preparation_id"])[0]
    assert producer["mode"] == "prepare"
    assert all(job["candidate_patch_sha256"] == "e" * 64 for job in jobs)


def test_ordinary_e2es_do_not_depend_on_unverified_preparation(tmp_path):
    queue = Queue(tmp_path / "queue.db")
    jobs = enqueue_submission(
        queue, "owner", "a" * 40, ["first.spec.ts", "second.spec.ts"], "e2e",
        source_root=tmp_path,
    )
    assert len(jobs) == len(queue.status()) == 2
    assert all(not job["preparation_id"] and not job["preparation_key"] for job in jobs)


def test_prepared_canary_rejects_component_mode(tmp_path):
    import pytest

    queue = Queue(tmp_path / "queue.db")
    with pytest.raises(ValueError, match="Prepared builds"):
        enqueue_submission(
            queue, "owner", "a" * 40, ["components/one.spec.ts"], "component",
            source_root=tmp_path, prepared_builds=True,
        )


def test_four_slots_lend_idle_reservation_and_share_owners(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.ci_coordinator.time.sleep", lambda _: None)
    queue = Queue(tmp_path / "queue.db", max_active=4)
    for n in range(6):
        queue.enqueue("bulk", "a" * 40, [f"{n}.spec.ts"])
    other = queue.enqueue("other", "a" * 40, ["other.spec.ts"])
    remote = Remote()
    queue.tick(remote, 100)
    assert len(remote.sent) == 4
    assert other["id"] in {job["id"] for job in remote.sent}
    fast = queue.enqueue("quick", "b" * 40, ["components/x.spec.ts"], "component")
    released = remote.sent[0]
    remote.visible = [dict(display_title=released["token"], status="completed", conclusion="success", id=7, html_url="https://example.test/7")]
    queue.tick(remote, 140)
    assert len(remote.sent) == 5
    assert remote.sent[-1]["id"] == fast["id"]


def test_default_twenty_slots_lend_idle_lightweight_reservation(tmp_path, monkeypatch):
    import json

    monkeypatch.delenv("OPENMATES_CI_MAX_ACTIVE", raising=False)
    monkeypatch.delenv("OPENMATES_CI_LIGHTWEIGHT_RESERVE", raising=False)
    monkeypatch.setattr("scripts.ci_coordinator.time.sleep", lambda _: None)
    queue = Queue(tmp_path / "queue.db")
    assert (queue.max_active, queue.lightweight_reserve) == (20, 1)
    for n in range(22):
        queue.enqueue("bulk", "a" * 40, [f"bulk-{n}.spec.ts"])
    remote = Remote()
    queue.tick(remote, 100)
    assert len(remote.sent) == 20
    assert all(job["mode"] == "e2e" for job in remote.sent)

    fast = queue.enqueue("quick", "b" * 40, ["components/fast.spec.ts"], "component")
    released = remote.sent[0]
    remote.visible = [dict(display_title=released["token"], status="completed", conclusion="success", id=7, html_url="https://example.test/7")]
    queue.tick(remote, 140)
    assert len(remote.sent) == 21
    assert remote.sent[-1]["id"] == fast["id"]
    assert len([job for job in queue.status() if job["state"] == "queued"]) == 2
    with queue.connect() as db:
        assert json.loads(queue.metadata(db, "capacity")) == {
            "total": 20, "lightweight_reserved": 1, "active": 20,
            "external": 0, "selfhosted_total": 1, "selfhosted_active": 0,
            "selfhosted_external": 0,
        }


def test_environment_capacity_override_lends_reservation(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENMATES_CI_MAX_ACTIVE", "6")
    monkeypatch.setenv("OPENMATES_CI_LIGHTWEIGHT_RESERVE", "2")
    monkeypatch.setattr("scripts.ci_coordinator.time.sleep", lambda _: None)
    queue = Queue(tmp_path / "queue.db")
    assert (queue.max_active, queue.lightweight_reserve) == (6, 2)
    for n in range(8):
        queue.enqueue("bulk", "a" * 40, [f"bulk-{n}.spec.ts"])
    remote = Remote()
    queue.tick(remote, 100)
    assert len(remote.sent) == 6
    for n in range(2):
        queue.enqueue("quick", "b" * 40, [f"components/fast-{n}.spec.ts"], "component")
    remote.visible = [dict(display_title=job["token"], status="completed", conclusion="success", id=number, html_url="https://example.test/7") for number, job in enumerate(remote.sent[:2], 1)]
    queue.tick(remote, 140)
    assert len(remote.sent) == 8
    assert all(job["mode"] == "component" for job in remote.sent[-2:])


def test_reopened_queue_adopts_higher_cap_without_resending_active_jobs(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENMATES_CI_MAX_ACTIVE", raising=False)
    monkeypatch.delenv("OPENMATES_CI_LIGHTWEIGHT_RESERVE", raising=False)
    monkeypatch.setattr("scripts.ci_coordinator.time.sleep", lambda _: None)
    path = tmp_path / "queue.db"
    queue = Queue(path, max_active=4)
    for n in range(12):
        queue.enqueue("bulk", "a" * 40, [f"bulk-{n}.spec.ts"])
    remote = Remote()
    queue.tick(remote, 100)
    assert len(remote.sent) == 4
    before = {job["id"] for job in remote.sent}

    resumed = Queue(path)
    resumed.tick(remote, 140)
    assert len(remote.sent) == 12
    assert before.issubset({job["id"] for job in remote.sent})
    assert len({job["id"] for job in remote.sent}) == 12
    fast = resumed.enqueue("quick", "b" * 40, ["components/fast.spec.ts"], "component")
    released = remote.sent[0]
    remote.visible = [dict(display_title=released["token"], status="completed", conclusion="success", id=7, html_url="https://example.test/7")]
    resumed.tick(remote, 180)
    assert len(remote.sent) == 13
    assert remote.sent[-1]["id"] == fast["id"]


def test_supersession_preserves_other_owners_scopes_and_running_jobs(tmp_path):
    queue = Queue(tmp_path / "queue.db")
    old = queue.enqueue("owner", "a" * 40, ["x.spec.ts"])
    other = queue.enqueue("other", "a" * 40, ["x.spec.ts"])
    different = queue.enqueue("owner", "a" * 40, ["y.spec.ts"])
    running = queue.enqueue("owner", "b" * 40, ["x.spec.ts"])
    with queue.connect() as db:
        db.execute("UPDATE jobs SET state='running',sent=1 WHERE id=?", (running["id"],))
    new = enqueue_submission(queue, "owner", "c" * 40, ["x.spec.ts"], "e2e")[0]
    assert queue.status(old["id"])[0]["state"] == "cancelled"
    assert queue.status(running["id"])[0]["state"] == "running"
    assert all(queue.status(job["id"])[0]["state"] == "queued" for job in (other, different, new))


def test_preparation_gates_consumers_and_records_exact_run(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.ci_coordinator.time.sleep", lambda _: None)
    queue = Queue(tmp_path / "queue.db")
    preparation = {
        "key": "f" * 64,
        "harness_commit": "b" * 40,
        "cli": True,
        "upload": False,
    }
    producer = queue.enqueue("owner", "a" * 40, [], "prepare", preparation=preparation)
    first = queue.enqueue("owner", "a" * 40, ["first.spec.ts"], preparation={**preparation, "id": producer["id"]})
    second = queue.enqueue("owner", "a" * 40, ["second.spec.ts"], preparation={**preparation, "id": producer["id"]})
    remote = Remote()
    queue.tick(remote, 100)
    assert [job["id"] for job in remote.sent] == [producer["id"]]
    assert queue.status(first["id"])[0]["phase"] == "waiting for preparation"
    remote.visible = [dict(display_title=producer["token"], status="completed", conclusion="success", id=42, html_url="https://example.test/42")]
    queue.tick(remote, 140)
    assert {job["id"] for job in remote.sent[1:]} == {first["id"], second["id"]}
    assert all(job["prepared_run_id"] == 42 for job in remote.sent[1:])


def test_failed_preparation_does_not_dispatch_or_credit_tests(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.ci_coordinator.time.sleep", lambda _: None)
    queue = Queue(tmp_path / "queue.db")
    preparation = {"key": "f" * 64, "harness_commit": "b" * 40}
    producer = queue.enqueue("owner", "a" * 40, [], "prepare", preparation=preparation)
    child = queue.enqueue("owner", "a" * 40, ["x.spec.ts"], preparation={**preparation, "id": producer["id"]})
    remote = Remote()
    queue.tick(remote, 100)
    remote.visible = [dict(display_title=producer["token"], status="completed", conclusion="failure", id=42, html_url="https://example.test/42")]
    queue.tick(remote, 140)
    assert len(remote.sent) == 1
    assert queue.status(child["id"])[0]["state"] == "failure"


def test_pytest_exact_nodes_are_not_browser_paths(tmp_path):
    import pytest
    queue = Queue(tmp_path / "queue.db")
    node = "backend/tests/test_example.py::test_regression"
    assert __import__("json").loads(queue.enqueue("owner", "a" * 40, [node], "pytest")["specs"]) == [node]
    with pytest.raises(ValueError):
        queue.enqueue("owner", "a" * 40, ["../test_example.py"], "pytest")


def test_interleaved_submission_cannot_cancel_unattached_producer(tmp_path):
    queue = Queue(tmp_path / "queue.db")
    preparation = {"key": "f" * 64, "harness_commit": "b" * 40}
    producer = queue.enqueue("owner", "a" * 40, [], "prepare", preparation=preparation)
    enqueue_submission(queue, "owner", "b" * 40, ["other.spec.ts"], "e2e")
    child = queue.enqueue("owner", "a" * 40, ["x.spec.ts"], preparation={**preparation, "id": producer["id"]})
    assert queue.status(producer["id"])[0]["state"] == "queued"
    assert child["preparation_id"] == producer["id"]


def test_refreshing_candidate_url_retains_logical_request(tmp_path):
    queue = Queue(tmp_path / "queue.db")
    candidate = {
        "source": "c" * 40, "base": "b" * 40, "tree": "d" * 40, "session": "owner",
        "patch_sha256": "e" * 64,
        "patch_url": "https://nbg1.your-objectstorage.com/private.patch?signature=first",
        "artifact_expires_at": (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat(),
    }
    first = queue.enqueue("owner", "c" * 40, ["x.spec.ts"], candidate=candidate)
    candidate["patch_url"] = "https://nbg1.your-objectstorage.com/private.patch?signature=refreshed"
    candidate["artifact_expires_at"] = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)).isoformat()
    second = queue.enqueue("owner", "c" * 40, ["x.spec.ts"], candidate=candidate)
    assert first["id"] == second["id"]
    assert second["candidate_patch_url"] == candidate["patch_url"]
    assert second["candidate_expires"] > first["candidate_expires"]


def test_uncertain_remote_reserves_capacity_but_not_lightweight_slot(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.ci_coordinator.time.sleep", lambda _: None)
    queue = Queue(tmp_path / "queue.db", max_active=4)
    remote = Remote()
    uncertain = queue.enqueue("owner", "a" * 40, ["x.spec.ts"])
    with queue.connect() as db:
        db.execute("UPDATE jobs SET state='attention',sent=1 WHERE id=?", (uncertain["id"],))
    for n in range(4):
        queue.enqueue("bulk", "a" * 40, [f"bulk-{n}.spec.ts"])
    fast = queue.enqueue("quick", "b" * 40, ["components/x.spec.ts"], "component")
    queue.tick(remote, 100)
    assert len(remote.sent) == 3
    assert fast["id"] in {job["id"] for job in remote.sent}
    assert uncertain["id"] not in {job["id"] for job in remote.sent}


def test_owner_occupancy_deducts_external_hosted_jobs_and_selfhosted_is_separate(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.ci_coordinator.time.sleep", lambda _: None)
    queue = Queue(tmp_path / "queue.db", max_active=12, max_selfhosted=1)
    remote = Remote()
    remote.account_occupancy = lambda tokens: {"hosted": 3, "selfhosted": 0}
    for n in range(14):
        queue.enqueue(f"owner-{n}", "a" * 40, [f"{n}.spec.ts"])
    target = queue.enqueue("capacity", "a" * 40, ["ordinary.spec.ts"])
    with queue.connect() as db:
        db.execute("UPDATE jobs SET specs=? WHERE id=?", ('["storage-capacity-target.spec.ts"]', target["id"]))
    queue.tick(remote, 100)
    assert len(remote.sent) == 10
    assert sum(job["mode"] == "e2e" and job["id"] != target["id"] for job in remote.sent) == 9
    assert target["id"] in {job["id"] for job in remote.sent}
    assert len({job["id"] for job in remote.sent}) == 10
    queue.tick(remote, 140)
    assert len(remote.sent) == 10


def test_account_scan_runs_only_when_new_admission_is_ready(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.ci_coordinator.time.sleep", lambda _: None)
    queue = Queue(tmp_path / "queue.db")
    remote = Remote()
    scans = []
    remote.account_occupancy = lambda tokens: (scans.append(tokens) or {"hosted": 2, "selfhosted": 0})
    queue.enqueue("one", "a" * 40, ["one.spec.ts"])
    queue.tick(remote, 100)
    assert len(scans) == 1
    queue.tick(remote, 250)
    assert len(scans) == 1
    queue.enqueue("two", "a" * 40, ["two.spec.ts"])
    queue.tick(remote, 300)
    assert len(scans) == 2
    assert len(remote.sent) == 2


def test_failed_occupancy_discovery_does_not_dispatch(tmp_path):
    queue = Queue(tmp_path / "queue.db")
    remote = Remote()
    remote.account_occupancy = lambda tokens: (_ for _ in ()).throw(GitHubError("discovery unavailable", 200))
    queue.enqueue("owner", "a" * 40, ["x.spec.ts"])
    queue.tick(remote, 100)
    assert remote.sent == []
    with queue.connect() as db:
        assert float(queue.metadata(db, "next_poll")) >= 200


def test_account_occupancy_counts_jobs_and_excludes_managed_runs():
    github = GitHub.__new__(GitHub)
    github.repo = "owner/current"
    calls = []

    def request(endpoint):
        calls.append(endpoint)
        if endpoint == "users/owner":
            return {"type": "User"}
        if endpoint.startswith("user/repos?"):
            return [{"full_name": "owner/current"}, {"full_name": "owner/other"}]
        if "created=%3E%3D" in endpoint:
            if endpoint.startswith("repos/owner/current/"):
                return {"total_count": 1, "workflow_runs": [{"id": 1, "status": "in_progress", "display_title": "managed-token"}]}
            return {"total_count": 1, "workflow_runs": [{"id": 2, "status": "in_progress", "display_title": "other workflow"}]}
        if endpoint == "repos/owner/other/actions/runs/2/jobs?per_page=100":
            return {"total_count": 2, "jobs": [
                {"status": "in_progress", "labels": ["ubuntu-latest"]},
                {"status": "queued", "labels": ["self-hosted", "openmates-capacity"]},
            ]}
        raise AssertionError(endpoint)

    github.request = request
    assert github.account_occupancy({"managed-token"}) == {"hosted": 1, "selfhosted": 1}
    assert not any("runs/1/jobs" in endpoint for endpoint in calls)


def test_hosted_entitlement_requires_explicit_validated_upgrade(tmp_path, monkeypatch):
    import pytest

    monkeypatch.delenv("OPENMATES_CI_HOSTED_ENTITLEMENT", raising=False)
    with pytest.raises(ValueError, match="hosted entitlement"):
        Queue(tmp_path / "invalid.db", max_active=40)
    upgraded = Queue(tmp_path / "upgraded.db", max_active=40, hosted_entitlement=40)
    assert upgraded.max_active == upgraded.hosted_entitlement == 40


def test_owner_discovery_fails_closed_when_inventory_exceeds_bound():
    import pytest

    github = GitHub.__new__(GitHub)
    github.repo = "owner/current"
    github.request = lambda endpoint: (
        {"type": "User"} if endpoint == "users/owner" else
        [{"full_name": "owner/current"}] * 100
    )
    with pytest.raises(ValueError, match="100 repositories"):
        github.account_occupancy(set())


def test_fifty_eight_repo_inventory_uses_one_recent_run_query_each():
    github = GitHub.__new__(GitHub)
    github.repo = "owner/current"
    calls = []
    repos = [{"full_name": "owner/current"}] + [
        {"full_name": f"owner/repo-{n}"} for n in range(57)
    ]

    def request(endpoint):
        calls.append(endpoint)
        if endpoint == "users/owner":
            return {"type": "User"}
        if endpoint.startswith("user/repos?"):
            return repos
        if "created=%3E%3D" in endpoint:
            return {"total_count": 0, "workflow_runs": []}
        raise AssertionError(endpoint)

    github.request = request
    assert github.account_occupancy(set()) == {"hosted": 0, "selfhosted": 0}
    assert len(calls) == 60


def test_busy_repo_falls_back_to_all_active_statuses_for_old_run():
    github = GitHub.__new__(GitHub)
    github.repo = "owner/current"
    statuses = []

    def request(endpoint):
        if endpoint == "users/owner":
            return {"type": "User"}
        if endpoint.startswith("user/repos?"):
            return [{"full_name": "owner/current"}]
        if "created=%3E%3D" in endpoint:
            return {"total_count": 101, "workflow_runs": [{"id": n, "status": "completed"} for n in range(100)]}
        if "status=" in endpoint:
            status = endpoint.split("status=", 1)[1].split("&", 1)[0]
            statuses.append(status)
            return {"total_count": 1 if status == "in_progress" else 0,
                    "workflow_runs": [{"id": 1000, "status": status}] if status == "in_progress" else []}
        if endpoint.endswith("runs/1000/jobs?per_page=100"):
            return {"total_count": 1, "jobs": [{"status": "in_progress", "labels": ["ubuntu-latest"]}]}
        raise AssertionError(endpoint)

    github.request = request
    assert github.account_occupancy(set()) == {"hosted": 1, "selfhosted": 0}
    assert set(statuses) == {"in_progress", "queued", "waiting", "pending", "requested"}


def test_account_discovery_obeys_serialized_rate_reserve(tmp_path):
    queue = Queue(tmp_path / "queue.db")
    queue.enqueue("owner", "a" * 40, ["x.spec.ts"])
    remote = Remote()
    remote.remaining = 100 + 80 + 2 * queue.max_active + 1
    remote.account_occupancy = lambda tokens: (_ for _ in ()).throw(AssertionError("must not discover below reserve"))
    queue.tick(remote, 100)
    assert remote.sent == []
