#!/usr/bin/env python3
# contract-test-file: tooling
"""Parallel-lane deploy pipeline contracts for sessions.py.

Lanes cannot commit, so deploy turns their dirty diff into a checkpoint commit
and replays it on origin/dev. These tests prove the pipeline never needs a
human to delete checkpoint refs, hand-regenerate generated YAML or clear the
worktree cap. Fixtures use isolated Git repositories under tmp_path only.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PATH = PROJECT_ROOT / "scripts" / "sessions.py"

# Deterministic stand-in for scripts/rust_migration_yaml.py: derives the
# generated overview from the curated lanes file, like the real generator.
RUST_GENERATOR_STUB = """\
from pathlib import Path
root = Path(__file__).resolve().parents[1]
lanes = (root / "docs/migration/rust/web-lanes.yml").read_text(encoding="utf-8")
(root / "docs/migration/rust/overview.yml").write_text("# GENERATED\\nlanes: " + lanes, encoding="utf-8")
"""


def load_sessions_module():
    spec = importlib.util.spec_from_file_location("openmates_sessions_lane_deploy_pipeline", SESSIONS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def create_fixture(tmp_path: Path) -> tuple[Path, Path, str]:
    """Return (root, lane worktree, base) with a pushed dev branch."""
    remote = tmp_path / "remote.git"
    root = tmp_path / "root"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "clone", str(remote), str(root)], check=True, capture_output=True)
    git(root, "config", "user.email", "tests@openmates.invalid")
    git(root, "config", "user.name", "OpenMates Tests")
    git(root, "checkout", "-b", "dev")
    (root / ".gitignore").write_text(".openmates-agent-worktrees/\n", encoding="utf-8")
    (root / "changed.txt").write_text("before\n", encoding="utf-8")
    (root / "other.txt").write_text("other\n", encoding="utf-8")
    (root / "scripts").mkdir()
    (root / "scripts" / "rust_migration_yaml.py").write_text(RUST_GENERATOR_STUB, encoding="utf-8")
    rust_dir = root / "docs" / "migration" / "rust"
    rust_dir.mkdir(parents=True)
    (rust_dir / "web-lanes.yml").write_text("one\n", encoding="utf-8")
    (rust_dir / "overview.yml").write_text("# GENERATED\nlanes: one\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-m", "fixture")
    git(root, "push", "-u", "origin", "dev")
    base = git(root, "rev-parse", "HEAD")
    lane = tmp_path / "lane"
    git(root, "worktree", "add", "--detach", str(lane), base)
    return root, lane, base


def advance_dev(root: Path, relative_path: str, content: str) -> str:
    (root / relative_path).write_text(content, encoding="utf-8")
    git(root, "add", relative_path)
    git(root, "commit", "-m", f"upstream {relative_path}")
    git(root, "push", "origin", "dev")
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def lane_env(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    root, lane, base = create_fixture(tmp_path)
    integrations = root / ".openmates-agent-worktrees"
    integrations.mkdir()
    monkeypatch.setattr(sessions, "PROJECT_ROOT", root)
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", integrations)
    metadata = {"path": str(lane), "base_commit": base}
    monkeypatch.setattr(sessions, "_load_sessions", lambda: {"sessions": {"abcd": {"worktree": metadata}}})
    return sessions, root, lane, base, metadata


def ref_value(root: Path, ref: str) -> str:
    result = subprocess.run(["git", "rev-parse", "--verify", "--quiet", ref], cwd=root, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def test_empty_diff_checkpoint_writes_no_ref_and_drops_stale_base_ref(lane_env):
    sessions, root, _lane, base, metadata = lane_env
    checkpoint_ref = sessions._worktree_checkpoint_ref("abcd")
    git(root, "update-ref", checkpoint_ref, base)  # stale ref from an earlier empty deploy

    files = ["changed.txt"]  # selected but unchanged in the lane
    commit = sessions._create_worktree_checkpoint_commit(
        "abcd", metadata, files, sessions._worktree_patch_id(metadata, files)
    )

    assert commit == ""
    assert ref_value(root, checkpoint_ref) == ""


def test_stale_base_equal_ref_is_replaced_by_new_checkpoint(lane_env):
    sessions, root, lane, base, metadata = lane_env
    checkpoint_ref = sessions._worktree_checkpoint_ref("abcd")
    git(root, "update-ref", checkpoint_ref, base)
    (lane / "changed.txt").write_text("after\n", encoding="utf-8")

    files = ["changed.txt"]
    commit = sessions._create_worktree_checkpoint_commit(
        "abcd", metadata, files, sessions._worktree_patch_id(metadata, files)
    )

    assert commit and commit != base
    assert ref_value(root, checkpoint_ref) == commit
    assert git(root, "rev-parse", f"{commit}^") == base


def test_checkpoint_equal_to_source_base_is_treated_as_no_checkpoint(lane_env):
    sessions, _root, _lane, base, metadata = lane_env
    assert sessions._usable_supplied_checkpoint(base, metadata) == ""


def test_stale_parent_checkpoint_without_unique_work_is_recreated(lane_env):
    sessions, root, lane, base, metadata = lane_env
    new_base = advance_dev(root, "other.txt", "upstream\n")
    git(lane, "fetch", "origin", "dev")
    metadata["base_commit"] = new_base
    (lane / "changed.txt").write_text("after\n", encoding="utf-8")
    files = ["changed.txt"]

    # The old checkpoint is the old base itself: integrated, nothing unique.
    assert sessions._usable_supplied_checkpoint(base, metadata) == ""
    integration = sessions._prepare_integration_worktree(
        "abcd", metadata, files, sessions._worktree_patch_id(metadata, files), new_base,
        checkpoint_commit=base,
    )
    checkout = Path(integration["path"])
    assert (checkout / "changed.txt").read_text(encoding="utf-8") == "after\n"
    sessions._remove_integration_worktree(integration)


def test_stale_parent_checkpoint_with_unique_work_still_blocks(lane_env):
    sessions, root, lane, base, metadata = lane_env
    (lane / "changed.txt").write_text("after\n", encoding="utf-8")
    files = ["changed.txt"]
    checkpoint = sessions._create_worktree_checkpoint_commit(
        "abcd", metadata, files, sessions._worktree_patch_id(metadata, files)
    )
    new_base = advance_dev(root, "other.txt", "upstream\n")
    moved = {**metadata, "base_commit": new_base}

    assert sessions._checkpoint_has_unique_work(checkpoint, moved)
    assert sessions._usable_supplied_checkpoint(checkpoint, moved) == checkpoint
    with pytest.raises(sessions.IntegrationConflict, match="holds unique work"):
        sessions._prepare_integration_worktree(
            "abcd", moved, files, sessions._worktree_patch_id(moved, files), new_base,
            checkpoint_commit=checkpoint,
        )
    # A foreign commit with unique work keeps compare-and-swap protection.
    git(root, "update-ref", sessions._worktree_checkpoint_ref("efgh"), checkpoint)
    with pytest.raises(RuntimeError, match="unverified provenance"):
        sessions._checkpoint_ref_expected_commit("efgh", sessions._worktree_checkpoint_ref("efgh"), new_base)


def test_generated_rust_yaml_is_excluded_from_patch_and_regenerated(lane_env):
    sessions, _root, lane, base, metadata = lane_env
    (lane / "docs/migration/rust/web-lanes.yml").write_text("two\n", encoding="utf-8")
    (lane / "docs/migration/rust/overview.yml").write_text("hand edited stale\n", encoding="utf-8")
    files = ["docs/migration/rust/overview.yml", "docs/migration/rust/web-lanes.yml"]

    source, generated = sessions._split_rust_migration_generated_artifacts(files)
    assert source == ["docs/migration/rust/web-lanes.yml"]
    assert generated == ["docs/migration/rust/overview.yml"]

    integration = sessions._prepare_integration_worktree(
        "abcd", metadata, files, sessions._worktree_patch_id(metadata, files), base
    )
    checkout = Path(integration["path"])
    overview = (checkout / "docs/migration/rust/overview.yml").read_text(encoding="utf-8")
    assert overview == "# GENERATED\nlanes: two\n"
    staged = set(git(checkout, "diff", "--cached", "--name-only").splitlines())
    assert staged == set(files)
    assert sessions._regenerate_rust_migration_artifacts(checkout, files) == ["docs/migration/rust/overview.yml"]
    sessions._remove_integration_worktree(integration)


def test_fast_forward_resets_dirty_generated_file_and_keeps_lane_edits(lane_env):
    sessions, root, lane, base, _metadata = lane_env
    (lane / "changed.txt").write_text("lane edit\n", encoding="utf-8")
    (lane / "docs/migration/rust/overview.yml").write_text("conflicting hand edit\n", encoding="utf-8")
    (root / "docs/migration/rust/web-lanes.yml").write_text("upstream\n", encoding="utf-8")
    (root / "docs/migration/rust/overview.yml").write_text("# GENERATED\nlanes: upstream\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-m", "upstream lanes")
    git(root, "push", "origin", "dev")
    target = git(root, "rev-parse", "HEAD")

    outcome = sessions.fast_forward_worktree_to_origin_dev(lane)

    assert outcome["status"] == "fast_forwarded"
    assert outcome["reset"] == ["docs/migration/rust/overview.yml"]
    assert outcome["warnings"] == []
    assert git(lane, "rev-parse", "HEAD") == target != base
    assert (lane / "changed.txt").read_text(encoding="utf-8") == "lane edit\n"
    assert (lane / "docs/migration/rust/overview.yml").read_text(encoding="utf-8") == "# GENERATED\nlanes: upstream\n"


def test_fast_forward_refuses_overlapping_dirty_edit_without_changes(lane_env):
    sessions, root, lane, base, _metadata = lane_env
    (lane / "changed.txt").write_text("lane edit\n", encoding="utf-8")
    advance_dev(root, "changed.txt", "upstream edit\n")

    outcome = sessions.fast_forward_worktree_to_origin_dev(lane)

    assert outcome["status"] == "blocked"
    assert outcome["overlap"] == ["changed.txt"]
    assert git(lane, "rev-parse", "HEAD") == base
    assert (lane / "changed.txt").read_text(encoding="utf-8") == "lane edit\n"


def test_fast_forward_accepts_overlap_already_equal_to_dev(lane_env):
    sessions, root, lane, _base, _metadata = lane_env
    (lane / "changed.txt").write_text("deployed\n", encoding="utf-8")  # this lane's earlier deploy
    target = advance_dev(root, "changed.txt", "deployed\n")

    outcome = sessions.fast_forward_worktree_to_origin_dev(lane)

    assert outcome["status"] == "fast_forwarded"
    assert git(lane, "rev-parse", "HEAD") == target
    assert git(lane, "status", "--porcelain") == ""


def test_refresh_base_cli_passes_rebase(monkeypatch, capsys):
    sessions = load_sessions_module()
    calls = []
    monkeypatch.setattr(
        sessions, "refresh_session_worktree_base",
        lambda session_id, **kwargs: calls.append((session_id, kwargs)) or {"session_id": session_id},
    )
    sessions.cmd_worktree(Namespace(worktree_action="refresh-base", session="abcd", rebase=True))
    sessions.cmd_worktree(Namespace(worktree_action="refresh-base", session="abcd", rebase=False))
    assert calls == [("abcd", {"rebase": True}), ("abcd", {})]


def test_reconcile_removes_integrated_clean_idle_lifecycle_worktree_only(monkeypatch):
    sessions = load_sessions_module()
    lifecycle = {"version": sessions.WORKSPACE_LIFECYCLE_VERSION}
    data = {
        "sessions": {sid: {"lifecycle": dict(lifecycle)} for sid in ("clean", "dirty", "active", "unique")},
        "deploy_queue": [],
    }
    candidates = [
        {"session_id": "clean", "path": "/tmp/agent-clean", "idle_hours": 200, "classification": "integrated"},
        {"session_id": "dirty", "path": "/tmp/agent-dirty", "idle_hours": 200, "classification": "integrated"},
        {"session_id": "active", "path": "/tmp/agent-active", "idle_hours": 1, "classification": "integrated"},
        {"session_id": "unique", "path": "/tmp/agent-unique", "idle_hours": 200, "classification": "unique_stale"},
    ]
    fresh_changes = {"clean": [], "dirty": ["src/unintegrated.py"], "active": [], "unique": ["a.py"]}
    removed = []
    monkeypatch.setattr(sessions, "_discover_worktree_candidates", lambda: [dict(c) for c in candidates])
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(
        sessions, "_refresh_reconciliation_candidate",
        lambda item, *_args: {**item, "changed_files": fresh_changes[item["session_id"]], "inspection_error": ""},
    )
    monkeypatch.setattr(sessions, "_worktree_target_files_match", lambda _candidate, _target: False)
    monkeypatch.setattr(sessions, "_remove_reconciled_worktree", lambda item: removed.append(item["session_id"]))
    monkeypatch.setattr(
        sessions, "_queue_coordinated_worktree_cleanup",
        lambda: (_ for _ in ()).throw(AssertionError("uncoordinated reconcile must not queue")),
    )

    report = sessions.reconcile_session_worktrees(
        apply_safe=True,
        only_classes=set(sessions.LIFECYCLE_RECLAIMABLE_CLASSES),
        coordinated=False,
    )

    assert report["deleted"] == removed == ["clean"]
    assert set(data["sessions"]) == {"dirty", "active", "unique"}


def test_capacity_runs_safe_reconcile_once_before_refusing(monkeypatch):
    sessions = load_sessions_module()
    breaches = [["worktree count limit reached (200/200)"], []]
    calls = []
    monkeypatch.setattr(sessions, "expire_managed_worktrees", lambda **_kwargs: {})
    monkeypatch.setattr(sessions, "_worktree_capacity_breaches", lambda: breaches.pop(0))
    monkeypatch.setattr(
        sessions, "reconcile_session_worktrees",
        lambda **kwargs: calls.append(kwargs) or {"deleted": ["old1"]},
    )

    sessions._enforce_worktree_creation_capacity()

    assert len(calls) == 1
    assert calls[0]["coordinated"] is False
    assert calls[0]["only_classes"] == {"integrated", "disposable_integration"}


def test_reclaimable_only_reconcile_defaults_to_the_shorter_idle_window():
    sessions = load_sessions_module()
    reclaimable = set(sessions.LIFECYCLE_RECLAIMABLE_CLASSES)

    assert sessions.WORKTREE_INTEGRATED_IDLE_HOURS < sessions.WORKTREE_CLEANUP_IDLE_HOURS
    assert sessions._reconcile_idle_threshold(None, reclaimable) == sessions.WORKTREE_INTEGRATED_IDLE_HOURS
    assert sessions._reconcile_idle_threshold(None, {"integrated"}) == sessions.WORKTREE_INTEGRATED_IDLE_HOURS
    # Classes that can hold unique work keep the long window.
    assert sessions._reconcile_idle_threshold(None, None) == sessions.WORKTREE_CLEANUP_IDLE_HOURS
    assert sessions._reconcile_idle_threshold(None, {"integrated", "superseded"}) == sessions.WORKTREE_CLEANUP_IDLE_HOURS
    assert sessions._reconcile_idle_threshold(12, reclaimable) == 12


# --- ci-source regeneration, --only auto-tracking, Rust migration input set ---

CLI_GENERATOR_STUB = """\
from pathlib import Path
root = Path(__file__).resolve().parents[1]
catalog = (root / "config/cli-command-catalog.json").read_text(encoding="utf-8")
(root / "docs/migration/rust/cli.yml").write_text("# GENERATED\\ncatalog: " + catalog, encoding="utf-8")
"""

SPEC_GENERATOR_STUB = """\
import sys
from pathlib import Path
root = Path(sys.argv[sys.argv.index("--repo-root") + 1])
source = (root / "specifications/source.txt").read_text(encoding="utf-8")
(root / "specifications/generated").mkdir(parents=True, exist_ok=True)
(root / "specifications/generated/registry.yml").write_text("registry: " + source, encoding="utf-8")
"""


def test_catalog_only_change_regenerates_cli_yml(lane_env):
    sessions, _root, lane, _base, _metadata = lane_env
    (lane / "scripts" / "rust_migration_yaml.py").write_text(CLI_GENERATOR_STUB, encoding="utf-8")
    (lane / "config").mkdir()
    (lane / "config/cli-command-catalog.json").write_text('{"verified": 266}\n', encoding="utf-8")
    files = ["config/cli-command-catalog.json"]

    assert sessions._should_regenerate_rust_migration_artifacts(files)
    assert sessions._regenerate_rust_migration_artifacts(lane, files) == ["docs/migration/rust/cli.yml"]
    assert "266" in (lane / "docs/migration/rust/cli.yml").read_text(encoding="utf-8")


def test_rust_generator_inputs_are_all_trigger_paths():
    from scripts import rust_migration_inputs as inputs

    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    try:
        import rust_migration_yaml as generator
    finally:
        sys.path.remove(str(PROJECT_ROOT / "scripts"))
    read_by_generator = [
        generator.legacy.CLI_CATALOG, generator.legacy.SDK_CAPABILITIES, generator.legacy.UNIT_REGISTRY,
        generator.legacy.UNIT_PROTOCOL, generator.CURATED, generator.LANES, generator.SPEC_LINKS,
        generator.ASSERTION_INDEX, generator.perf.HISTORY,
    ]
    for path in read_by_generator:
        assert inputs.is_rust_migration_input(path.as_posix()), path


def test_stale_specification_artifacts_are_rebuilt_for_publication_then_restored(lane_env):
    sessions, _root, lane, _base, _metadata = lane_env
    from scripts import lane_ci_source

    (lane / "scripts" / "specifications.py").write_text(SPEC_GENERATOR_STUB, encoding="utf-8")
    (lane / "specifications" / "generated").mkdir(parents=True)
    (lane / "specifications/source.txt").write_text("new\n", encoding="utf-8")
    registry = lane / "specifications/generated/registry.yml"
    registry.write_text("registry: stale\n", encoding="utf-8")

    with lane_ci_source.fresh_generated_artifacts(
        lane, ["specifications/source.txt"], specification_governed=True
    ) as warnings:
        assert warnings == []
        assert registry.read_text(encoding="utf-8") == "registry: new\n"
    assert registry.read_text(encoding="utf-8") == "registry: stale\n"

    with lane_ci_source.fresh_generated_artifacts(lane, ["changed.txt"], specification_governed=False):
        assert registry.read_text(encoding="utf-8") == "registry: stale\n"


def test_only_files_are_tracked_automatically_and_other_session_stays_advisory(monkeypatch, capsys):
    sessions = load_sessions_module()
    stored = {"sessions": {"abcd": {"modified_files": ["old.py"]}}}
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(stored))

    modified = sessions._auto_track_only_files(
        "abcd", stored["sessions"]["abcd"], "only", ["new.py", "shared.py"], ["old.py"], {"shared.py": "efgh"}
    )

    assert modified == ["old.py", "new.py", "shared.py"]
    assert stored["sessions"]["abcd"]["modified_files"] == ["old.py", "new.py", "shared.py"]
    err = capsys.readouterr().err
    assert "shared.py [also tracked by: efgh; advisory]" in err
    assert "new.py [also" not in err
    # Unrelated dirty files are not tracked: only the --only selection is.
    assert "unrelated.py" not in modified
    assert sessions._auto_track_only_files("abcd", {}, "default", ["x.py"], ["old.py"], {}) == ["old.py"]
