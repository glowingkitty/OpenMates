# Daily meeting

Hybrid: the dev server prepares a briefing, the founder holds the meeting by
voice in the Claude app, and the decisions are written back on the dev server.
[`FOCUS.md`](../../../FOCUS.md) records the week goals, today's focus and the
parking lot as information for the meeting; it does not restrict which work
chats may take on.

## Flow
1. **Every 30 minutes** `scripts/mac_reminders.py sync` copies the open
   OpenMates and Personal Tasks reminders from the Mac (Tailscale) to
   `~/.local/state/openmates/reminders-cache.json` (private). The Mac is often
   offline in the morning, so the briefing uses the latest copy.
2. **Weekdays 11:30 Europe/Berlin** `scripts/daily_meeting_briefing.py --scheduled` (the crontab fires at
   09:30 and 10:30 UTC to cover winter and summer time; only the 11:30 Berlin run proceeds):
   - `scripts/daily_meeting_context.py collect` gathers Claude Code chats since
     the last meeting, commits (incl. `openmates-marketing`), OpenMates Tasks
     changes, nightly tests, open GitHub issues (`gh`) and Linear issues
     (`scripts/daily_meeting_issues.py`; needs `LINEAR_API_KEY` in the cron
     environment, else reported as a data gap), FOCUS.md and the reminders (live,
     else the copy);
   - Gemini Flash (`scripts/_gemini_flash_container.py`, run inside the `api`
     container with the Vault key) summarizes the chats — Claude Code stores only
     titles, no summaries;
   - renders `logs/daily-meetings/YYYY-MM-DD-briefing.md` (private): meeting
     instructions for Claude, FOCUS.md, progress, reminders, then
     appendices with all reminders/chats/Tasks/commits;
   - renders it as a PDF (`scripts/daily_meeting_pdf.py`; the Claude app cannot
     fetch the long Markdown from a link) and uploads that with
     `scripts/response_media.py` (private S3 link, 48 h), then, before posting, checks that Tasks, reminders and Claude chats are live (up to 2 retries, 60 s apart); the Discord message says either "live as of HH:MM" or exactly what is not up to date, and the PDF opens with a warning banner for stale Tasks or reminders. Then it posts the link to Discord (`DISCORD_WEBHOOK_DAILY_MEETING`, else
     `DISCORD_WEBHOOK_DEV_NIGHTLY`).
3. **Meeting:** download the PDF from the Discord link, attach it in the
   daily-meeting chat in the Claude app and start a voice call. Claude asks
   exactly one question at a time, with a recommendation, then waits. The meeting
   has 7 blocks and is built for ADHD: Block 1 is a check-in. Claude first sums up
   in plain words what the commits and chats since the last meeting show
   (Appendix E and B), then asks what else the founder did that is not shown
   there, with the open reminders and Tasks (overdue and recent) as grouped
   memory prompts ("Did you get to X?"), never read one by one. Then: how happy
   with the progress 1-5, largest priorities, energy today 1-5. Block 1 ends
   with the daily drift check (below), then
   safety net (production alerts, chats waiting),
   focus (max 3 tasks, each with a 5-minute first step, time slot and stop rule; the
   task that serves the current milestone gets the first work slot of the day),
   reminders in groups with times, parking lot, and an optional 5-minute backlog
   cleanup that is skipped when energy is low. Ideas that come up mid-meeting are
   parked in one line, and it ends with a three-line read-back. The meeting ends
   with a `DECISIONS <date>` note whose first line is `Check-in:`.
4. **Write-back:** paste the note into a Claude Code chat on the dev server; the
   `daily-meeting-and-orchestration` skill updates FOCUS.md, Reminders and
   OpenMates Tasks and can start the approved work chats.

## Apple Reminders
`scripts/mac_reminders.py` (`sync`, `overview`, `list`, `create`, `complete`,
`set-due`, `update`, `move`, `batch`) → `apple_remote.py reminders-op` over
Tailscale SSH → fixed EventKit helper `scripts/_apple_reminders_remote.py` on the
Mac. Writes only to OpenMates and Personal Tasks; delete only on an explicit "delete" decision (irreversible). EventKit,
not AppleScript: AppleScript lookups scan every reminder and time out. The
remote command guard (`apple_no_delete_guard.py`) admits only this helper.

**Due times rule:** a reminder is never due on a bare day. Every due carries a
time (`YYYY-MM-DD HH:MM`, Berlin); `mac_reminders.py` and the Mac helper refuse
date-only values. Setting a due also sets the start date and replaces the alarms
with one alarm at that time, so Reminders and Calendar show the same moment.

## FOCUS.md is private
`FOCUS.md` holds the founder's current focus and parking lot. It lives only in the
canonical checkout, is listed in `.gitignore` and must never be committed: this
repository is public. Personal items (health, appointments, finances) never belong
in it or anywhere else in the repository.

## Backlog cleanup
The meeting also keeps the to-do lists healthy. Section 4 of the briefing lists a
batch of the oldest open OpenMates Tasks (todo, backlog, blocked), GitHub issues and
Linear issues (10 per tracker; items kept in the last 30 days are skipped, see
`logs/daily-meetings/cleanup-reviewed.json`). Claude takes them in groups of 3-5,
asks one question per group with a recommendation (close or delete, merge, delay,
keep) and records the answers in the `Cleanup:` lines of the decisions note. The
`daily-meeting-and-orchestration` skill applies them: Tasks via `openmates tasks`,
GitHub via `gh issue close` (as not planned, with a comment), Linear via the API.

## Alerts (production first)

The usage line states when it was read: the provider can lower or reset the figure after the briefing is
built, so `/usage` wins if it differs. The briefing opens with an "Alerts" section, right after the usage line: reported issues of the
last 48 h from production, then dev (with processed / not processed yet), and the most repeating
ERROR/CRITICAL log messages of the last 24 h per server (ids and numbers masked so repeats group).
Data comes from `backend/scripts/debug.py` via `scripts/daily_meeting_health.py`. Only short id,
title, age and status are kept; contact emails and share links (which carry chat keys) are never
included. The meeting discusses production reports before planning the day's focus.

## Marketing and growth numbers (production only)

After the Alerts, the briefing shows aggregate production counts: total users, new signups since the
last meeting and in the last 7 days (with signups started but not finished), daily and weekly active
users, new paying users and credit purchases, each against the equally long period before. Dev data is
never used. `scripts/daily_meeting_growth.py` calls the read-only admin endpoint
`POST /v1/admin/debug/growth-metrics` (`backend/core/api/app/routes/admin_growth_metrics.py`) through
`backend/scripts/growth_metrics_query.py` in the api container (admin API key from Vault). The endpoint
writes nothing and returns counts only. Left out completely: admins and the server's configured test
accounts (server side), plus every email found in the dev server's `.env` and in the private
`logs/daily-meetings/growth-excluded-emails.txt` (one email per line; add the founder's other accounts
there). Only SHA-256 hashes of those emails are sent. Active users come from the last session check,
so each run stores an aggregate snapshot in `logs/daily-meetings/growth-history.json` and compares with
the previous one. Claude reports the numbers in about one minute in Block 2 (marketing), right after the check-in and its drift check and relates
them to the current milestone.

## Privacy of meeting data
`logs/` is gitignored: briefings, contexts, decision notes and the reminder caches never enter the repository. Before writing reminders, always sync from the Mac first and work from that live list.

## Freshness of Tasks and Reminders
Both lists are kept as private, timestamped copies under `~/.local/state/openmates/`
(`reminders-cache.json` every 30 min, `tasks-cache.json` hourly via
`scripts/daily_meeting_tasks_cache.py sync`). The briefing refreshes both right before it
builds. If the live read fails it uses the copy and says how old it is: a warning at the very
top ("OpenMates Tasks are NOT up to date" / "UNAVAILABLE") that the meeting must read out first,
plus a data-gap line. Cron has a minimal PATH, so the Tasks script finds the `openmates` CLI in
`~/.npm-global/bin` itself and the crontab lines set that PATH. `mac_reminders.py` sets a task
identity for the Apple no-delete guard, which otherwise refused every cron run.

## Marketing and business development (Block 2, every meeting)
Marketing is a fixed, continuous part of every meeting, not a "marketing week". Block 2 follows the
check-in and precedes the safety net (`scripts/daily_meeting_marketing.py`; the growth numbers moved
here from Block 1). It has five parts:
1. **Growth numbers from production plus ONE honest sentence** (realistic and critical, on the founder's
   side, never hype or discouraging). The briefing prints a deterministic draft, for example
   "0 signups in 7 days: people aren't finding us yet, so outreach beats features right now."
2. **Win counter** (messages sent, replies, posts, applications): the founder reports the new counts, the
   decisions note records them in the `Wins:` line, the briefing sums last meeting, this week and the
   last 14 days, so progress is visible before signups move.
3. **Exactly 3 proposals of about 20 minutes** with a done line, for the founder's situation (at home with
   the camera, or on the go): the least recently picked items of the menu whose prerequisites are
   finished. The pick gets the first work slot (`Marketing pick:`). Business development (business
   angels, partnerships, press contacts, job search) is part of the menu; business angels appear only
   after the videos and the landing page are finished (`Marketing finished:`).
4. **1-2 fresh ideas** per day (marketing or business development), taken, parked or dropped
   (`Marketing ideas:`); the briefing lists the ideas of the last 14 days so none repeats. This replaces
   the weekly marketing ideas email (the Mon/Thu `recommendations` job of the marketing automation is
   disabled).
5. **Style feedback loop:** every idea and text follows the style rules printed in the block. When the
   founder says something "doesn't sound like me" or "doesn't make sense", the meeting records it in the
   `Style feedback:` part of the decisions note and a chat adds the rule to the style guide right away.

The menu and the style guides live in the **private marketing repository**, not in this repo:
`daily-meeting/marketing-menu.md` (menu), `marketing-style.md` section "Feedback rules from the daily
meeting" (voice rules; the entry point to the communication strategy) and `press/press-style.md` (press
text, "Words and tone"). The briefing reads them at generation time; without the menu file it falls back to a
neutral built-in menu and says so (a gap, never an empty list).

**Idea inbox and feature priority.** New feature or optimisation ideas are captured as a Task labelled `idea`
with one sentence; no chat starts for them that day unless urgent. Late afternoon and evening are the
founder's time for ideas and experiments. The weekly goals block reviews the inbox. Features are no longer
the primary factor: when one comes up it is ranked by how likely it is to gain users; only the best case
that beats a marketing action is NOW, the rest go to the idea inbox or the side notes (triage marks
feature-like Tasks LATER with that reason).

## Daily limits, LATER, DROP and the decision log
- **Limits:** at most **3 waiting chats and 3 reminders** are NOW per meeting (importance order; the briefing
  enforces it in `Triage.cap_now`). The rest become LATER (tomorrow) in the side notes.
- **LATER (chat):** the chat writes done / not done / next step / open decisions into its Task with the
  `paused` label and `PAUSED <today> until <date>` (the pause convention above) and is archived (searchable,
  reopenable). On the resume date the "Paused chats" section lists it as NOW by itself.
- **DROP:** archive the chat or close the Task, issue or reminder; nothing is deleted. One `Dropped:` line per
  drop in the decisions note (`- <chat|task|idea|reminder|issue> | <what> | <why> | <Task id>`); the reason is
  required. `scripts/daily_meeting_apply.py apply` appends it to the **decision log**
  (`logs/decision-log/dropped.jsonl` of the canonical checkout, private; `scripts/decision_log.py add|check|list`):
  what, date, why, by whom.
- **Re-check:** the section "Dropped before — still want it?" lists new ideas, new Tasks and waiting chats whose
  words match a logged drop ("We dropped this on <date> because <reason>. Still want it?"). The answer goes into
  the note (`revive: <what> | <why>`). The same `decision_log.py check "<text>"` is meant for the dev connector's
  `start_chat` path (separate Task).

## Triage: NOW, LATER, DROP
The founder is easily pulled away by small issues, so the briefing pre-sorts **every** item (production
and dev errors, reported issues, waiting and paused chats, Tasks, reminders, GitHub/Linear cleanup
items) and proposes a label with a one-line reason; the founder only confirms or changes it
(`scripts/daily_meeting_triage.py`).

| Label | Rule | Where it shows |
|---|---|---|
| NOW | serves a current priority, or is evidence that real users are affected (production errors, unprocessed production reports, failed requests, payment or signup problems), or is a reminder due today | in its section, tagged `[NOW: reason]`; the only items the meeting discusses |
| LATER | still useful, otherwise fits no priority; gets a proposed date (7 days, off the weekend; a paused chat's resume date; a reminder's own date) | "Side notes" at the very end |
| DROP | fits no priority and has no reason to keep: noise, finished chat with no open question, backlog Task with no priority, issue untouched 60+ days | "Side notes": propose close or archive |

Clear noise (the `Noise:` words: unused providers like Baseten, cache warnings, test timing), dev-only
errors and dev reports without a priority are side notes automatically. A production report whose
words overlap two or more with a recent `fix` commit is marked "likely fixed by ..." (LATER, next day)
instead of being raised. **The priorities are read from `FOCUS.md` section `## Current priorities`**
(`- <priority>: word, word`, then a `Noise:` line); edit that section when the priorities change.
Without the section the built-in defaults are used and a "Triage gap" line in Side notes says so.
Side notes are not discussed unless asked; at the end the meeting asks once "N side notes, proposals
unchanged, confirm?". Confirming executes the proposals (LATER chat: park until the date; DROP chat:
archive; DROP Task or issue: close). The decisions note records the labels the founder changed under
`Triage:` and the label in front of every `Chats:` line. Nothing is hidden: LATER and DROP chats,
Tasks and reports remain listed in the Side notes, and the no-decision check still covers them.

## Chats waiting on you
After the alerts the briefing lists **every** dev-server Claude Code chat whose last real message
came from the assistant (idle at least 2 h, last 30 days; no cap and no age cut-off, also for
finished-work replies). A chat leaves the list only when it is answered, archived, its Task is Done,
or its Task is paused (it then shows under "Paused chats"). Each entry has a short title, how long it
has waited, its linked Task, the one question or decision it needs in plain words ("Needs", Gemini
Flash; if that call fails the last question of the reply is used and a data gap says so) and an
italic one-line summary. The list is sorted by importance against the current priorities (marketing,
agentic coding, Projects, safety; `PRIORITY_TOPICS` in `scripts/daily_meeting_paused.py`, kept in
sync with FOCUS.md), then by Task priority, then oldest wait first. The meeting discusses the top 3
aloud; the full list is always in the briefing. Data: `scripts/daily_meeting_waiting.py`.

## Paused chats
A fixed briefing section lists every not-done Task labelled `paused`, soonest resume date first,
with its saved state: done, not done, next step, open decisions, resume date and reason.

**Pause convention.** A chat that stops before its work is finished (usage limit, waiting for a
date, parked in the meeting) runs, before it stops, one `openmates tasks edit <task> --add-label paused
--description "<block>"` call with this block (the Task is created first if the chat has none):

```
PAUSED 2026-11-14 until 2026-11-20 11:00 — weekly usage used up
Done: <what is finished and deployed>
Not done: <what remains>
Next step: <the exact first action when resuming>
Open decisions: <questions for the founder, or "none">
```
`PAUSED <since> until <resume date> [HH:MM] — <reason>` is the first line; the four fields follow.
The block is the saved state: the resuming chat needs nothing else. To resume, the chat (or the
meeting) removes the label (`--remove-label paused`) and sets the Task status. Parser and checks:
`scripts/daily_meeting_paused.py`.

## One outcome per chat, nothing drops out silently
Every chat in "Chats waiting on you" and in "Paused chats" ends the meeting in exactly one outcome,
recorded one line per chat in the `Chats:` section of the decisions note:

| Outcome | Note line | What the dev server does |
|---|---|---|
| answer now | `<chat> [Task] -> answer now: <reply>` | sends the reply to the chat (`send_message`) |
| park | `-> park until YYYY-MM-DD HH:MM: <done / not done / next step / open decisions>` | writes the pause block and `paused` label into the Task |
| reschedule | `-> reschedule to YYYY-MM-DD: <reason>` | same pause block, resume date = the new date |
| archive | `-> archive` | archives the chat (`archive_session`) and records it in `waiting-reviewed.json` |
| resume now | `-> resume now: <first step>` | removes the `paused` label, wakes the chat with the next step |

"Keep" is not an outcome. **No-decision check:** the briefing flags (section "No decision for more
than 7 days", and the first thing the meeting handles) every waiting chat that has waited more than
7 days, and every paused chat whose resume date has passed, has no resume date, or has incomplete
saved state after 7 days of pause.

## Plain-language rule
IDs, agent names and tasks are never mentioned bare in the briefing, the meeting or the decisions
note: each comes with a few plain words saying what it is, and the ID only in brackets after it.
The briefing shows chats by title (else the last prompt or reply in words, never "untitled" or a
slug) with their Task title, and Tasks, GitHub and Linear issues as "title (id)". The meeting
script (`MEETING_SCRIPT`) tells Claude to speak and write the same way.

## Mentor stance and the daily drift check
Claude runs the meeting as a critical mentor, not as a note-taker: honest and constructive, it says
plainly what the briefing's evidence shows and praises only what the evidence supports, without a
lecture. Every meeting, at the end of Block 1, it compares the commits and the chats since the last
meeting with the current milestone, states the rough share of the work that served it, names the
drift and where the time went, and asks exactly one question that lets the founder draw the
conclusion. Background work the founder approved to run on its own (the Rust rewrite, migrations named
in the agreed adjustments) is named separately and does not count as drift. The
result is the note's `Drift:` line, so the next meeting can say whether it got better or worse. Right
after the drift share, Claude gives the production growth numbers in about one minute, with their trend,
related to the milestone (small numbers are named as noise).

## Structured decisions note (reminder and Task tables)
The note's `Reminder changes:` and `Task changes:` sections are tables, one row per change, with the exact
reminder title, a time in every due and the plain Task title. A Task's `Due` cell (`YYYY-MM-DD`, or `YYYY-MM-DD HH:MM` in Berlin time)
is applied on `create` and on `edit` rows and checked on the live Task afterwards. `scripts/daily_meeting_apply.py plan|apply
--note <file>` reads the live reminders (Mac) and live Tasks, resolves every row (exact title or a unique
prefix), applies the unambiguous rows and then re-reads both lists. It prints one result per row (OK /
FAILED / NEEDS ATTENTION) and exits 1 if any row is not applied and verified, so a change can no longer be
skipped silently. Mac offline: the reminder ops are saved to `<date>-pending-reminders.json`. Goals, Meeting,
Chats, Cleanup and Parking lot lines are listed as manual steps for the skill.

## Goals and milestones (Mondays)
`GOALS.md` (private, gitignored, canonical checkout) holds the mission, at most 3 goals, milestones (each with
a done-when and a date) and a `Last weekly review:` line. Tasks that serve a milestone carry the label
`milestone:<name>`. The briefing shows GOALS.md, per-milestone Task progress (against a snapshot about a week
old) and drift warnings (review overdue, high-priority Tasks without a milestone, a milestone with open
high-priority Tasks and no movement). Every day the meeting asks which milestone today's top task serves; on
Mondays Block 7 is the goals block (about 10 minutes, replacing the backlog cleanup; if Monday's was missed or no
review exists yet, it is due on the next meeting until a `Last weekly review:` date in the current week is recorded): on track? still the right
milestone (the mission and goals once a quarter or when asked)? the next milestone split into 3-7 Tasks and the
week's priority order. Data: `scripts/daily_meeting_goals.py`.

## Opportunities (events and jobs, in their own chats)

Events, jobs and (later) email are handled in their own dedicated chats with the founder,
so each keeps its full context; the daily meeting only shows one line per area ("5 new
events waiting; continue in the Events chat") plus deadlines in the next 3 days. It never
goes through items one by one and never runs the jobs-profile setup.

Shared memory: `scripts/daily_meeting_opportunities.py` keeps everything in one private
folder on the dev host, `~/.local/state/openmates/opportunities/` (mode 0700, files 0600;
`OPENMATES_OPPORTUNITIES_DIR` overrides it in tests). It is outside the git checkout and
never committed:

- `jobs-profile.md`: living memory (experience and CV, jobs wanted, criteria, later the
  writing style for applications) plus a `## Search` block of `key: value` lines
  (`queries`, `countries`, `locations`, `remote`, `employment_type`, `relevance`). It starts
  empty; while `queries` is empty no job search runs and the Jobs chat runs the setup.
- `events-profile.md`: interests and a `## Search` block (`queries`, `cities` with dates such
  as `<City> from YYYY-MM-DD until YYYY-MM-DD`, `window_days`, `relevance`). Cities are
  asked, never assumed.
- `tracking.json`: every event and job ever found with status (`new`, `interested`,
  `signed_up`, `applied`, `skipped`), dates, deadline, links, notes and history. Nothing is
  shown twice.
- `last-search.json` (counts and quality warnings of the last search) and `history/` (the
  previous version of a file before each change).

Each briefing build (cron and `meeting_refresh`) runs the searches with the dev server's
own skills through the installed CLI, logged in as the personal dev account against the
dev API (`openmates apps events search` with Meetup, Luma and Eventbrite;
`openmates apps jobs search`), and appends the top 5 new events (next 14 days, per city and
date range) and top 5 new jobs. A failed search is a data gap, never a failed briefing.

The dedicated chats read and write the memory through the script's commands (`read`,
`set-status`, `add-item`, `profile`, `summary`; see its docstring), which the private dev
connector exposes to the Claude app. Poor results or a missing search feature become an
OpenMates Task to improve the event or job search skill.

The folder lives on the dev host disk only; no off-host backup of it is configured here.

## Improving the meeting itself
Every meeting ends with a two-minute "improve the meeting" block: the assistant proposes one change with its
recommendation, based on evidence from that meeting, and asks whether to adopt it, replace it or do nothing.
A change is a one-week trial (never two at once) and is reviewed the next time. Small tuning lives in the
private `logs/daily-meetings/meeting-settings.md` and takes effect the next day; structural changes edit the
meeting script. `meeting-changelog.md` keeps the dated history; both appear in the briefing as "Agreed meeting
adjustments". The note carries a `Meeting:` line.
