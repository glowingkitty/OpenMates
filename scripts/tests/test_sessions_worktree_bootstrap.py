#!/usr/bin/env python3
# contract-test-file: tooling
"""Red contracts for deterministic session-worktree bootstrap.

The tests isolate sessions.py state and command execution so bootstrap behavior
can be implemented without modifying root dependencies or generated artifacts.
Real package installation remains covered by the isolated runtime verifier.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PATH = PROJECT_ROOT / "scripts" / "sessions.py"


def load_sessions_module():
    spec = importlib.util.spec_from_file_location("openmates_sessions_bootstrap", SESSIONS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_bootstrap_is_worktree_local_and_idempotent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    root = tmp_path / "root"
    worktree = tmp_path / "worktree"
    root.mkdir()
    worktree.mkdir()
    calls: list[tuple[tuple[str, ...], Path | None]] = []

    def fake_run(command, cwd=None, timeout=None):
        calls.append((tuple(command), Path(cwd) if cwd else None))
        return 0, "", ""

    monkeypatch.setattr(sessions, "PROJECT_ROOT", root)
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)
    monkeypatch.setattr(sessions, "_run_cmd", fake_run)

    first = sessions.bootstrap_session_worktree(worktree)
    second = sessions.bootstrap_session_worktree(worktree)

    assert first["status"] == "ready"
    assert second["status"] == "ready"
    assert calls
    assert all(cwd == worktree for _, cwd in calls)
    assert all(str(root / "node_modules") not in " ".join(command) for command, _ in calls)
    assert "--config.engine-strict=false" in calls[0][0]
    assert not any(argument.startswith("--filter") for argument in calls[0][0])


def test_bootstrap_failure_never_reports_ready(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    root = tmp_path / "root"
    worktree = tmp_path / "worktree"
    root.mkdir()
    worktree.mkdir()
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)
    monkeypatch.setattr(sessions, "_run_cmd", lambda command, cwd=None, timeout=None: (1, "", "offline cache miss"))

    result = sessions.bootstrap_session_worktree(worktree)

    assert result["status"] == "failed"
    assert result["reason"] == "dependency_install_failed"
    assert "offline cache miss" in result["message"]


def test_integration_bootstraps_for_backend_app_metadata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    calls: list[tuple[Path, bool]] = []
    monkeypatch.setattr(sessions, "_reuse_prepared_dependencies", lambda checkout, prepared: None)
    monkeypatch.setattr(
        sessions,
        "bootstrap_session_worktree",
        lambda root, *, dependencies_prepared: calls.append((root, dependencies_prepared)) or {"status": "ready"},
    )

    sessions._bootstrap_integration_for_files(tmp_path, ["backend/apps/health/app.yml"])

    assert calls == [(tmp_path, True)]


def test_scoped_integration_uses_prepared_dependencies(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    root = tmp_path / "root"
    worktree = tmp_path / "worktree"
    root.mkdir()
    worktree.mkdir()
    calls: list[tuple[str, ...]] = []

    def fake_run(command, cwd=None, timeout=None):
        assert Path(cwd) == worktree
        calls.append(tuple(command))
        return 0, "", ""

    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)
    reused: list[tuple[Path, Path]] = []
    monkeypatch.setattr(sessions, "_reuse_prepared_dependencies", lambda checkout, prepared: reused.append((checkout, prepared)))
    monkeypatch.setattr(sessions, "_run_cmd", fake_run)
    sessions._bootstrap_integration_for_files(worktree, ["frontend/apps/web_app/src/routes/+page.svelte"])

    assert reused == [(worktree, root)]
    assert calls == [
        ("node", "frontend/packages/ui/scripts/build-tokens.js"),
        ("node", "frontend/packages/ui/scripts/build-translations.js"),
        ("node", "frontend/packages/ui/scripts/validate-locales.js"),
    ]


@pytest.mark.parametrize("changed_file", [
    "frontend/packages/ui/package.json",
    "frontend/apps/web_app/package.json",
    "package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml", ".npmrc", ".pnpmfile.cjs",
    "patches/example.patch",
])
def test_dependency_edits_keep_full_integration_install(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, changed_file: str,
) -> None:
    sessions = load_sessions_module()
    calls: list[tuple[Path, bool]] = []
    monkeypatch.setattr(
        sessions,
        "bootstrap_session_worktree",
        lambda root, *, dependencies_prepared: calls.append((root, dependencies_prepared)) or {"status": "ready"},
    )

    sessions._bootstrap_integration_for_files(
        tmp_path, ["backend/apps/health/app.yml", changed_file],
    )

    assert calls == [(tmp_path, False)]


@pytest.mark.parametrize("changed_file", ["package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml"])
def test_root_dependency_edits_alone_trigger_full_bootstrap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, changed_file: str,
) -> None:
    sessions = load_sessions_module()
    calls: list[tuple[Path, bool]] = []
    monkeypatch.setattr(
        sessions,
        "bootstrap_session_worktree",
        lambda root, *, dependencies_prepared: calls.append((root, dependencies_prepared)) or {"status": "ready"},
    )

    sessions._bootstrap_integration_for_files(tmp_path, [changed_file])

    assert calls == [(tmp_path, False)]


def test_scoped_integration_cache_miss_still_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    sessions = load_sessions_module()
    root = tmp_path / "root"
    worktree = tmp_path / "worktree"
    root.mkdir()
    worktree.mkdir()
    calls: list[tuple[str, ...]] = []

    def fake_run(command, cwd=None, timeout=None):
        calls.append(tuple(command))
        return 1, "", "offline cache miss"

    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)
    monkeypatch.setattr(sessions, "_run_cmd", fake_run)

    with pytest.raises(RuntimeError, match="dependency_install_failed.*offline cache miss"):
        sessions._bootstrap_integration_for_files(worktree, ["frontend/apps/web_app/package.json"])

    assert calls == [(
        "pnpm", "install", "--offline",
        "--frozen-lockfile", "--ignore-scripts", "--config.engine-strict=false",
    )]


def prepared_dependency_fixture(tmp_path: Path) -> tuple[Path, Path]:
    prepared = tmp_path / "prepared"
    checkout = tmp_path / "integration"
    manifests = {
        "package.json": {"name": "openmates", "packageManager": "pnpm@10.23.0", "devDependencies": {"tool": "1.0"}},
        "frontend/packages/ui/package.json": {"name": "@repo/ui", "dependencies": {"left-pad": "1.0"}},
        "frontend/apps/cli/package.json": {"name": "openmates", "dependencies": {"@repo/ui": "workspace:*"}},
    }
    for root in (prepared, checkout):
        root.mkdir()
        (root / "pnpm-workspace.yaml").write_text("packages:\n  - frontend/apps/*\n  - frontend/packages/*\n", encoding="utf-8")
        (root / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
        for relative, manifest in manifests.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(manifest), encoding="utf-8")
    modules = prepared / "node_modules"
    store = modules / ".pnpm"
    (store / "node_modules" / "@repo").mkdir(parents=True)
    (store / "lock.yaml").write_text((prepared / "pnpm-lock.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    (modules / ".modules.yaml").write_text(
        "nodeLinker: isolated\npackageManager: pnpm@10.23.0\nvirtualStoreDir: .pnpm\n"
        "included:\n  dependencies: true\n  devDependencies: true\n  optionalDependencies: true\n",
        encoding="utf-8",
    )
    for name in ("tool", "left-pad"):
        package = store / f"{name}@1.0" / "node_modules" / name
        package.mkdir(parents=True)
        (package / "index.js").write_text(f"module.exports = '{name}'\n", encoding="utf-8")
    (modules / "tool").symlink_to(Path(".pnpm/tool@1.0/node_modules/tool"), target_is_directory=True)
    ui_modules = prepared / "frontend/packages/ui/node_modules"
    ui_modules.mkdir()
    (ui_modules / "left-pad").symlink_to(Path(os.path.relpath(
        store / "left-pad@1.0/node_modules/left-pad", ui_modules,
    )), target_is_directory=True)
    cli_scope = prepared / "frontend/apps/cli/node_modules/@repo"
    cli_scope.mkdir(parents=True)
    (cli_scope / "ui").symlink_to(Path(os.path.relpath(
        prepared / "frontend/packages/ui", cli_scope,
    )), target_is_directory=True)
    hoist_scope = store / "node_modules/@repo"
    (hoist_scope / "ui").symlink_to(Path(os.path.relpath(
        prepared / "frontend/packages/ui", hoist_scope,
    )), target_is_directory=True)
    (store / "node_modules/openmates").symlink_to(Path(os.path.relpath(
        prepared / "frontend/apps/cli", store / "node_modules",
    )), target_is_directory=True)
    (store / "node_modules/fsevents").symlink_to(Path("../fsevents@2.3.3/node_modules/fsevents"), target_is_directory=True)
    bins = modules / ".bin"
    bins.mkdir()
    (bins / "tool").write_text(f"#!/bin/sh\nNODE_PATH={prepared}/node_modules/.pnpm\n", encoding="utf-8")
    (checkout / "frontend/packages/ui/source.js").write_text("integration", encoding="utf-8")
    (prepared / "frontend/packages/ui/source.js").write_text("canonical", encoding="utf-8")
    return prepared, checkout


def test_prepared_dependencies_resolve_workspace_to_integration(tmp_path: Path) -> None:
    sessions = load_sessions_module()
    prepared, checkout = prepared_dependency_fixture(tmp_path)

    sessions._reuse_prepared_dependencies(checkout, prepared)

    assert (checkout / "node_modules/tool").resolve() == prepared / "node_modules/.pnpm/tool@1.0/node_modules/tool"
    assert (checkout / "frontend/packages/ui/node_modules/left-pad").exists()
    assert (checkout / "frontend/apps/cli/node_modules/@repo/ui").resolve() == checkout / "frontend/packages/ui"
    assert (checkout / "node_modules/.pnpm/node_modules/@repo/ui").resolve() == checkout / "frontend/packages/ui"
    assert (checkout / "node_modules/.pnpm/node_modules/openmates").resolve() == checkout / "frontend/apps/cli"
    assert (checkout / "node_modules/.pnpm/node_modules/fsevents").is_symlink()
    assert (checkout / "frontend/apps/cli/node_modules/@repo/ui/source.js").read_text(encoding="utf-8") == "integration"
    shim = (checkout / "node_modules/.bin/tool").read_text(encoding="utf-8")
    assert str(checkout / "node_modules/.pnpm") in shim
    assert str(prepared) not in shim


@pytest.mark.parametrize("damage", ["lock", "manifest", "installed_lock", "missing_dependency", "local_dependency"])
def test_prepared_dependencies_refuse_stale_or_incomplete_source(tmp_path: Path, damage: str) -> None:
    sessions = load_sessions_module()
    prepared, checkout = prepared_dependency_fixture(tmp_path)
    if damage == "lock":
        (checkout / "pnpm-lock.yaml").write_text("changed", encoding="utf-8")
    elif damage == "manifest":
        (checkout / "frontend/apps/cli/package.json").write_text("{}", encoding="utf-8")
    elif damage == "installed_lock":
        (prepared / "node_modules/.pnpm/lock.yaml").write_text("changed", encoding="utf-8")
    elif damage == "local_dependency":
        local_manifest = prepared / "frontend/apps/cli/package.json"
        text = local_manifest.read_text(encoding="utf-8").replace("workspace:*", "file:../../packages/ui")
        local_manifest.write_text(text, encoding="utf-8")
        (checkout / "frontend/apps/cli/package.json").write_text(text, encoding="utf-8")
    else:
        (prepared / "node_modules/tool").unlink()

    with pytest.raises(RuntimeError, match="Prepared dependencies"):
        sessions._reuse_prepared_dependencies(checkout, prepared)

    assert not (checkout / "node_modules").exists()


def test_prepared_dependencies_refuse_foreign_hoisted_workspace_link(tmp_path: Path) -> None:
    sessions = load_sessions_module()
    prepared, checkout = prepared_dependency_fixture(tmp_path)
    hoisted = prepared / "node_modules/.pnpm/node_modules/@repo/ui"
    hoisted.unlink()
    foreign = tmp_path / "foreign/ui"
    foreign.mkdir(parents=True)
    hoisted.symlink_to(Path(os.path.relpath(foreign, hoisted.parent)), target_is_directory=True)

    with pytest.raises(RuntimeError, match="hoisted workspace link points outside integration"):
        sessions._reuse_prepared_dependencies(checkout, prepared)


def test_prepared_bootstrap_generation_failure_is_not_install_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    sessions = load_sessions_module()
    calls: list[tuple[str, ...]] = []

    def fail_generation(command, cwd=None, timeout=None):
        calls.append(tuple(command))
        return 1, "", "generation failed"

    monkeypatch.setattr(sessions, "_run_cmd", fail_generation)
    result = sessions.bootstrap_session_worktree(tmp_path, dependencies_prepared=True)
    assert result["reason"] == "prerequisite_generation_failed"
    assert calls == [("node", "frontend/packages/ui/scripts/build-tokens.js")]


def test_shared_runtime_resources_are_linked_into_worktree(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    root = tmp_path / "root"
    worktree = tmp_path / "worktree"
    reports = root / "logs" / "nightly-reports"
    reports.mkdir(parents=True)
    worktree.mkdir()
    (root / ".env").write_text("EXAMPLE=value\n", encoding="utf-8")
    (reports / "stale-code.json").write_text('{"findings": []}\n', encoding="utf-8")
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)

    result = sessions.link_shared_worktree_resources(worktree)

    assert result == [".env", "logs/nightly-reports"]
    assert (worktree / ".env").is_symlink()
    assert (worktree / ".env").resolve() == root / ".env"
    assert (worktree / "logs" / "nightly-reports").is_symlink()
    assert (worktree / "logs" / "nightly-reports" / "stale-code.json").read_text(encoding="utf-8") == '{"findings": []}\n'


def test_shared_runtime_linking_refuses_to_replace_local_content(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    root = tmp_path / "root"
    worktree = tmp_path / "worktree"
    root.mkdir()
    worktree.mkdir()
    (root / ".env").write_text("ROOT=value\n", encoding="utf-8")
    (worktree / ".env").write_text("LOCAL=value\n", encoding="utf-8")
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)

    with pytest.raises(RuntimeError, match="Refusing to replace existing worktree runtime resource"):
        sessions.link_shared_worktree_resources(worktree)

    assert (worktree / ".env").read_text(encoding="utf-8") == "LOCAL=value\n"


def test_shared_runtime_links_survive_resources_created_later(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    root = tmp_path / "root"
    worktree = tmp_path / "worktree"
    root.mkdir()
    worktree.mkdir()
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", root)

    result = sessions.link_shared_worktree_resources(worktree)

    assert result == [".env", "logs/nightly-reports"]
    assert (worktree / ".env").is_symlink()
    assert (worktree / "logs" / "nightly-reports").is_symlink()
    (root / ".env").write_text("LATER=value\n", encoding="utf-8")
    (root / "logs" / "nightly-reports").mkdir(parents=True)
    (root / "logs" / "nightly-reports" / "stale-code.json").write_text("{}\n", encoding="utf-8")
    assert (worktree / ".env").read_text(encoding="utf-8") == "LATER=value\n"
    assert (worktree / "logs" / "nightly-reports" / "stale-code.json").read_text(encoding="utf-8") == "{}\n"
