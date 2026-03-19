#!/usr/bin/env python3
"""
scripts/_workflow_review_helper.py

Nightly workflow review — analyzes yesterday's opencode sessions to extract
improvement suggestions for sessions.py, debug.py, and CLAUDE.md.

Architecture context: See CLAUDE.md (Session Lifecycle section)

Commands:
    dry-run     Build and print the prompt without calling opencode
    run-review  Build prompt and run opencode analysis

State file: scripts/.workflow-review-state.json
DB: /home/superdev/.local/share/opencode/opencode.db (sqlite3, direct access)

Extraction logic per session:
  - text parts: all assistant/user prose
  - bash tool calls to sessions.py: header lines only (first 10 lines of output)
  - bash tool calls to sessions.py deploy: full output (small, high signal)
  - bash tool calls to debug.py: full output (actual debugging signal)
  - everything else dropped (Read/Edit/Write/Glob/file/step-start/step-finish)

Not intended to be called directly by users; use nightly-workflow-review.sh instead.
Can be run manually for testing:
    DRY_RUN=true python3 scripts/_workflow_review_helper.py dry-run
    python3 scripts/_workflow_review_helper.py dry-run   # same as above
    python3 scripts/_workflow_review_helper.py run-review
"""

import json
import os

from _opencode_utils import run_opencode_session
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path


# ── Constants ────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
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
    "dependabot", "concurrent", "deploy", "opencode",
]

# Bash commands worth extracting tool output for (beyond text parts)
SESSIONS_TOOL_COMMANDS = ["sessions.py"]
DEBUG_TOOL_COMMANDS = ["debug.py"]

# Max lines to keep from sessions.py start output (skip boilerplate)
SESSIONS_START_HEADER_LINES = 12


# ── State helpers ─────────────────────────────────────────────────────────────

def _empty_state() -> dict:
    return {
        "last_review_date": None,
        "last_summary": "N/A (first run)",
        "last_session_url": None,
    }


def _load_state() -> dict:
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


# ── DB helpers ────────────────────────────────────────────────────────────────

def _day_range_ms(date_str: str) -> tuple[int, int]:
    """Return (start_ms, end_ms) for a YYYY-MM-DD date in UTC."""
    d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    start = int(d.timestamp() * 1000)
    end = int((d + timedelta(days=1) - timedelta(milliseconds=1)).timestamp() * 1000)
    return start, end


def _is_workflow_relevant(title: str) -> bool:
    t = title.lower()
    return any(k in t for k in WORKFLOW_KEYWORDS)


def _extract_sessions_start_header(output: str) -> str:
    """Keep only the first N lines of sessions.py start output (skip stale docs, project index, instruction docs)."""
    lines = output.splitlines()
    # Find where the boilerplate begins (STALE, PROJECT INDEX, INSTRUCTION DOCS, BACKLOG)
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


def _extract_part_content(session_id: str, conn: sqlite3.Connection) -> str:
    """
    Extract relevant content from a session's parts.
    Returns a single string combining user/assistant text + targeted tool outputs.
    """
    parts = conn.execute("""
        SELECT json_extract(data, '$.type') as ptype, data
        FROM part
        WHERE session_id = ?
        ORDER BY time_created
    """, (session_id,)).fetchall()

    segments = []

    for p in parts:
        ptype = p["ptype"]
        raw = p["data"]

        if ptype == "text":
            try:
                d = json.loads(raw)
                text = (d.get("text") or "").strip()
                if text:
                    segments.append(text)
            except Exception:
                pass

        elif ptype == "tool":
            try:
                d = json.loads(raw)
                tool = d.get("tool", "")
                if tool != "bash":
                    continue
                state = d.get("state", {})
                if not isinstance(state, dict):
                    continue
                inp = state.get("input", {})
                cmd = inp.get("command", "")
                output = state.get("output", "") or ""

                is_sessions = any(k in cmd for k in SESSIONS_TOOL_COMMANDS)
                is_debug = any(k in cmd for k in DEBUG_TOOL_COMMANDS)

                if not (is_sessions or is_debug):
                    continue

                # For sessions.py start: trim boilerplate, keep header
                is_start_call = is_sessions and "sessions.py start" in cmd
                is_deploy_call = is_sessions and "sessions.py deploy" in cmd

                if is_start_call:
                    trimmed_output = _extract_sessions_start_header(output)
                    segments.append(f"$ {cmd}\n{trimmed_output}")
                elif is_deploy_call or is_debug:
                    # Keep full output for deploy and debug calls
                    segments.append(f"$ {cmd}\n{output[:3000]}")  # cap at 3K each
                else:
                    # Other sessions.py subcommands: keep command + first 20 lines
                    first_lines = "\n".join(output.splitlines()[:20])
                    segments.append(f"$ {cmd}\n{first_lines}")
            except Exception:
                pass

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
    Query the opencode SQLite DB and build session digests for yesterday.

    Returns (digest_text, session_count, total_chars)
    """
    if not DB_PATH.is_file():
        print(f"[workflow-review] ERROR: opencode DB not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    start_ms, end_ms = _day_range_ms(yesterday)

    sessions = conn.execute("""
        SELECT id, title, time_created
        FROM session
        WHERE time_created BETWEEN ? AND ?
        AND directory = ?
        ORDER BY time_created
    """, (start_ms, end_ms, str(PROJECT_ROOT))).fetchall()

    total = len(sessions)
    relevant = [s for s in sessions if _is_workflow_relevant(s["title"] or "")]
    skipped = total - len(relevant)

    if verbose:
        print(f"[workflow-review] {total} sessions on {yesterday}: {len(relevant)} relevant, {skipped} skipped")

    digests = []
    grand_chars = 0

    for s in relevant:
        title = s["title"] or "(untitled)"
        ts = datetime.fromtimestamp(s["time_created"] / 1000, tz=timezone.utc)
        time_str = ts.strftime("%H:%M UTC")

        content = _extract_part_content(s["id"], conn)
        trimmed, was_truncated = _truncate(content, PER_SESSION_BUDGET)
        grand_chars += len(trimmed)

        trunc_note = f" [truncated from {len(content):,} chars]" if was_truncated else ""
        header = f"### Session: {title} ({time_str}){trunc_note}"

        digests.append(f"{header}\n\n{trimmed}")

        if verbose:
            print(f"  {len(trimmed):>6,} chars | {title[:70]}")

    conn.close()

    digest_text = "\n\n---\n\n".join(digests) if digests else "(no relevant sessions found)"

    if verbose:
        print(f"[workflow-review] Total digest: {grand_chars:,} chars (~{grand_chars//4:,} tokens)")

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
        print(f"[workflow-review] Prompt: {len(prompt):,} chars (~{len(prompt)//4:,} tokens) from {count} sessions")

    return prompt


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_dry_run(yesterday: str) -> None:
    """Build and print the prompt without calling opencode."""
    print(f"[workflow-review] DRY RUN for {yesterday}")
    state = _load_state()
    prompt = build_prompt(yesterday, state, verbose=True)

    print("\n" + "=" * 70)
    print("PROMPT (first 6000 chars):")
    print("=" * 70)
    print(prompt[:6000])
    if len(prompt) > 6000:
        print(f"\n... ({len(prompt) - 6000:,} more chars) ...")
    print("=" * 70)
    print(f"\nTotal prompt: {len(prompt):,} chars (~{len(prompt)//4:,} tokens)")


def cmd_run_review(yesterday: str) -> None:
    """Build prompt and run opencode analysis."""
    state = _load_state()
    prompt = build_prompt(yesterday, state, verbose=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    session_title = f"workflow-review {yesterday}"

    print(f"[workflow-review] Starting opencode session '{session_title}'...")

    returncode, share_url = run_opencode_session(
        prompt=prompt,
        session_title=session_title,
        project_root=str(PROJECT_ROOT),
        log_prefix="[workflow-review]",
        agent="plan",
        timeout=900,
    )

    if share_url:
        # Emit parseable line for any caller capturing OPENCODE_URL:
        print(f"OPENCODE_URL:{share_url}")

    # Save state
    state["last_review_date"] = today
    state["last_summary"] = share_url or "(see log)"
    state["last_session_url"] = share_url
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
