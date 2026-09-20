# contract-test-file: tooling
"""Protect candidate publication from staging changes and secret inclusion.

Tests use disposable Git repositories and a fake private artifact uploader.
No Git branch or network resource is created.
See docs/plans/isolated-github-tests/plan.yml.
"""

import subprocess
import pytest
from scripts.ci_source import candidate_preflight, reviewed_paths, fingerprint


def repository(tmp_path):
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    manifest = tmp_path / "scripts/ci_coverage_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"groups":{"uploads":{"specs":[]}}}\n')
    subprocess.run(["git", "-C", str(tmp_path), "add", str(manifest)], check=True)
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


def test_candidate_preflight_compiles_only_touched_python(tmp_path):
    root = repository(tmp_path)
    (root / "valid.py").write_text("value = 1\n")
    receipt = candidate_preflight(root, ["valid.py"], session_id="fixture")
    assert receipt["checks"] == [{"check": "python-compile", "paths": ["valid.py"]}]
    assert receipt["future_deploy_requirements"] == []
    (root / "invalid.py").write_text("value =\n")
    with pytest.raises(ValueError, match="Python syntax"):
        candidate_preflight(root, ["invalid.py"], session_id="fixture")


def test_resolved_patch_preflight_surfaces_deferred_requirements(tmp_path):
    root = repository(tmp_path)
    receipt = candidate_preflight(
        root,
        ["backend/tests/test_changed.py"],
        session_id="fixture",
        materialized=False,
    )
    assert receipt["status"] == "deferred"
    assert receipt["checks"] == []
    assert "Specifications: trailer" in receipt["future_deploy_requirements"]
    assert "syntax" in receipt["deferred_checks"][0]
    assert "were not checked" in receipt["deferred_checks"][0]


def test_unchanged_source_uses_reachable_base_without_artifact(tmp_path, monkeypatch):
    from scripts import ci_source

    root = repository(tmp_path)
    monkeypatch.setattr(ci_source, "DISK_RESERVE", 0)
    result = ci_source.publish(
        root,
        "fixture",
        [],
        artifact_uploader=lambda *args, **kwargs: pytest.fail("No artifact required"),
    )
    assert result["unchanged"] is True
    assert result["source"] == ci_source.git(root, "rev-parse", "HEAD")


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
    def controlled_git(root, *args, **kwargs):
        if args[0] == "push":
            pytest.fail("CI publication must never push a Git ref")
        return real_git(root, *args, **kwargs)

    uploads = []

    def upload(path, *, source, sha256):
        uploads.append((path.read_bytes(), source, sha256))
        return {
            "url": "https://nbg1.your-objectstorage.com/private?signature=test",
            "bucket": "private",
            "key": f"candidate/{source}.patch",
            "expires_at": "2026-09-21T00:00:00+00:00",
        }

    monkeypatch.setattr(ci_source, "git", controlled_git)
    monkeypatch.setattr(ci_source, "DISK_RESERVE", 0)
    result = ci_source.publish(
        root,
        "daba",
        [],
        base=base,
        resolved_patch=patch_path,
        patch_sha256=hashlib.sha256(patch.encode()).hexdigest(),
        artifact_uploader=upload,
    )
    assert "ref" not in result
    assert len(uploads) == 1
    assert uploads[0][1:] == (result["source"], result["patch_sha256"])
    assert hashlib.sha256(uploads[0][0]).hexdigest() == result["patch_sha256"]
    manifest = root / "logs/ci-candidates" / result["source"] / "manifest.json"
    assert manifest.is_file()
    assert (manifest.stat().st_mode & 0o777) == 0o600
    assert real_git(root, "show", result["source"] + ":new.py") == 'print("candidate")'
    assert real_git(root, "rev-parse", "HEAD") == base
    assert (root / ".git/index").read_bytes() == before_index
    assert not (root / "new.py").exists()
    assert (root / "unrelated.py").read_text() == "preserve dirty work"
