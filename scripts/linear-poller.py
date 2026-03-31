#!/usr/bin/env python3
"""
scripts/linear-poller.py

Polls Linear for issues with 'claude-plan', 'claude-research', or 'claude-fix'
labels and spawns Claude Code sessions in Zellij for each one.

- claude-plan: spawns a plan-mode session (read-only research, posts findings)
- claude-research: spawns a research session (codebase + web analysis, posts findings as comments)
- claude-fix: spawns an execute-mode session (implements fix, deploys)

Designed to run every 30s by the linear-poller systemd service (see
linear-cron-setup.sh). Each invocation is stateless — label presence is the
only state needed. Concurrent runs prevented by flock in systemd ExecStart.

Usage:
    python3 scripts/linear-poller.py          # normal run
    python3 scripts/linear-poller.py --dry-run # show what would happen
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Ensure sibling modules are importable
_SCRIPTS_DIR = str(Path(__file__).parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from _linear_client import (
    LABEL_CLAUDE_FIX_ID,
    LABEL_CLAUDE_PLAN_ID,
    LABEL_CLAUDE_RESEARCH_ID,
    LABEL_CLAUDE_WORKING_ID,
    add_label,
    get_issue_with_comments,
    list_issues_with_label,
    post_comment,
    remove_specific_label,
    update_issue_status,
)
from _zellij_utils import (
    MAX_CONCURRENT_SESSIONS,
    count_active_sessions,
    spawn_claude_session,
)

PROJECT_ROOT = Path(__file__).parent.parent
TMP_DIR = PROJECT_ROOT / "scripts" / ".tmp"
LOG_PREFIX = "[linear-poller]"


# ── Prompt Builders ─────────────────────────────────────────────────────────


def _format_comments(comments: List[Dict]) -> str:
    """Format issue comments for inclusion in the prompt."""
    if not comments:
        return "(No comments.)"
    lines = []
    for c in comments:
        lines.append(f"**{c['author']}** ({c['created_at'][:10]}):\n{c['body']}")
    return "\n\n---\n\n".join(lines)


def _build_linear_tracking_instructions(
    identifier: str,
    session_name: str,
) -> str:
    """Build the Linear MCP tracking instructions appended to every prompt."""
    return (
        f"\n\n"
        f"LINEAR TASK TRACKING (REQUIRED):\n"
        f"This session is linked to Linear issue {identifier}.\n"
        f"Use the Linear MCP tools to keep the task updated:\n"
        f"- Post SHORT progress comments (1-2 lines) on significant milestones:\n"
        f'  Use mcp__linear__save_comment with issueId: "{identifier}" and body: "your update"\n'
        f"- Good examples: 'Found root cause in file.ts:245 — race condition on X'\n"
        f"  or 'Fix deployed: commit abc123, updated key derivation'\n"
        f"- At END: update status via mcp__linear__save_issue with\n"
        f'  id: "{identifier}", state: "In Review",\n'
        f"  and post a final comment including resume commands:\n"
        f"  zellij attach {session_name}\n"
        f"  claude --resume <your-session-id>\n"
    )


def _build_prompt(issue: Dict, mode: str, session_name: str) -> str:
    """Build investigation/fix prompt for a Linear issue."""
    identifier = issue.get("identifier", "?")
    comments_text = _format_comments(issue.get("comments", []))

    if mode == "research":
        mode_instructions = (
            "IMPORTANT: This is a RESEARCH session. "
            "You MUST NOT edit, write, or create any files. "
            "Only read, search, and analyze code + search the web. "
            "Research this task thoroughly: identify relevant code, estimate complexity, "
            "find related patterns, and note potential pitfalls. "
            "Post your findings as a structured comment on the Linear issue using "
            "mcp__linear__save_comment. Do NOT implement anything."
        )
    elif mode == "plan":
        mode_instructions = (
            "IMPORTANT: This is a PLAN-ONLY session. "
            "You MUST NOT edit, write, or create any files. "
            "Only read, search, and analyze code. "
            "Present your findings and proposed fix as a summary — do not implement it."
        )
    else:
        mode_instructions = (
            "IMPORTANT: This is an EXECUTE session. "
            "You have full access to read, edit, and create files. "
            "Investigate the issue and implement the fix directly. "
            "Use sessions.py deploy to commit and push when done."
        )

    tracking = _build_linear_tracking_instructions(identifier, session_name)

    return (
        f"{mode_instructions}\n\n"
        f"## Task: {identifier} — {issue.get('title', '?')}\n\n"
        f"**Status:** {issue.get('state', '?')} | "
        f"**Labels:** {', '.join(issue.get('labels', [])) or 'none'}\n\n"
        f"### Description\n\n"
        f"{issue.get('description') or '(No description.)'}\n\n"
        f"### Recent Comments\n\n"
        f"{comments_text}\n\n"
        f"---\n\n"
        f"## Instructions\n\n"
        f"1. Research the codebase — use Glob, Grep, and Read to understand what's involved\n"
        f"2. Identify the root cause or implementation approach\n"
        f"3. Search for existing patterns to reuse\n"
        f"4. Assess complexity — scope, risks, dependencies\n"
        + (
            f"5. Implement the fix and deploy via sessions.py deploy\n"
            if mode == "execute"
            else f"5. Write a structured summary of findings and recommended approach\n"
        )
        + tracking
    )


# ── Core Logic ──────────────────────────────────────────────────────────────


def _spawn_for_issue(issue: Dict, mode: str) -> bool:
    """Spawn a Claude session for a single Linear issue. Returns True on success."""
    identifier = issue["identifier"]
    mode_prefix = {"plan": "plan", "research": "research", "execute": "fix"}
    session_name = f"{mode_prefix.get(mode, mode)}-{identifier}"
    trigger_label_map = {
        "plan": LABEL_CLAUDE_PLAN_ID,
        "research": LABEL_CLAUDE_RESEARCH_ID,
        "execute": LABEL_CLAUDE_FIX_ID,
    }
    trigger_label_id = trigger_label_map[mode]

    # Fetch full context with comments
    full_issue = get_issue_with_comments(identifier)
    if not full_issue:
        full_issue = issue
        full_issue.setdefault("comments", [])

    # Build and write prompt to temp file
    prompt = _build_prompt(full_issue, mode, session_name)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    prompt_file = TMP_DIR / f"poller-prompt-{identifier}.txt"
    prompt_file.write_text(prompt, encoding="utf-8")

    rel_path = prompt_file.relative_to(PROJECT_ROOT)
    claude_prompt = f"Read {rel_path} in full and follow all the instructions precisely."

    # Research sessions use plan permission mode (read-only)
    permission = "plan" if mode in ("plan", "research") else "execute"
    success = spawn_claude_session(
        session_name=session_name,
        prompt=claude_prompt,
        cwd=str(PROJECT_ROOT),
        permission_mode=permission,
    )

    if not success:
        print(f"{LOG_PREFIX} {identifier}: FAILED to spawn session", file=sys.stderr)
        return False

    # Swap labels: remove trigger label, add claude-is-working
    current_labels = full_issue.get("label_ids", [])
    remove_specific_label(full_issue["id"], trigger_label_id, current_labels)
    # Recalculate label_ids after removal
    updated_labels = [lid for lid in current_labels if lid != trigger_label_id]
    if LABEL_CLAUDE_WORKING_ID not in updated_labels:
        updated_labels.append(LABEL_CLAUDE_WORKING_ID)
    add_label(full_issue["id"], updated_labels)

    # Mark In Progress
    update_issue_status(full_issue["id"], "In Progress")

    # Post session info comment
    mode_desc = {
        "plan": "plan (read-only investigation)",
        "research": "research (codebase + web analysis)",
        "execute": "execute (implementing fix)",
    }.get(mode, mode)
    post_comment(
        full_issue["id"],
        f"**Claude {mode} session started:** `{session_name}`\n\n"
        f"**Attach:** `zellij attach {session_name}`\n"
        f"**Web UI:** http://localhost:8082\n\n"
        f"Mode: {mode_desc}"
    )

    print(f"{LOG_PREFIX} {identifier}: spawned '{session_name}' ({mode} mode)")
    return True


def poll_and_spawn(dry_run: bool = False) -> None:
    """Poll Linear for claude-plan/claude-fix issues and spawn sessions."""

    # Collect candidates from all trigger labels
    candidates: List[Tuple[Dict, str]] = []  # (issue, mode)

    # claude-fix takes priority (execute > research > plan)
    for issue in list_issues_with_label("claude-fix"):
        if "claude-is-working" not in issue["labels"]:
            candidates.append((issue, "execute"))

    for issue in list_issues_with_label("claude-research"):
        if "claude-is-working" not in issue["labels"]:
            existing_ids = {c[0]["identifier"] for c in candidates}
            if issue["identifier"] not in existing_ids:
                candidates.append((issue, "research"))

    for issue in list_issues_with_label("claude-plan"):
        if "claude-is-working" not in issue["labels"]:
            existing_ids = {c[0]["identifier"] for c in candidates}
            if issue["identifier"] not in existing_ids:
                candidates.append((issue, "plan"))

    if not candidates:
        return  # Nothing to do — silent (runs every 30s)

    print(f"{LOG_PREFIX} Found {len(candidates)} issue(s) to process")

    for issue, mode in candidates:
        active = count_active_sessions()
        if active >= MAX_CONCURRENT_SESSIONS:
            label_name = {"plan": "plan", "research": "research", "execute": "fix"}.get(mode, mode)
            post_comment(
                issue["id"],
                f"**Queued** — session limit reached ({active}/{MAX_CONCURRENT_SESSIONS}). "
                f"This task will auto-start when a slot opens. "
                f"The `claude-{label_name}` label is retained for retry."
            )
            print(f"{LOG_PREFIX} {issue['identifier']}: queued (limit {active}/{MAX_CONCURRENT_SESSIONS})")
            continue

        if dry_run:
            print(f"{LOG_PREFIX} [DRY RUN] Would spawn {mode} session for {issue['identifier']}")
            continue

        _spawn_for_issue(issue, mode)


# ── Entry Point ─────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Poll Linear for claude-plan/claude-fix issues and spawn sessions"
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen")
    args = parser.parse_args()
    poll_and_spawn(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
