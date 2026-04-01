#!/usr/bin/env python3
"""
scripts/_workflow_review_helper.py

Nightly workflow review — analyzes yesterday's Claude Code sessions to extract
improvement suggestions for sessions.py, debug.py, and CLAUDE.md.

Architecture context: See CLAUDE.md (Session Lifecycle section)

Commands:
    dry-run     Build and print the prompt without calling claude
    run-review  Build prompt and run claude analysis

State file: scripts/.workflow-review-state.json
Data source: Claude Code JSONL session files in ~/.claude/projects/<project-slug>/

Extraction logic per session:
  - text parts: all assistant/user prose
  - bash tool calls to sessions.py: header lines only (first 12 lines of output)
  - bash tool calls to sessions.py deploy: full output (small, high signal)
  - bash tool calls to debug.py: full output (actual debugging signal)
  - everything else dropped (Read/Edit/Write/Glob/Agent/file-history-snapshot/progress)

Not intended to be called directly by users; use nightly-workflow-review.sh instead.
Can be run manually for testing:
    DRY_RUN=true python3 scripts/_workflow_review_helper.py dry-run
    python3 scripts/_workflow_review_helper.py dry-run   # same as above
    python3 scripts/_workflow_review_helper.py run-review

Public API (importable by other helpers, e.g. _daily_meeting_helper.py):
    build_session_digests(yesterday: str) → (digest_text, count, chars)
    build_prompt(yesterday: str, state: dict) → str
    load_state() → dict
"""

import json
import os

from _claude_utils import run_claude_session
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path


# ── Constants ────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent

# Claude Code stores sessions as JSONL files per project, keyed by a slugified
# absolute path (/ replaced with -). Top-level *.jsonl are main sessions;
# {uuid}/subagents/*.jsonl are subagent conversations (skipped).
SESSIONS_DIR = (
    Path.home() / ".claude" / "projects"
    / "-home-superdev-projects-OpenMates"
)

STATE_FILE = PROJECT_ROOT / "scripts" / ".workflow-review-state.json"
PROMPT_TEMPLATE = PROJECT_ROOT / "scripts" / "prompts" / "workflow-review.md"

# Max chars to include per session (head + tail truncation)
PER_SESSION_BUDGET = 12_000
HEAD_RATIO = 0.4
TAIL_RATIO = 0.3

# Title keywords that mark a session as workflow-relevant
WORKFLOW_KEYWORDS = [
    "session", "debug", "workflow", "audit", "cron", "issues", "backlog",
    "test", "script", "cli", "plan", "improve", "helper", "nightly",
    "dependabot", "concurrent", "deploy", "claude", "opencode",
]

# Bash commands worth extracting tool output for (beyond text parts)
SESSIONS_TOOL_COMMANDS = ["sessions.py"]
DEBUG_TOOL_COMMANDS = ["debug.py"]

# Max lines to keep from sessions.py start output (skip boilerplate)
SESSIONS_START_HEADER_LINES = 12

# JSONL entry types to skip entirely (no useful content for review)
_SKIP_TYPES = frozenset({
    "progress", "system", "queue-operation", "file-history-snapshot",
    "custom-title",
})

# User message prefixes that are system noise, not real user input
_NOISE_PREFIXES = (
    "<local-command-caveat>", "<command-name>", "<local-command-stdout>",
    "<system-reminder>",
)


# ── State helpers ─────────────────────────────────────────────────────────────

def _empty_state() -> dict:
    return {
        "last_review_date": None,
        "last_summary": "N/A (first run)",
        "last_session_id": None,
    }


def load_state() -> dict:
    state = _empty_state()
    if STATE_FILE.is_file():
        try:
            data = json.loads(STATE_FILE.read_text())
            for k in state:
                state[k] = data.get(k, state[k])
        except Exception as e:
            print(f"[workflow-review] WARNING: could not load state: {e}", file=sys.stderr)
    return state


def _save_state(state: dict) -> None:
    tmp = str(STATE_FILE) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")
    os.replace(tmp, STATE_FILE)
    print(f"[workflow-review] State saved: {STATE_FILE}")


# ── JSONL helpers ────────────────────────────────────────────────────────────

def _is_workflow_relevant(title: str) -> bool:
    t = title.lower()
    return any(k in t for k in WORKFLOW_KEYWORDS)


def _extract_sessions_start_header(output: str) -> str:
    """Keep only the first N lines of sessions.py start output (skip stale docs, project index, instruction docs)."""
    lines = output.splitlines()
    boilerplate_markers = [
        "== STALE", "== PROJECT INDEX", "== INSTRUCTION DOCS",
        "== BACKLOG", "Arch docs", "Project:", "Load:",
        "== TASK COMPLETION", "== END",
    ]
    keep = []
    for line in lines:
        if any(line.strip().startswith(m) for m in boilerplate_markers):
            break
        keep.append(line)
        if len(keep) >= SESSIONS_START_HEADER_LINES:
            break
    return "\n".join(keep)


def _parse_session_meta(jsonl_path: Path) -> dict | None:
    """
    Read the first ~20 lines of a JSONL file to extract session metadata.

    Returns dict with keys: session_id, title, timestamp_iso, timestamp_dt
    or None if the file can't be parsed.
    """
    title = None
    first_timestamp = None
    session_id = jsonl_path.stem  # UUID from filename

    try:
        with open(jsonl_path) as f:
            for i, line in enumerate(f):
                if i > 30:
                    break
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                etype = entry.get("type", "")

                # Custom title (set by --name flag or auto-generated)
                if etype == "custom-title" and not title:
                    title = entry.get("customTitle", "")

                # Capture first timestamp from any entry
                if not first_timestamp and entry.get("timestamp"):
                    first_timestamp = entry["timestamp"]

                # Fallback title: first real user message
                if etype == "user" and not title:
                    msg = entry.get("message", {})
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        # Skip system/command noise
                        stripped = content.strip()
                        if stripped and not any(stripped.startswith(p) for p in _NOISE_PREFIXES):
                            title = stripped[:120]

    except (OSError, UnicodeDecodeError):
        return None

    if not first_timestamp:
        return None

    try:
        # Claude Code uses ISO 8601 timestamps (e.g. "2026-03-24T19:04:54.004Z")
        ts_dt = datetime.fromisoformat(first_timestamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None

    return {
        "session_id": session_id,
        "title": title or "(untitled)",
        "timestamp_iso": first_timestamp,
        "timestamp_dt": ts_dt,
        "path": jsonl_path,
    }


def _extract_session_content(jsonl_path: Path) -> str:
    """
    Extract relevant content from a Claude Code JSONL session file.

    Reads user/assistant text + targeted Bash tool outputs for sessions.py
    and debug.py. Skips everything else (Read, Edit, Glob, Agent, progress, etc.).

    Returns a single string combining all extracted segments.
    """
    segments = []
    # Track pending Bash tool_use calls that match our target commands,
    # so we can capture their tool_result output from subsequent user messages.
    pending_bash: dict[str, str] = {}  # tool_use_id → command string

    try:
        with open(jsonl_path) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                etype = entry.get("type", "")

                if etype in _SKIP_TYPES:
                    continue

                # ── Assistant messages: text blocks + Bash tool_use blocks ──
                if etype == "assistant":
                    msg = entry.get("message", {})
                    content = msg.get("content", [])
                    if not isinstance(content, list):
                        continue

                    for block in content:
                        btype = block.get("type", "")

                        if btype == "text":
                            text = (block.get("text") or "").strip()
                            if text:
                                segments.append(text)

                        elif btype == "tool_use" and block.get("name") == "Bash":
                            inp = block.get("input", {})
                            cmd = inp.get("command", "")
                            tool_id = block.get("id", "")

                            is_sessions = any(k in cmd for k in SESSIONS_TOOL_COMMANDS)
                            is_debug = any(k in cmd for k in DEBUG_TOOL_COMMANDS)

                            if (is_sessions or is_debug) and tool_id:
                                pending_bash[tool_id] = cmd

                # ── User messages: plain text + tool_result blocks ──────────
                elif etype == "user":
                    msg = entry.get("message", {})
                    content = msg.get("content", "")

                    # Plain text user message
                    if isinstance(content, str):
                        stripped = content.strip()
                        if stripped and not any(stripped.startswith(p) for p in _NOISE_PREFIXES):
                            segments.append(stripped)

                    # List of content blocks (may contain tool_result)
                    elif isinstance(content, list):
                        for block in content:
                            btype = block.get("type", "")

                            if btype == "tool_result":
                                tool_id = block.get("tool_use_id", "")
                                if tool_id not in pending_bash:
                                    continue

                                cmd = pending_bash.pop(tool_id)

                                # Extract output text from tool_result content
                                result_content = block.get("content", "")
                                if isinstance(result_content, list):
                                    # Content is a list of blocks
                                    output_parts = []
                                    for rb in result_content:
                                        if rb.get("type") == "text":
                                            output_parts.append(rb.get("text", ""))
                                    output = "\n".join(output_parts)
                                elif isinstance(result_content, str):
                                    output = result_content
                                else:
                                    output = ""

                                # Apply same filtering as the old SQLite reader
                                is_sessions = any(k in cmd for k in SESSIONS_TOOL_COMMANDS)
                                is_start = is_sessions and "sessions.py start" in cmd
                                is_deploy = is_sessions and "sessions.py deploy" in cmd
                                is_debug = any(k in cmd for k in DEBUG_TOOL_COMMANDS)

                                if is_start:
                                    trimmed = _extract_sessions_start_header(output)
                                    segments.append(f"$ {cmd}\n{trimmed}")
                                elif is_deploy or is_debug:
                                    segments.append(f"$ {cmd}\n{output[:3000]}")
                                else:
                                    # Other sessions.py subcommands: command + first 20 lines
                                    first_lines = "\n".join(output.splitlines()[:20])
                                    segments.append(f"$ {cmd}\n{first_lines}")

    except (OSError, UnicodeDecodeError) as e:
        segments.append(f"(error reading session: {e})")

    return "\n\n".join(segments)


def _truncate(text: str, budget: int) -> tuple[str, bool]:
    """Apply head+tail truncation to fit within budget chars."""
    if len(text) <= budget:
        return text, False
    head = int(budget * HEAD_RATIO)
    tail = int(budget * TAIL_RATIO)
    omitted = len(text) - head - tail
    return (
        text[:head]
        + f"\n\n[...{omitted:,} chars omitted (middle of session)...]\n\n"
        + text[-tail:],
        True,
    )


# ── Main extraction ───────────────────────────────────────────────────────────

def build_session_digests(yesterday: str, verbose: bool = False) -> tuple[str, int, int]:
    """
    Scan Claude Code JSONL session files and build digests for yesterday.

    Returns (digest_text, relevant_count, total_chars)
    """
    if not SESSIONS_DIR.is_dir():
        print(f"[workflow-review] ERROR: sessions dir not found at {SESSIONS_DIR}", file=sys.stderr)
        sys.exit(1)

    target_date = datetime.strptime(yesterday, "%Y-%m-%d").date()

    # Pre-filter by file mtime (fast; avoids reading every JSONL)
    # Use a 1-day buffer on each side to account for timezone differences
    day_start_ts = datetime(
        target_date.year, target_date.month, target_date.day,
        tzinfo=timezone.utc,
    ).timestamp()
    day_end_ts = day_start_ts + 86400

    candidates = []
    for p in SESSIONS_DIR.glob("*.jsonl"):
        mtime = p.stat().st_mtime
        # Include files modified within ±24h of the target day
        if mtime >= (day_start_ts - 86400) and mtime <= (day_end_ts + 86400):
            candidates.append(p)

    # Parse metadata and filter to exact date
    sessions = []
    for p in candidates:
        meta = _parse_session_meta(p)
        if meta and meta["timestamp_dt"].date() == target_date:
            sessions.append(meta)

    # Sort by timestamp
    sessions.sort(key=lambda s: s["timestamp_dt"])

    total = len(sessions)
    relevant = [s for s in sessions if _is_workflow_relevant(s["title"])]
    skipped = total - len(relevant)

    if verbose:
        print(f"[workflow-review] {total} sessions on {yesterday}: {len(relevant)} relevant, {skipped} skipped")

    digests = []
    grand_chars = 0

    for s in relevant:
        title = s["title"]
        time_str = s["timestamp_dt"].strftime("%H:%M UTC")

        content = _extract_session_content(s["path"])
        trimmed, was_truncated = _truncate(content, PER_SESSION_BUDGET)
        grand_chars += len(trimmed)

        trunc_note = f" [truncated from {len(content):,} chars]" if was_truncated else ""
        header = f"### Session: {title} ({time_str}){trunc_note}"

        digests.append(f"{header}\n\n{trimmed}")

        if verbose:
            print(f"  {len(trimmed):>6,} chars | {title[:70]}")

    digest_text = "\n\n---\n\n".join(digests) if digests else "(no relevant sessions found)"

    if verbose:
        print(f"[workflow-review] Total digest: {grand_chars:,} chars (~{grand_chars // 4:,} tokens)")

    return digest_text, len(relevant), grand_chars


def build_prompt(yesterday: str, state: dict, verbose: bool = False) -> str:
    """Build the full prompt by substituting into the template."""
    if not PROMPT_TEMPLATE.is_file():
        print(f"[workflow-review] ERROR: prompt template not found at {PROMPT_TEMPLATE}", file=sys.stderr)
        sys.exit(1)

    digests, count, chars = build_session_digests(yesterday, verbose=verbose)
    last_summary = state.get("last_summary") or "N/A (first run)"

    template = PROMPT_TEMPLATE.read_text()
    prompt = (
        template
        .replace("{{DATE}}", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        .replace("{{YESTERDAY}}", yesterday)
        .replace("{{LAST_SUMMARY}}", last_summary)
        .replace("{{SESSION_DIGESTS}}", digests)
    )

    if verbose:
        print(f"[workflow-review] Prompt: {len(prompt):,} chars (~{len(prompt) // 4:,} tokens) from {count} sessions")

    return prompt


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_dry_run(yesterday: str) -> None:
    """Build and print the prompt without calling claude."""
    print(f"[workflow-review] DRY RUN for {yesterday}")
    state = load_state()
    prompt = build_prompt(yesterday, state, verbose=True)

    print("\n" + "=" * 70)
    print("PROMPT (first 6000 chars):")
    print("=" * 70)
    print(prompt[:6000])
    if len(prompt) > 6000:
        print(f"\n... ({len(prompt) - 6000:,} more chars) ...")
    print("=" * 70)
    print(f"\nTotal prompt: {len(prompt):,} chars (~{len(prompt) // 4:,} tokens)")


def cmd_run_review(yesterday: str) -> None:
    """Build prompt and run claude analysis."""
    state = load_state()
    prompt = build_prompt(yesterday, state, verbose=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    session_title = f"workflow-review {yesterday}"

    print(f"[workflow-review] Starting claude session '{session_title}'...")

    returncode, session_id = run_claude_session(
        prompt=prompt,
        session_title=session_title,
        project_root=str(PROJECT_ROOT),
        log_prefix="[workflow-review]",
        agent="plan",
        timeout=900,
        job_type="workflow-review",
    )

    if session_id:
        # Emit parseable line for any caller capturing session ID
        print(f"CLAUDE_SESSION_ID:{session_id}")

    # Save state
    state["last_review_date"] = today
    state["last_summary"] = session_id or "(see log)"
    state["last_session_id"] = session_id
    _save_state(state)

    if returncode != 0:
        sys.exit(returncode)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]

    # Allow overriding the target date for testing
    # e.g. REVIEW_DATE=2026-03-17 python3 _workflow_review_helper.py dry-run
    override_date = os.environ.get("REVIEW_DATE", "")
    if override_date:
        yesterday = override_date
    else:
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    if not args or args[0] == "dry-run":
        cmd_dry_run(yesterday)
    elif args[0] == "run-review":
        cmd_run_review(yesterday)
    else:
        print(f"[workflow-review] Unknown command: {args[0]}", file=sys.stderr)
        print("Usage: _workflow_review_helper.py [dry-run|run-review]", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
