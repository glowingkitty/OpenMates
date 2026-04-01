#!/usr/bin/env python3
"""
scripts/linear-enricher.py

Nightly task enrichment: fetches all open Linear tasks (Todo/Backlog) that
haven't been researched recently, and spawns lightweight Claude Code research
sessions to analyze each one. Findings are posted as structured comments on
the Linear issues, and labels are auto-applied based on content analysis.

Designed to run nightly via the linear-enricher.timer systemd service.
Each invocation processes up to MAX_TASKS_PER_RUN tasks to avoid overloading
the system with concurrent sessions.

Usage:
    python3 scripts/linear-enricher.py              # normal run
    python3 scripts/linear-enricher.py --dry-run     # show what would happen
    python3 scripts/linear-enricher.py --max-tasks 3 # limit tasks per run
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

# Ensure sibling modules are importable
_SCRIPTS_DIR = str(Path(__file__).parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from _linear_client import (
    get_issue_with_comments,
    list_open_issues,
)
from _zellij_utils import (
    MAX_CONCURRENT_SESSIONS,
    count_active_sessions,
    spawn_claude_session,
)

PROJECT_ROOT = Path(__file__).parent.parent
TMP_DIR = PROJECT_ROOT / "scripts" / ".tmp"
PROMPT_TEMPLATE_PATH = PROJECT_ROOT / "scripts" / "prompts" / "linear-task-research.md"
LOG_PREFIX = "[linear-enricher]"

# Max tasks to research per nightly run (avoids system overload)
DEFAULT_MAX_TASKS_PER_RUN = 5

# Skip tasks that were researched within this window (days)
RESEARCH_COOLDOWN_DAYS = 7

# Marker text in comments to detect previous research
RESEARCH_MARKER = "Research Summary (automated)"


# ── Helpers ────────────────────────────────────────────────────────────────


def _has_recent_research(comments: List[Dict], cooldown_days: int = RESEARCH_COOLDOWN_DAYS) -> bool:
    """Check if any comment contains a recent automated research summary."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=cooldown_days)

    for comment in comments:
        if RESEARCH_MARKER in comment.get("body", ""):
            # Parse the comment date
            created_at = comment.get("created_at", "")
            if created_at:
                try:
                    comment_date = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    if comment_date > cutoff:
                        return True
                except (ValueError, TypeError):
                    pass
    return False


def _is_enrichable(issue: Dict) -> bool:
    """
    Determine if a task is worth researching.

    Skip tasks that:
    - Already have claude-is-working label (being worked on)
    - Have very short or empty descriptions (likely stubs)
    - Are marked as Done or Cancelled
    """
    labels = issue.get("labels", [])
    if "claude-is-working" in labels:
        return False

    # Skip tasks with no meaningful content to research
    title = issue.get("title", "")
    description = issue.get("description", "")
    if len(title) < 5 and len(description) < 10:
        return False

    return True


def _format_comments(comments: List[Dict]) -> str:
    """Format issue comments for inclusion in the prompt."""
    if not comments:
        return "(No comments.)"
    lines = []
    for c in comments:
        lines.append(f"**{c['author']}** ({c['created_at'][:10]}):\n{c['body']}")
    return "\n\n---\n\n".join(lines)


def _build_research_prompt(issue: Dict, session_name: str) -> str:
    """Build the research prompt from the template, substituting placeholders."""
    identifier = issue.get("identifier", "?")
    comments_text = _format_comments(issue.get("comments", []))
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if PROMPT_TEMPLATE_PATH.is_file():
        template = PROMPT_TEMPLATE_PATH.read_text()
    else:
        # Inline fallback if template is missing
        template = (
            "Research Linear task {{IDENTIFIER}} — {{TITLE}}.\n\n"
            "Description:\n{{DESCRIPTION}}\n\n"
            "Comments:\n{{COMMENTS}}\n\n"
            "Post a structured research summary as a comment on the issue."
        )

    prompt = (
        template
        .replace("{{IDENTIFIER}}", identifier)
        .replace("{{TITLE}}", issue.get("title", "?"))
        .replace("{{DESCRIPTION}}", issue.get("description") or "(No description.)")
        .replace("{{STATE}}", issue.get("state", "?"))
        .replace("{{LABELS}}", ", ".join(issue.get("labels", [])) or "none")
        .replace("{{COMMENTS}}", comments_text)
        .replace("{{DATE}}", date_str)
    )

    # Append Linear tracking instructions
    prompt += (
        f"\n\n"
        f"LINEAR TASK TRACKING:\n"
        f"This research session is for Linear issue {identifier}.\n"
        f"Post your research findings as a comment using mcp__linear__save_comment "
        f'with issueId: "{identifier}".\n'
        f"If you identify labels to add, use mcp__linear__save_issue with "
        f'id: "{identifier}" and the labels array (merge with existing, never remove).\n'
    )

    return prompt


def _spawn_research(issue: Dict) -> bool:
    """Spawn a read-only Claude research session for a single issue."""
    identifier = issue["identifier"]
    session_name = f"enrich-{identifier}"

    # Build and write prompt to temp file
    prompt = _build_research_prompt(issue, session_name)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    prompt_file = TMP_DIR / f"enricher-prompt-{identifier}.txt"
    prompt_file.write_text(prompt, encoding="utf-8")

    rel_path = prompt_file.relative_to(PROJECT_ROOT)
    claude_prompt = f"Read {rel_path} in full and follow all the instructions precisely."

    success = spawn_claude_session(
        session_name=session_name,
        prompt=claude_prompt,
        cwd=str(PROJECT_ROOT),
        permission_mode="plan",  # Read-only — research sessions never write files
    )

    if not success:
        print(f"{LOG_PREFIX} {identifier}: FAILED to spawn research session", file=sys.stderr)
        return False

    print(f"{LOG_PREFIX} {identifier}: spawned research session '{session_name}'")
    return True


# ── Core Logic ─────────────────────────────────────────────────────────────


def enrich_tasks(dry_run: bool = False, max_tasks: int = DEFAULT_MAX_TASKS_PER_RUN) -> None:
    """Fetch enrichable tasks and spawn research sessions for each."""

    # Fetch all open tasks in Todo and Backlog states
    open_issues = list_open_issues(states=["Todo", "Backlog"])
    if not open_issues:
        print(f"{LOG_PREFIX} No open issues found — nothing to enrich.")
        return

    print(f"{LOG_PREFIX} Found {len(open_issues)} open issue(s), filtering for enrichment...")

    # Filter to enrichable tasks and check for recent research
    candidates: List[Dict] = []
    for issue in open_issues:
        if not _is_enrichable(issue):
            continue

        # Fetch full issue with comments to check for recent research
        full_issue = get_issue_with_comments(issue["identifier"])
        if not full_issue:
            continue

        comments = full_issue.get("comments", [])
        if _has_recent_research(comments):
            continue

        full_issue["comments"] = comments
        candidates.append(full_issue)

    if not candidates:
        print(f"{LOG_PREFIX} All tasks already researched or not enrichable.")
        return

    print(f"{LOG_PREFIX} {len(candidates)} task(s) eligible for enrichment (max {max_tasks})")

    spawned = 0
    for issue in candidates[:max_tasks]:
        active = count_active_sessions()
        if active >= MAX_CONCURRENT_SESSIONS:
            print(
                f"{LOG_PREFIX} Session limit reached ({active}/{MAX_CONCURRENT_SESSIONS}) "
                f"— stopping enrichment run."
            )
            break

        if dry_run:
            print(
                f"{LOG_PREFIX} [DRY RUN] Would research {issue['identifier']}: "
                f"{issue['title'][:60]}"
            )
            spawned += 1
            continue

        if _spawn_research(issue):
            spawned += 1

    print(f"{LOG_PREFIX} Enrichment run complete: {spawned} task(s) {'would be ' if dry_run else ''}researched.")


# ── Entry Point ────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Nightly Linear task enrichment — research open tasks and post findings"
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen")
    parser.add_argument(
        "--max-tasks",
        type=int,
        default=DEFAULT_MAX_TASKS_PER_RUN,
        help=f"Max tasks to research per run (default: {DEFAULT_MAX_TASKS_PER_RUN})",
    )
    args = parser.parse_args()
    enrich_tasks(dry_run=args.dry_run, max_tasks=args.max_tasks)


if __name__ == "__main__":
    main()
