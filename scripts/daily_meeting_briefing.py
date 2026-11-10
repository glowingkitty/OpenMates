#!/usr/bin/env python3
"""Build the weekday daily meeting briefing, upload it privately, post the link to Discord.

Pipeline (weekdays 11:30 Europe/Berlin via the dev-server crontab):
  1. scripts/daily_meeting_context.py collect — deterministic evidence: Claude chats,
     git (incl. marketing repo), OpenMates Tasks, nightly tests, FOCUS.md, and Apple
     Reminders (live, or the copy `mac_reminders.py sync` refreshes every 30 minutes).
  2. Gemini Flash (in the api container, Vault key) summarizes the Claude chats;
     Claude Code stores only short titles, no summaries.
  3. Markdown briefing → private 48 h S3 link (scripts/response_media.py) → Discord.
The user pastes the Discord message into a Claude app chat and holds the meeting
by voice; the resulting decisions note is applied on the dev server with the
`daily-meeting-and-orchestration` skill. Docs: docs/contributing/guides/daily-meeting.md
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import re
import os
from pathlib import Path
import subprocess
import time
import sys
from zoneinfo import ZoneInfo

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import daily_meeting_context as context  # noqa: E402 - sibling scripts, path set above
import mac_reminders  # noqa: E402

TZ = ZoneInfo("Europe/Berlin")
PHASE_ANCHOR = date(2026, 11, 2)  # Monday of the first Marketing Week; weeks alternate
WEBHOOK_KEYS = ("DISCORD_WEBHOOK_DAILY_MEETING", "DISCORD_WEBHOOK_DEV_NIGHTLY")
LINK_SECONDS = 48 * 3600
SCHEDULED_AT = (11, 30)  # Berlin time of the cron run; the crontab fires at 09:30 and 10:30 UTC


def phase(day: date) -> tuple[str, date, date]:
    monday = day - timedelta(days=day.weekday())
    marketing = ((monday - PHASE_ANCHOR).days // 7) % 2 == 0
    return ("Marketing Week" if marketing else "Build Week"), monday, monday + timedelta(days=6)


def configured_value(root: Path, key: str) -> str:
    if os.environ.get(key):
        return os.environ[key]
    env = root / ".env"
    if env.is_file():
        for line in env.read_text().splitlines():
            name, sep, value = line.strip().partition("=")
            if sep and name.strip() == key:
                return value.strip().strip("'\"")
    return ""


# ── Gemini chat summary ───────────────────────────────────────────────────────

SUMMARY_PROMPT = """You summarize a solo founder's AI coding-agent chats from the last \
working day for his morning planning meeting. Input: JSON list of chats (title, user \
prompts, the agent's final reply, timestamps). Return JSON only:
{"themes": [{"theme": str, "outcome": str, "state": "done"|"ongoing"|"stuck"}],
 "loose_ends": [str],
 "chats": [{"session": str, "summary": str}]}
- themes: at most 6, merge related chats, outcome in <= 25 plain words, concrete.
- loose_ends: at most 6 half-finished or risky items the founder should decide on.
- chats: one entry per input chat, summary <= 20 words.
- No secrets, emails or tokens. English. Chats:
"""


WAITING_PROMPT = """Each item is an AI coding-agent chat that waits for its solo founder. For \
each one write ONE plain sentence (<= 25 words; no IDs, code, file names or jargon): what the \
chat is about and what it needs from the founder now. Return JSON only:
{"chats": [{"session": str, "summary": str}]}
One entry per input chat. No secrets, emails or tokens. English. Chats:
"""


def _gemini_json(prompt: str) -> dict:
    """One Gemini Flash call in the api container; raises on a failed run or a non-object reply."""
    helper = (SCRIPTS / "_gemini_flash_container.py").read_text()
    run = subprocess.run(["docker", "exec", "-i", "api", "python", "-c", helper],
                         input=json.dumps({"prompt": prompt, "json": True}),
                         capture_output=True, text=True, timeout=400)
    if run.returncode:
        raise RuntimeError(context.clean(run.stderr, 300))
    reply = json.loads(run.stdout)
    if not isinstance(reply, dict):
        raise ValueError("reply is not a JSON object")
    return reply


def summarize_chats(chats: list[dict], gaps: list[str]) -> dict:
    if not chats:
        return {}
    try:
        return _gemini_json(SUMMARY_PROMPT + json.dumps(chats, ensure_ascii=False))
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as error:
        gaps.append(f"Gemini chat summary failed ({context.clean(str(error), 200)}); appendix lists chat titles only")
        return {}


def summarize_waiting(waiting: dict, gaps: list[str]) -> None:
    """Give every waiting chat a one-line plain summary, so the meeting need not decode its last reply."""
    chats = waiting.get("chats") or []
    if not chats:
        return
    items = [{"session": c["session"], "title": c.get("title", ""), "task": c.get("task_title", ""),
              "waiting_for": c.get("signal", ""), "last_prompt": c.get("last_prompt", ""),
              "last_reply": c.get("last_reply", "")} for c in chats]
    try:
        reply = _gemini_json(WAITING_PROMPT + json.dumps(items, ensure_ascii=False))
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as error:
        gaps.append(f"One-line summaries of the waiting chats failed ({context.clean(str(error), 200)}); "
                    "they show their last reply only")
        return
    lines = {row.get("session"): row.get("summary") for row in reply.get("chats") or [] if isinstance(row, dict)}
    for chat in chats:
        text = re.sub(r"\s+", " ", str(lines.get(chat["session"]) or "")).strip()
        if text:
            chat["summary"] = text[:240]
    missing = sum(1 for chat in chats if not chat.get("summary"))
    if missing:
        gaps.append(f"{missing} waiting chat(s) got no one-line summary; they show their last reply only")


# ── Markdown ──────────────────────────────────────────────────────────────────

def _due_label(item: dict) -> str:
    due = mac_reminders.due_date(item)
    if not due:
        return "no date"
    text = due.strftime("%a %d %b")
    if item.get("due") and len(item["due"]) > 10:
        stamp = datetime.fromisoformat(item["due"].replace("Z", "+00:00")).astimezone(TZ)
        text += stamp.strftime(" %H:%M")
    return text


def _reminder_line(item: dict) -> str:
    return f"- {item['title']} — {item['list']}, {_due_label(item)}"


RETRIES = 2
RETRY_WAIT_SECONDS = 60

MEETING_SCRIPT = """\
## How to run this meeting (instructions for Claude)
You are running a ~20-minute **voice** daily meeting with the founder of OpenMates, \
a solo founder who has ADHD, often has 10–15 agent chats running and keeps getting \
pulled into new features and bugs while marketing (videos, press) slips. \
The meeting must lower overwhelm, not add to it.
- Speak short, plain sentences. Never read IDs, links or long lists aloud; summarize.
- **Plain-language rule:** never mention an ID (TASK-…, issue numbers, session or commit \
ids), an agent name (e.g. "agent-33bc") or a task bare. Always say what it is in a few plain \
words ("the Projects editing task", "the chat about PDF uploads"). In the decisions note, write \
the plain description first and the ID only in brackets after it.
- Ask **exactly one question at a time**, with your recommendation where one applies, then wait.
- Respect the phase rules below. In a Marketing Week, gently push back on features, \
refactors, UX polish and bug fixes that do not block marketing; offer the parking lot.
- **ADHD-friendly rules:** (a) open by naming the 6 blocks (plus a 2-minute closing "improve the meeting") and the time \
budget, and say "Block N of 6" when you move on, so the founder always knows where we are; (b) never more \
than **3** commitments for the day, each with a concrete **first step that takes 5 minutes** \
and a time of day; (c) a new idea mid-meeting is parked in one line ("parked: …") and the \
meeting returns to the agenda — never debate it now; (d) when the founder rambles, reflect \
back in one sentence and ask the next question; (e) if energy is low (1–2), plan one small \
win first and drop the backlog cleanup; (f) add a stop rule to each task ("if X is not \
working after 45 minutes, park it and tell me"); (g) end with a three-line read-back.
- **Flow (6 blocks):**
  - **Block 1 — Check-in (the founder talks, you listen).** Ask these four, one at a time, \
and do not use the briefing yet: (1) What have you been up to since the last meeting — what \
did you work on? (2) How happy are you with that progress, 1–5, and why? (3) What do you \
currently see as the largest priorities? (4) How is your energy today, 1–5? Then reflect \
back in two sentences and compare gently with the facts in the briefing (commits, Task \
changes, yesterday's decisions): name any mismatch ("you said X, but I see no commits for \
it — blocked, or moved?"). Ask about yesterday's tasks (done, not done, moved?) unless the \
git commits make it obvious — then still ask for a one-line confirmation.
  - **Block 2 — Safety net.** If the briefing opens with a ⚠ warning that the OpenMates \
Tasks or the reminders are not up to date, say so first. Then **production first**: \
summarize the "Alerts" section in a few sentences — reported production issues (new or not \
processed yet), then dev reports, then the errors that repeat most — and ask whether anything \
needs attention before planning; production reports outrank everything else. Then the \
**chats waiting on the founder**: one chat at a time (questions and blockers first), say in \
one sentence what it is waiting for (use the chat's one-line summary in italics) and ask what to do — continue (and with what reply), \
park, archive or done — with your recommendation. Stop after the top 3 chats if energy is low.
  - **Block 3 — Focus.** Agree **today's single focus** — propose one from the week's goals \
and the founder's stated priorities — then up to **3 tasks**, each with done-criterion, \
first 5-minute step, time slot and stop rule. Then one short question, every day: **which \
milestone does today's top task serve?** (see "Goals and milestones" in the briefing); if it \
serves none, say so and ask whether to do it anyway, park it or swap it.
  - **Block 4 — Reminders.** Go through overdue and today/tomorrow reminders **in groups** \
(done / move to a date and time you suggest / keep), not one by one. Every moved or new \
reminder needs a **time of day**, never just a date — suggest one. Offer one optional \
midday reminder "Still on <focus>?" as a gentle anchor. Spread moved reminders over several \
days so no day is overloaded.
  - **Block 5 — Parking lot and week goals.** Additions/removals and week-goal changes. \
Read back anything parked during the meeting.
  - **Block 6 on Mondays — Goals and milestones (about 10 minutes; this replaces the backlog \
cleanup).** It also runs on the first later meeting of the week when Monday's was missed: the \
"Goals and milestones" section then says "Weekly goals block is due today". Follow that section: (1) is the current milestone on track — \
use the progress evidence and the drift warnings; (2) is it still the right milestone, and once \
a quarter or when asked, are the mission and the (at most 3) goals still right; (3) split the \
next milestone into 3-7 concrete Tasks (plain title, priority, done-criterion) and agree the \
priority order for the week. One question at a time, with your recommendation. If energy is \
1-2, shrink it to three questions: on track? blocked? is the top priority still right?
  - **Block 6 on days without a due goals block — Backlog cleanup (optional, max 5 minutes, skip if energy is low or the \
meeting already ran 20 minutes).** The meeting also keeps the to-do lists healthy. Take \
**one** batch in groups of 3-5 related items (one question per group, with your \
recommendation): which can be **closed or deleted** (obsolete, done, no longer wanted), \
**merged** into another (duplicates), **delayed** (park for a later Build Week) or **kept**. \
Be critical: say when an item looks stale, vague or contradicts the current goals. In a \
Marketing Week, recommend delaying non-marketing items. Never decide for the founder; \
deletion needs a clear "yes".
- Ask clarifying questions in these directions when relevant: what blocks this week's goals; \
deadlines at risk; whether too many chats are running (and whether the remaining weekly \
Claude usage covers the planned agent work — if it runs out before the reset, cut agent \
work first); parked code that is about to be purged; open GitHub issues and Linear issues \
(Appendix D) that block a goal or can be closed or parked; reminders whose date no longer \
makes sense.
- Close with the three-line read-back: "Today: <focus>. First step: <step> at <time>. \
Parked: <items>."
- **Improve the meeting (2 minutes, every meeting, after the read-back).** Propose **one** change \
to how this meeting runs, with your recommendation, based on evidence from today (it ran long, a \
block was skipped or got "skip" answers, the same item was parked again, stale data was read out, \
a question was unclear) and ask one question: "do you want this change, a different one, or none?" \
"None" is always fine. A change is a one-week trial: if "Agreed meeting adjustments" below lists a \
trial that has run a week, ask first whether to keep, adjust or revert it. Never run two trials at once.
- Then output the decisions note **exactly in this format** in a code block, so it can be \
pasted back to the development server. **Reminder changes and Task changes are tables with one \
row per change, never prose**: the dev server applies and verifies every row, and a row it cannot \
match is reported back. Use the exact reminder title as it appears in the briefing, a time in \
every due (`YYYY-MM-DD HH:MM`, Berlin), and the plain title of a Task (never only an ID).

```
DECISIONS {date}
Check-in: progress <1-5>, energy <1-5>; did: <one line>; priorities: <up to 3, one line>
Focus: <single most important task today>
Focus tasks:
1. <task> (done when: …; first step: …; at HH:MM; stop rule: …; milestone: <name or none>)
Reminder changes:
| Action | Reminder (exact title) | List | New due | New title | Notes |
|---|---|---|---|---|---|
| move | <title> | | YYYY-MM-DD HH:MM | | |
| done | <title> | | | | |
| delete | <title> | | | | |
| create | <new title> | OpenMates or Personal Tasks | YYYY-MM-DD HH:MM | | <notes> |
| update | <title> | | | <new title> | <notes> |
Task changes:
| Action | Task (exact title) | New title | Priority | Status | Label | Due | Description |
|---|---|---|---|---|---|---|---|
| create | <plain title> | | none/low/medium/high/urgent | todo | milestone:<name> | YYYY-MM-DD | <goal, done-criterion> |
| edit | <title> | <new title> | <priority> | <status> | <label to add> | | <description> |
| done | <title> | | | | | | |
| delete | <title> | | | | | | |
Goals:
| Level | Item | Action | Done when | By |
|---|---|---|---|---|
| mission / goal / milestone | <plain wording> | add / edit / done / drop / keep | <measurable result> | YYYY-MM-DD |
Chats:
- <chat title> -> reply: <text> | park | archive | done | keep
Cleanup:
- <plain title> (<GitHub #123 | Linear ABC-1 | TASK-123>) -> close | delete | merge <other id> | delay | keep
Parking lot:
+ <added item> | - <removed item>
Week goals: <unchanged | new goals>
Meeting: <the one change agreed for the meeting itself> -> adopt | adjust | revert | none (trial until YYYY-MM-DD)
Notes: <anything else>
```
"""


def _issue_section(title: str, rows: list[dict] | None, extra: str) -> list[str]:
    if rows is None:
        return [f"**{title}:** unavailable — see data gaps.", ""]
    out = [f"**{title} ({len(rows)} open)** — newest activity first, top 15:"]
    for row in rows[:15]:
        tags = ", ".join(filter(None, [row.get(extra), *row.get("labels", [])[:3]]))
        out.append(f"- {row['title']} ({row['id']}" + (f", {tags}" if tags else "") + ")")
    if len(rows) > 15:
        out.append(f"- … {len(rows) - 15} more")
    return out + [""]


def _alerts_section(alerts: dict) -> list[str]:
    out = ["", "## Alerts — production and dev (reported issues first, errors of the last 24 h)", ""]
    if not alerts:
        return out + ["_Alerts unavailable — see data gaps._"]
    for env, title in (("production", "Production"), ("dev", "Dev server")):
        part = alerts.get(env) or {}
        issues, errors = part.get("issues"), part.get("errors")
        out.append(f"### {title} — reported issues (last 48 h)")
        if issues is None:
            out.append("- unavailable (see data gaps)")
        else:
            out += [f"- **{i['id']}** ({i['age']}{', admin' if i['admin'] else ''}, "
                    f"{'processed' if i['processed'] else '**not processed yet**'}): {i['title']}"
                    for i in issues["recent"]] or ["- none"]
            older = issues.get("older_unprocessed_in_latest_batch", 0)
            if older:
                out.append(f"- plus {older} older unprocessed reports in the latest batch")
        out += ["", f"### {title} — repeating errors (last 24 h)"]
        if errors is None:
            out.append("- unavailable (see data gaps)")
        else:
            out.append(f"{errors['total']} ERROR/CRITICAL rows, {errors['distinct']} distinct"
                       + (" (query truncated)" if errors.get("truncated") else "") + ".")
            out += [f"- {e['count']}× `{e['service']}` {e['where']}: {e['message']}"
                    for e in errors["top"]] or ["- none"]
        out.append("")
    return out


def _cleanup_section(cleanup: dict) -> list[str]:
    out = ["## 4. Backlog cleanup", "",
           "The meeting also tidies the to-do lists. Review this batch (oldest first): "
           "close/delete what is obsolete, merge duplicates, delay what should wait, keep the rest.", ""]
    labels = (("tasks", "OpenMates Tasks (todo, backlog, blocked)", lambda t: f"{t['title']} ({t['id']}) "
                                                                                  f"[{t.get('status')}, {t.get('priority')}]"),
              ("github", "GitHub issues", lambda i: f"{i['title']} ({i['id']}, last activity {i['updated']})"),
              ("linear", "Linear issues", lambda i: f"{i['title']} ({i['id']}, {i.get('state')}, "
                                                    f"last activity {i['updated']})"))
    for key, title, line in labels:
        part = cleanup.get(key) or {}
        out.append(f"**{title}: {part.get('total', 0)} open, {len(part.get('batch', []))} to review today**")
        out += [f"- {line(item)}" for item in part.get("batch", [])] or ["- nothing to review"]
        out.append("")
    return out


def _tasks_banner(status: dict) -> list[str]:
    """Loud warning at the very top when the OpenMates Tasks are missing or not current."""
    if status.get("fresh") and status.get("source") == "live":
        return []
    if status.get("source") == "cache":
        stamp = f"{status['fetched_at'][:16]} UTC, {status.get('age_hours')} h old"
        return [f"> **⚠ OpenMates Tasks are NOT up to date** — the live read failed, so this briefing "
                f"uses the copy from {stamp}. Say this at the start of the meeting; Task statuses may "
                f"have changed since.", ""]
    return ["> **⚠ OpenMates Tasks are UNAVAILABLE** — no live read and no earlier copy. Say this at the "
            "start of the meeting and do not plan from Tasks today.", ""]


def _waiting_section(waiting: dict) -> list[str]:
    chats = waiting.get("chats") or []
    out = ["", "## Chats waiting on you (the assistant spoke last)", ""]
    if not chats:
        return out + ["_None: every recent dev-server chat has your last word or is finished._"]
    for chat in chats:
        task = (f", Task \"{chat['task_title']}\" ({chat['task']})" if chat.get("task_title")
                else f", Task {chat['task']}" if chat.get("task") else "")
        summary = f" — _{chat['summary']}_" if chat.get("summary") else ""
        out.append(f"- **{chat['title']}**{summary} (idle {chat['idle_hours']} h{task}; "
                   f"id `{chat['session'][:8]}`) — {chat['signal']}: {chat['last_reply'][:300]}")
    if waiting.get("omitted"):
        out.append(f"- plus {waiting['omitted']} more waiting chats (older or finished work), not listed")
    return out + [""]


def _goals_section(goals: dict, today: date) -> list[str]:
    """Mission, goals and milestones (GOALS.md) with progress evidence; the Monday block runs on this."""
    due = goals.get("block_due", today.weekday() == 0) if goals else False
    out = ["", "## Goals and milestones" + (" — **run the weekly goals block (Block 6) today**" if due else ""), ""]
    if not goals:
        return out + ["_Goals data unavailable._", ""]
    if due:
        out += [f"**Weekly goals block is due today** ({goals.get('block_reason') or 'Monday'}). It replaces the "
                "backlog cleanup. If GOALS.md is still marked as a draft, first confirm or correct the mission, the "
                "goals and the milestones (names, done-when, dates), then split the current milestone into Tasks "
                "and agree this week's priority order.", ""]
    for warning in goals.get("warnings", []):
        out.append(f"> **⚠** {warning}")
    if goals.get("warnings"):
        out.append("")
    if goals.get("goals_file"):
        text = re.sub(r"^(#{1,2}) ", "#### ", goals["goals_file"].strip(), flags=re.M)
        out += [f"Last weekly review: {goals.get('last_review') or 'never'}.", "", text, ""]
    progress = goals.get("progress") or {}
    rows = progress.get("milestones") or {}
    out.append(f"**Progress per milestone** (Tasks labelled `milestone:<name>`; baseline: {progress.get('baseline', '?')}):")
    out += [f"- **{name}**: " + ", ".join(f"{count} {status}" for status, count in row["statuses"].items())
            + f"; moved this week: {row['moved_this_week']}; open high priority: {row['open_high']}"
            for name, row in rows.items()] or ["- no Task carries a milestone label yet"]
    loose = progress.get("high_open_without_milestone") or {}
    if loose.get("count"):
        out.append(f"- {loose['count']} open high-priority Tasks without a milestone, e.g. " + "; ".join(loose["examples"][:4]))
    out.append("")
    if not due:
        out.append("_Weekly goals block not due today: only ask which milestone today's top task serves._")
        out.append("")
    return out


def _meeting_adjustments(goals: dict) -> list[str]:
    """Adjustments the founder agreed in earlier 'improve the meeting' blocks (private file)."""
    settings, log = (goals or {}).get("meeting_settings"), (goals or {}).get("meeting_changelog") or []
    if not settings and not log:
        return []
    out = ["## Agreed meeting adjustments (follow these; they override the script above where they differ)", ""]
    if settings:
        out += [settings, ""]
    if log:
        out += ["Recent changes to the meeting (newest last):"] + [f"- {line.lstrip('- ')}" for line in log] + [""]
    return out


def _reminders_banner(rem: dict) -> list[str]:
    if rem.get("source") == "live":
        return []
    if rem:
        return [f"> **⚠ Apple Reminders are NOT up to date** — the Mac was unreachable, so this briefing uses "
                f"the copy synced {str(rem.get('fetched_at', '?'))[:16]} UTC. Say this at the start of the meeting.", ""]
    return ["> **⚠ Apple Reminders are UNAVAILABLE** — no live read and no earlier copy. Say this at the "
            "start of the meeting.", ""]


def render(ev: dict, chats_summary: dict, today: date, generated: datetime) -> str:
    name, monday, sunday = phase(today)
    next_name, next_monday, _ = phase(monday + timedelta(days=7))
    rem = ev.get("reminders") or {}
    tasks = ev.get("tasks") or {}
    nightly = ev.get("nightly") or {}
    last = nightly.get("last_nightly_run_with_tests") or {}
    mix = (ev.get("work_mix") or {}).get("commits_by_type", {})
    mkt = ev.get("marketing") or {}
    out = [f"# OpenMates daily meeting briefing — {today.strftime('%A %d %B %Y')}", ""]
    out += _tasks_banner(ev.get("tasks_status") or {})
    out += _reminders_banner(ev.get("reminders") or {})
    out.append(f"**Phase:** {name} ({monday:%d %b}–{sunday:%d %b}); next: {next_name} from "
               f"{next_monday:%a %d %b}.  ")
    source = rem.get("source")
    rem_note = ("live from the Mac" if source == "live" else
                f"Mac offline — copy synced {rem.get('fetched_at', '?')[:16]} UTC" if source else "unavailable")
    out.append(f"**Data:** since {ev['window']['since']} · reminders {rem_note} · generated "
               f"{generated.astimezone(TZ):%H:%M}.")
    usage = (ev.get("claude_usage") or {}).get("weekly")
    if usage:
        left = max(0.0, 100 - usage["used_percent"])
        elapsed = (f", {usage['week_elapsed_percent']}% of the week gone"
                   if "week_elapsed_percent" in usage else "")
        pace = (f" At this week's rate it runs out **{usage['runs_out']}**, before the reset."
                if usage.get("runs_out") else " At this week's rate it lasts until the reset.")
        out += ["", f"**Claude subscription — {left:.0f}% of the weekly limit left** "
                    f"({usage['used_percent']:.0f}% used{elapsed}; resets {usage['resets']}; read at "
                    f"{generated.astimezone(TZ):%H:%M}, the provider can change it later, so trust /usage "
                    f"if it differs).{pace} Plan agent work to fit what is left."]
    else:
        out += ["", "**Claude subscription:** weekly usage unavailable (see data gaps)."]
    out += _alerts_section(ev.get("alerts") or {})
    out += _waiting_section(ev.get("waiting_chats") or {})
    product = ev.get("product") or {}
    if product:
        out += ["", "## About OpenMates", ""]
        if product.get("tagline"):
            out.append(f"**{product['tagline']}**")
            out.append("")
        if product.get("description"):
            out.append(product["description"])
        if product.get("features"):
            out += ["", "Core features:"] + [f"- {feature}" for feature in product["features"]]
    out += ["", MEETING_SCRIPT.replace("{date}", today.isoformat()), "", *_meeting_adjustments(ev.get("goals") or {}), "## Phase rules", "",
            "- **Marketing Week:** marketing work (storyboards, Remotion video editing, screen "
            "recordings, press outreach, marketing copy) plus bug fixes that clearly block "
            "marketing. Everything else goes to the parking lot.",
            "- **Build Week:** features, bug fixes, UX from the parking lot; marketing still "
            "matters but need not fill the week.", ""]
    focus_text = re.sub(r"^(#{1,2}) ", "### ", ev.get("focus_file", "").strip(), flags=re.M)
    out += ["## 1. Focus file (FOCUS.md)", "", focus_text or "_FOCUS.md missing._", ""]
    out += _goals_section(ev.get("goals") or {}, today)
    previous = ev.get("previous_meeting") or {}
    if previous.get("decisions"):
        out += [f"### Decisions from the last meeting ({previous['date']})",
                "Check what was done; carry over what wasn't.", "", "```",
                previous["decisions"].strip(), "```", ""]

    out += ["## 2. Since the last meeting", ""]
    for theme in chats_summary.get("themes", []):
        out.append(f"- **{theme.get('theme')}** ({theme.get('state')}): {theme.get('outcome')}")
    if chats_summary.get("loose_ends"):
        out += ["", "**Loose ends:**"] + [f"- {item}" for item in chats_summary["loose_ends"]]
    done = tasks.get("done_since_last_meeting", [])
    out += ["", f"**Tasks:** {len(done)} done since last meeting"
            + (": " + "; ".join(t["title"] for t in done[:8]) if done else "")
            + f". In progress: {tasks.get('counts', {}).get('in_progress', 0)} "
            f"({', '.join(f'{v} {k}' for k, v in tasks.get('in_progress_by_chat_state', {}).items())}); "
            f"blocked: {tasks.get('counts', {}).get('blocked', 0)}; todo: {tasks.get('counts', {}).get('todo', 0)}."]
    commits = ev.get("git", {}).get("commits_on_dev", [])
    out.append(f"**Code:** {len(commits)} commits on dev since last meeting; last 10 days by type: "
               + ", ".join(f"{k} {v}" for k, v in mix.items())
               + f". Marketing repo: {mkt.get('commits_last_7_days', '?')} commits in 7 days "
               f"(last: {mkt.get('last_commit', 'n/a')}).")
    for item in ev.get("parked_code_at_risk") or []:
        out.append(f"**⚠ Parked code purged {item['purged']}:** unlanded worktree {item['worktree']} "
                   f"(archive {item['archive']}) — recover it or decide to drop it.")
    if last:
        out.append(f"**Nightly tests** ({last.get('date')}): {last.get('passed_count')} passed, "
                   f"{last.get('failed_count')} failed, {last.get('not_run_count')} not run.")
    out.append("")

    out += ["## 3. Reminders", ""]
    if rem:
        today_items = [i for i in rem.get("due_next_days", []) if mac_reminders.due_date(i) == today]
        tomorrow = [i for i in rem.get("due_next_days", [])
                    if mac_reminders.due_date(i) == today + timedelta(days=1)]
        out += ["**Still open from the past 7 days:**"] + (
            [_reminder_line(i) for i in rem.get("overdue_recent", [])] or ["- none"])
        out += ["", "**Due today:**"] + ([_reminder_line(i) for i in today_items] or ["- none"])
        out += ["", "**Due tomorrow:**"] + ([_reminder_line(i) for i in tomorrow] or ["- none"])
        counts = rem.get("counts", {})
        out += ["", f"Next 7 days in total: {sum(counts.get('due_next_days', {}).values())} (full list in "
                f"Appendix A). Without date: {sum(counts.get('undated', {}).values())}. Older overdue "
                f"backlog: {sum(counts.get('overdue_old', {}).values())}."]
    else:
        out.append("_Reminders unavailable — see data gaps._")
    if ev.get("gaps"):
        out += ["", "**Data gaps:** " + " · ".join(ev["gaps"])]

    out += [""] + _cleanup_section(ev.get("cleanup") or {})
    out += ["---", "", "## Appendix A — Reminders, next 7 days", ""]
    by_day: dict[str, list[str]] = {}
    for item in rem.get("due_next_days", []):
        by_day.setdefault(_due_label(item)[:10], []).append(_reminder_line(item))
    for day, lines in by_day.items():
        out += [f"**{day}**"] + lines + [""]
    out += ["**No date:**"] + [_reminder_line(i) for i in rem.get("undated", [])] + [""]

    out += ["## Appendix B — Claude chats since the last meeting", ""]
    summaries = {c.get("session"): c.get("summary") for c in chats_summary.get("chats", [])}
    for chat in ev.get("claude_chats", []):
        text = summaries.get(chat["session"]) or chat.get("title") or (chat.get("user_prompts") or (chat.get("steered_by_other_sessions") or [""]))[0][:120]
        out.append(f"- {chat['last_activity']} — **{chat.get('title') or 'untitled'}**: {text}")
    out += ["", "## Appendix C — Tasks", ""]
    ts = ev.get("tasks_status") or {}
    if ts.get("fetched_at"):
        out += [f"_Tasks as of {ts['fetched_at'][:16]} UTC ({ts.get('source')}"
                f"{'' if ts.get('fresh') else ', NOT up to date'})._", ""]
    for label, key in (("In progress", "in_progress"), ("Blocked", "blocked"), ("Top todo", "todo_top")):
        rows = (tasks.get("open") or {}).get(key, [])
        out.append(f"**{label} ({len(rows)}):**")
        out += [f"- {t.get('id')} {t.get('title')}" + (f" [{t['priority']}]" if t.get("priority") else "")
                for t in rows[:25]]
        if len(rows) > 25:
            out.append(f"- … {len(rows) - 25} more")
        out.append("")
    issues = ev.get("issues") or {}
    out += ["## Appendix D — GitHub and Linear issues", ""]
    out += _issue_section("GitHub issues", issues.get("github"), "")
    out += _issue_section("Linear issues", issues.get("linear"), "state")
    out += ["## Appendix E — Commits on dev", ""]
    out += [f"- {c['when']} {c['subject']}" for c in commits[:80]]
    if len(commits) > 80:
        out.append(f"- … {len(commits) - 80} more")
    return "\n".join(out).rstrip() + "\n"


# ── Delivery ──────────────────────────────────────────────────────────────────

def post_discord(root: Path, text: str) -> dict:
    import discord_webhook

    for key in WEBHOOK_KEYS:
        url = configured_value(root, key)
        if url:
            result = discord_webhook.post_message(webhook_url=url, payload={"content": text[:1990]})
            if not result:
                raise RuntimeError(f"Discord delivery via {key} was not confirmed")
            return {"channel": key, **result}
    raise RuntimeError("no Discord webhook configured")


def freshness(evidence: dict) -> list[str]:
    """What is NOT current in the evidence (empty list = Tasks, reminders and chats all live)."""
    problems = []
    tasks = evidence.get("tasks_status") or {}
    if tasks.get("source") != "live":
        stamp = f"copy from {tasks['fetched_at'][:16]} UTC" if tasks.get("fetched_at") else "no copy"
        problems.append(f"OpenMates Tasks not live ({stamp})")
    rem = evidence.get("reminders") or {}
    if rem.get("source") != "live":
        problems.append(f"Apple Reminders not live (copy synced {str(rem.get('fetched_at', '?'))[:16]} UTC)"
                        if rem else "Apple Reminders unavailable")
    if not evidence.get("claude_chats"):
        problems.append("no Claude chats found on the dev server")
    return problems


def discord_text(today: date, url: str, problems: list[str] | None = None, generated: str = "") -> str:
    name, _, _ = phase(today)
    status = ("✅ Tasks, reminders and Claude chats are live" + (f" as of {generated}" if generated else "")
              if not problems else "⚠️ Not up to date: " + "; ".join(problems))
    return (f"**Daily meeting briefing — {today:%a %d %b}** ({name})\n{status}\n"
            f"Download the PDF and attach it in the daily-meeting chat. Claude: read all of it, "
            f"then run today's voice daily meeting exactly as its \"How to run this meeting\" "
            f"section describes.\n{url}\n(private link, valid 48 h)")


def _collect(root: Path, out: Path, today: date) -> dict:
    if context.main(["collect", "--root", str(root)]):
        raise RuntimeError("context collection failed")
    return json.loads((out / f"{today.isoformat()}-context.json").read_text())


def in_scheduled_slot(local: datetime) -> bool:
    """Cron fires at 09:30 and 10:30 UTC to cover CET and CEST; only the weekday 11:30 Berlin run proceeds."""
    hour, minute = SCHEDULED_AT
    return local.weekday() < 5 and local.hour == hour and local.minute >= minute


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scheduled", action="store_true",
                        help="cron mode: weekdays, only from 11:30 to 11:59 Berlin, once per day")
    parser.add_argument("--force", action="store_true", help="rebuild even if today's briefing was sent")
    parser.add_argument("--no-send", action="store_true", help="build and upload, skip Discord")
    parser.add_argument("--no-upload", action="store_true", help="build only")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    local = now.astimezone(TZ)
    if args.scheduled and not in_scheduled_slot(local):
        return 0
    from agent_state import canonical_root

    root = canonical_root(SCRIPTS.parent)
    out = context.meeting_dir(root)
    today = local.date()
    path = out / f"{today.isoformat()}-briefing.md"
    state_path = out / "briefing-state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    if state.get(today.isoformat(), {}).get("sent") and not args.force:
        print(f"already sent: {state[today.isoformat()]}")
        return 0
    try:
        evidence = _collect(root, out, today)
        problems = freshness(evidence)
        for _ in range(RETRIES if problems else 0):  # Mac or CLI may only be briefly unreachable
            time.sleep(RETRY_WAIT_SECONDS)
            evidence = _collect(root, out, today)
            problems = freshness(evidence)
            if not problems:
                break
        summary = summarize_chats(evidence.get("claude_chats", []), evidence.setdefault("gaps", []))
        summarize_waiting(evidence.get("waiting_chats") or {}, evidence["gaps"])
        path.write_text(render(evidence, summary, today, now))
        path.chmod(0o600)
        result: dict = {"briefing": str(path)}
        if not args.no_upload:
            import daily_meeting_pdf
            import response_media

            pdf = daily_meeting_pdf.render_pdf(path, path.with_suffix(".pdf"))
            result["pdf"] = str(pdf)
            upload = response_media.upload_file(pdf, alt=f"Daily meeting briefing {today}",
                                                expires_in=LINK_SECONDS)
            result["url"] = upload["url"]
            if not args.no_send:
                result["discord"] = post_discord(root, discord_text(today, upload["url"], problems,
                                                              now.astimezone(TZ).strftime("%H:%M")))
                state[today.isoformat()] = {"sent": now.isoformat(), "key": upload.get("key")}
                state_path.write_text(json.dumps(state, indent=1))
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as error:
        if args.scheduled:
            post_discord(root, f"⚠️ Daily meeting briefing for {today} failed: {context.clean(str(error), 300)}")
        raise
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
