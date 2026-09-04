#!/usr/bin/env python3
"""Tests for worktree-backed deploy planning in sessions.py.

The deploy integration helpers are intentionally tested without committing to
the real repository. They verify that the root index is no longer the source of
truth for a session's change set.
"""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PATH = PROJECT_ROOT / "scripts" / "sessions.py"


def load_sessions_module():
    spec = importlib.util.spec_from_file_location("openmates_sessions_worktree_deploy", SESSIONS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def make_cloud_git_repo(
    tmp_path: Path,
    sessions,
    monkeypatch,
    *,
    branch: str = "main",
    remote_tail: str = "OpenMatesCloud.git",
    patch_remote_hash: bool = True,
) -> tuple[Path, Path]:
    cloud = tmp_path / "OpenMatesCloud"
    remote = tmp_path / "remotes" / remote_tail
    cloud.mkdir()
    remote.parent.mkdir()
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True, text=True)
    run_git(cloud, "init")
    run_git(cloud, "checkout", "-b", branch)
    run_git(cloud, "config", "user.email", "tests@example.invalid")
    run_git(cloud, "config", "user.name", "Session Tests")
    (cloud / "README.md").write_text("base\n", encoding="utf-8")
    run_git(cloud, "add", "README.md")
    run_git(cloud, "commit", "-m", "initial")
    run_git(cloud, "remote", "add", "origin", str(remote))
    monkeypatch.setattr(sessions, "OPENMATESCLOUD_REPO_ROOT", cloud.resolve())
    if patch_remote_hash:
        monkeypatch.setattr(sessions, "OPENMATESCLOUD_REPO_REMOTE_ID_SHA256", sessions._remote_identity_sha256(str(remote)))
    return cloud, remote


def stub_external_deploy_lock(monkeypatch, sessions, calls: list[tuple] | None = None) -> list[tuple]:
    if calls is None:
        calls = []

    def acquire(lock_type, session_id, **kwargs):
        calls.append(("acquire", lock_type, session_id, kwargs))
        return True

    def release(lock_type, **kwargs):
        calls.append(("release", lock_type, kwargs))
        return True

    monkeypatch.setattr(sessions, "_wait_and_acquire_session_lock", acquire)
    monkeypatch.setattr(sessions, "_release_session_lock", release)
    return calls


def test_worktree_changed_files_are_scoped_to_session_diff(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    worktree = tmp_path / "agent-abcd"
    def fake_run(cmd, cwd=None):
        if cmd[:3] == ["git", "diff", "--name-only"]:
            return 0, "scripts/sessions.py\ndocs/example.md\n", ""
        if cmd == ["git", "ls-files", "--others", "--exclude-standard"]:
            return 0, "scripts/tests/new_test.py\n", ""
        return 0, "", ""

    monkeypatch.setattr(
        sessions,
        "_run_cmd",
        fake_run,
    )

    changed = sessions._worktree_changed_files({"path": str(worktree), "base_commit": "abc123"})

    assert changed == ["docs/example.md", "scripts/sessions.py", "scripts/tests/new_test.py"]


def test_worktree_patch_id_is_scoped_to_selected_files(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    included = tmp_path / "included.txt"
    excluded = tmp_path / "excluded.txt"
    included.write_text("included", encoding="utf-8")
    excluded.write_text("first", encoding="utf-8")
    commands = []

    def fake_run(cmd, **_kwargs):
        commands.append(cmd)
        return SimpleNamespace(returncode=0, stdout=b"tracked diff", stderr=b"")

    monkeypatch.setattr(sessions.subprocess, "run", fake_run)
    monkeypatch.setattr(sessions, "_worktree_untracked_files", lambda _metadata: {"included.txt", "excluded.txt"})
    metadata = {"path": str(tmp_path), "base_commit": "abc123"}

    first = sessions._worktree_patch_id(metadata, ["tracked.py", "included.txt"])
    excluded.write_text("second", encoding="utf-8")
    second = sessions._worktree_patch_id(metadata, ["tracked.py", "included.txt"])

    assert first == second
    diff_commands = [command for command in commands if command[:2] == ["git", "diff"]]
    assert diff_commands == [
        ["git", "diff", "--binary", "abc123", "--", "tracked.py"],
        ["git", "diff", "--binary", "abc123", "--", "tracked.py"],
    ]


def test_apply_worktree_diff_with_only_untracked_file_skips_tracked_diff(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    worktree = tmp_path / "worktree"
    root = tmp_path / "root"
    source = worktree / "new.txt"
    source.parent.mkdir(parents=True)
    source.write_text("new file", encoding="utf-8")
    root.mkdir()
    subprocess_calls = []

    def fake_run(*args, **kwargs):
        subprocess_calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(sessions, "PROJECT_ROOT", root)
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)
    monkeypatch.setattr(sessions, "_worktree_untracked_files", lambda _metadata: {"new.txt"})
    monkeypatch.setattr(sessions.subprocess, "run", fake_run)

    sessions._apply_worktree_diff_to_root(
        {"path": str(worktree), "base_commit": "abc123"},
        ["new.txt"],
    )

    assert subprocess_calls == []
    assert (root / "new.txt").read_text(encoding="utf-8") == "new file"


def test_session_deploy_files_ignore_foreign_root_dirty(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    worktree = tmp_path / "agent-abcd"
    session = {
        "modified_files": ["scripts/sessions.py", "docs/example.md"],
        "worktree": {"path": str(worktree), "base_commit": "abc123", "status": "active"},
    }
    monkeypatch.setattr(sessions, "_worktree_changed_files", lambda _metadata: ["scripts/sessions.py"])

    to_commit = sessions._session_deploy_files(session, exclude={"docs/example.md"})

    assert to_commit == ["scripts/sessions.py"]


def test_session_deploy_files_accept_legacy_worktree_tracking(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    session = {
        "modified_files": [
            ".openmates-agent-worktrees/agent-abcd/.openmates-agent-worktrees/agent-abcd/scripts/sessions.py"
        ],
        "worktree": {"path": str(tmp_path / "agent-abcd"), "base_commit": "abc123", "status": "active"},
    }
    monkeypatch.setattr(sessions, "_worktree_changed_files", lambda _metadata: ["scripts/sessions.py"])

    assert sessions._session_deploy_files(session, exclude=set()) == ["scripts/sessions.py"]


def test_session_deploy_files_exclude_runtime_proof_artifacts(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    worktree = tmp_path / "agent-abcd"
    session = {
        "modified_files": [
            "frontend/apps/web_app/tests/example.spec.ts",
            "scripts/.tmp/query_control_plane_runtime.py",
            "test-results/proof-videos/abcd/example.spec/approved-contract.json",
            "test-results/proof-video-sources/source.json",
        ],
        "worktree": {"path": str(worktree), "base_commit": "abc123", "status": "active"},
    }
    monkeypatch.setattr(sessions, "_worktree_changed_files", lambda _metadata: list(session["modified_files"]))

    assert sessions._session_deploy_files(session, exclude=set()) == [
        "frontend/apps/web_app/tests/example.spec.ts"
    ]


def test_session_deploy_files_filters_runtime_artifact_dirs_before_snapshot(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    worktree = tmp_path / "agent-abcd"
    artifact_dir = worktree / "test-results" / "proof-videos" / "abcd" / "example.spec" / "frames"
    artifact_dir.mkdir(parents=True)
    (worktree / "safe.py").write_text("pending\n", encoding="utf-8")
    session = {
        "modified_files": [
            "safe.py",
            "test-results/proof-videos/abcd/example.spec/frames",
        ],
        "worktree": {
            "path": str(worktree),
            "base_commit": "base",
            "merged_commit": "merged",
            "status": "active",
        },
    }
    monkeypatch.setattr(
        sessions,
        "_worktree_changed_files",
        lambda _metadata: list(session["modified_files"]),
    )
    monkeypatch.setattr(
        sessions,
        "_snapshot_worktree_base_states",
        lambda _metadata, files: {relative_path: {"exists": False} for relative_path in files},
    )

    assert sessions._session_deploy_files(session, exclude=set()) == ["safe.py"]


def test_session_deploy_files_exclude_changes_already_on_target_branch(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    worktree = tmp_path / "agent-abcd"
    worktree.mkdir()
    (worktree / "already-merged.py").write_text("current\n", encoding="utf-8")
    (worktree / "pending.py").write_text("pending\n", encoding="utf-8")
    session = {
        "modified_files": ["already-merged.py", "pending.py"],
        "worktree": {"path": str(worktree), "base_commit": "base", "status": "active"},
    }
    monkeypatch.setattr(
        sessions,
        "_worktree_changed_files",
        lambda _metadata: ["already-merged.py", "pending.py"],
    )
    monkeypatch.setattr(
        sessions,
        "_snapshot_worktree_base_states",
        lambda metadata, _files: {
            "already-merged.py": sessions._snapshot_file_states(worktree, ["already-merged.py"])["already-merged.py"],
            "pending.py": {"exists": True, "sha256": "different", "executable": False},
        } if metadata.get("merged_commit") == "origin/dev" else {},
    )

    assert sessions._session_deploy_files(session, exclude=set()) == ["pending.py"]


def test_snapshot_worktree_base_states_handles_literal_bracket_paths(tmp_path):
    sessions = load_sessions_module()
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init")
    run_git(repo, "config", "user.email", "tests@example.invalid")
    run_git(repo, "config", "user.name", "Session Tests")
    route = repo / "frontend" / "routes" / "[slug]" / "+page.svelte"
    route.parent.mkdir(parents=True)
    route.write_text("<h1>route</h1>\n", encoding="utf-8")
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-m", "route")
    commit = run_git(repo, "rev-parse", "HEAD").stdout.strip()

    states = sessions._snapshot_worktree_base_states(
        {"path": str(repo), "base_commit": commit},
        ["frontend/routes/[slug]/+page.svelte"],
    )

    assert states["frontend/routes/[slug]/+page.svelte"]["exists"] is True


def test_snapshot_worktree_base_states_treats_deleted_bracket_paths_as_missing(tmp_path):
    sessions = load_sessions_module()
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init")
    run_git(repo, "config", "user.email", "tests@example.invalid")
    run_git(repo, "config", "user.name", "Session Tests")
    route = repo / "frontend" / "routes" / "[slug]" / "+page.svelte"
    route.parent.mkdir(parents=True)
    route.write_text("<h1>route</h1>\n", encoding="utf-8")
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-m", "route")
    route.unlink()
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-m", "delete route")
    commit = run_git(repo, "rev-parse", "HEAD").stdout.strip()

    states = sessions._snapshot_worktree_base_states(
        {"path": str(repo), "base_commit": commit},
        ["frontend/routes/[slug]/+page.svelte"],
    )

    assert states["frontend/routes/[slug]/+page.svelte"] == {"exists": False}


def test_merged_worktree_deploy_selects_only_changes_after_recorded_snapshot(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    unchanged = tmp_path / "unchanged.py"
    amended = tmp_path / "amended.py"
    unchanged.write_text("same\n", encoding="utf-8")
    amended.write_text("after\n", encoding="utf-8")
    session = {
        "modified_files": ["unchanged.py", "amended.py"],
        "worktree": {
            "path": str(tmp_path),
            "status": "merged",
            "merged_commit": "last-deploy",
            "root_applied_files": {
                "amended.py": {
                    "exists": True,
                    "sha256": "previous",
                    "executable": False,
                },
            },
        },
    }
    monkeypatch.setattr(sessions, "_worktree_changed_files", lambda _metadata: ["unchanged.py", "amended.py"])
    monkeypatch.setattr(
        sessions,
        "_snapshot_worktree_base_states",
        lambda _metadata, _files: {
            "unchanged.py": sessions._snapshot_file_states(tmp_path, ["unchanged.py"])["unchanged.py"],
            "amended.py": {"exists": True, "sha256": "previous", "executable": False},
        },
    )

    assert sessions._session_deploy_files(session, exclude=set()) == ["amended.py"]


def test_merged_worktree_deploy_selects_revert_and_deletion(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    reverted = tmp_path / "reverted.py"
    reverted.write_text("original\n", encoding="utf-8")
    session = {
        "modified_files": ["reverted.py", "added.py"],
        "worktree": {"path": str(tmp_path), "status": "merged", "merged_commit": "last-deploy"},
    }
    monkeypatch.setattr(sessions, "_worktree_changed_files", lambda _metadata: [])
    monkeypatch.setattr(
        sessions,
        "_snapshot_worktree_base_states",
        lambda _metadata, _files: {
            "reverted.py": {"exists": True, "sha256": "deployed-content", "executable": False},
            "added.py": {"exists": True, "sha256": "deployed-added", "executable": False},
        },
    )

    assert sessions._session_deploy_files(session, exclude=set()) == ["added.py", "reverted.py"]


def test_relative_repo_path_prefers_session_worktree(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    repo = tmp_path / "OpenMates"
    worktree = repo / ".openmates-agent-worktrees" / "agent-abcd"
    monkeypatch.setattr(sessions, "PROJECT_ROOT", repo)

    session = {"worktree": {"path": str(worktree), "base_commit": "abc123", "status": "active"}}

    assert sessions._relative_repo_path_for_session(worktree / "scripts" / "sessions.py", session) == "scripts/sessions.py"
    assert sessions._relative_repo_path_for_session(repo / "scripts" / "sessions.py", session) == "scripts/sessions.py"


def test_relative_repo_path_uses_openmatescloud_repo_root(tmp_path):
    sessions = load_sessions_module()
    cloud = tmp_path / "OpenMatesCloud"
    sessions.OPENMATESCLOUD_REPO_ROOT = cloud.resolve()
    session = {
        "repo_id": "openmatescloud",
        "repo_name": "OpenMatesCloud",
        "repo_root": str(cloud),
        "repo_branch": "main",
    }

    assert sessions._relative_repo_path_for_session(cloud / "docker-compose.openmatescloud.yml", session) == "docker-compose.openmatescloud.yml"
    assert sessions._relative_repo_path_for_session(cloud / "backend" / "tests" / "test_overlay_compose.py", session) == "backend/tests/test_overlay_compose.py"


def test_external_repo_session_deploy_files_use_session_checkout(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    cloud = tmp_path / "OpenMatesCloud"
    monkeypatch.setattr(sessions, "OPENMATESCLOUD_REPO_ROOT", cloud.resolve())
    session = {
        "repo_id": "openmatescloud",
        "repo_name": "OpenMatesCloud",
        "repo_root": str(tmp_path / "evil"),
        "repo_branch": "evil",
        "modified_files": ["docker-compose.openmatescloud.yml", "backend/tests/test_overlay_compose.py"],
    }
    seen_roots = []

    def fake_dirty(*, checkout_root=None):
        seen_roots.append(checkout_root)
        return {"docker-compose.openmatescloud.yml", "untracked.txt"}

    monkeypatch.setattr(sessions, "_get_dirty_files", fake_dirty)

    assert sessions._session_deploy_files(session, exclude=set()) == ["docker-compose.openmatescloud.yml"]
    assert seen_roots == [cloud.resolve()]


def test_external_repo_session_deploy_files_ignore_injected_worktree(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    cloud = tmp_path / "OpenMatesCloud"
    monkeypatch.setattr(sessions, "OPENMATESCLOUD_REPO_ROOT", cloud.resolve())
    session = {
        "repo_id": "openmatescloud",
        "modified_files": ["docker-compose.openmatescloud.yml"],
        "worktree": {"path": str(tmp_path / "evil-worktree"), "base_commit": "abc123", "status": "active"},
    }
    seen_roots = []

    def fake_dirty(*, checkout_root=None):
        seen_roots.append(checkout_root)
        return {"docker-compose.openmatescloud.yml"}

    monkeypatch.setattr(sessions, "_get_dirty_files", fake_dirty)
    monkeypatch.setattr(
        sessions,
        "_worktree_changed_files",
        lambda _metadata: (_ for _ in ()).throw(AssertionError("external sessions must ignore worktree metadata")),
    )

    assert sessions._session_deploy_files(session, exclude=set()) == ["docker-compose.openmatescloud.yml"]
    assert seen_roots == [cloud.resolve()]


def test_external_openmatescloud_deploy_runs_gate_and_pushes_main(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    stub_external_deploy_lock(monkeypatch, sessions)
    cloud = tmp_path / "OpenMatesCloud"
    monkeypatch.setattr(sessions, "OPENMATESCLOUD_REPO_ROOT", cloud.resolve())
    remote_url = "git@example.invalid:OpenMatesCloud.git"
    monkeypatch.setattr(sessions, "OPENMATESCLOUD_REPO_REMOTE_ID_SHA256", sessions._remote_identity_sha256(remote_url))
    (cloud / "backend" / "tests").mkdir(parents=True)
    (cloud / "backend" / "tests" / "test_overlay_compose.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    (cloud / "docker-compose.openmatescloud.yml").write_text("services: {}\n", encoding="utf-8")
    session = {
        "repo_id": "openmatescloud",
        "repo_name": "OpenMatesCloud",
        "repo_root": str(cloud),
        "repo_branch": "main",
        "repo_remote": "origin",
        "modified_files": ["docker-compose.openmatescloud.yml"],
    }
    commands = []

    def fake_run(cmd, cwd=None, timeout=120):
        commands.append((cmd, cwd, timeout))
        if cmd == ["git", "rev-parse", "--show-toplevel"]:
            return 0, str(cloud.resolve()), ""
        if cmd == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return 0, "main", ""
        if cmd == ["git", "remote", "get-url", "origin"]:
            return 0, remote_url, ""
        if cmd == ["git", "rev-parse", "HEAD"]:
            return 0, "abc123456789", ""
        return 0, "", ""

    monkeypatch.setattr(sessions, "_run_cmd", fake_run)
    monkeypatch.setattr(sessions, "_get_staged_files", lambda *, checkout_root=None: set())
    monkeypatch.setattr(sessions, "_validate_staged_deploy_files", lambda *_args, **_kwargs: True)

    sessions._deploy_external_repo(
        SimpleNamespace(session="cafe", title="fix: cloud", message="", no_verify=False, use_staged=False),
        session,
        ["docker-compose.openmatescloud.yml"],
        [],
    )

    assert ([sessions.sys.executable, "-m", "pytest", "backend/tests/test_overlay_compose.py"], str(cloud.resolve()), 120) in commands
    assert (["git", "push", "origin", "HEAD:refs/heads/main"], str(cloud.resolve()), 300) in commands


def test_openmatescloud_metadata_ignores_environment_overrides(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    cloud = tmp_path / "OpenMatesCloud"
    monkeypatch.setattr(sessions, "OPENMATESCLOUD_REPO_ROOT", cloud.resolve())
    monkeypatch.setenv("OPENMATES_CLOUD_REPO_ROOT", str(tmp_path / "evil"))
    monkeypatch.setenv("OPENMATES_CLOUD_REPO_BRANCH", "evil")
    monkeypatch.setenv("OPENMATES_CLOUD_REPO_REMOTE", "upstream")

    metadata = sessions._repo_metadata("openmatescloud")

    assert metadata["repo_root"] == str(cloud.resolve())
    assert metadata["repo_branch"] == "main"
    assert metadata["repo_remote"] == "origin"


def test_external_openmatescloud_deploy_ignores_tampered_session_metadata(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    stub_external_deploy_lock(monkeypatch, sessions)
    cloud, remote = make_cloud_git_repo(tmp_path, sessions, monkeypatch)
    (cloud / "README.md").write_text("changed\n", encoding="utf-8")
    session = {
        "repo_id": "openmatescloud",
        "repo_name": "EvilCloud",
        "repo_root": str(tmp_path / "evil"),
        "repo_branch": "evil",
        "repo_remote": "upstream",
        "modified_files": ["README.md"],
    }

    sessions._deploy_external_repo(
        SimpleNamespace(session="cafe", title="fix: cloud", message="", no_verify=True, use_staged=False),
        session,
        ["README.md"],
        [],
    )

    assert run_git(cloud, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "main"
    assert run_git(cloud, "status", "--porcelain").stdout.strip() == ""
    remote_head = subprocess.run(
        ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/main"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert remote_head == run_git(cloud, "rev-parse", "HEAD").stdout.strip()


def test_openmatescloud_validation_rejects_wrong_branch(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    make_cloud_git_repo(tmp_path, sessions, monkeypatch, branch="feature")

    try:
        sessions._validate_session_repo(sessions._repo_metadata("openmatescloud"))
    except RuntimeError as exc:
        assert "must be on main" in str(exc)
    else:
        raise AssertionError("expected wrong branch validation failure")


def test_openmatescloud_validation_rejects_wrong_remote(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    make_cloud_git_repo(tmp_path, sessions, monkeypatch, remote_tail="Other.git", patch_remote_hash=False)
    trusted_remote = tmp_path / "remotes" / "OpenMatesCloud.git"
    monkeypatch.setattr(sessions, "OPENMATESCLOUD_REPO_REMOTE_ID_SHA256", sessions._remote_identity_sha256(str(trusted_remote)))

    try:
        sessions._validate_session_repo(sessions._repo_metadata("openmatescloud"))
    except RuntimeError as exc:
        assert "origin remote is not valid" in str(exc)
    else:
        raise AssertionError("expected wrong remote validation failure")


def test_openmatescloud_validation_rejects_same_basename_untrusted_remote(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    cloud, trusted_remote = make_cloud_git_repo(tmp_path, sessions, monkeypatch)
    untrusted_remote = tmp_path / "untrusted" / "OpenMatesCloud.git"
    untrusted_remote.parent.mkdir()
    run_git(cloud, "remote", "set-url", "origin", str(untrusted_remote))
    monkeypatch.setattr(sessions, "OPENMATESCLOUD_REPO_REMOTE_ID_SHA256", sessions._remote_identity_sha256(str(trusted_remote)))

    try:
        sessions._validate_session_repo(sessions._repo_metadata("openmatescloud"))
    except RuntimeError as exc:
        assert "origin remote is not valid" in str(exc)
    else:
        raise AssertionError("expected same-basename remote validation failure")


def test_openmatescloud_validation_rejects_non_default_remote_port(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    cloud, _trusted_remote = make_cloud_git_repo(tmp_path, sessions, monkeypatch)
    trusted_url = "ssh://git@example.invalid/OpenMatesCloud.git"
    untrusted_url = "ssh://git@example.invalid:2222/OpenMatesCloud.git"
    monkeypatch.setattr(sessions, "OPENMATESCLOUD_REPO_REMOTE_ID_SHA256", sessions._remote_identity_sha256(trusted_url))
    run_git(cloud, "remote", "set-url", "origin", untrusted_url)

    try:
        sessions._validate_session_repo(sessions._repo_metadata("openmatescloud"))
    except RuntimeError as exc:
        assert "origin remote is not valid" in str(exc)
    else:
        raise AssertionError("expected non-default port remote validation failure")


def test_external_openmatescloud_deploy_preserves_foreign_staged_files(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    stub_external_deploy_lock(monkeypatch, sessions)
    cloud, _remote = make_cloud_git_repo(tmp_path, sessions, monkeypatch)
    (cloud / "README.md").write_text("changed\n", encoding="utf-8")
    (cloud / "foreign.txt").write_text("foreign\n", encoding="utf-8")
    run_git(cloud, "add", "foreign.txt")

    try:
        sessions._deploy_external_repo(
            SimpleNamespace(session="cafe", title="fix: cloud", message="", no_verify=True, use_staged=False),
            {"repo_id": "openmatescloud", "modified_files": ["README.md"]},
            ["README.md"],
            [],
        )
    except RuntimeError as exc:
        assert "staged files outside this session" in str(exc)
    else:
        raise AssertionError("expected foreign staged file validation failure")

    assert run_git(cloud, "diff", "--name-only", "--cached").stdout.splitlines() == ["foreign.txt"]


def test_external_openmatescloud_deploy_revalidates_after_gate_before_staging(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    stub_external_deploy_lock(monkeypatch, sessions)
    cloud, _remote = make_cloud_git_repo(tmp_path, sessions, monkeypatch)
    (cloud / "README.md").write_text("changed\n", encoding="utf-8")

    def mutate_branch_during_gate(_session, _files, *, checkout_root, no_verify):
        run_git(checkout_root, "checkout", "-b", "feature")

    monkeypatch.setattr(sessions, "_run_external_repo_deploy_gates", mutate_branch_during_gate)

    try:
        sessions._deploy_external_repo(
            SimpleNamespace(session="cafe", title="fix: cloud", message="", no_verify=True, use_staged=False),
            {"repo_id": "openmatescloud", "modified_files": ["README.md"]},
            ["README.md"],
            [],
        )
    except RuntimeError as exc:
        assert "must be on main" in str(exc)
    else:
        raise AssertionError("expected post-gate branch validation failure")

    assert run_git(cloud, "diff", "--name-only", "--cached").stdout.strip() == ""


def test_external_openmatescloud_deploy_holds_repo_lock_around_body(monkeypatch):
    sessions = load_sessions_module()
    calls: list[tuple] = []
    stub_external_deploy_lock(monkeypatch, sessions, calls)

    def fake_locked(*_args, **_kwargs):
        calls.append(("body",))

    monkeypatch.setattr(sessions, "_deploy_external_repo_locked", fake_locked)

    sessions._deploy_external_repo(
        SimpleNamespace(session="cafe", title="fix: cloud", message="", no_verify=True, use_staged=False),
        {"repo_id": "openmatescloud", "modified_files": ["README.md"]},
        ["README.md"],
        [],
    )

    assert calls[0][0:3] == ("acquire", "openmatescloud_deploy", "cafe")
    assert calls[1] == ("body",)
    assert calls[2] == ("release", "openmatescloud_deploy", {"released_by": "cafe"})


def test_external_openmatescloud_deploy_rejects_same_session_lock_reentry(monkeypatch):
    sessions = load_sessions_module()
    calls: list[tuple] = []

    monkeypatch.setattr(
        sessions,
        "_wait_and_acquire_session_lock",
        lambda lock_type, session_id, **kwargs: calls.append(("acquire", lock_type, session_id, kwargs)) or False,
    )
    monkeypatch.setattr(
        sessions,
        "_release_session_lock",
        lambda lock_type, **kwargs: calls.append(("release", lock_type, kwargs)) or True,
    )
    monkeypatch.setattr(
        sessions,
        "_deploy_external_repo_locked",
        lambda *_args, **_kwargs: calls.append(("body",)),
    )

    try:
        sessions._deploy_external_repo(
            SimpleNamespace(session="cafe", title="fix: cloud", message="", no_verify=True, use_staged=False),
            {"repo_id": "openmatescloud", "modified_files": ["README.md"]},
            ["README.md"],
            [],
        )
    except RuntimeError as exc:
        assert "deploy lock is already held" in str(exc)
    else:
        raise AssertionError("expected same-session lock re-entry failure")

    assert calls == [("acquire", "openmatescloud_deploy", "cafe", {
        "phase": "deploying_sibling_repo",
        "timeout": None,
        "poll": 30,
    })]


def test_external_openmatescloud_deploy_lock_uses_deploy_ttl():
    sessions = load_sessions_module()

    assert sessions._lock_stale_minutes("openmatescloud_deploy") == sessions.VERCEL_DEPLOY_LOCK_MINUTES


def test_cmd_deploy_external_repo_ignores_injected_worktree_metadata(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    cloud = tmp_path / "OpenMatesCloud"
    monkeypatch.setattr(sessions, "OPENMATESCLOUD_REPO_ROOT", cloud.resolve())
    captured = {}
    session = {
        "repo_id": "openmatescloud",
        "modified_files": ["README.md"],
        "worktree": {"path": str(tmp_path / "evil-worktree"), "base_commit": "abc123", "status": "active"},
    }

    monkeypatch.setattr(sessions, "_load_sessions", lambda: {"sessions": {"cafe": session}})
    monkeypatch.setattr(sessions, "_get_dirty_files", lambda *, checkout_root=None: {"README.md"})
    monkeypatch.setattr(
        sessions,
        "_worktree_patch_id",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("external deploy must not hash worktree metadata")),
    )
    monkeypatch.setattr(
        sessions,
        "_deploy_external_repo",
        lambda _args, _session, to_commit, _dirty: captured.setdefault("to_commit", to_commit),
    )

    sessions.cmd_deploy(SimpleNamespace(
        session="cafe",
        exclude=[],
        use_staged=False,
        expected_patch_id="",
        expected_checkpoint_commit="",
        end_session=False,
        skip_visual_smoke_reason=None,
    ))

    assert captured["to_commit"] == ["README.md"]


def test_external_repo_use_staged_rejects_foreign_sibling_index(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    cloud = tmp_path / "OpenMatesCloud"
    monkeypatch.setattr(sessions, "OPENMATESCLOUD_REPO_ROOT", cloud.resolve())
    deploy_called = False

    monkeypatch.setattr(
        sessions,
        "_load_sessions",
        lambda: {"sessions": {"cafe": {"repo_id": "openmatescloud", "modified_files": ["owned.txt"]}}},
    )
    monkeypatch.setattr(sessions, "_get_dirty_files", lambda *, checkout_root=None: set())
    monkeypatch.setattr(sessions, "_session_deploy_files", lambda _session, _exclude: [])
    monkeypatch.setattr(sessions, "_get_staged_files", lambda *, checkout_root=None: {"owned.txt", "foreign.txt"})

    def fake_external_deploy(*_args):
        nonlocal deploy_called
        deploy_called = True

    monkeypatch.setattr(sessions, "_deploy_external_repo", fake_external_deploy)

    try:
        sessions.cmd_deploy(SimpleNamespace(
            session="cafe",
            exclude=[],
            use_staged=True,
            expected_patch_id="",
            expected_checkpoint_commit="",
            end_session=False,
            skip_visual_smoke_reason=None,
        ))
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("expected foreign staged use-staged failure")

    assert deploy_called is False


def test_external_repo_use_staged_reads_sibling_index(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    cloud = tmp_path / "OpenMatesCloud"
    monkeypatch.setattr(sessions, "OPENMATESCLOUD_REPO_ROOT", cloud.resolve())
    captured = {}
    seen_checkout_roots = []

    monkeypatch.setattr(sessions, "_load_sessions", lambda: {"sessions": {"cafe": {"repo_id": "openmatescloud", "modified_files": ["cloud.txt"]}}})
    monkeypatch.setattr(sessions, "_get_dirty_files", lambda *, checkout_root=None: set())
    monkeypatch.setattr(sessions, "_session_deploy_files", lambda _session, _exclude: [])

    def fake_staged_files(*, checkout_root=None):
        seen_checkout_roots.append(checkout_root)
        return {"cloud.txt"} if checkout_root == cloud.resolve() else {"root.txt"}

    def fake_external_deploy(_args, _session, to_commit, _dirty):
        captured["to_commit"] = to_commit

    monkeypatch.setattr(sessions, "_get_staged_files", fake_staged_files)
    monkeypatch.setattr(sessions, "_deploy_external_repo", fake_external_deploy)

    sessions.cmd_deploy(SimpleNamespace(
        session="cafe",
        exclude=[],
        use_staged=True,
        expected_patch_id="",
        expected_checkpoint_commit="",
        end_session=False,
        skip_visual_smoke_reason=None,
    ))

    assert seen_checkout_roots == [cloud.resolve()]
    assert captured["to_commit"] == ["cloud.txt"]


def test_prune_stale_preserves_managed_worktree_sessions(monkeypatch):
    sessions = load_sessions_module()
    monkeypatch.setattr(sessions, "_hours_since", lambda _value: sessions.STALE_SESSION_HOURS + 1)
    data = {
        "sessions": {
            "plain": {"last_active": "old"},
            "bound": {"last_active": "old", "opencode_session_id": "ses_active"},
            "worktree": {"last_active": "old", "worktree": {"path": "/tmp/agent", "status": "active"}},
            "archived": {"last_active": "old", "worktree": {"path": "/tmp/archive", "status": "archived"}},
        }
    }

    assert sessions._prune_stale(data) == ["plain", "bound", "archived"]
    assert set(data["sessions"]) == {"worktree"}
