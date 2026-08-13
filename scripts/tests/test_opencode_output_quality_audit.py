# contract-test-file: tooling
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
RETROSPECTIVE_GUIDANCE = """
## Agent Workflow Retrospective

For every non-trivial task-closing summary, cover the agentic process, not about the request's product results.
Report only observed preventable process problems.
Include research, delegated agents, and sub-chats.
Do not repeat implementation results or test outcomes. Ordinary task difficulty is not a workflow issue.
Check existing hooks, skills, agents, agent instructions,
and deterministic audits/tests before recommending the smallest concrete workflow improvement.
Do not recommend new prompt prose when a deterministic guard is more reliable.
State when no change is warranted. Use None observed. Do not invent problems, expose hidden reasoning,
guess durations, or include raw private logs or private chat content.
Simple requests, clarification-only turns, and progress updates are excluded.
""".strip()
CLARIFYING_QUESTION_GUIDANCE = """
Whenever asking a clarifying question, provide `Recommendation:` with the
evidence-based preferred answer and `Examples:` with task-specific options. If
uncertain, choose the safest reversible default.
""".strip()
SCAN_FIRST_GUIDANCE = """
When a final answer needs more than one sentence, use a scan-first layout. Start
with one state heading: `## ✅ Done`, `## 🚧 Blocked`, `## ❓ Decision Needed`, or
`## 🧠 Investigation`. Prefer compact tables for files, tests, blockers, risks,
and next actions. Use icons semantically and sparingly. Do not paste large YAML,
JSON, contracts, or logs into blocker summaries unless the user asks.
""".strip()


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


def write_runtime_instructions(root: Path, text: str) -> None:
    for name in ("AGENTS.md", "CLAUDE.md"):
        (root / name).write_text(text, encoding="utf-8")


def write_clarifying_guidance_files(root: Path) -> None:
    for name in (
        ".claude/rules/planning.md",
        ".claude/skills/clarify/SKILL.md",
        ".claude/skills/specify/SKILL.md",
        ".claude/skills/create-pr/SKILL.md",
        ".claude/skills/next-tasks/SKILL.md",
        ".claude/skills/add-focus-mode/SKILL.md",
        ".claude/skills/add-memory-type/SKILL.md",
        ".claude/skills/reproduce-first/SKILL.md",
        ".claude/skills/new-task/SKILL.md",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(CLARIFYING_QUESTION_GUIDANCE, encoding="utf-8")


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


def test_rejects_duplicate_opencode_config_keys(tmp_path: Path) -> None:
    audit = load_audit_module()
    (tmp_path / "opencode.json").write_text(
        '{"permission":{"firecrawl_firecrawl_search":"ask","firecrawl_firecrawl_search":"deny"}}',
        encoding="utf-8",
    )

    issues = audit.audit_instruction_surface(tmp_path)

    assert len(issues) == 1
    assert issues[0].message == "duplicate JSON key: firecrawl_firecrawl_search"


def test_accepts_concise_core_with_lazy_loading_and_quality_guidance(tmp_path: Path) -> None:
    audit = load_audit_module()
    write_core(
        tmp_path,
        f"""
# Agent Workflow Core

Keep default context concise. Lazy-load frontend, backend, testing, privacy,
Apple, and spec rules only when relevant. Final responses should cite evidence,
changed files, verification commands, failed checks, uncertainty, and next steps.
Use exact commands and state when verification was not run. Firecrawl is a
quota-backed fallback only.
Batch independent calls in one turn. When a todo update and the next operation
are independent, avoid a standalone model round-trip.
{RETROSPECTIVE_GUIDANCE}
## Deployed Verification
Playwright `*.spec.ts` verification is deployed-code verification. If local UI,
embed, or spec changes are needed, perform a scoped `dev` deploy with
`python3 scripts/sessions.py deploy`, wait for Vercel Ready, then dispatch
`python3 scripts/tests.py run --spec <name>.spec.ts --gate-deploy --expected-commit <sha>`
against `https://app.dev.openmates.org`.
{CLARIFYING_QUESTION_GUIDANCE}
{SCAN_FIRST_GUIDANCE}
        """.strip(),
    )
    write_runtime_instructions(
        tmp_path,
        f"{CLARIFYING_QUESTION_GUIDANCE}\n\n{SCAN_FIRST_GUIDANCE}\n\n{RETROSPECTIVE_GUIDANCE}",
    )
    write_clarifying_guidance_files(tmp_path)
    config = {
        "instructions": ["docs/contributing/guides/agent-workflow-core.md"],
        "permission": {tool: "ask" for tool in audit.FIRECRAWL_TOOL_PERMISSIONS},
    }

    issues = audit.audit_instruction_surface(tmp_path, config)

    assert issues == []


def test_requires_recommendations_and_examples_for_clarifying_questions(tmp_path: Path) -> None:
    audit = load_audit_module()
    write_core(tmp_path, CLARIFYING_QUESTION_GUIDANCE)
    write_runtime_instructions(tmp_path, f"{RETROSPECTIVE_GUIDANCE}\n\nAsk one question.")
    write_clarifying_guidance_files(tmp_path)

    issues = audit.audit_instruction_surface(tmp_path, {"instructions": []})

    assert any(
        issue.path == "AGENTS.md" and "clarifying-question guidance" in issue.message
        for issue in issues
    )


def test_rejects_generic_or_optional_clarifying_question_guidance() -> None:
    audit = load_audit_module()
    generic = """
    Every clarifying question includes Recommendation: with a preferred answer
    and Examples: when useful. Choose the safest reversible default.
    """

    issues = audit._audit_clarifying_question_guidance("skill.md", generic)

    assert issues
    assert "evidence-based" in issues[0].message


def test_requires_scan_first_final_answer_guidance(tmp_path: Path) -> None:
    audit = load_audit_module()
    write_core(tmp_path, CLARIFYING_QUESTION_GUIDANCE)
    write_runtime_instructions(tmp_path, f"{CLARIFYING_QUESTION_GUIDANCE}\n\n{RETROSPECTIVE_GUIDANCE}")
    write_clarifying_guidance_files(tmp_path)

    issues = audit.audit_instruction_surface(tmp_path, {"instructions": []})

    assert any(
        issue.path == "AGENTS.md" and "scan-first final-answer guidance" in issue.message
        for issue in issues
    )


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


def test_rejects_missing_workflow_retrospective(tmp_path: Path) -> None:
    audit = load_audit_module()
    write_core(
        tmp_path,
        """
# Agent Workflow Core

Lazy-load detailed rules. Include verification, uncertainty, and exact command
evidence in every final response. Firecrawl is a quota-backed fallback.
Batch independent calls in one turn and avoid a standalone todo update model round-trip.
Playwright `*.spec.ts` verification is deployed-code verification.
Run python3 scripts/sessions.py deploy and then use
--gate-deploy --expected-commit against https://app.dev.openmates.org.
""".strip(),
    )
    write_runtime_instructions(tmp_path, "No retrospective guidance.")
    config = {
        "instructions": ["docs/contributing/guides/agent-workflow-core.md"],
        "permission": {tool: "ask" for tool in audit.FIRECRAWL_TOOL_PERMISSIONS},
    }

    issues = audit.audit_instruction_surface(tmp_path, config)

    assert any("workflow retrospective" in issue.message for issue in issues)


def test_requires_cross_runtime_workflow_retrospective_guidance(tmp_path: Path) -> None:
    audit = load_audit_module()
    write_core(tmp_path, "Agent Workflow Retrospective with None observed.")
    write_runtime_instructions(tmp_path, "Ordinary instructions without the required contract.")

    issues = audit.audit_instruction_surface(tmp_path, {"instructions": []})

    assert any(issue.path == "AGENTS.md" and "workflow retrospective" in issue.message for issue in issues)
    assert any(issue.path == "CLAUDE.md" and "workflow retrospective" in issue.message for issue in issues)


def test_retrospective_contract_clauses_must_be_in_the_section() -> None:
    audit = load_audit_module()

    for phrase in audit.REQUIRED_RETROSPECTIVE_PHRASES:
        mutated = RETROSPECTIVE_GUIDANCE.replace(phrase, "omitted", 1)
        mutated += f"\n\n## Other Guidance\n{phrase}"

        issues = audit._audit_retrospective_guidance("AGENTS.md", mutated)

        assert issues, phrase
        assert phrase in issues[0].message


def test_rejects_result_oriented_retrospective_contract() -> None:
    audit = load_audit_module()
    contradictory_clauses = (
        "Include implementation results in this section.",
        "Report changed files in this retrospective.",
        "Include discovered product bugs in this section.",
        "Summarize test outcomes in this retrospective.",
        "Report remaining product work in this section.",
    )

    for clause in contradictory_clauses:
        issues = audit._audit_retrospective_guidance("AGENTS.md", RETROSPECTIVE_GUIDANCE + "\n" + clause)

        assert issues, clause
        assert "contradicts" in issues[0].message


def test_accepts_workflow_caused_result_exception() -> None:
    audit = load_audit_module()
    guidance = RETROSPECTIVE_GUIDANCE + (
        "\nSummarize test outcomes when an agent-workflow deficiency caused them."
    )

    assert audit._audit_retrospective_guidance("AGENTS.md", guidance) == []


def test_rejects_cross_runtime_retrospective_drift(tmp_path: Path) -> None:
    audit = load_audit_module()
    write_core(tmp_path, RETROSPECTIVE_GUIDANCE)
    write_runtime_instructions(tmp_path, RETROSPECTIVE_GUIDANCE)
    (tmp_path / "AGENTS.md").write_text(
        RETROSPECTIVE_GUIDANCE + "\nThis runtime has extra guidance.",
        encoding="utf-8",
    )

    issues = audit.audit_instruction_surface(tmp_path, {"instructions": []})

    assert any(issue.path == "cross-runtime" for issue in issues)


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


def test_tool_turn_telemetry_counts_only_conservative_batching_candidates() -> None:
    audit = load_audit_module()

    report = audit.summarize_tool_turns(
        [
            {
                "session_id": "one",
                "time_created": 1_000,
                "tokens_input": 10,
                "tokens_cache_read": 100,
                "tools": [{"name": "read", "args": {"filePath": "/repo/a.py"}}],
            },
            {
                "session_id": "one",
                "time_created": 2_000,
                "tokens_input": 20,
                "tokens_cache_read": 200,
                "tools": [{"name": "read", "args": {"filePath": "/repo/b.py"}}],
            },
            {
                "session_id": "one",
                "time_created": 3_000,
                "tokens_input": 30,
                "tokens_cache_read": 300,
                "tools": [{"name": "todowrite", "args": {"todos": []}}],
            },
            {
                "session_id": "one",
                "time_created": 4_000,
                "tokens_input": 40,
                "tokens_cache_read": 400,
                "tools": [{"name": "grep", "args": {"pattern": "Example"}}],
            },
        ]
    )

    assert report == {
        "assistant_tool_turns": 4,
        "tool_calls": 4,
        "singleton_tool_turns": 4,
        "singleton_tool_turn_rate": 1.0,
        "conservative_batchable_turns": 1,
        "standalone_todo_turns": 1,
        "todo_next_turn_context": {"tokens_input": 40, "tokens_cache_read": 400},
        "tool_error_counts": {},
    }


def test_tool_turn_telemetry_normalizes_workflow_error_categories() -> None:
    audit = load_audit_module()
    report = audit.summarize_tool_turns(
        [
            {
                "session_id": "one",
                "time_created": 1_000,
                "tools": [
                    {
                        "name": "bash",
                        "args": {},
                        "status": "error",
                        "error": "[OpenMates child ownership guard] Reason: child role unknown",
                    }
                ],
            },
            {
                "session_id": "one",
                "time_created": 2_000,
                "tools": [
                    {
                        "name": "grep",
                        "args": {},
                        "status": "error",
                        "error": "Ripgrep JSON record exceeded 65536 bytes",
                    }
                ],
            },
        ]
    )

    assert report["tool_error_counts"] == {"child_role": 1, "grep_output_too_large": 1}


def test_tool_turn_telemetry_keeps_dependent_same_file_reads_sequential() -> None:
    audit = load_audit_module()

    report = audit.summarize_tool_turns(
        [
            {
                "session_id": "one",
                "time_created": 1_000,
                "tools": [{"name": "read", "args": {"filePath": "/repo/a.py", "offset": 1}}],
            },
            {
                "session_id": "one",
                "time_created": 2_000,
                "tools": [{"name": "read", "args": {"filePath": "/repo/a.py", "offset": 500}}],
            },
        ]
    )

    assert report["conservative_batchable_turns"] == 0


def test_tool_turn_telemetry_normalizes_equivalent_read_paths() -> None:
    audit = load_audit_module()
    root = audit._opencode_project_directory()

    report = audit.summarize_tool_turns(
        [
            {
                "session_id": "one",
                "time_created": 1_000,
                "tools": [{"name": "read", "args": {"filePath": "./scripts/example.py"}}],
            },
            {
                "session_id": "one",
                "time_created": 2_000,
                "tools": [{"name": "read", "args": {"filePath": str(root / "scripts/example.py")}}],
            },
        ]
    )

    assert report["conservative_batchable_turns"] == 0


def test_tool_turn_telemetry_normalizes_equivalent_patch_paths() -> None:
    audit = load_audit_module()
    root = audit._opencode_project_directory()

    report = audit.summarize_tool_turns(
        [
            {
                "session_id": "one",
                "time_created": 1_000,
                "tools": [
                    {
                        "name": "apply_patch",
                        "args": {"patchText": "*** Begin Patch\n*** Update File: ./scripts/example.py\n*** End Patch"},
                    }
                ],
            },
            {
                "session_id": "one",
                "time_created": 2_000,
                "tools": [
                    {
                        "name": "apply_patch",
                        "args": {"patchText": f"*** Begin Patch\n*** Update File: {root}/scripts/example.py\n*** End Patch"},
                    }
                ],
            },
        ]
    )

    assert report["conservative_batchable_turns"] == 0


def test_tool_turn_telemetry_resolves_worktree_aliases_before_normalizing() -> None:
    audit = load_audit_module()
    root = audit._opencode_project_directory()
    worktrees = root / ".openmates-agent-worktrees"

    first = worktrees / "agent-a/../agent-b/scripts/example.py"
    second = worktrees / "agent-b/scripts/example.py"

    assert audit._canonical_tool_path(str(first)) == "scripts/example.py"
    assert audit._canonical_tool_path(str(first)) == audit._canonical_tool_path(str(second))
