#!/usr/bin/env python3
"""Build the weekday daily meeting briefing, upload it privately, post the link to Discord.

Pipeline (weekdays 10:00 Europe/Berlin via the dev-server crontab):
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


def summarize_chats(chats: list[dict], gaps: list[str]) -> dict:
    if not chats:
        return {}
    helper = (SCRIPTS / "_gemini_flash_container.py").read_text()
    payload = json.dumps({"prompt": SUMMARY_PROMPT + json.dumps(chats, ensure_ascii=False), "json": True})
    try:
        run = subprocess.run(["docker", "exec", "-i", "api", "python", "-c", helper], input=payload,
                             capture_output=True, text=True, timeout=400)
        if run.returncode:
            raise RuntimeError(context.clean(run.stderr, 300))
        return json.loads(run.stdout)
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as error:
        gaps.append(f"Gemini chat summary failed ({context.clean(str(error), 200)}); appendix lists chat titles only")
        return {}


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


MEETING_SCRIPT = """\
## How to run this meeting (instructions for Claude)
You are running a ~15-minute **voice** daily meeting with the founder of OpenMates, \
a solo founder who often has 10–15 agent chats running and keeps getting \
pulled into new features and bugs while marketing (videos, press) slips.
- Speak short, plain sentences. Never read IDs, links or long lists aloud; summarize.
- Ask **at most 3 questions at a time**, each with your recommendation, then wait.
- Respect the phase rules below. In a Marketing Week, gently push back on features, \
refactors, UX polish and bug fixes that do not block marketing; offer the parking lot.
- Flow: (1) one-sentence recap of yesterday and today's phase; (2) agree **today's \
single focus** — propose one from the week's goals; (3) go through overdue and \
today/tomorrow reminders **in groups** (done / move to a date and time you suggest / \
keep), not one by one. Every moved or new reminder needs a **time of day**, never \
just a date — suggest one; (4) agree **up to 3 tasks**; (5) parking-lot additions/removals and \
week-goal changes; (6) read back and output the decisions note.
- Ask clarifying questions in these directions: what blocks this week's goals; \
deadlines at risk; loose ends from yesterday's chats (finish, park or drop?); \
whether too many chats are running (and whether the remaining weekly Claude usage \
covers the planned agent work — if it runs out before the reset, cut agent work first); \
parked code that is about to be purged; reminders whose date no longer makes sense.
- Finish with the decisions note **exactly in this format** in a code block, so it \
can be pasted back to the development server:

```
DECISIONS {date}
Focus: <single most important task today>
Tasks:
1. <task> (done when: …)
Reminders:
- "<exact reminder title>" -> done | move YYYY-MM-DD HH:MM | keep
New reminders:
- "<title>" (OpenMates|Personal Tasks, YYYY-MM-DD HH:MM)
Parking lot:
+ <added item> | - <removed item>
Week goals: <unchanged | new goals>
Notes: <anything else>
```
"""


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
                    f"({usage['used_percent']:.0f}% used{elapsed}; resets {usage['resets']}).{pace} "
                    "Plan agent work to fit what is left."]
    else:
        out += ["", "**Claude subscription:** weekly usage unavailable (see data gaps)."]
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
    out += ["", MEETING_SCRIPT.replace("{date}", today.isoformat()), "## Phase rules", "",
            "- **Marketing Week:** marketing work (storyboards, Remotion video editing, screen "
            "recordings, press outreach, marketing copy) plus bug fixes that clearly block "
            "marketing. Everything else goes to the parking lot.",
            "- **Build Week:** features, bug fixes, UX from the parking lot; marketing still "
            "matters but need not fill the week.", ""]
    focus_text = re.sub(r"^(#{1,2}) ", "### ", ev.get("focus_file", "").strip(), flags=re.M)
    out += ["## 1. Focus file (FOCUS.md)", "", focus_text or "_FOCUS.md missing._", ""]
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

    out += ["", "---", "", "## Appendix A — Reminders, next 7 days", ""]
    by_day: dict[str, list[str]] = {}
    for item in rem.get("due_next_days", []):
        by_day.setdefault(_due_label(item)[:10], []).append(_reminder_line(item))
    for day, lines in by_day.items():
        out += [f"**{day}**"] + lines + [""]
    out += ["**No date:**"] + [_reminder_line(i) for i in rem.get("undated", [])] + [""]

    out += ["## Appendix B — Claude chats since the last meeting", ""]
    summaries = {c.get("session"): c.get("summary") for c in chats_summary.get("chats", [])}
    for chat in ev.get("claude_chats", []):
        text = summaries.get(chat["session"]) or chat.get("title") or (chat.get("user_prompts") or [""])[0][:120]
        out.append(f"- {chat['last_activity']} — **{chat.get('title') or 'untitled'}**: {text}")
    out += ["", "## Appendix C — Tasks", ""]
    for label, key in (("In progress", "in_progress"), ("Blocked", "blocked"), ("Top todo", "todo_top")):
        rows = (tasks.get("open") or {}).get(key, [])
        out.append(f"**{label} ({len(rows)}):**")
        out += [f"- {t.get('id')} {t.get('title')}" + (f" [{t['priority']}]" if t.get("priority") else "")
                for t in rows[:25]]
        if len(rows) > 25:
            out.append(f"- … {len(rows) - 25} more")
        out.append("")
    out += ["## Appendix D — Commits on dev", ""]
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


def discord_text(today: date, url: str) -> str:
    name, _, _ = phase(today)
    return (f"**Daily meeting briefing — {today:%a %d %b}** ({name})\n"
            f"Download the PDF and attach it in the daily-meeting chat. Claude: read all of it, "
            f"then run today's voice daily meeting exactly as its \"How to run this meeting\" "
            f"section describes.\n{url}\n(private link, valid 48 h)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scheduled", action="store_true",
                        help="cron mode: weekdays, only in the 10:xx Berlin hour, once per day")
    parser.add_argument("--force", action="store_true", help="rebuild even if today's briefing was sent")
    parser.add_argument("--no-send", action="store_true", help="build and upload, skip Discord")
    parser.add_argument("--no-upload", action="store_true", help="build only")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    local = now.astimezone(TZ)
    if args.scheduled and (local.weekday() >= 5 or local.hour != 10):
        return 0  # cron fires at 08 and 09 UTC to cover CET/CEST; only 10:xx Berlin proceeds
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
        if context.main(["collect", "--root", str(root)]):
            raise RuntimeError("context collection failed")
        evidence = json.loads((out / f"{today.isoformat()}-context.json").read_text())
        summary = summarize_chats(evidence.get("claude_chats", []), evidence.setdefault("gaps", []))
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
                result["discord"] = post_discord(root, discord_text(today, upload["url"]))
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
