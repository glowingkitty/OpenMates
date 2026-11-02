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
