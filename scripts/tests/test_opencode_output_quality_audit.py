"""Tests for OpenCode output-quality and context-efficiency audits.

Purpose: keep OpenCode's default repo context concise while preserving the
evidence and verification guidance needed for high-quality answers.
Architecture: exercise the audit module directly with temporary configs and
privacy-safe aggregate telemetry fixtures.
Security: no OpenCode process starts and no raw local chats are read.
Run: python3 -m pytest scripts/tests/test_opencode_output_quality_audit.py.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = ROOT / "scripts/audit_opencode_output_quality.py"


def load_audit_module():
    spec = importlib.util.spec_from_file_location("audit_opencode_output_quality", AUDIT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_core(root: Path, text: str) -> Path:
    path = root / "docs" / "contributing" / "guides" / "agent-workflow-core.md"
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_rejects_eager_long_rule_docs(tmp_path: Path) -> None:
    audit = load_audit_module()
    config = {
        "instructions": [
            ".claude/rules/planning.md",
            ".claude/rules/testing.md",
            "docs/contributing/guides/spec-driven-development.md",
        ]
    }

    issues = audit.audit_config(config, root=tmp_path)

    assert any("always-loaded" in issue.message for issue in issues)


def test_accepts_concise_core_with_lazy_loading_and_quality_guidance(tmp_path: Path) -> None:
    audit = load_audit_module()
    write_core(
        tmp_path,
        """
# Agent Workflow Core

Keep default context concise. Lazy-load frontend, backend, testing, privacy,
Apple, and spec rules only when relevant. Final responses should cite evidence,
changed files, verification commands, failed checks, uncertainty, and next steps.
Use exact commands and state when verification was not run.
""".strip(),
    )
    config = {"instructions": ["docs/contributing/guides/agent-workflow-core.md"]}

    issues = audit.audit_instruction_surface(tmp_path, config)

    assert issues == []


def test_rejects_duplicated_guidance_and_missing_final_answer_evidence(tmp_path: Path) -> None:
    audit = load_audit_module()
    repeated = "Lazy-load frontend, backend, testing, privacy, Apple, and spec rules only when relevant."
    write_core(
        tmp_path,
        f"""
# Agent Workflow Core

{repeated}
{repeated}
Keep default context concise.
""".strip(),
    )
    config = {"instructions": ["docs/contributing/guides/agent-workflow-core.md"]}

    issues = audit.audit_instruction_surface(tmp_path, config)

    assert any("duplicated guidance" in issue.message for issue in issues)
    assert any("final-answer evidence" in issue.message for issue in issues)


def test_aggregate_telemetry_report_redacts_raw_chat_content() -> None:
    audit = load_audit_module()

    report = audit.summarize_opencode_telemetry(
        sessions=[
            {
                "id": "ses_private",
                "title": "Private customer support issue",
                "agent": "build",
                "model": "gpt-5.5",
                "tokens_input": 100,
                "tokens_output": 20,
                "tokens_cache_read": 300,
                "prompt": "private prompt with SECRET_TOKEN",
                "message": "raw user message",
                "tool_output": "command output body",
            },
            {
                "id": "ses_other",
                "title": "Another private title",
                "agent": "explore",
                "model": "gpt-5.5",
                "tokens_input": 300,
                "tokens_output": 40,
                "tokens_cache_read": 900,
            },
        ],
        log_lines=[
            "WARN failed to add snapshot files for /private/path",
            "ERROR stream error: private response body",
        ],
    )

    encoded = json.dumps(report, sort_keys=True)
    assert report["session_count"] == 2
    assert report["tokens_input"]["p50"] == 200
    assert report["agent_counts"] == {"build": 1, "explore": 1}
    assert "Private customer support issue" not in encoded
    assert "SECRET_TOKEN" not in encoded
    assert "raw user message" not in encoded
    assert "command output body" not in encoded
    assert "private response body" not in encoded
