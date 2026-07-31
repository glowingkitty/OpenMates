"""Tests for Claude Code, Codex, and OpenCode tooling parity audits.

Purpose: make shared safety hook coverage reproducible from tracked files rather
than from ignored local Claude settings or implicit bridge behavior.
Architecture: temporary repositories hold a compact parity manifest plus minimal
tool config files that the audit inspects deterministically.
Security: tests use synthetic hook names and do not read credentials or chats.
Run: python3 -m pytest scripts/tests/test_agent_tooling_parity_audit.py.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = ROOT / "scripts/audit_agent_tooling_parity.py"


def load_audit_module():
    spec = importlib.util.spec_from_file_location("audit_agent_tooling_parity", AUDIT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_valid_fixture(root: Path) -> None:
    write_file(
        root / "docs/architecture/agent-tooling-parity.yml",
        """
shared_hooks:
  - name: bash-guard.sh
    event: PreToolUse
    matcher: Bash
    tools: [claude, codex, opencode]
    opencode_terms: [guardBash]
  - name: e2e-encryption-guard.sh
    event: PreToolUse
    matcher: apply_patch|Edit|Write
    tools: [claude, codex, opencode]
    opencode_delegates_to_codex_bridge: true
    opencode_terms: ['runBridge("PreToolUse"']
  - name: pii-logger-guard.sh
    event: PreToolUse
    matcher: apply_patch|Edit|Write
    tools: [claude, codex]
    exceptions:
      opencode: OpenCode delegates this through the Codex bridge for edit tools.
quickstart:
  path: docs/contributing/guides/agent-workflow-quickstart.md
  required_terms:
    - sync_agent_parity.py --check
    - audit_opencode_output_quality.py
    - audit_agent_tooling_parity.py
    - sessions.py worktree ensure
    - sessions.py deploy
""".strip(),
    )
    write_file(
        root / ".claude/settings.json",
        """
{"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":[{"type":"command","command":".claude/hooks/bash-guard.sh"}]},{"matcher":"apply_patch|Edit|Write","hooks":[{"type":"command","command":".claude/hooks/e2e-encryption-guard.sh"},{"type":"command","command":".claude/hooks/pii-logger-guard.sh"}]}]}}
""".strip(),
    )
    write_file(
        root / ".codex/hooks/claude-hook-bridge.sh",
        """
  PreToolUse)
    TOOL=$(tool_name)
    if [ "$TOOL" = "Bash" ]; then
      run_hook "bash-guard.sh"
    fi
    case "$TOOL" in
      apply_patch|Edit|Write)
        run_hook "e2e-encryption-guard.sh"
        run_for_files "PreToolUse" true "pii-logger-guard.sh"
        ;;
    esac
    ;;
""".strip(),
    )
    write_file(root / ".opencode/plugins/openmates-hooks.js", "function guardBash() {}\nrunBridge(\"PreToolUse\")\n")
    write_file(
        root / "docs/contributing/guides/agent-workflow-quickstart.md",
        """
# Agent Workflow Quickstart

Run sync_agent_parity.py --check, audit_opencode_output_quality.py, and
audit_agent_tooling_parity.py. Use sessions.py worktree ensure before edits and
sessions.py deploy for commits.
""".strip(),
    )


def test_valid_fixture_passes(tmp_path: Path) -> None:
    audit = load_audit_module()
    write_valid_fixture(tmp_path)

    assert audit.audit(tmp_path) == []


def test_missing_tracked_claude_shared_hook_fails(tmp_path: Path) -> None:
    audit = load_audit_module()
    write_valid_fixture(tmp_path)
    settings = tmp_path / ".claude/settings.json"
    settings.write_text(settings.read_text(encoding="utf-8").replace("pii-logger-guard.sh", ""), encoding="utf-8")

    issues = audit.audit(tmp_path)

    assert any("Claude settings missing shared hook" in issue.message for issue in issues)


def test_wrong_tracked_claude_matcher_fails(tmp_path: Path) -> None:
    audit = load_audit_module()
    write_valid_fixture(tmp_path)
    settings = tmp_path / ".claude/settings.json"
    settings.write_text(settings.read_text(encoding="utf-8").replace("apply_patch|Edit|Write", "Edit"), encoding="utf-8")

    issues = audit.audit(tmp_path)

    assert any("Claude settings missing shared hook" in issue.message for issue in issues)


def test_missing_codex_bridge_hook_without_exception_fails(tmp_path: Path) -> None:
    audit = load_audit_module()
    write_valid_fixture(tmp_path)
    bridge = tmp_path / ".codex/hooks/claude-hook-bridge.sh"
    bridge.write_text(bridge.read_text(encoding="utf-8").replace("bash-guard.sh", ""), encoding="utf-8")

    issues = audit.audit(tmp_path)

    assert any("Codex bridge missing shared hook" in issue.message for issue in issues)


def test_codex_bridge_narrowed_matcher_fails(tmp_path: Path) -> None:
    audit = load_audit_module()
    write_valid_fixture(tmp_path)
    bridge = tmp_path / ".codex/hooks/claude-hook-bridge.sh"
    bridge.write_text(
        bridge.read_text(encoding="utf-8").replace(
            'run_hook "e2e-encryption-guard.sh"',
            'if [ "$TOOL" = "apply_patch" ]; then\n          run_hook "e2e-encryption-guard.sh"\n        fi',
        ),
        encoding="utf-8",
    )

    issues = audit.audit(tmp_path)

    assert any("Codex bridge missing shared hook: e2e-encryption-guard.sh" in issue.message for issue in issues)


def test_tool_specific_exception_with_reason_passes(tmp_path: Path) -> None:
    audit = load_audit_module()
    write_valid_fixture(tmp_path)
    plugin = tmp_path / ".opencode/plugins/openmates-hooks.js"
    plugin.write_text("function guardBash() {}\n", encoding="utf-8")

    issues = audit.audit(tmp_path)

    assert not any("pii-logger-guard.sh" in issue.message and "OpenCode" in issue.message for issue in issues)


def test_opencode_delegated_hook_requires_codex_bridge_hook(tmp_path: Path) -> None:
    audit = load_audit_module()
    write_valid_fixture(tmp_path)
    manifest = tmp_path / "docs/architecture/agent-tooling-parity.yml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            "\nquickstart:",
            """
  - name: delegated-guard.sh
    event: PreToolUse
    matcher: apply_patch|Edit|Write
    tools: [opencode]
    opencode_delegates_to_codex_bridge: true
    opencode_terms: ['runBridge("PreToolUse"']
quickstart:""",
        ),
        encoding="utf-8",
    )

    issues = audit.audit(tmp_path)

    assert any("OpenCode delegated hook missing from Codex bridge" in issue.message for issue in issues)


def test_quickstart_missing_required_links_fails(tmp_path: Path) -> None:
    audit = load_audit_module()
    write_valid_fixture(tmp_path)
    (tmp_path / "docs/contributing/guides/agent-workflow-quickstart.md").write_text(
        "# Agent Workflow Quickstart\n\nToo vague.\n",
        encoding="utf-8",
    )

    issues = audit.audit(tmp_path)

    assert any("quickstart missing required term" in issue.message for issue in issues)


def test_unrepresented_tracked_claude_hook_fails(tmp_path: Path) -> None:
    audit = load_audit_module()
    write_valid_fixture(tmp_path)
    settings = tmp_path / ".claude/settings.json"
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["hooks"]["PreToolUse"][1]["hooks"].append(
        {"type": "command", "command": ".claude/hooks/unlisted-guard.sh"}
    )
    settings.write_text(json.dumps(data), encoding="utf-8")

    issues = audit.audit(tmp_path)

    assert any("tracked Claude hook is missing from parity manifest: unlisted-guard.sh" in issue.message for issue in issues)


def test_unrepresented_tracked_claude_hook_file_fails(tmp_path: Path) -> None:
    audit = load_audit_module()
    write_valid_fixture(tmp_path)
    write_file(tmp_path / ".claude/hooks/unlisted-file-guard.sh", "#!/bin/bash\n")

    issues = audit.audit(tmp_path)

    assert any("tracked Claude hook file is missing from parity manifest: unlisted-file-guard.sh" in issue.message for issue in issues)


def test_unrepresented_codex_bridge_reference_fails(tmp_path: Path) -> None:
    audit = load_audit_module()
    write_valid_fixture(tmp_path)
    bridge = tmp_path / ".codex/hooks/claude-hook-bridge.sh"
    bridge.write_text(bridge.read_text(encoding="utf-8") + '\nrun_hook "bridge-only-guard.sh"\n', encoding="utf-8")

    issues = audit.audit(tmp_path)

    assert any("Codex bridge hook reference is missing from parity manifest: bridge-only-guard.sh" in issue.message for issue in issues)
