# contract-test-file: tooling
"""Exercise the two-branch invariant in disposable repositories."""

from pathlib import Path
import subprocess

import pytest

from scripts import branch_invariant


def run(*command, cwd=None):
    return subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True)


def repository(tmp_path):
    remote = tmp_path / "remote.git"
    root = tmp_path / "repo"
    run("git", "init", "--bare", str(remote))
    run("git", "init", str(root))
    run("git", "-C", str(root), "config", "user.name", "CI")
    run("git", "-C", str(root), "config", "user.email", "ci@example.com")
    (root / "fixture").write_text("fixture")
    run("git", "-C", str(root), "add", "fixture")
    run("git", "-C", str(root), "commit", "-m", "fixture")
    run("git", "-C", str(root), "branch", "-M", "dev")
    run("git", "-C", str(root), "branch", "main")
    run("git", "-C", str(root), "branch", "extra")
    run("git", "-C", str(root), "remote", "add", "origin", str(remote))
    run("git", "-C", str(root), "push", "origin", "dev", "main", "extra")
    return root


def test_archive_precedes_exact_cleanup(tmp_path, monkeypatch):
    root = repository(tmp_path)
    monkeypatch.setattr(branch_invariant, "code_violations", lambda _: [])
    before = branch_invariant.audit(root)
    assert set(before["extra_local"]) == {"extra"}
    assert set(before["extra_remote"]) == {"extra"}
    archived = branch_invariant.archive(root, tmp_path / "backup")
    assert archived["bundle_sha256"]
    result = branch_invariant.cleanup(root, Path(archived["manifest"]))
    assert result["deleted_local"] == ["extra"]
    assert result["deleted_remote"] == ["extra"]
    assert set(result["final"]["local"]) == {"dev", "main"}
    assert set(result["final"]["remote"]) == {"dev", "main"}


def test_cleanup_rejects_ref_drift_after_archive(tmp_path, monkeypatch):
    root = repository(tmp_path)
    monkeypatch.setattr(branch_invariant, "code_violations", lambda _: [])
    archived = branch_invariant.archive(root, tmp_path / "backup")
    run("git", "-C", str(root), "commit", "--allow-empty", "-m", "drift")
    run("git", "-C", str(root), "update-ref", "refs/heads/extra", "dev")
    with pytest.raises(RuntimeError, match="changed after archival"):
        branch_invariant.cleanup(root, Path(archived["manifest"]))
