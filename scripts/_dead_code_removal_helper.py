#!/usr/bin/env python3
"""
scripts/_dead_code_removal_helper.py

Python helper for nightly-dead-code-removal.sh.

Handles: findings prioritisation, state tracking (skip already-removed items),
building the opencode prompt, and dispatching opencode in build mode.

Called by the shell script via:
    python3 scripts/_dead_code_removal_helper.py run

Environment variables (set by the shell script):
    FINDINGS_JSON_B64       — base64-encoded JSON output from find_dead_code.py
    STATE_FILE_PATH         — path to .dead-code-removal-state.json
    PROJECT_ROOT            — absolute repo root path
    DRY_RUN                 — "true" to skip actual opencode invocation
    PROMPT_TEMPLATE_PATH    — path to scripts/prompts/dead-code-removal.md
    MAX_FINDINGS_TOTAL      — hard cap on items sent to opencode (default: 50)
    CURRENT_SHA             — current HEAD SHA (written to state after run)
    TODAY_DATE              — current date as YYYY-MM-DD

State file format (.dead-code-removal-state.json):
{
  "last_run_at": "2026-03-18T02:00:00Z",
  "last_run_sha": "abc1234",
  "total_runs": 12,
  "total_items_removed": 87,
  "removed_items": [
    {
      "key": "python::unused_import::backend/apps/ai/utils/llm_utils.py::19",
      "removed_at": "2026-03-18T02:00:00Z",
      "code": "`importlib` imported but unused"
    }
  ]
}
"""

import base64
import json
import os

from _opencode_utils import run_opencode_session
import sys
from datetime import datetime, timezone


# Confidence priority for sorting (high first)
CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2}

# Category priority — Python auto-fixes are safest, so lead with those
CATEGORY_ORDER = {"python": 0, "svelte": 1, "css": 2, "typescript": 3}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_state(state_file: str) -> dict:
    empty: dict = {
        "last_run_at": None,
        "last_run_sha": None,
        "total_runs": 0,
        "total_items_removed": 0,
        "removed_items": [],
    }
    if not os.path.isfile(state_file):
        return empty
    try:
        with open(state_file) as f:
            data = json.load(f)
        # Ensure all keys present
        for k, v in empty.items():
            data.setdefault(k, v)
        return data
    except Exception as e:
        print(f"[dead-code] WARNING: could not load state file: {e} — starting fresh.", file=sys.stderr)
        return empty


def _save_state(state_file: str, data: dict) -> None:
    tmp = state_file + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, state_file)
    print(f"[dead-code] State saved: {state_file}")


def _item_key(item: dict) -> str:
    """Stable dedup key for a finding."""
    return "::".join([
        item.get("category", ""),
        item.get("subcategory", ""),
        item.get("file", ""),
        str(item.get("line", "")),
        item.get("code", "")[:60],
    ])


def _format_findings_body(items: list[dict]) -> str:
    """
    Format the findings into a clear, structured body for the prompt.
    Groups by category → subcategory, with file:line and snippet.
    """
    lines: list[str] = []
    by_category: dict[str, list] = {}
    for item in items:
        by_category.setdefault(item["category"], []).append(item)

    for cat in sorted(by_category, key=lambda c: CATEGORY_ORDER.get(c, 99)):
        cat_items = by_category[cat]
        lines.append(f"### {cat.upper()} ({len(cat_items)} items)")
        lines.append("")

        by_sub: dict[str, list] = {}
        for item in cat_items:
            by_sub.setdefault(item["subcategory"], []).append(item)

        for sub, sub_items in by_sub.items():
            lines.append(f"#### {sub.replace('_', ' ').title()}")
            lines.append("")
            for item in sub_items:
                conf = item.get("confidence", "medium")
                conf_icon = {"high": "🔴", "medium": "🟡"}.get(conf, "⚪")
                auto = " `[auto-fix: ruff --fix]`" if item.get("auto_fixable") else ""
                lines.append(f"- {conf_icon} **`{item['file']}:{item.get('line', '?')}`**{auto}")
                lines.append(f"  {item['message']}")
                ctx = item.get("context", "").strip()
                if ctx:
                    lines.append("  ```")
                    for ctx_line in ctx.splitlines():
                        lines.append(f"  {ctx_line}")
                    lines.append("  ```")
                lines.append("")

    return "\n".join(lines)


def run() -> None:
    """Main entry point."""
    findings_b64 = os.environ.get("FINDINGS_JSON_B64", "")
    state_file = os.environ.get("STATE_FILE_PATH", "")
    project_root = os.environ.get("PROJECT_ROOT", "")
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    prompt_template_path = os.environ.get("PROMPT_TEMPLATE_PATH", "")
    max_total = int(os.environ.get("MAX_FINDINGS_TOTAL", "50"))
    current_sha = os.environ.get("CURRENT_SHA", "unknown")
    today_date = os.environ.get("TODAY_DATE", datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    if not state_file:
        print("[dead-code] ERROR: STATE_FILE_PATH not set.", file=sys.stderr)
        sys.exit(1)

    # Decode findings
    try:
        findings_json = base64.b64decode(findings_b64).decode("utf-8")
        data = json.loads(findings_json)
        all_items: list[dict] = data.get("items", [])
    except Exception as e:
        print(f"[dead-code] ERROR: Could not parse findings JSON: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[dead-code] Raw findings from detector: {len(all_items)}")

    if not all_items:
        print("[dead-code] No dead code found — nothing to do.")
        # Still update state
        state = _load_state(state_file)
        state["last_run_at"] = _now_iso()
        state["last_run_sha"] = current_sha
        _save_state(state_file, state)
        return

    # Load state to filter already-removed items
    state = _load_state(state_file)
    removed_keys: set[str] = {e["key"] for e in state.get("removed_items", [])}

    # Filter out already-removed items
    fresh_items = [item for item in all_items if _item_key(item) not in removed_keys]
    skipped_already_done = len(all_items) - len(fresh_items)
    if skipped_already_done:
        print(f"[dead-code] Skipped {skipped_already_done} item(s) already removed in previous runs.")

    if not fresh_items:
        print("[dead-code] All detected items were already removed in previous runs — nothing to do.")
        state["last_run_at"] = _now_iso()
        state["last_run_sha"] = current_sha
        _save_state(state_file, state)
        return

    # Sort: high confidence first, then by category priority
    fresh_items.sort(key=lambda i: (
        CONFIDENCE_ORDER.get(i.get("confidence", "medium"), 1),
        CATEGORY_ORDER.get(i.get("category", ""), 9),
    ))

    # Cap to max_total
    items_to_send = fresh_items[:max_total]
    capped = len(fresh_items) - len(items_to_send)
    if capped:
        print(f"[dead-code] Capped to {max_total} items (deferred {capped} to next run).")

    print(f"[dead-code] Sending {len(items_to_send)} item(s) to opencode.")

    # Summarise categories
    cat_counts: dict[str, int] = {}
    for item in items_to_send:
        cat_counts[item["category"]] = cat_counts.get(item["category"], 0) + 1
    categories_str = ", ".join(f"{cat} ({n})" for cat, n in sorted(cat_counts.items()))
    print(f"[dead-code] Breakdown: {categories_str}")

    # Build prompt
    if not prompt_template_path or not os.path.isfile(prompt_template_path):
        print(f"[dead-code] ERROR: Prompt template not found: {prompt_template_path}", file=sys.stderr)
        sys.exit(1)

    with open(prompt_template_path) as f:
        template = f.read()

    findings_body = _format_findings_body(items_to_send)
    prompt = (
        template
        .replace("{{DATE}}", today_date)
        .replace("{{TOTAL_FINDINGS}}", str(len(items_to_send)))
        .replace("{{CATEGORIES}}", categories_str)
        .replace("{{FINDINGS_BODY}}", findings_body)
    )

    if dry_run:
        print("[dead-code] DRY RUN — would run opencode with the following prompt:")
        print("-" * 70)
        print(prompt[:3000])
        if len(prompt) > 3000:
            print(f"... ({len(prompt) - 3000} more chars)")
        print("-" * 70)
        # Still update state SHA so --force isn't needed next dry-run
        state["last_run_at"] = _now_iso()
        state["last_run_sha"] = current_sha
        _save_state(state_file, state)
        return

    # Dispatch opencode in build mode (agent=None)
    session_title = f"chore: dead code removal {today_date}"
    print(f"[dead-code] Starting opencode session '{session_title}'...")

    returncode, share_url = run_opencode_session(
        prompt=prompt,
        session_title=session_title,
        project_root=project_root,
        log_prefix="[dead-code]",
        agent=None,    # build mode — no agent flag
        timeout=2400,  # 40 minutes — dead code removal involves many file edits
    )

    # Record items as removed in state regardless of opencode exit code —
    # if opencode ran at all it likely cleaned some items; next run re-detects remainder.
    now_iso = _now_iso()
    new_removed = [
        {
            "key": _item_key(item),
            "removed_at": now_iso,
            "code": item.get("message", item.get("code", "")),
        }
        for item in items_to_send
    ]
    state["removed_items"] = state.get("removed_items", []) + new_removed
    state["total_items_removed"] = state.get("total_items_removed", 0) + len(items_to_send)
    state["total_runs"] = state.get("total_runs", 0) + 1
    state["last_run_at"] = now_iso
    state["last_run_sha"] = current_sha
    _save_state(state_file, state)

    if returncode != 0:
        sys.exit(returncode)


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] != "run":
        print(f"Usage: {sys.argv[0]} run", file=sys.stderr)
        sys.exit(1)
    run()
