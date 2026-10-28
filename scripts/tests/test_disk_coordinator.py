# contract-test-file: tooling
"""Disk coordination contracts, using isolated ledgers and actual child owners."""

import os
import subprocess
import sys
import threading
import uuid
from collections import namedtuple

import pytest

from scripts import disk_coordinator as disk
from scripts import resource_budget as budget

Usage = namedtuple("Usage", "total used free")


def fixture(tmp_path, *, free=200, used=800, kinds=()):
    now = [1000.0]
    usage = [Usage(1000, used, free)]
    root = tmp_path / "repo"
    root.mkdir()
    c = disk.Coordinator(
        tmp_path / "host",
        usage=lambda _: usage[0],
        inodes=lambda _: 100000,
        clock=lambda: now[0],
    )
    c.register(root, maintenance=kinds)
    return c, root, now, usage


def request(c, root, *, operation="build", thread=None, amount=70):
    return c.request(
        root,
        amount,
        operation=operation,
        thread=thread or str(uuid.uuid4()),
        min_free=50,
        max_used_percent=99,
        min_inodes=10,
    )


def test_shared_filesystem_admission_cannot_overcommit_across_repositories(tmp_path):
    c, root, _, _ = fixture(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    c.register(other, maintenance=())
    requests = []
    errors = []

    def enqueue(i):
        try:
            requests.append(request(c, other if i % 2 else root, operation=str(i)))
        except BaseException as error:
            errors.append(error)

    threads = [threading.Thread(target=enqueue, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert not errors and len(requests) == 8
    with c.leadership():
        c.tick(recovery_margin=0)
        rows = c.requests(root) + c.requests(other)
        assert sum(r["amount"] for r in rows if r["state"] == "granted") == 140
        assert sum(r["state"] == "waiting" for r in rows) == 6
        with pytest.raises(BlockingIOError):
            with disk.Coordinator(c.root).leadership():
                pytest.fail("second cleanup owner")


def test_chat_wait_survives_tool_exit_and_retries_reuse_only_current_cycle(tmp_path):
    c, root, _, _ = fixture(tmp_path)
    thread = str(uuid.uuid4())
    code = """from scripts.disk_coordinator import Coordinator
import sys
c=Coordinator(sys.argv[1]); print(c.request(sys.argv[2],70,operation='build',thread=sys.argv[3],min_free=50,max_used_percent=99,min_inodes=10)['id'])"""
    child = subprocess.run(
        [sys.executable, "-c", code, str(c.root), str(root), thread],
        capture_output=True,
        text=True,
        check=True,
    )
    first = child.stdout.strip()
    with c.leadership():
        c.tick(recovery_margin=0)
        assert c.get(first)["state"] == "granted"
        retried = request(c, root, thread=thread)
        assert retried["id"] == first
        claim = c.claim(first, retried["grant_id"])
        assert claim["state"] == "claimed"
        c.release(first)
        assert request(c, root, thread=thread)["id"] != first


def test_zero_progress_cleanup_is_coalesced_and_backs_off(tmp_path):
    c, root, now, _ = fixture(tmp_path, free=100, used=900, kinds=("managed",))
    for i in range(5):
        request(c, root, operation=str(i))
    calls = []
    with c.leadership():
        for _ in range(5):
            c.tick(
                cleaner=lambda *args: (
                    calls.append(args) or {"reclaimed_estimate_bytes": 0}
                ),
                recovery_margin=0,
            )
        assert calls == [(str(root), "managed")]
        assert all(
            r["state"] == "waiting" and "additional bytes" in r["reason"]
            for r in c.requests(root)
        )
        c.enqueue_maintenance(root, "managed")
        c.tick(cleaner=lambda *args: calls.append(args))
        assert len(calls) == 1
        now[0] += disk.CLEANUP_BACKOFF + 1
        c.tick(cleaner=lambda *args: calls.append(args), recovery_margin=0)
        assert len(calls) == 2  # pressure and cron request share one pass


def test_old_workspace_ceiling_does_not_freeze_ci_and_keeps_its_peak(tmp_path):
    c, root, now, usage = fixture(tmp_path)
    oldest = c.request(root, 70, operation="workspace", thread=str(uuid.uuid4()),
                       min_free=50, max_used_percent=85, min_inodes=10)
    now[0] += 61
    ci = request(c, root, operation="ci-source", amount=10)
    large = request(c, root, operation="large", amount=140)
    with c.leadership():
        c.tick(recovery_margin=0)
        assert c.get(oldest["id"])["state"] == "waiting"
        assert "ceiling=85" in c.get(oldest["id"])["reason"]
        assert "21 additional bytes" in c.get(oldest["id"])["reason"]
        assert c.get(ci["id"])["state"] == "granted"
        assert c.get(large["id"])["state"] == "waiting"
        # The older workspace gets first use of capacity recovered by cleanup.
        usage[0] = Usage(1000, 750, 250)
        c.tick(recovery_margin=0)
        assert c.get(oldest["id"])["state"] == "granted"


def test_cleanup_remeasures_before_resuming_and_keeps_recovery_margin(tmp_path):
    c, root, now, usage = fixture(tmp_path, free=100, used=900, kinds=("managed",))
    row = request(c, root)

    def clean(*_):
        usage[0] = Usage(1000, 790, 210)
        return {"reclaimed_estimate_bytes": 110}

    with c.leadership():
        c.tick(cleaner=clean, recovery_margin=80)
        assert c.get(row["id"])["state"] == "waiting"
        c.tick(cleaner=clean, recovery_margin=100)
        assert c.get(row["id"])["state"] == "waiting"  # 210-70 < 50+100
        usage[0] = Usage(1000, 750, 250)
        c.tick(cleaner=clean, recovery_margin=100)
        assert c.get(row["id"])["state"] == "granted"


def test_expiry_and_actual_materialization_do_not_double_book(tmp_path):
    c, root, now, usage = fixture(tmp_path)
    row = request(c, root)
    with c.leadership():
        c.tick(recovery_margin=0)
        grant = c.get(row["id"])["grant_id"]
        c.acknowledge(row["id"], grant)
        assert c.get(row["id"])["outstanding"] == 70
        now[0] += disk.GRANT_SECONDS + 1
        assert not c.valid_grant(row["id"], grant)
        c.tick(recovery_margin=0)
        row = c.get(row["id"])
        assert row["grant_id"] != grant
        c.claim(row["id"], row["grant_id"])
        usage[0] = Usage(1000, 850, 150)
        c.materialized(row["id"], 50)
        assert c.get(row["id"])["outstanding"] == 20
        second = request(c, root, operation="second")
        c.tick(recovery_margin=0)
        assert c.get(second["id"])["state"] == "granted"  # 150-20-70 >= 50
        with pytest.raises(RuntimeError, match="peak"):
            c.materialized(row["id"], 71)


def test_capacity_loss_before_claim_returns_to_waiting(tmp_path):
    c, root, _, usage = fixture(tmp_path)
    row = request(c, root)
    with c.leadership():
        c.tick(recovery_margin=0)
        granted = c.get(row["id"])
        usage[0] = Usage(1000, 980, 20)
        assert c.claim(row["id"], granted["grant_id"]) is None
        assert c.get(row["id"])["state"] == "waiting"


def test_once_inferred_task_is_bound_and_cannot_transfer_to_another_task(tmp_path):
    c, root, _, _ = fixture(tmp_path)
    thread = str(uuid.uuid4())
    row = request(c, root, thread=thread)
    assert c.bind_task(row["id"], thread, "original-task")
    assert not c.bind_task(row["id"], thread, "replacement-task")
    assert not c.bind_task(row["id"], str(uuid.uuid4()), "original-task")
    retried = request(c, root, thread=thread)
    assert retried["id"] == row["id"] and retried["task_id"] == "original-task"
    with pytest.raises(ValueError, match="different capacity"):
        c.request(
            root,
            70,
            operation="build",
            thread=thread,
            task_id="replacement-task",
            min_free=50,
            max_used_percent=99,
            min_inodes=10,
        )


def test_zombie_allocation_owner_releases_only_after_its_group_is_inert(
    tmp_path, monkeypatch
):
    c, root, _, _ = fixture(tmp_path)
    row = request(c, root)
    with c.leadership():
        c.tick(recovery_margin=0)
        row = c.get(row["id"])
        c.claim(row["id"], row["grant_id"])
        from scripts import disk_coordinator_state as state

        monkeypatch.setattr(state, "allocation_exited", lambda _: True)
        with c.db(write=True) as db:
            c._reconcile(db)
        assert c.get(row["id"])["state"] == "complete"


def test_failed_git_identity_resolution_cannot_create_an_independent_budget(
    tmp_path, monkeypatch
):
    root = tmp_path / "linked"
    root.mkdir()
    (root / ".git").write_text("gitdir: unavailable")
    from scripts import disk_coordinator_state as state

    monkeypatch.setattr(
        state.subprocess, "run", lambda *a, **k: type("Result", (), {"returncode": 1})()
    )
    with pytest.raises(RuntimeError, match="identity"):
        state.configured(root)


def test_dead_anonymous_group_leader_does_not_release_live_descendants(
    tmp_path, monkeypatch
):
    c, root, _, _ = fixture(tmp_path)
    row = c.request(
        root,
        70,
        operation="anonymous-owned-group",
        min_free=50,
        max_used_percent=99,
        min_inodes=10,
    )
    with c.leadership():
        c.tick(recovery_margin=0)
        row = c.get(row["id"])
        c.claim(row["id"], row["grant_id"])
        with c.db(write=True) as db:
            db.execute("UPDATE requests SET owner_group=123 WHERE id=?", (row["id"],))
        from scripts import disk_coordinator_state as state

        monkeypatch.setattr(state, "group_alive", lambda _: True)
        monkeypatch.setattr(budget, "_owner_is_dead", lambda _: True)
        with c.db(write=True) as db:
            c._reconcile(db)
        assert c.get(row["id"])["state"] == "claimed"
        assert c.get(row["id"])["outstanding"] == 70


def test_unknown_live_owner_keeps_claim_but_dead_owner_releases_only_commitment(
    tmp_path, monkeypatch
):
    c, root, _, _ = fixture(tmp_path)
    row = request(c, root)
    protected = root / "recovery.patch"
    protected.write_text("unfinished source")
    with c.leadership():
        c.tick(recovery_margin=0)
        row = c.get(row["id"])
        c.claim(row["id"], row["grant_id"])
        actual = budget._start_time
        monkeypatch.setattr(
            budget, "_start_time", lambda pid: "" if pid == os.getpid() else actual(pid)
        )
        # Direct reconciliation isolates unknown owner handling from leadership identity.
        with c.db(write=True) as db:
            c._reconcile(db)
        assert c.get(row["id"])["state"] == "claimed"
        monkeypatch.setattr(budget, "_owner_is_dead", lambda _: True)
        with c.db(write=True) as db:
            c._reconcile(db)
        assert c.get(row["id"])["state"] == "complete"
        assert protected.read_text() == "unfinished source"


def test_unavailable_service_fails_closed_and_preserves_wait(tmp_path, monkeypatch):
    c, root, _, _ = fixture(tmp_path)
    ticks = iter([0, 10])
    monkeypatch.setattr(budget.time, "monotonic", lambda: next(ticks))
    with pytest.raises(disk.DiskWait):
        with budget.reserve(
            root,
            70,
            operation="build",
            thread=str(uuid.uuid4()),
            min_free=50,
            max_used_percent=99,
        ):
            pytest.fail("unavailable service admitted work")
    assert c.requests(root)[0]["state"] == "waiting"


def test_manual_cleanup_queues_instead_of_deleting_after_cutover(tmp_path):
    c, root, _, _ = fixture(tmp_path, kinds=("managed",))
    report = budget.cleanup(root, manifest={"dry_run": True, "root": str(root)})
    assert report["queued"] and report["removed"] == []
    with c.db() as db:
        assert db.execute("SELECT state FROM maintenance").fetchone()[0] == "waiting"


def test_owner_fence_cannot_be_forged_with_an_unrelated_descriptor(
    tmp_path, monkeypatch
):
    c, _, _, _ = fixture(tmp_path)
    with c.leadership():
        unrelated = tmp_path / "unrelated"
        unrelated.write_text("")
        with unrelated.open() as f:
            monkeypatch.setenv("OPENMATES_DISK_OWNER_PID", str(os.getpid()))
            monkeypatch.setenv("OPENMATES_DISK_OWNER_FD", str(f.fileno()))
            assert not disk.owner_check(c)
        monkeypatch.setenv("OPENMATES_DISK_OWNER_FD", str(c._leader.fileno()))
        assert disk.owner_check(c)


def test_disable_preserves_waits_and_refuses_live_grants(tmp_path):
    c, root, _, _ = fixture(tmp_path)
    row = request(c, root)
    with c.leadership():
        c.tick(recovery_margin=0)
        with pytest.raises(RuntimeError, match="outstanding"):
            c.disable(root)
        c.defer(row["id"])
        c.disable(root)
        assert disk.configured(root) is None
        assert c.get(row["id"])["state"] == "waiting"
