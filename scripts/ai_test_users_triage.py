"""Which AI test-user issues start a debugging chat by themselves (owner, 23 Nov 2026).

Every kept finding of a run is one issue (grouped by cause within its environment). Each issue gets a
`debug` entry that the run's Discord message shows:

  route "auto"      A clear functional error: a console error or exception (e.g. "RangeError: Unknown node
                    type: listItem"), a hang or timeout, raw JSON or code shown instead of an embed, a failed
                    send, a crash or a broken flow. A debugging chat starts without asking.
  route "approval"  Everything else, above all subjective UI or design findings ("this looks wrong"), and
                    any finding the environment may explain (suspect). No chat starts; the message lists it
                    for Marco's approval so he can catch false positives. `ai_test_users.py debug` starts the
                    chat once he approves.

Before a chat starts, open OpenMates Tasks, running Claude chats and the debug chats this pipeline
started in the last LEDGER_DAYS days are checked for the same issue (its issue id, short id or a
similar title); a match is linked instead of starting a duplicate.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import ai_test_users_message as message_text

ROOT = Path(__file__).resolve().parents[1]
SAME_ISSUE = 0.5  # title similarity at which an open Task or chat counts as the same issue
LEDGER_DAYS = 2
LEDGER_FILE = "debug-chats.jsonl"

# Judge categories (backend/scripts/ai_test_users/models.py): (1) error messages or crashes,
# (3) unreadable data (raw JSON, null/undefined, i18n keys) and (6) slow responses are functional;
# slow responses only when the evidence shows a hang or timeout, not just a slow but finished answer.
FUNCTIONAL_CATEGORY = re.compile(r"error|crash|unreadable", re.I)
SLOW_CATEGORY = re.compile(r"slow", re.I)
FUNCTIONAL_EVIDENCE = re.compile(
    r"\b(?:Range|Type|Reference|Syntax|Uncaught\s*)?Error:|\bexception\b|\buncaught\b|\bcrash(?:ed|es)?\b"
    r"|\bhang(?:s|ing)?\b|\bhung\b|\btimed?[ -]?out\b|\btimeout\b|settled=False|never (?:arriv|finish|load|end)"
    r"|\bspinner\b.*\bnever\b|raw json|json payload|\{\"[a-z_]+\":|instead of (?:an|the) embed"
    r"|fail(?:ed|s)? to send|send(?:ing)? failed|message (?:was )?not sent|broken flow|dead end",
    re.I)


def route(finding: dict) -> tuple[str, str]:
    """("auto" | "approval", short reason) for one finding."""
    if finding.get("suspect"):
        return "approval", f"may be the environment ({finding['suspect']})"
    category = str(finding.get("category") or "")
    text = f"{finding.get('title') or ''} {finding.get('evidence') or ''}"
    if FUNCTIONAL_EVIDENCE.search(text):
        return "auto", "functional error"
    if FUNCTIONAL_CATEGORY.search(category):
        return "auto", "functional error"
    if SLOW_CATEGORY.search(category):
        return "approval", "slow but finished answer"
    return "approval", "looks subjective (UI, design or wording)"


def _mentions(text: str, issue: dict) -> bool:
    ids = [i for i in (issue.get("short_issue_id"), (issue.get("issue_id") or "")[:8]) if i]
    return any(re.search(rf"\b{re.escape(i)}\b", text, re.I) for i in ids)


def coverage(issue: dict, tasks: list[dict], chats: list[dict], ledger: list[dict]) -> str:
    """What already covers this issue ("" when nothing does): an open Task, a running chat or a recent debug chat."""
    title = issue["title"]
    for task in tasks:
        text = f"{task.get('title') or ''} {task.get('description') or ''}"
        if _mentions(text, issue) or message_text.similar(title, str(task.get("title") or "")) >= SAME_ISSUE:
            return f"open Task {task.get('short_id') or task.get('id')}"
    for chat in chats:
        texts = [chat.get("last_prompt") or ""] + [s.get("task") or "" for s in chat.get("sessions") or []]
        if any(_mentions(t, issue) or message_text.similar(title, t) >= SAME_ISSUE for t in texts):
            return f"running chat {str(chat.get('chat'))[:8]}"
    for entry in ledger:
        if entry.get("short_issue_id") == issue.get("short_issue_id") or \
                message_text.similar(title, str(entry.get("title") or "")) >= SAME_ISSUE:
            return f"debug chat \"{entry.get('chat_title')}\" started {str(entry.get('at'))[:10]}"
    return ""


def ledger_entries(base: Path | None, now: float | None = None) -> list[dict]:
    """Debug chats this pipeline started in the last LEDGER_DAYS days (none without a state folder)."""
    path = base / LEDGER_FILE if base else None
    if path is None or not path.exists():
        return []
    cutoff = (now or time.time()) - LEDGER_DAYS * 86400
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [r for r in rows if float(r.get("epoch") or 0) >= cutoff]


def record_chat(base: Path, issue: dict, chat_title: str, now: float | None = None) -> None:
    stamp = now or time.time()
    entry = {"epoch": stamp, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stamp)), "env": issue["env"],
             "short_issue_id": issue.get("short_issue_id"), "title": issue["title"], "chat_title": chat_title}
    base.mkdir(parents=True, exist_ok=True)
    with (base / LEDGER_FILE).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def issues_of(results: list[dict]) -> list[dict]:
    """Kept findings (bug or suspect) grouped by cause within each environment, with their filed report."""
    out = []
    for env in ("dev", "prod"):
        groups = message_text.causes([r for r in results if r.get("target") == env])
        for group in groups:
            if group["verdict"] == "not a bug":
                continue
            lead = next((m for m in group["members"] if m["report"]), group["members"][0])
            out.append({"env": env, "title": group["title"], "group": group, "finding": lead["finding"],
                        "short_issue_id": lead["report"], "issue_id": None})
    return out


def start_chat(issue: dict, launch=None) -> dict:
    """Start the investigation chat for one issue through the dispatcher (daily cap applies)."""
    import claude_dispatch
    import issues as issue_api

    if not issue.get("short_issue_id"):
        return {"status": "no_report", "note": "no report was filed, so no chat can open it"}
    issue_id = issue_api.resolve_issue_identifier(issue["env"], issue["short_issue_id"])
    if not claude_dispatch.UUID_RE.match(issue_id or ""):
        return {"status": "failed", "note": "issue id not found"}
    issue["issue_id"] = issue_id
    return (launch or claude_dispatch.launch_test_user_chat)(issue_id, issue["short_issue_id"], issue["env"])


def triage(results: list[dict], base: Path | None, dispatch: bool, tasks: list[dict] | None = (), chats=None,
           launch=None, now: float | None = None) -> list[dict]:
    """Route every issue, link what already covers it and (with `dispatch`) start the auto chats.

    Returns the issues with a `debug` entry: route, why, status (started | queued | deferred | covered |
    approval | would_start | no_report | failed), and the chat title or covering Task/chat. `tasks` None means
    the open Tasks could not be listed: no chat starts then, since duplicates could not be ruled out."""
    found = issues_of(results)
    ledger = ledger_entries(base, now)
    for issue in found:
        lane, why = route(issue["finding"])
        debug = {"route": lane, "why": why}
        issue["debug"] = debug
        if lane == "approval":
            debug["status"] = "approval"
            continue
        if tasks is None:
            debug.update(status="failed", note="open Tasks could not be checked for duplicates, so no chat started")
            continue
        covered = coverage(issue, tasks, chats or [], ledger)
        if covered:
            debug.update(status="covered", covered_by=covered)
        elif not dispatch:
            debug["status"] = "would_start"
        else:
            debug.update(start_chat(issue, launch))
            if debug["status"] in ("started", "queued"):
                record_chat(base, issue, debug["chat_title"], now)
                ledger = ledger_entries(base, now)
    return found


def running_chats() -> list[dict]:
    import agent_peers

    return agent_peers.peers(ROOT, current="")
