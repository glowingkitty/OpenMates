# contract-test-file: tooling
"""Leftover deploy integration checkouts expire only when nothing in them is unpushed (TASK-541)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import integration_checkout_expiry as expiry  # noqa: E402 - repo-local module, path set just above


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
                               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org",
                               "PATH": "/usr/bin:/bin"}).stdout.strip()


def checkout(tmp_path: Path) -> tuple[Path, Path]:
    """A repository whose origin/dev is one commit, and an integration checkout at that commit."""
    root = tmp_path / "worktrees"
    repo = root / "integration-ab12-0123456789ab"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "dev")
    (repo / "app.py").write_text("one\n")
    git(repo, "add", "app.py")
    git(repo, "commit", "-q", "-m", "base")
    git(repo, "update-ref", "refs/remotes/origin/dev", "HEAD")
    return root, repo


def stage_change(repo: Path, text: str) -> None:
    (repo / "app.py").write_text(text)
    git(repo, "add", "app.py")


def test_staged_patch_that_was_pushed_is_landed(tmp_path):
    _root, repo = checkout(tmp_path)
    base = git(repo, "rev-parse", "HEAD")
    stage_change(repo, "two\n")
    # The same patch was pushed as a commit, then dev moved on with another edit.
    git(repo, "commit", "-q", "-m", "deploy")
    stage_change(repo, "three\n")
    git(repo, "commit", "-q", "-m", "later")
    git(repo, "update-ref", "refs/remotes/origin/dev", "HEAD")
    git(repo, "reset", "-q", "--hard", base)
    stage_change(repo, "two\n")
    assert expiry.integration_checkout_landed(repo, "origin/dev") is True


def test_staged_patch_never_pushed_is_kept(tmp_path):
    _root, repo = checkout(tmp_path)
    stage_change(repo, "unpushed\n")
    assert expiry.integration_checkout_landed(repo, "origin/dev") is False


def test_untracked_file_is_kept(tmp_path):
    _root, repo = checkout(tmp_path)
    (repo / "notes.txt").write_text("only here\n")
    assert expiry.integration_checkout_landed(repo, "origin/dev") is False


def test_patch_still_in_its_source_lane_is_landed(tmp_path):
    root, repo = checkout(tmp_path)
    stage_change(repo, "lane work\n")
    lane = root / "agent-ab12"
    lane.mkdir()
    (lane / "app.py").write_text("lane work\n")
    assert expiry.source_lane(repo) == lane
    assert expiry.integration_checkout_landed(repo, "origin/dev") is True


def test_unstaged_edit_beside_a_pushed_patch_is_kept(tmp_path):
    _root, repo = checkout(tmp_path)
    base = git(repo, "rev-parse", "HEAD")
    stage_change(repo, "two\n")
    git(repo, "commit", "-q", "-m", "deploy")
    git(repo, "update-ref", "refs/remotes/origin/dev", "HEAD")
    git(repo, "reset", "-q", "--hard", base)
    stage_change(repo, "two\n")
    (repo / "app.py").write_text("two\nplus an edit nobody pushed\n")
    assert expiry.integration_checkout_landed(repo, "origin/dev") is False
