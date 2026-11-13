# Daily meeting

Hybrid: the dev server prepares a briefing, the founder holds the meeting by
voice in the Claude app, and the decisions are written back on the dev server.
What may be worked on is defined in [`FOCUS.md`](../../../FOCUS.md)
(Marketing Week / Build Week cycle, week goals, today's focus, parking lot).

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
     instructions for Claude, phase rules, FOCUS.md, progress, reminders, then
     appendices with all reminders/chats/Tasks/commits;
   - renders it as a PDF (`scripts/daily_meeting_pdf.py`; the Claude app cannot
     fetch the long Markdown from a link) and uploads that with
     `scripts/response_media.py` (private S3 link, 48 h), then, before posting, checks that Tasks, reminders and Claude chats are live (up to 2 retries, 60 s apart); the Discord message says either "live as of HH:MM" or exactly what is not up to date, and the PDF opens with a warning banner for stale Tasks or reminders. Then it posts the link to Discord (`DISCORD_WEBHOOK_DAILY_MEETING`, else
     `DISCORD_WEBHOOK_DEV_NIGHTLY`).
3. **Meeting:** download the PDF from the Discord link, attach it in the
   daily-meeting chat in the Claude app and start a voice call. Claude asks
   exactly one question at a time, with a recommendation, then waits. The meeting
   has 6 blocks and is built for ADHD: Block 1 is a check-in. Claude first sums up
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

## Chats waiting on you
After the alerts the briefing lists dev-server Claude Code chats whose last real message came
from the assistant (idle at least 2 h, last 5 days; finished-work replies only within 36 h; chats
whose Task is Done or that were dismissed in the last 14 days are skipped). Each shows what it is
waiting for (question, blocker, done), its Task if linked, and the last reply, and opens with a one-line
plain summary in italics (Gemini Flash: what the chat is about and what it needs from the founder; if that
call fails the line is left out and a data gap says so). The meeting goes
through them one at a time; answers go into the `Chats:` lines of the decisions note. Replies are
sent by the dev-server Claude to the chat itself (`send_message`); only chats that cannot be reached get a printed reply. Data: `scripts/daily_meeting_waiting.py`.

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
in the phase rules or the agreed adjustments) is named separately and does not count as drift. The
result is the note's `Drift:` line, so the next meeting can say whether it got better or worse.

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
Mondays Block 6 is the goals block (about 10 minutes, replacing the backlog cleanup; if Monday's was missed or no
review exists yet, it is due on the next meeting until a `Last weekly review:` date in the current week is recorded): on track? still the right
milestone (the mission and goals once a quarter or when asked)? the next milestone split into 3-7 Tasks and the
week's priority order. Data: `scripts/daily_meeting_goals.py`.

## Improving the meeting itself
Every meeting ends with a two-minute "improve the meeting" block: the assistant proposes one change with its
recommendation, based on evidence from that meeting, and asks whether to adopt it, replace it or do nothing.
A change is a one-week trial (never two at once) and is reviewed the next time. Small tuning lives in the
private `logs/daily-meetings/meeting-settings.md` and takes effect the next day; structural changes edit the
meeting script. `meeting-changelog.md` keeps the dated history; both appear in the briefing as "Agreed meeting
adjustments". The note carries a `Meeting:` line.
