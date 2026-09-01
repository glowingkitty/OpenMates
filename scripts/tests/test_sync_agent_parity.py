"""Tests for agent parity synchronization side effects.

Purpose: keep normal sync behavior aligned with the drift checks that deploys run.
Architecture: patch sync_agent_parity path constants to isolated temp fixtures.
Privacy: fixtures contain only synthetic shell snippets and no environment values.
Tests: python3 -m pytest scripts/tests/test_sync_agent_parity.py.
"""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "sync_agent_parity.py"


def load_module():
    spec = importlib.util.spec_from_file_location("sync_agent_parity", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_non_check_sync_repairs_codex_hook_mirrors(tmp_path: Path, monkeypatch) -> None:
    module = load_module()
    claude_hooks = tmp_path / ".claude" / "hooks"
    codex_hooks = tmp_path / ".codex" / "hooks"
    claude_hooks.mkdir(parents=True)
    codex_hooks.mkdir(parents=True)
    bridge = codex_hooks / "claude-hook-bridge.sh"
    bridge.write_text('case "$1" in "auto-track.sh"|"pre-edit-guard.sh") exit 0 ;; esac\n', encoding="utf-8")

    auto_track_source = claude_hooks / "auto-track.sh"
    auto_track_source.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    auto_track_source.chmod(0o755)
    auto_track_target = codex_hooks / "auto-track.sh"
    auto_track_target.write_text("#!/bin/bash\nexit 1\n", encoding="utf-8")
    auto_track_target.chmod(0o600)

    pre_edit_source = claude_hooks / "pre-edit-guard.sh"
    pre_edit_source.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    pre_edit_source.chmod(0o755)

    monkeypatch.setattr(module, "CLAUDE_HOOKS_DIR", claude_hooks)
    monkeypatch.setattr(module, "CODEX_HOOKS_DIR", codex_hooks)
    monkeypatch.setattr(module, "CODEX_HOOK_BRIDGE", bridge)
    monkeypatch.setattr(module, "NON_CLAUDE_HOOK_COMMANDS", {})

    check_failures = module.sync_hooks(check=True)

    assert any("drifted" in failure for failure in check_failures)
    assert any("missing Codex hook mirror" in failure for failure in check_failures)
    assert module.sync_hooks(check=False) == []
    assert auto_track_target.read_text(encoding="utf-8") == auto_track_source.read_text(encoding="utf-8")
    assert (auto_track_target.stat().st_mode & 0o777) == 0o755
    assert (codex_hooks / "pre-edit-guard.sh").read_text(encoding="utf-8") == pre_edit_source.read_text(encoding="utf-8")
    assert module.sync_hooks(check=True) == []


def test_proof_video_reviewer_is_callable_as_primary_and_subagent(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "proof-video-reviewer.md"
    source.write_text(
        "---\nname: proof-video-reviewer\ndescription: Review frames.\ntools: Read\n---\nReview every frame.\n",
        encoding="utf-8",
    )

    rendered = module.render_opencode_agent(source)

    assert "mode: all" in rendered
    assert '"*": deny' in rendered
    assert '"test-results/proof-videos/**/review-prompt-round-*.json": allow' in rendered
    assert '"test-results/proof-videos/**/frames/*": allow' in rendered
    assert "grep: deny" in rendered
    assert "glob: deny" in rendered
    assert "task: deny" in rendered
    assert "bash: deny" in rendered
    assert "edit: deny" in rendered
