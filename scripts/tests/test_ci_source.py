# contract-test-file: tooling
"""Protect candidate publication from staging changes and secret inclusion.

Tests use disposable Git repositories and never publish a remote branch.
Only source-path validation and deterministic content capture are exercised.
Snapshot publication is owned by the existing sessions.py entry point.
See docs/plans/isolated-github-tests/plan.yml.
"""

import subprocess
import pytest
from scripts.ci_source import reviewed_paths, fingerprint


def repository(tmp_path):
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=CI",
            "-c",
            "user.email=ci@example.com",
            "commit",
            "--allow-empty",
            "-m",
            "fixture",
        ],
        check=True,
        capture_output=True,
    )
    return tmp_path


def test_rejects_secret_and_symlink_paths(tmp_path):
    root = repository(tmp_path)
    (root / ".env").write_text("synthetic")
    with pytest.raises(ValueError, match="environment"):
        reviewed_paths(root, [".env"])
    (root / "outside").write_text("synthetic")
    (root / "alias.py").symlink_to(root / "outside")
    with pytest.raises(ValueError, match="symlink"):
        reviewed_paths(root, ["alias.py"])


def test_only_explicit_untracked_source_and_content_changes(tmp_path):
    root = repository(tmp_path)
    (root / "selected.py").write_text("one")
    (root / "unrelated.py").write_text("two")
    index_before = (root / ".git/index").read_bytes()
    paths = reviewed_paths(root, ["selected.py"])
    assert paths == ["selected.py"]
    before = fingerprint(root, paths)
    (root / "selected.py").write_text("three")
    assert fingerprint(root, paths) != before
    assert (root / ".git/index").read_bytes() == index_before


def test_resolved_patch_uses_reviewed_base_without_touching_worktree(
    tmp_path, monkeypatch
):
    import hashlib
    from scripts import ci_source

    root = repository(tmp_path)
    base = ci_source.git(root, "rev-parse", "HEAD")
    patch = 'diff --git a/new.py b/new.py\nnew file mode 100644\n--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n+print("candidate")\n'
    patch_path = root / "reviewed.patch"
    patch_path.write_text(patch)
    (root / "unrelated.py").write_text("preserve dirty work")
    before_index = (root / ".git/index").read_bytes()
    real_git = ci_source.git
    pushes = []

    def controlled_git(root, *args, **kwargs):
        if args[0] == "push":
            pushes.append(args)
            return ""
        return real_git(root, *args, **kwargs)

    monkeypatch.setattr(ci_source, "git", controlled_git)
    monkeypatch.setattr(ci_source, "DISK_RESERVE", 0)
    result = ci_source.publish(
        root,
        "daba",
        [],
        base=base,
        resolved_patch=patch_path,
        patch_sha256=hashlib.sha256(patch.encode()).hexdigest(),
    )
    assert pushes and pushes[0][2].endswith(result["ref"])
    assert real_git(root, "show", result["source"] + ":new.py") == 'print("candidate")'
    assert real_git(root, "rev-parse", "HEAD") == base
    assert (root / ".git/index").read_bytes() == before_index
    assert not (root / "new.py").exists()
    assert (root / "unrelated.py").read_text() == "preserve dirty work"
