# contract-test-file: tooling
"""Host scratch cleanup removes only stale, unused, user-owned entries."""

import os
from pathlib import Path
import time

from scripts import host_disk_cleanup as cleanup

DAY = 86400


def _make(path: Path, age_days: float, *, nested_recent: bool = False) -> Path:
    path.mkdir(parents=True)
    (path / "data.bin").write_bytes(b"x" * 4096)
    old = time.time() - age_days * DAY
    for entry in (path / "data.bin", path):
        os.utime(entry, (old, old))
    if nested_recent:
        (path / "fresh.log").write_text("still being written")
        os.utime(path, (old, old))
    return path


def test_removes_only_stale_unused_unprotected_tmp_entries(tmp_path):
    tmp, recovery = tmp_path / "tmp", tmp_path / "recovery"
    stale = _make(tmp / "old-build", 10)
    recent = _make(tmp / "today-build", 0)
    deep_recent = _make(tmp / "old-top-new-inside", 10, nested_recent=True)
    protected = _make(tmp / "claude-1001", 10)
    in_use = _make(tmp / "used-by-process", 10)

    dry = cleanup.run(tmp, recovery, apply=False, in_use=[str(in_use / "data.bin")])
    assert [item["path"] for item in dry["deleted"]] == [str(stale)]
    assert stale.exists()  # dry run reports only

    report = cleanup.run(tmp, recovery, apply=True, in_use=[str(in_use / "data.bin")])
    assert [item["path"] for item in report["deleted"]] == [str(stale)]
    assert report["reclaimed_bytes"] > 0
    assert report["skipped"] == {"recent": 2, "in_use": 1, "permission": 0}
    assert not stale.exists()
    for kept in (recent, deep_recent, protected, in_use):
        assert kept.exists()


def test_recovery_archives_expire_after_their_own_longer_window(tmp_path):
    tmp, recovery = tmp_path / "tmp", tmp_path / "recovery"
    tmp.mkdir()
    archives = recovery / "expired-worktrees"
    archives.mkdir(parents=True)
    old_archive = archives / "agent-old.tar.gz"
    young_archive = archives / "agent-young.tar.gz"
    for archive, age in ((old_archive, cleanup.RECOVERY_MAX_AGE_DAYS + 1), (young_archive, 5)):
        archive.write_bytes(b"archive")
        stamp = time.time() - age * DAY
        os.utime(archive, (stamp, stamp))
    old_copy = _make(recovery / "agent-1234-20260903T105409Z", cleanup.RECOVERY_MAX_AGE_DAYS + 1)

    report = cleanup.run(tmp, recovery, apply=True, in_use=[])
    assert sorted(item["path"] for item in report["deleted"]) == sorted([str(old_archive), str(old_copy)])
    assert young_archive.exists()
    assert archives.is_dir()  # the archive directory itself is never a candidate


def test_sockets_and_symlinks_in_tmp_are_left_alone(tmp_path):
    tmp, recovery = tmp_path / "tmp", tmp_path / "recovery"
    tmp.mkdir()
    target = _make(tmp_path / "elsewhere", 10)
    link = tmp / "link"
    link.symlink_to(target)
    report = cleanup.run(tmp, recovery, apply=True, in_use=[])
    assert report["deleted"] == []
    assert link.is_symlink() and target.exists()


def test_permission_denied_entries_are_skipped_not_failures(tmp_path, monkeypatch):
    tmp, recovery = tmp_path / "tmp", tmp_path / "recovery"
    stale = _make(tmp / "container-owned", 10)

    def denied(_path):
        raise PermissionError("root-owned child")

    monkeypatch.setattr(cleanup.shutil, "rmtree", denied)
    report = cleanup.run(tmp, recovery, apply=True, in_use=[])
    assert report["failures"] == []
    assert report["deleted"] == []
    assert report["skipped"]["permission"] == 1
    assert stale.exists()


def _queue(repository: Path, rows: list[tuple[str, str, str]]) -> None:
    import sqlite3

    path = repository / "logs/ci-coordinator/queue.sqlite3"
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE jobs (id TEXT, source TEXT, state TEXT, run_id TEXT,"
                   " prepared_run_id TEXT, preparation_id TEXT, preparation_key TEXT,"
                   " candidate_tree TEXT, candidate_base TEXT)")
        db.executemany("INSERT INTO jobs (id,source,state) VALUES (?,?,?)", rows)


def _retention(repository: Path, tmp_path: Path, **kwargs) -> dict:
    return cleanup.run(tmp_path / "tmp", tmp_path / "recovery", apply=True, in_use=[],
                       repository=repository, cache_root=tmp_path / "cache",
                       **{"cargo_paths": [], **kwargs})


def test_ci_artifacts_use_three_day_threshold_and_active_job_protection(tmp_path):
    repo = tmp_path / "repo"
    runs, cands = repo / "test-results/ci-runs", repo / "logs/ci-candidates"
    old = _make(runs / "old-run", 4)
    fresh = _make(runs / "fresh-run", 2)
    queued = _make(runs / "queued-run", 30)
    preparing = _make(cands / ("a" * 40), 30)
    done = _make(cands / ("b" * 40), 30)
    _queue(repo, [("queued-run", "x", "queued"), ("job1", "a" * 40, "preparing"),
                  ("job2", "b" * 40, "success"), ("old-run", "y", "success")])

    report = _retention(repo, tmp_path)
    assert {Path(item["path"]) for item in report["deleted"]} == {old, done}
    assert not old.exists() and not done.exists()
    for kept in (fresh, queued, preparing):
        assert kept.exists()


def test_ci_artifacts_kept_when_queue_unreadable_and_dry_run_reports_only(tmp_path):
    repo = tmp_path / "repo"
    old = _make(repo / "test-results/ci-runs/old-run", 10)
    (repo / "logs/ci-coordinator").mkdir(parents=True)
    (repo / "logs/ci-coordinator/queue.sqlite3").write_text("not a database")
    report = _retention(repo, tmp_path)
    assert report["deleted"] == [] and old.exists()

    (repo / "logs/ci-coordinator/queue.sqlite3").unlink()
    dry = cleanup.run(tmp_path / "tmp", tmp_path / "recovery", apply=False, in_use=[],
                      repository=repo, cache_root=tmp_path / "cache", cargo_paths=[])
    assert [item["category"] for item in dry["deleted"]] == ["ci_run"]
    assert dry["reclaimed_bytes"] > 0 and old.exists()


def test_rust_dirs_need_24h_idle_and_no_running_cargo(tmp_path):
    repo, cache = tmp_path / "repo", tmp_path / "cache"
    idle = _make(repo / ".openmates-agent-worktrees/agent-1111/target", 2)
    recent = _make(repo / ".openmates-agent-worktrees/agent-2222/target", 0.5)
    busy_cwd = _make(repo / ".openmates-agent-worktrees/agent-3333/target", 2)
    busy_env = _make(cache / "openmates-rust-bench", 2)
    idle_cache = _make(cache / "openmates-rust-old", 2)

    report = _retention(repo, tmp_path, cargo_paths=[
        str(busy_cwd.parent / "crates/core"), str(busy_env / "debug")])
    assert {Path(item["path"]) for item in report["deleted"]} == {idle, idle_cache}
    for kept in (recent, busy_cwd, busy_env):
        assert kept.exists()


def test_cache_session_scratch_and_cargo_targets_are_reclaimed_when_idle(tmp_path):
    repo, cache = tmp_path / "repo", tmp_path / "cache"
    old_scratch = _make(cache / "3e82-pkgs", 4)
    fresh_scratch = _make(cache / "a248-demo", 1)
    in_use_scratch = _make(cache / "fe65-cand", 4)
    old_target = _make(cache / "business-pkg-target", 2)
    building_target = _make(cache / "tools-pkg-target", 2)
    shared_tool_cache = _make(cache / "ms-playwright", 30)
    not_session_named = _make(cache / "openmates-caddy", 30)

    report = cleanup.run(tmp_path / "tmp", tmp_path / "recovery", apply=True,
                         in_use=[str(in_use_scratch / "out.log")], repository=repo,
                         cache_root=cache, cargo_paths=[str(building_target / "debug")])
    assert {Path(item["path"]) for item in report["deleted"]} == {old_scratch, old_target}
    assert {item["category"] for item in report["deleted"]} == {"cache_scratch", "rust_cache"}
    for kept in (fresh_scratch, in_use_scratch, building_target, shared_tool_cache,
                 not_session_named):
        assert kept.exists()


def test_sibling_recovery_archive_folder_follows_recovery_retention(tmp_path):
    recovery = tmp_path / ".openmates-worktree-recovery"
    recovery.mkdir()
    archives = tmp_path / "OpenMates-worktree-recovery-archives"
    old = _make(archives / "orphans-old.tar.zst", 20)
    recent = _make(archives / "orphans-recent.tar.zst", 2)
    report = cleanup.run(tmp_path / "tmp", recovery, apply=True, in_use=[])
    assert [Path(item["path"]) for item in report["deleted"]] == [old]
    assert recent.exists()
