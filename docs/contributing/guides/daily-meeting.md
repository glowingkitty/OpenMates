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
     `scripts/response_media.py` (private S3 link, 48 h), then posts the link to Discord (`DISCORD_WEBHOOK_DAILY_MEETING`, else
     `DISCORD_WEBHOOK_DEV_NIGHTLY`).
3. **Meeting:** download the PDF from the Discord link, attach it in the
   daily-meeting chat in the Claude app and start a voice call. Claude asks
   exactly one question at a time, with a recommendation, then waits. The meeting
   ends with a `DECISIONS <date>` note.
4. **Write-back:** paste the note into a Claude Code chat on the dev server; the
   `daily-meeting-and-orchestration` skill updates FOCUS.md, Reminders and
   OpenMates Tasks and can start the approved work chats.

## Apple Reminders
`scripts/mac_reminders.py` (`sync`, `overview`, `list`, `create`, `complete`,
`set-due`, `update`, `move`, `batch`) → `apple_remote.py reminders-op` over
Tailscale SSH → fixed EventKit helper `scripts/_apple_reminders_remote.py` on the
Mac. Writes only to OpenMates and Personal Tasks; no delete action. EventKit,
not AppleScript: AppleScript lookups scan every reminder and time out. The
remote command guard (`apple_no_delete_guard.py`) admits only this helper.

**Due times rule:** a reminder is never due on a bare day. Every due carries a
time (`YYYY-MM-DD HH:MM`, Berlin); `mac_reminders.py` and the Mac helper refuse
date-only values. Setting a due also sets the start date and replaces the alarms
with one alarm at that time, so Reminders and Calendar show the same moment.
