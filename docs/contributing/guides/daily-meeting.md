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
2. **Weekdays 10:00 Europe/Berlin** `scripts/daily_meeting_briefing.py --scheduled`:
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
   has 6 blocks and is built for ADHD: Block 1 is a check-in in the founder's own
   words (what have you been up to, how happy with the progress 1-5, largest
   priorities, energy today 1-5), then safety net (production alerts, chats waiting),
   focus (max 3 tasks, each with a 5-minute first step, time slot and stop rule),
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

The briefing opens with an "Alerts" section, right after the usage line: reported issues of the
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
waiting for (question, blocker, done), its Task if linked, and the last reply. The meeting goes
through them one at a time; answers go into the `Chats:` lines of the decisions note. Replies are
sent by the dev-server Claude to the chat itself (`send_message`); only chats that cannot be reached get a printed reply. Data: `scripts/daily_meeting_waiting.py`.

## Plain-language rule
IDs, agent names and tasks are never mentioned bare in the briefing, the meeting or the decisions
note: each comes with a few plain words saying what it is, and the ID only in brackets after it.
The briefing shows chats by title (else the last prompt or reply in words, never "untitled" or a
slug) with their Task title, and Tasks, GitHub and Linear issues as "title (id)". The meeting
script (`MEETING_SCRIPT`) tells Claude to speak and write the same way.
