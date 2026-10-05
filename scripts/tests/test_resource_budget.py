# contract-test-file: tooling
"""Disk budget and cleanup tests use only isolated fixture directories."""

import json
from datetime import timezone
import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time

import pytest

from scripts import resource_budget as budget


def test_inventory_counts_other_files_after_unsafe_link_without_following_it(tmp_path):
    own = tmp_path / "owned"
    own.mkdir()
    first, second = own / "first", own / "second"
    first.write_bytes(b"a" * 4096)
    second.write_bytes(b"b" * 4096)
    external = tmp_path / "external"
    external.write_bytes(b"x" * 65536)
    link = own / "link"
    link.symlink_to(external)
    count, safe = budget._bytes(own)
    assert safe is False
    assert count == sum(item.lstat().st_blocks * 512 for item in (own, first, second, link))


def _queue(root: Path, rows: list[tuple[str, str, str]]) -> None:
    path = root / "logs/ci-coordinator/queue.sqlite3"
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE jobs (id TEXT, source TEXT, state TEXT, owner TEXT)")
        db.executemany("INSERT INTO jobs VALUES (?,?,?, 'fixture')", rows)


def _result(root: Path, name: str, source: str, *, state="success", delivery="delivered") -> Path:
    path = root / "test-results/ci-runs" / name
    (path / "test-results").mkdir(parents=True)
    (path / "test-results" / "large.webm").write_bytes(b"synthetic video")
    (path / "test-results" / "ci-startup-phases.json").write_text('{"seconds": 1}')
    (path / "test-results" / "ci-runtime-images.json").write_text("{}")
    (path / "test-results" / "ci-artifacts.json").write_text("{}")
    (path / "receipt.json").write_text(json.dumps({"id": name, "source_commit": source,
                                                     "state": state, "cleanup": {"run_id": "1"}}))
    (path / "codex-evidence.json").write_text(json.dumps({"records": {
        "evidence": {"recording": "available", "upload": "uploaded", "delivery": delivery}
    }}))
    old = time.time() - budget.RESULT_AGE_SECONDS - 3600
    os.utime(path / "receipt.json", (old, old))
    return path


def test_concurrent_reservations_reject_second_allocation(tmp_path, monkeypatch):
    monkeypatch.setattr(budget.shutil, "disk_usage", lambda _root: type("Usage", (),
                        {"total": 1000, "used": 800, "free": 200})())
    entered = threading.Event()
    release = threading.Event()
    outcome = []

    def first():
        with budget.reserve(tmp_path, 70, min_free=50, max_used_percent=90):
            entered.set()
            release.wait(timeout=5)

    thread = threading.Thread(target=first)
    thread.start()
    assert entered.wait(timeout=5)
    with pytest.raises(RuntimeError, match="Disk budget exceeded"):
        with budget.reserve(tmp_path, 70, min_free=50, max_used_percent=90):
            pass
    release.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    with budget.reserve(tmp_path, 70, min_free=50, max_used_percent=90):
        outcome.append("admitted")
    assert outcome == ["admitted"]


def test_dead_owner_reservation_is_released(tmp_path):
    code = ("import os; from pathlib import Path; from scripts.resource_budget import reserve; "
            "lease=reserve(Path(os.environ['BUDGET_ROOT']),1,min_free=0,max_used_percent=100); "
            "lease.__enter__(); os._exit(0)")
    subprocess.run([sys.executable, "-c", code], check=True,
                   env={**os.environ, "BUDGET_ROOT": str(tmp_path)})
    with budget.reserve(tmp_path, 1, min_free=0, max_used_percent=100):
        assert len(budget._reservations(budget._control(tmp_path))) == 1


def test_cleanup_requires_reviewed_manifest_and_keeps_pending_and_failure(tmp_path):
    source = "a" * 40
    good = _result(tmp_path, "success01", source)
    pending_source = "b" * 40
    pending = _result(tmp_path, "pending01", pending_source)
    failed = _result(tmp_path, "failure01", source, state="failure")
    undelivered = _result(tmp_path, "undeliv01", source, delivery="pending")
    _queue(tmp_path, [("success01", source, "success"), ("pending01", pending_source, "queued"),
                      ("failure01", source, "failure"), ("undeliv01", source, "success")])
    candidate = tmp_path / "logs/ci-candidates" / source
    candidate.mkdir(parents=True)
    (candidate / "candidate.patch").write_bytes(b"valuable old patch")
    worktree = tmp_path / ".openmates-agent-worktrees/agent-open"
    worktree.mkdir(parents=True)
    (worktree / "work.py").write_text("unfinished")

    manifest = budget.inventory(tmp_path)
    choices = {Path(item["path"]).name: item for item in manifest["entries"]}
    assert choices["success01"]["action"] == "remove_result_payload"
    assert choices["pending01"]["reason"] == "non_success_or_active_job"
    assert choices["failure01"]["reason"] == "non_success_or_active_job"
    assert choices["undeliv01"]["reason"] == "evidence_delivery_pending"
    assert choices[source]["action"] == "retain"
    assert choices["agent-open"]["action"] == "retain"
    assert (good / "test-results/large.webm").exists()  # Inventory is dry-run.

    result = budget.cleanup(tmp_path, manifest=manifest)
    assert result["removed"] == [str(good)]
    assert (good / "receipt.json").exists()
    assert (good / "codex-evidence.json").exists()
    assert not (good / "test-results/large.webm").exists()
    assert (good / "test-results/ci-startup-phases.json").exists()
    assert (good / "test-results/ci-runtime-images.json").exists()
    assert (good / "test-results/ci-artifacts.json").exists()
    assert (pending / "test-results/large.webm").exists()
    assert (failed / "test-results/large.webm").exists()
    assert (undelivered / "test-results/large.webm").exists()
    assert (candidate / "candidate.patch").read_bytes() == b"valuable old patch"
    assert (worktree / "work.py").exists()


def test_changed_payload_and_unknown_queue_fail_closed(tmp_path):
    source = "a" * 40
    result = _result(tmp_path, "success01", source)
    _queue(tmp_path, [("success01", source, "success")])
    manifest = budget.inventory(tmp_path)
    (result / "new.txt").write_text("changed after review")
    assert budget.cleanup(tmp_path, manifest=manifest)["removed"] == []
    assert (result / "test-results/large.webm").exists()
    (tmp_path / "logs/ci-coordinator/queue.sqlite3").unlink()
    assert budget.inventory(tmp_path)["entries"][0]["action"] == "retain"


def test_active_session_owner_protects_terminal_result(tmp_path):
    source = "a" * 40
    result = _result(tmp_path, "success01", source)
    _queue(tmp_path, [("success01", source, "success")])
    sessions = tmp_path / ".claude/sessions.json"
    sessions.parent.mkdir(parents=True)
    sessions.write_text(json.dumps({"sessions": {"fixture": {"worktree": {"status": "active"}}}}))
    manifest = budget.inventory(tmp_path)
    assert manifest["entries"][0]["reason"] == "active_session_owner"
    assert budget.cleanup(tmp_path, manifest=manifest)["removed"] == []
    assert (result / "test-results/large.webm").exists()


def test_pending_same_source_consumer_and_runtime_lease_protect_payload(tmp_path):
    source = "a" * 40
    result = _result(tmp_path, "success01", source)
    _queue(tmp_path, [("success01", source, "success"),
                      ("consumer01", source, "queued")])
    report = budget.inventory(tmp_path)
    assert report["pending_ci_source_count"] == 1
    assert report["entries"][0]["reason"] == "pending_source_consumer"
    with sqlite3.connect(tmp_path / "logs/ci-coordinator/queue.sqlite3") as db:
        db.execute("UPDATE jobs SET state='success' WHERE id='consumer01'")
    sessions = tmp_path / ".claude/sessions.json"
    sessions.parent.mkdir(parents=True)
    sessions.write_text(json.dumps({"sessions": {}, "infrastructure": {
        "test_leases": {"fixture-lease": {"owner": "fixture"}}, "docker_operations": []}}))
    report = budget.inventory(tmp_path)
    assert report["runtime_leases"]["test_lease_count"] == 1
    assert report["entries"][0]["reason"] == "runtime_lease_or_operation"
    assert (result / "test-results/large.webm").exists()


def test_integrated_candidate_patch_retires_only_after_consumer(tmp_path):
    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, check=True,
                              capture_output=True, text=True).stdout.strip()

    git("init", "-b", "dev")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.test")
    (tmp_path / "file.txt").write_text("integrated")
    git("add", "file.txt")
    git("commit", "-m", "fixture")
    source = git("rev-parse", "HEAD")
    candidate = tmp_path / "logs/ci-candidates" / source
    candidate.mkdir(parents=True)
    patch = candidate / "candidate.patch"
    patch.write_bytes(b"exact reproducible patch")
    expired = budget.datetime.fromtimestamp(time.time() - budget.RESULT_AGE_SECONDS - 3600,
                                                timezone.utc).isoformat()
    (candidate / "manifest.json").write_text(json.dumps({
        "source": source, "session": "finished", "artifact_expires_at": expired,
        "local_patch": str(patch), "patch_sha256": hashlib.sha256(patch.read_bytes()).hexdigest(),
    }))
    _queue(tmp_path, [("consumer01", source, "queued")])
    assert budget.inventory(tmp_path)["entries"][0]["action"] == "retain"
    with sqlite3.connect(tmp_path / "logs/ci-coordinator/queue.sqlite3") as db:
        db.execute("UPDATE jobs SET state='success'")
    manifest = budget.inventory(tmp_path)
    assert manifest["entries"][0]["action"] == "remove_candidate_patch"
    assert patch.is_file()
    assert budget.cleanup(tmp_path, manifest=manifest)["removed"] == [str(candidate)]
    assert not patch.exists()
    assert (candidate / "manifest.json").exists()


def test_opt_in_admission_reclaims_only_reviewed_classification(tmp_path, monkeypatch):
    source = "a" * 40
    result = _result(tmp_path, "success01", source)
    _queue(tmp_path, [("success01", source, "success")])
    reviewed = budget.inventory(tmp_path)
    budget.enable_auto(tmp_path, manifest=reviewed)
    assert budget._auto_enabled(tmp_path)

    def usage(_root):
        occupied = (result / "test-results/large.webm").exists()
        return type("Usage", (), {"total": 1000, "used": 800 if occupied else 700,
                                   "free": 200 if occupied else 300})()

    monkeypatch.setattr(budget.shutil, "disk_usage", usage)
    with budget.reserve(tmp_path, 70, min_free=0, max_used_percent=85):
        assert not (result / "test-results/large.webm").exists()
    assert list(budget._control(tmp_path).glob("auto-dry-run-*.json"))
    budget.disable_auto(tmp_path)
    assert not budget._auto_enabled(tmp_path)


def test_enable_rejects_stale_review(tmp_path):
    source = "a" * 40
    result = _result(tmp_path, "success01", source)
    _queue(tmp_path, [("success01", source, "success")])
    reviewed = budget.inventory(tmp_path)
    (result / "test-results/new.txt").write_text("new evidence")
    with pytest.raises(RuntimeError, match="changed since review"):
        budget.enable_auto(tmp_path, manifest=reviewed)
    assert not budget._auto_enabled(tmp_path)


def test_fast_revalidation_keeps_eligibility_without_worktree_walk(tmp_path, monkeypatch):
    source = "a" * 40
    result = _result(tmp_path, "success01", source)
    _queue(tmp_path, [("success01", source, "success")])
    worktree = tmp_path / ".openmates-agent-worktrees/agent-fixture"
    (worktree / "node_modules/package").mkdir(parents=True)
    (worktree / "node_modules/package/index.js").write_text("fixture")

    full = budget.inventory(tmp_path)
    fast = budget.inventory(tmp_path, count_bytes=False)
    def decisions(report):
        return [(item["path"], item["action"], item.get("payload_snapshot"),
                 item.get("reclaim_bytes")) for item in report["entries"]]

    assert decisions(fast) == decisions(full)
    assert fast["totals"]["worktrees"] is None
    assert fast["totals"]["results"] == full["totals"]["results"]
    assert fast["reclaim_bytes"] == full["reclaim_bytes"]

    original_bytes = budget._bytes
    original_rglob = Path.rglob

    def no_worktree_bytes(path, **kwargs):
        if path == worktree or path.is_relative_to(worktree):
            raise AssertionError("fast revalidation walked worktree bytes")
        return original_bytes(path, **kwargs)

    def no_worktree_rglob(path, pattern):
        if path == worktree or path.is_relative_to(worktree):
            raise AssertionError("fast revalidation scanned worktree dependencies")
        return original_rglob(path, pattern)

    monkeypatch.setattr(budget, "_bytes", no_worktree_bytes)
    monkeypatch.setattr(Path, "rglob", no_worktree_rglob)
    budget.enable_auto(tmp_path, manifest=full)
    assert budget.cleanup(tmp_path, manifest=full)["removed"] == [str(result)]
    assert not (result / "test-results/large.webm").exists()


def test_enable_still_rejects_new_inventory_entry(tmp_path):
    source = "a" * 40
    _result(tmp_path, "success01", source)
    _queue(tmp_path, [("success01", source, "success")])
    reviewed = budget.inventory(tmp_path)
    new_candidate = tmp_path / "logs/ci-candidates" / ("b" * 40)
    new_candidate.mkdir(parents=True)
    (new_candidate / "candidate.patch").write_text("new source")
    with pytest.raises(RuntimeError, match="changed since review"):
        budget.enable_auto(tmp_path, manifest=reviewed)
    assert not budget._auto_enabled(tmp_path)


def test_inventory_counts_shared_worktree_inode_once(tmp_path):
    first = tmp_path / ".openmates-agent-worktrees/agent-one"
    second = tmp_path / ".openmates-agent-worktrees/agent-two"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "shared.bin").write_bytes(b"x" * 4096)
    os.link(first / "shared.bin", second / "shared.bin")
    (second / "own.bin").write_bytes(b"y" * 4096)
    report = budget.inventory(tmp_path)
    expected = (first.stat().st_blocks + second.stat().st_blocks
                + (first / "shared.bin").stat().st_blocks
                + (second / "own.bin").stat().st_blocks) * 512
    assert report["totals"]["worktrees"] == expected
    assert all(item["action"] == "retain" for item in report["entries"])
