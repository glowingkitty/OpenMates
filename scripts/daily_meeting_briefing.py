#!/usr/bin/env python3
"""Build the weekday daily meeting briefing, upload it privately, post the link to Discord.

Pipeline (weekdays 08:30 Europe/Berlin via the dev-server meeting timer):
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
import tempfile
import time
import sys
from zoneinfo import ZoneInfo

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import daily_meeting_context as context  # noqa: E402 - sibling scripts, path set above
import mac_reminders  # noqa: E402
from daily_meeting_accountability import BRIEFING_TIME  # noqa: E402 - sibling scripts, path set above
import daily_meeting_morning  # noqa: E402 - sibling scripts, path set above
import daily_meeting_growth  # noqa: E402
import daily_meeting_marketing  # noqa: E402
import decision_log  # noqa: E402
import daily_meeting_opportunities  # noqa: E402
import daily_meeting_triage as triage  # noqa: E402
import claude_idle_chats  # noqa: E402
import worktree_wip  # noqa: E402

TZ = ZoneInfo("Europe/Berlin")
WEBHOOK_KEYS = ("DISCORD_WEBHOOK_DAILY_MEETING", "DISCORD_WEBHOOK_DEV_NIGHTLY")
LINK_SECONDS = 48 * 3600


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
each one write (no IDs, code, file names or jargon): "title" = a short plain title (<= 6 words), \
"summary" = ONE plain sentence (<= 25 words) on what the chat is about, and "needs" = the one \
question or decision it needs from the founder now, in plain words (<= 20 words). Return JSON only:
{"chats": [{"session": str, "title": str, "summary": str, "needs": str}]}
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
    rows = {row.get("session"): row for row in reply.get("chats") or [] if isinstance(row, dict)}
    for chat in chats:
        row = rows.get(chat["session"]) or {}
        for key, limit in (("summary", 240), ("needs", 200)):
            text = re.sub(r"\s+", " ", str(row.get(key) or "")).strip()
            if text:
                chat[key] = text[:limit]
        short = re.sub(r"\s+", " ", str(row.get("title") or "")).strip()
        if short:
            chat["title"] = short[:80]
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
a solo founder who has ADHD and often has 10–15 agent chats running. \
The meeting must lower overwhelm, not add to it.
- **Mentor stance:** you are the founder's critical mentor, not a note-taker and not a \
cheerleader. Be honest and constructive: say plainly what the evidence in this briefing shows, \
also when it is uncomfortable, and praise only what the evidence supports. No lecture and no \
blame: one clear observation, then one question that lets the founder draw the conclusion. The \
founder decides; you make sure the decision is made with open eyes. Honest does not mean heavy: \
keep it short and move on.
- Speak short, plain sentences. Never read IDs, links or long lists aloud; summarize.
- **Triage rule (the briefing has already sorted every item):** the founder is easily pulled \
away by small issues, so every item (production and dev errors, reported issues, waiting and paused \
chats, Tasks, reminders) carries a proposed label and a one-line reason, read from FOCUS.md \
"Current priorities". **NOW** = serves a current priority or is evidence that real users are \
affected (failed requests, outages, payment or signup problems, user reports not yet addressed) \
or is due today. **LATER** = still useful, with a proposed date. **DROP** = fits no priority, no \
reason to keep: close or archive. **Talk through NOW items only**, in the order of the sections; \
the founder just confirms or changes each proposed label. LATER and DROP items sit in the single \
"Side notes" section at the very end: do not discuss them unless the founder asks; at the end of the \
meeting say only "N side notes, proposals unchanged, confirm?". Confirming executes the proposals \
(LATER chat: it writes done / not done / next step / open decisions into its Task with label `paused` and \
the `PAUSED <today> until <date>` line, then is archived, searchable and reopenable, and the briefing brings \
it back on that date by itself; DROP: archive the chat or close the Task, issue or reminder, never delete, \
and add one `Dropped:` line with the reason). **Daily limits: at most 3 waiting chats and 3 reminders are \
NOW per meeting** (the briefing already enforces it; the rest are LATER with tomorrow as date in the side \
notes). **Decision log:** the section "Dropped before — still want it?" lists new ideas, Tasks and chats \
that resemble something dropped earlier; read each question aloud ("We dropped this on <date> because \
<reason>. Still want it?") and record the answer in the `Dropped:` part (`revive`). Noise (unused \
providers, dev-only errors, cache warnings, test timing) and reported issues that recent commits \
likely fixed are already side notes; never raise them. If the founder changes a label, that line \
goes into the `Triage:` part of the decisions note.
- **Marketing time and the build gate (11:00-17:00 Berlin, every workday):** during it no build work \
(features, improvements, optimisation, research, benchmarking) starts unless it has an OBVIOUS, concrete link to \
marketing, business development or a real end-user flow problem (users affected now, signups or payments broken); \
after 17:00 building is free. The dev connector judges every `start_chat` and every `send_message` (follow-up \
messages that add scope count) with a sceptical neutral model: it passes, queues until 17:00 (sent automatically \
with a note) or puts the request in the idea inbox, and logs the reason. Release steps (pull requests, deploys, merges) and pure ops and safety fixes for live users, \
outages, answers to a chat's question and pause or stop messages always pass; the founder can override explicitly \
(`[override build gate: <reason>]`), and the override is logged. At most 3 non-marketing build chats run at once; \
a fourth waits for a slot. **Voice and meeting assistants: during marketing time, before sending build work through \
the connector, ask once: "That's build work — inbox, queue for 17:00, or does it really help marketing?"** and act \
on the answer (inbox: create the `idea` Task; queue: send as is, the gate queues it; marketing: add the \
override with the founder's one-sentence reason).
- **Meta-work limit:** at most 10-15 minutes of this meeting on workflow or meeting optimisation (this script, \
the briefing, tooling, process). Say "meta-work timer started" when the first such topic begins and "10 minutes \
of meta-work used" at the limit; anything more goes to the weekly goals block (an `idea` Task), not into today.
- **Idea inbox:** new feature or optimisation ideas (from the founder or from you) are not discussed \
or started. Capture each as a Task with the label `idea` and one sentence (a `create` row in the \
decisions note: label `idea`, status backlog). **No chat starts that day for an idea unless it is urgent.** \
The weekly goals block (Block 7 on Mondays) reviews the "Idea inbox" section: promote, park or drop each.
- **Feature priority rule:** features are no longer the primary factor. When a feature comes up, rank \
it by **how likely it is to gain users** (one honest sentence: who would come, and why) against the \
marketing and business-development work. Only the feature with the best case, if it beats a marketing \
action, is NOW; every other feature goes to the idea inbox (an `idea` Task) or the side notes, never \
into a work chat that day. In the weekly goals block rank the features of the idea inbox by that case.
- **Plain-language rule:** never mention an ID (TASK-…, issue numbers, session or commit \
ids), an agent name (e.g. "agent-33bc") or a task bare. Always say what it is in a few plain \
words ("the Projects editing task", "the chat about PDF uploads"). In the decisions note, write \
the plain description first and the ID only in brackets after it.
- Ask **exactly one question at a time**, with your recommendation where one applies, then wait.
- **ADHD-friendly rules:** (a) open by naming the 6 blocks (plus a 2-minute closing "improve the meeting") and the time \
budget, and say "Block N of 6" when you move on, so the founder always knows where we are; (b) never more \
than **3** commitments for the day, each with a concrete **first step that takes 5 minutes** \
and a time of day; (c) a new idea mid-meeting is parked in one line ("parked: …") and the \
meeting returns to the agenda — never debate it now; (d) when the founder rambles, reflect \
back in one sentence and ask the next question; (e) if energy is low (1–2), plan one small \
win first and drop the backlog cleanup; (f) add a stop rule to each task ("if X is not \
working after 45 minutes, park it and tell me"); (g) end with a three-line read-back.
- **Flow (7 blocks):**
  - **Block 1 — Check-in (the founder talks, you listen).** Four questions, one at a time. \
(1) **What you can see, then what else.** Do not open with an open "what have you been up to?". \
First review the commits since the last meeting (Appendix E) and the chats that were started or \
active (Appendix B, with "Since the last meeting") and give a short plain-language summary of \
what you can see was worked on: two to four sentences, grouped by theme, no IDs and no list read \
aloud ("I can see work on the voice calls, the Apple app and the Rust core, and two fixes for \
the press page"). Then ask what else the founder did that is not shown there. To help their \
memory, use the concrete open reminders (section 3: still open from the past 7 days, due today) \
and Tasks (Appendix C: changed since the last meeting, in progress, blocked; yesterday's \
decisions) as prompts, **grouped and summarized, never read one by one** ("Did you get to the \
journalist emails and the two press reminders?", "Anything on the job search?"). At most three \
grouped prompts; skip items the commits already show as done. Then ask the remaining three, one \
at a time and without more briefing facts: (2) How happy are you with that progress, 1–5, and \
why? (3) What do you currently see as the largest priorities? (4) How is your energy today, \
1–5? Then reflect back in two sentences and compare gently with the facts in the briefing \
(commits, Task changes, yesterday's decisions): name any mismatch ("you said X, but I see no \
commits for it — blocked, or moved?"). Ask about yesterday's tasks (done, not done, moved?) \
unless the git commits or the founder's answer to (1) make it obvious — then still ask for a \
one-line confirmation. \
Then the **daily drift check** (every meeting, about one minute, in the mentor stance): compare \
what was actually done since the last meeting — the commits (Appendix E) and the chats that were \
started or active (Appendix B) — with the current milestone ("Goals and milestones"). State the \
rough share that served the milestone ("about a third of the work served the press release; the \
rest went into …"), name the drift plainly and say where the time went instead. Work the founder \
has approved to run on its own in the background (the Rust rewrite and any migration named in the \
agreed adjustments) is named separately and does not count as drift. If the \
previous decisions note has a `Drift:` line, say whether it got better or worse.
  - **Block 2 — Marketing and business development (every meeting, fixed, about 3-4 minutes; both are a \
continuous part of the day, not a "marketing week"; business development means business angels, \
partnerships, press contacts and similar; never skip it, shorten it when energy is low).** \
(a) **Growth numbers** from "Marketing and growth numbers (production)", plain language, rounded, \
never a list read aloud: total users, new signups since the last meeting and in the last 7 days, \
active users, new paying users and credit purchases, each against the previous period. Small numbers \
are noise: say so. If unavailable, say that in one sentence and never guess. Then **exactly ONE honest \
interpretation sentence** (start from the draft in the "Marketing and business development block" section): realistic and \
critical, but helpful and on the founder's side; never naive or hype, never discouraging. Example: \
"0 signups this week: people aren't finding us yet, so outreach beats features right now." No open \
question about the numbers. \
(b) **Win counter** (messages sent, replies, posts, applications): read the one line, ask for the new \
counts since the last meeting and record them in the `Wins:` line. Progress is visible before signups move. \
(c) **Exactly 3 concrete marketing proposals**, about 20 minutes each with a clear done line, from the \
block's menu proposals (the menu is maintained in the private marketing repository, so the list is never \
empty). Ask whether the founder is at home with the camera or on the go and offer the 3 that fit; \
business angels only appear once the videos and the landing page are finished. The founder picks one: \
**it gets the first work slot of the day** in Block 4 and goes into the decisions note as \
`Marketing pick:`. Mention outreach to lapsed paying users whenever it is on the list: asking them why \
they stopped is high-value. \
(d) **1-2 fresh ideas** (marketing or business development) next to the 3 proposals, every day, \
concrete and never one from "already offered"; the founder says take, park or drop; record them in the \
`Marketing ideas:` line. A taken idea becomes one of tomorrow's menu actions or a Task; a parked one an \
`idea` Task. This replaces the old weekly marketing ideas email. \
(e) **Style feedback loop.** Every idea and text you propose follows the "Style rules" in the block. \
When the founder says an idea or text **"doesn't sound like me"** or **"doesn't make sense"**, do not \
defend it: record it at once in the `Style feedback:` part of the decisions note (the text or idea, the \
complaint, and the founder's own words for what is right, asked in one short question), offer a corrected \
version, and move on. A chat then updates the style guide in the marketing repository right away.
  - **Block 3 — Safety net.** If the briefing opens with a ⚠ warning that the OpenMates \
Tasks or the reminders are not up to date, say so first. Then **production first**: \
summarize the NOW items of the "Alerts" section in a few sentences — reported production issues (new or not \
processed yet), then the production errors that repeat most; dev items are side notes unless labelled NOW — and ask whether anything \
needs attention before planning; production reports outrank everything else. Then the \
**chats waiting on the founder** and the **paused chats**: discuss the top 3 waiting chats \
aloud, one at a time (the list is sorted by importance, then wait): say in one sentence what the chat \
needs (the "Needs" line) and ask what to do, with your recommendation. **Every NOW chat in "Chats waiting \
on you" and in "Paused chats" ends the meeting in exactly one outcome (a LATER or DROP chat gets \
its outcome from its confirmed side-note proposal: park until the date, or archive)**: *answer now* (the reply), \
*park* (with a resume date; the chat saves done / not done / next step / open decisions in its Task, \
label `paused`, `PAUSED <today> until <date>` line), *reschedule* (a new date to discuss it again, same \
pause note) or *archive*. "Keep" is not an outcome. When a topic may have other chats, look them up with the dev connector's `search_chats` and say \"there is also chat X about this\" (a semantic related-chats tool is planned). Chats beyond the top 3 are not read aloud: after the \
top 3, give the count of the rest and offer a **default for all of them** ("park all until <date>" or \
"answer in the work block") and say which would be archived. Read the paused chats as one sentence each: \
what is saved, the next step and the resume date; resume those whose date has come. A chat only \
leaves the lists when answered, resumed or archived. If the section "No decision for more than 7 \
days" is shown, take those chats first, before the top 3.
  - **Block 4 — Focus.** Agree **today's single focus** — propose one from the week's goals \
and the founder's stated priorities — then up to **3 tasks**, each with done-criterion, \
first 5-minute step, time slot and stop rule. **The marketing pick from Block 2 always gets the first work slot of the day**, then the task \
that serves the current milestone (the same task if the pick serves it); everything else is planned after \
them. Late afternoon and evening are the founder's time for ideas and experiments: schedule those there. Then one short \
question, every day: **which milestone does today's top task serve?** (see "Goals and milestones" \
in the briefing); if it serves none, say so plainly and ask whether to do it anyway, park it or \
swap it.
  - **Block 5 — Reminders.** Go through overdue and today/tomorrow reminders **in groups** \
(done / move to a date and time you suggest / keep), not one by one. Every moved or new \
reminder needs a **time of day**, never just a date — suggest one. Offer one optional \
midday reminder "Still on <focus>?" as a gentle anchor. Spread moved reminders over several \
days so no day is overloaded.
    **Opportunities (one sentence, at the end of Block 5):** read the two lines of the \
"Opportunities" section (new events and jobs waiting) and any deadline in the next 3 days, then say \
"continue in the Events chat / the Jobs chat". Never go through events or jobs one by one here and \
never run the jobs-profile setup in this meeting: both happen in their own chats.
  - **Block 6 — Parking lot and week goals.** Additions/removals and week-goal changes. \
Read back anything parked during the meeting.
  - **Block 7 on Mondays — Goals and milestones (about 10 minutes; this replaces the backlog \
cleanup).** It also runs on the first later meeting of the week when Monday's was missed: the \
"Goals and milestones" section then says "Weekly goals block is due today". Follow that section: (1) is the current milestone on track — \
use the progress evidence and the drift warnings; (2) is it still the right milestone, and once \
a quarter or when asked, are the mission and the (at most 3) goals still right; (2b) review the "Idea inbox" \
(promote, park or drop each idea; rank features by how likely they are to gain users); (3) split the \
next milestone into 3-7 concrete Tasks (plain title, priority, done-criterion) and agree the \
priority order for the week. One question at a time, with your recommendation. If energy is \
1-2, shrink it to three questions: on track? blocked? is the top priority still right?
  - **Block 7 on days without a due goals block — Backlog cleanup (optional, max 5 minutes, skip if energy is low or the \
meeting already ran 20 minutes).** The meeting also keeps the to-do lists healthy. Take \
**one** batch in groups of 3-5 related items (one question per group, with your \
recommendation): which can be **closed or deleted** (obsolete, done, no longer wanted), \
**merged** into another (duplicates), **delayed** (parked for later) or **kept**. \
Be critical: say when an item looks stale, vague or contradicts the current goals. \
Never decide for the founder; deletion needs a clear "yes".
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
Drift: ~<n>% of the work since the last meeting served <milestone>; the rest: <where it went>; founder's conclusion: <one line>
Focus: <single most important task today>
Marketing pick: <menu item> (done when: …; at HH:MM)
Wins: messages <n>, replies <n>, posts <n>, applications <n>
Marketing finished: <menu items finished since the last meeting, or empty>
Marketing ideas: <1-2 fresh ideas offered today> -> take | park | drop (per idea)
Style feedback:
- <text or idea> -> doesn't sound like me | doesn't make sense: <what is wrong; what the founder would say instead>
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
| edit | <title> | <new title> | <priority> | <status> | <label to add> | YYYY-MM-DD | <description> |
| done | <title> | | | | | | |
| delete | <title> | | | | | | |
Goals:
| Level | Item | Action | Done when | By |
|---|---|---|---|---|
| mission / goal / milestone | <plain wording> | add / edit / done / drop / keep | <measurable result> | YYYY-MM-DD |
Triage (labels the founder CHANGED, one line each; "Side notes: proposals confirmed" if none):
- <item title> -> NOW | LATER YYYY-MM-DD | DROP (<reason in a few words>)
Side notes: proposals confirmed | changed as listed above
Chats (EVERY NOW chat of "Chats waiting on you" and "Paused chats", one line each, exactly one outcome, the label first; side-note chats get theirs from the confirmed proposal):
- <NOW|LATER YYYY-MM-DD|DROP> <chat title> [<Task id>] -> answer now: <reply text> | park until YYYY-MM-DD HH:MM: <done / not done / next step / open decisions> | reschedule to YYYY-MM-DD: <reason> | archive | resume now: <first step>
Dropped (EVERY DROP, one line each; nothing is deleted, only archived or closed; the reason is mandatory):
- <chat | task | idea | reminder | issue> | <what, plain title> | <why> | <Task id or empty>
- revive: <what, plain title> | <why it matters again>
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


def _alerts_section(alerts: dict, tri: "triage.Triage | None" = None) -> list[str]:
    out = ["", "## Alerts — production and dev (reported issues first, errors of the last 24 h)", ""]
    if not alerts:
        return out + ["_Alerts unavailable — see data gaps._"]
    for env, title in (("production", "Production"), ("dev", "Dev server")):  # title.split()[0] names the Side-notes kind
        part = alerts.get(env) or {}
        issues, errors = part.get("issues"), part.get("errors")
        out.append(f"### {title} — reported issues (last 48 h)")
        if issues is None:
            out.append("- unavailable (see data gaps)")
        else:
            rows = [i for i in issues["recent"]
                    if not tri or tri.keep(f"{title.split()[0]} report", f"{i['id']} {i['title']}", tri.issue(env, i))]
            out += [f"- **{i['id']}** ({i['age']}{', admin' if i['admin'] else ''}, "
                    f"{'processed' if i['processed'] else '**not processed yet**'}): {i['title']}"
                    + (tri.tag(tri.issue(env, i)) if tri else "") for i in rows] or ["- none to discuss"]
            older = issues.get("older_unprocessed_in_latest_batch", 0)
            if older:
                out.append(f"- plus {older} older unprocessed reports in the latest batch")
        out += ["", f"### {title} — repeating errors (last 24 h)"]
        if errors is None:
            out.append("- unavailable (see data gaps)")
        else:
            out.append(f"{errors['total']} ERROR/CRITICAL rows, {errors['distinct']} distinct"
                       + (" (query truncated)" if errors.get("truncated") else "") + ".")
            rows = [e for e in errors["top"] if not tri or tri.keep(
                f"{title.split()[0]} error", f"{e['count']}× `{e['service']}` {e['message'][:90]}", tri.error(env, e))]
            out += [f"- {e['count']}× `{e['service']}` {e['where']}: {e['message']}"
                    + (tri.tag(tri.error(env, e)) if tri else "") for e in rows] or ["- none to discuss"]
        out.append("")
    return out


def _cleanup_section(cleanup: dict, tri: "triage.Triage | None" = None) -> list[str]:
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
        check = (tri.task if key == "tasks" else tri.external) if tri else None
        batch = [i for i in part.get("batch", []) if not tri or tri.keep(
            "Task" if key == "tasks" else "Issue", f"{i['title']} ({i['id']})", check(i))]
        out.append(f"**{title}: {part.get('total', 0)} open, {len(batch)} to review today**")
        out += [f"- {line(item)}" + (tri.tag(check(item)) if tri else "") for item in batch] or ["- nothing to review" if not tri else "- nothing to discuss (see Side notes)"]
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


def _chat_lifecycle_line(path: Path | None = None) -> list[str]:
    """Counts from the dev-host chat lifecycle (scripts/claude_idle_chats.py status file)."""
    path = path or claude_idle_chats.state_dir() / "status.json"
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ["_Chat lifecycle counts unavailable: the lifecycle timer has not written its status yet._", ""]
    return [f"_{claude_idle_chats.status_line(summary)} As of {summary['at'][11:16]} UTC._", ""]


def _waited(hours: float) -> str:
    return f"{int(hours // 24)} d {int(hours % 24)} h" if hours >= 24 else f"{hours:g} h"


def _task_text(chat: dict) -> str:
    if chat.get("task_title"):
        return f"Task \"{chat['task_title']}\" ({chat['task']})"
    return f"Task {chat['task']}" if chat.get("task") else "no linked Task"


def _waiting_section(waiting: dict, tri: "triage.Triage | None" = None) -> list[str]:
    """NOW chats waiting on the founder, most important first (never capped); the rest go to the Side notes."""
    all_chats = waiting.get("chats") or []
    verdicts = {c["session"]: tri.chat(c, None) for c in all_chats} if tri else {}
    if tri:
        tri.cap_now([(c["session"], verdicts[c["session"]]) for c in all_chats], "waiting chats")
    chats = [c for c in all_chats if not tri or tri.keep("Chat", f"{c['title']} (waited {_waited(c['idle_hours'])})",
                                                          verdicts[c["session"]])]
    out = ["", f"## Chats waiting on you ({len(chats)}{f' NOW of {len(all_chats)}' if tri else ''}; the assistant spoke last)", "",
           "_Sorted by importance (current priorities in FOCUS.md), then by wait. The meeting discusses the top 3 "
           "aloud; each NOW chat here needs one outcome: answer now, park, reschedule or archive. LATER and DROP "
           "chats are in the Side notes at the very end, nothing is dropped._", "", *_chat_lifecycle_line()]
    if not chats:
        out.append("_None to discuss: every waiting chat is a side note or the founder has the last word._")
    for number, chat in enumerate(chats, 1):
        topic = f" · {chat['priority_topic']}" if chat.get("priority_topic") else ""
        out.append(f"{number}. **{chat['title']}** — waited {_waited(chat['idle_hours'])} · {_task_text(chat)}"
                   f"{topic} · id `{chat['session'][:8]}`" + (tri.tag(verdicts[chat["session"]]) if tri else ""))
        out.append(f"   - Needs: {chat.get('needs') or chat['signal']}")
        if chat.get("summary"):
            out.append(f"   - _{chat['summary']}_")
        elif chat.get("last_reply"):
            out.append(f"   - {chat['signal']}: {chat['last_reply'][:300]}")
    return out + _paused_section(waiting.get("paused") or [], tri) + _no_decision_section(waiting.get("flags") or [])


def _dropped_recheck(ev: dict) -> list[str]:
    """New ideas, Tasks and waiting chats that resemble something dropped earlier (decision log)."""
    logged = ev.get("drop_log") or []
    tasks = ev.get("tasks") or {}
    candidates = [("idea", t.get("title", "")) for t in tasks.get("idea_inbox") or []]
    candidates += [("new Task", t.get("title", "")) for t in tasks.get("changed_since_last_meeting") or [] if t.get("from") == "new"]
    candidates += [("chat", f"{c.get('title', '')} {c.get('needs', '')}") for c in (ev.get("waiting_chats") or {}).get("chats") or []]
    hits = [(kind, text, entry) for kind, text in candidates for entry in decision_log.match(text, logged)]
    if not hits:
        return []
    return ["", f"## Dropped before — still want it? ({len(hits)})", "",
            "_These resemble something dropped earlier (decision log). Ask the founder; \"yes\" revives it, \"no\" keeps it dropped._", "",
            *[f"- {kind} \"{text.strip()[:90]}\": {decision_log.question(entry)}" for kind, text, entry in hits[:10]], ""]


def _paused_section(paused: list[dict], tri: "triage.Triage | None" = None) -> list[str]:
    """Fixed section: every chat or Task paused with the pause convention (docs/contributing/guides/daily-meeting.md)."""
    total, verdicts = len(paused), {r["task"]: tri.paused(r) for r in paused} if tri else {}
    paused = [r for r in paused if not tri or tri.keep("Paused chat", f"{r['title']} ({r['task']})", verdicts[r["task"]])]
    out = ["", f"## Paused chats ({len(paused)}{f' NOW of {total}' if tri else ''})", "",
           "_Every chat or Task labelled `paused`, soonest resume date first; paused chats whose resume date has not "
           "come are LATER side notes. Each NOW one needs an outcome: resume now, park (new resume date), "
           "reschedule or archive._", ""]
    if not paused:
        return out + ["_None to discuss: no chat or Task is paused, or all resume later (see Side notes)._", ""]
    for number, row in enumerate(paused, 1):
        resume = f"{row['resume']} {row['resume_at']}".strip() if row["resume"] else "NO RESUME DATE"
        reason = f" ({row['reason']})" if row["reason"] else ""
        since = f", paused since {row['since']}" if row["since"] else ""
        out.append(f"{number}. **{row['title']}** ({row['task']}){reason} — resume after **{resume}**{since}")
        for name in ("Done", "Not done", "Next step", "Open decisions"):
            out.append(f"   - {name}: {row.get(name) or '**missing**: the chat must save it in its Task'}")
        if row.get("flag"):
            out.append(f"   - ⚠ {row['flag']}" + (tri.tag(verdicts[row["task"]]) if tri else ""))
    return out + [""]


def _no_decision_section(flags: list[str]) -> list[str]:
    if not flags:
        return ["", "_No-decision check: no waiting or paused chat is older than 7 days without a decision._", ""]
    return ["", f"## ⚠ No decision for more than 7 days ({len(flags)})", "",
            "_Nothing leaves these lists silently: decide each one today (answer, park, reschedule or archive)._", "",
            *[f"- {flag}" for flag in flags], ""]


def _goals_section(goals: dict, today: date) -> list[str]:
    """Mission, goals and milestones (GOALS.md) with progress evidence; the Monday block runs on this."""
    due = goals.get("block_due", today.weekday() == 0) if goals else False
    out = ["", "## Goals and milestones" + (" — **run the weekly goals block (Block 7) today**" if due else ""), ""]
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
    rem = ev.get("reminders") or {}
    tasks = ev.get("tasks") or {}
    nightly = ev.get("nightly") or {}
    last = nightly.get("last_nightly_run_with_tests") or {}
    mix = (ev.get("work_mix") or {}).get("commits_by_type", {})
    mkt = ev.get("marketing") or {}
    out = [f"# OpenMates daily meeting briefing — {today.strftime('%A %d %B %Y')}", ""]
    out += _tasks_banner(ev.get("tasks_status") or {})
    out += _reminders_banner(ev.get("reminders") or {})
    source = rem.get("source")
    rem_note = ("live from the Mac" if source == "live" else
                f"Mac offline — copy synced {rem.get('fetched_at', '?')[:16]} UTC" if source else "unavailable")
    out += ["**Timers:** meta-work (workflow or meeting optimisation) limit 10-15 minutes today, the rest goes to "
            "the weekly goals block. Build gate: marketing time 11:00-17:00 Berlin; build work waits until 17:00 "
            "unless it obviously serves marketing, business development or broken user flows.", ""]
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
    tri = triage.Triage(ev.get("focus_file", ""), ev.get("git", {}).get("commits_on_dev", []), today)
    out += _alerts_section(ev.get("alerts") or {}, tri)
    out += daily_meeting_morning.render(ev.get("morning_accountability") or {})
    out += daily_meeting_growth.render(ev.get("growth"))
    out += daily_meeting_marketing.render(ev.get("marketing_block"))
    out += _waiting_section(ev.get("waiting_chats") or {}, tri)
    out += _dropped_recheck(ev)
    out += ["", "## Unfinished work in worktrees (dev→main readiness)", "", *worktree_wip.briefing_lines()]
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
    out += ["", MEETING_SCRIPT.replace("{date}", today.isoformat()), "", *_meeting_adjustments(ev.get("goals") or {})]
    focus_text = re.sub(r"^(#{1,2}) ", "### ", ev.get("focus_file", "").strip(), flags=re.M)
    out += [
        "## Product video recording gate", "",
        "Ask Marco to record a flow only after reviewing a clean, sound-on end-to-end video of that flow "
        "on production. Sign up a clearly marked throwaway production account with an AI test user gift "
        "card code, exclude it from stats and delete it after the run, including failed runs. Check for "
        "broken behavior, slow responses, UI glitches and wrong embeds. Assign each failing flow to "
        "a Task owner for a fix and rerun.", "",
    ]
    out += ["## 1. Focus file (FOCUS.md)", "", focus_text or "_FOCUS.md missing._", ""]
    out += _goals_section(ev.get("goals") or {}, today)
    ideas = tasks.get("idea_inbox") or []
    out += ["## Idea inbox (Tasks labelled `idea`; reviewed in the weekly goals block, no chat starts for them)", ""]
    out += [f"- {t.get('title')} ({t.get('id')})" for t in ideas] or ["- empty"]
    out.append("")
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
        overdue = rem.get("overdue_recent", [])
        verdicts = {id(i): tri.reminder(i, mac_reminders.due_date(i)) for i in overdue + today_items + tomorrow}
        tri.cap_now([(id(i), verdicts[id(i)]) for i in today_items + overdue + tomorrow], "reminders")

        def now(items):
            return [_reminder_line(i) + tri.tag(verdicts[id(i)]) for i in items if tri.keep(
                "Reminder", f"{i['title']} ({_due_label(i)})", verdicts[id(i)])] or ["- none to discuss"]
        out += ["**Still open from the past 7 days (NOW only):**"] + now(overdue)
        out += ["", "**Due today (NOW only):**"] + now(today_items)
        out += ["", "**Due tomorrow (NOW only):**"] + now(tomorrow)
        counts = rem.get("counts", {})
        out += ["", f"Next 7 days in total: {sum(counts.get('due_next_days', {}).values())} (full list in "
                f"Appendix A). Without date: {sum(counts.get('undated', {}).values())}. Older overdue "
                f"backlog: {sum(counts.get('overdue_old', {}).values())}."]
    else:
        out.append("_Reminders unavailable — see data gaps._")
    if ev.get("gaps"):
        out += ["", "**Data gaps:** " + " · ".join(ev["gaps"])]

    out += daily_meeting_opportunities.render(ev.get("opportunities"))
    out += [""] + _cleanup_section(ev.get("cleanup") or {}, tri)
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
    changed = tasks.get("changed_since_last_meeting") or []
    out.append(f"**Changed since the last meeting, still open ({len(changed)}):**")
    out += [f"- {t.get('id')} {t.get('title')} ({t.get('from')} → {t.get('to')})" for t in changed[:25]]
    if len(changed) > 25:
        out.append(f"- … {len(changed) - 25} more")
    out.append("")
    for label, key in (("In progress", "in_progress"), ("Blocked", "blocked"), ("Top todo", "todo_top")):
        rows = [t for t in (tasks.get("open") or {}).get(key, []) if tri.keep("Task", f"{t.get('title')} ({t.get('id')})", tri.task(t))]
        out.append(f"**{label} (NOW {len(rows)}):**")
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
    out += triage.side_note_lines(tri.notes, tri.gap)
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
    status = ("✅ Tasks, reminders and Claude chats are live" + (f" as of {generated}" if generated else "")
              if not problems else "⚠️ Not up to date: " + "; ".join(problems))
    return (f"**Daily meeting briefing — {today:%a %d %b}**\n{status}\n"
            f"Download the PDF and attach it in the daily-meeting chat. Claude: read all of it, "
            f"then run today's voice daily meeting exactly as its \"How to run this meeting\" "
            f"section describes.\n{url}\n(private link, valid 48 h)")


def _collect(root: Path, out: Path, today: date) -> dict:
    if context.main(["collect", "--root", str(root)]):
        raise RuntimeError("context collection failed")
    return json.loads((out / f"{today.isoformat()}-context.json").read_text())


def in_scheduled_slot(local: datetime) -> bool:
    """Allow a weekday morning timer run to start within the 08:30 slot."""
    return local.weekday() < 5 and local.hour == BRIEFING_TIME.hour and local.minute >= BRIEFING_TIME.minute


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scheduled", action="store_true",
                        help="weekday timer mode, from 08:30 to 08:59 Berlin, once per day")
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
        try:  # personal searches must never stop the briefing; a failure shows as a data gap
            evidence["opportunities"] = daily_meeting_opportunities.collect(today, evidence["gaps"])
        except (OSError, ValueError) as error:
            evidence["gaps"].append(f"opportunities unavailable ({context.clean(str(error), 200)})")
        evidence["morning_accountability"] = daily_meeting_morning.collect(root, out, evidence, now)
        # Connector refresh and the timer can overlap. Readers see a complete private file.
        text = render(evidence, summary, today, now)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=out, delete=False) as handle:
            handle.write(text)
        Path(handle.name).replace(path)
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
