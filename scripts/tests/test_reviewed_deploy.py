# contract-test-file: tooling
"""Exercise reviewed deployment safety in disposable repositories.

Candidates model reconciled patches whose physical worktree still has an old HEAD.
Validation must preserve staging and reject drift, mismatched scope and tampering.
The deletion guard must still reject edits beyond the reviewed patch.
No real repository deployment or external API is used.
"""

import pytest
from scripts import reviewed_deploy as review
from scripts.ci_source import git
from test_ci_source import repository
from test_sessions_worktree_lifecycle import load_sessions_module


def commit(root, name, content):
    (root / name).write_text(content)
    git(root, "add", "--", name)
    git(root, "-c", "user.name=CI", "-c", "user.email=ci@example.com", "commit", "-m", "fixture")
    return git(root, "rev-parse", "HEAD")


def fixture(tmp_path):
    root = repository(tmp_path)
    base = commit(root, "source.py", "old\nupstream\n")
    candidate = commit(root, "source.py", "old\n")
    git(root, "update-ref", f"refs/remotes/origin/codex/ci/fixture/{candidate}", candidate)
    (root / "source.py").write_text("preserved dirty source\n")
    (root / "other.py").write_text("preserved staged source\n")
    git(root, "add", "other.py")
    return root, base, candidate


def test_reviewed_candidate_preserves_worktree_index_and_rejects_drift(tmp_path):
    root, base, candidate = fixture(tmp_path)
    before = review.source_identity(root, ["source.py"])
    data = review.validate(root, "fixture", candidate, base, ["source.py"])
    assert data["deletions"] == {"source.py": 1}
    assert before == review.source_identity(root, ["source.py"])
    review.verify_current_base(root, data, base)
    with pytest.raises(RuntimeError, match="changed upstream"):
        review.verify_current_base(root, data, candidate)
    (root / "source.py").write_text("concurrent change\n")
    with pytest.raises(RuntimeError, match="changed during"):
        review.verify_source(root, data)


def test_reviewed_candidate_requires_exact_parent_scope_and_retained_identity(tmp_path):
    root, base, candidate = fixture(tmp_path)
    with pytest.raises(RuntimeError, match="exactly match"):
        review.validate(root, "fixture", candidate, base, ["other.py"])
    with pytest.raises(RuntimeError, match="exactly the reviewed base"):
        review.validate(root, "fixture", candidate, candidate, ["source.py"])


def test_reviewed_deletion_guard_uses_reviewed_intent_but_still_blocks_amplification(tmp_path, monkeypatch):
    sessions = load_sessions_module()
    monkeypatch.setattr(sessions, "_worktree_head", lambda *_: "old-head")
    counts = {"source.py": 1}
    monkeypatch.setattr(sessions, "_numstat_deletions", lambda *a, **k: counts)
    metadata = {"path": str(tmp_path), "reviewed_deploy": {"deletions": {"source.py": 1}}}
    sessions._enforce_no_integration_deletion_amplification(
        metadata, ["source.py"], tmp_path, patch_id="review", prepared_base="current",
    )
    counts["source.py"] = 2
    with pytest.raises(sessions.IntegrationConflict, match="amplification"):
        sessions._enforce_no_integration_deletion_amplification(
            metadata, ["source.py"], tmp_path, patch_id="review", prepared_base="current",
        )


def test_real_integration_applies_reviewed_tree_without_touching_source(tmp_path, monkeypatch):
    root, base, candidate = fixture(tmp_path / "source")
    data = review.validate(root, "fixture", candidate, base, ["source.py"])
    target = tmp_path / "integration"
    git(tmp_path, "clone", "--no-hardlinks", str(root), str(target))
    git(target, "switch", "--detach", base)
    sessions = load_sessions_module()
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)
    metadata = {"path": str(root), "base_commit": base, "merged_commit": base, "reviewed_deploy": data}
    sessions._apply_worktree_diff_to_checkout(
        metadata, data["paths"], target, patch_id=data["patch_id"],
        prepared_base=base, checkpoint_commit=candidate,
    )
    review.verify_staged(target, data)
    review.verify_source(root, data)
    assert (target / "source.py").read_text() == "old\n"
    (target / "source.py").write_text("unreviewed edit\n")
    git(target, "add", "source.py")
    with pytest.raises(RuntimeError, match="differ from"):
        review.verify_staged(target, data)
