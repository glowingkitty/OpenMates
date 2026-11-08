#!/usr/bin/env python3
# contract-test-file: tooling
"""Lane deploy scope contracts: repeatable --only, no silent partial deploys,
and auto-tracking of new files a lane creates in its own worktree.

Regression: ``deploy --only a --only b`` used to keep only ``b`` (argparse
store), so a lane deployed one of ten files without noticing. Fixtures use
isolated Git repositories under tmp_path only.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import types
from pathlib import Path

from scripts.lane_deploy_scope import new_untracked_files, omitted_only_files, omitted_only_message

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PATH = PROJECT_ROOT / "scripts" / "sessions.py"


def load_sessions_module():
    spec = importlib.util.spec_from_file_location("openmates_sessions_lane_deploy_scope", SESSIONS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse(monkeypatch, sessions, command: str, *argv: str):
    captured = {}
    target = {"deploy": "cmd_deploy", "prepare-deploy": "cmd_prepare_deploy", "verify-prepared": "cmd_verify_prepared"}
    monkeypatch.setattr(sessions, target[command], lambda args: captured.setdefault("args", args))
    monkeypatch.setattr(sys, "argv", ["sessions.py", command, "--session", "abcd", *argv])
    sessions.main()
    return captured["args"]


def test_deploy_only_and_exclude_accumulate_across_repeated_flags(monkeypatch):
    sessions = load_sessions_module()
    args = parse(
        monkeypatch, sessions, "deploy", "--title", "fix: x",
        "--only", "a.py", "--only", "b.py", "c.py", "-e", "x.py", "--exclude", "y.py",
    )
    assert args.only == ["a.py", "b.py", "c.py"]
    assert args.exclude == ["x.py", "y.py"]


def test_prepare_and_verify_prepared_only_accumulate(monkeypatch):
    sessions = load_sessions_module()
    assert parse(monkeypatch, sessions, "prepare-deploy", "--only", "a", "--only", "b").only == ["a", "b"]
    verify = parse(monkeypatch, sessions, "verify-prepared", "--profile", "installed-cli-identity",
                   "--only", "a", "--only", "b")
    assert verify.only == ["a", "b"]


def test_omitted_only_files_lists_dirty_tracked_files_left_out():
    omitted = omitted_only_files(
        "only",
        ["a.py"],
        {"a.py", "b.py", "c.py", "ignored.py", "specifications/generated/registry.yml", "foreign.py"},
        ["a.py", "b.py", "c.py", "ignored.py", "clean.py", "specifications/generated/registry.yml"],
        {"ignored.py"},
    )
    assert omitted == ["b.py", "c.py"]
    assert omitted_only_files("default", ["a.py"], {"b.py"}, ["b.py"], set()) == []
    message = omitted_only_message("abcd", omitted)
    assert "b.py" in message and "--exclude" in message and "--only" in message


def init_repo(root: Path) -> None:
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    (root / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", ".gitignore"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=T", "-c", "user.email=t@example.com", "commit", "-m", "init"],
        check=True, capture_output=True,
    )


def test_new_untracked_files_skips_ignored_tracked_secret_and_generated(tmp_path):
    init_repo(tmp_path)
    for name in ["scripts/new_module.py", "scripts/known.py", "ignored/out.txt", ".env",
                 "logs/run.log", "specifications/generated/registry.yml"]:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("x\n", encoding="utf-8")
    assert new_untracked_files(tmp_path, ["scripts/known.py"]) == ["scripts/new_module.py"]


def test_ci_source_auto_tracks_new_lane_files_before_publishing(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    init_repo(tmp_path)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "new_module.py").write_text("x\n", encoding="utf-8")
    store = {"sessions": {"abcd": {"modified_files": ["old.py"]}}}
    published = {}

    def mutate(callback):
        callback(store)

    def publish(root, sid, files, **_kwargs):
        published["files"] = list(files)
        return {"source": "s"}

    monkeypatch.setattr(sessions, "_load_sessions", lambda: store)
    monkeypatch.setattr(sessions, "_mutate_sessions", mutate)
    monkeypatch.setattr(sessions, "_session_checkout_root", lambda _session: tmp_path)
    monkeypatch.setattr(sessions, "is_valid_managed_worktree_path", lambda _path: True)
    monkeypatch.setitem(sys.modules, "ci_source", types.SimpleNamespace(publish=publish))
    sessions.cmd_ci_source(types.SimpleNamespace(session="abcd", base=None, resolved_patch=None, patch_sha256=None))

    assert published["files"] == ["old.py", "scripts/new_module.py"]
    assert store["sessions"]["abcd"]["modified_files"] == ["old.py", "scripts/new_module.py"]
