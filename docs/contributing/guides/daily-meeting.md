# Daily meeting

A weekday planning chat in Claude Code on the dev server (text or dictation, no
voice call). A scheduled task opens it around 10:15 Europe/Berlin; it shows up in
the Claude app. The `daily-meeting-and-orchestration` skill drives it.

## Flow
1. `scripts/daily_meeting_context.py collect` gathers the last working day:
   Claude Code chats on the dev server, commits (incl. `openmates-marketing`),
   the commit-type mix, OpenMates Tasks changes (diffed against the previous
   snapshot), nightly test status, and the Apple Reminders overview. Output:
   `logs/daily-meetings/YYYY-MM-DD-context.json` (gitignored, private).
2. Recap, candid focus check, ≤3 numbered questions per round.
3. Approved plan → Reminders changes → new or resumed Claude chats per stream.
   Records: `scripts/daily_meeting.py --record priorities|answer|proposal|approve`.

## Apple Reminders
`scripts/mac_reminders.py` (`overview`, `list`, `create`, `complete`, `set-due`,
`update`, `move`, `batch`) → `apple_remote.py reminders-op` over Tailscale SSH →
fixed EventKit helper `scripts/_apple_reminders_remote.py` on the Mac.

- Lists read: OpenMates, Personal Tasks. Writes only there; no delete action.
- The Mac must be awake and on Tailscale; otherwise the meeting continues and
  lists the intended changes.
- EventKit, not AppleScript: AppleScript lookups scan every reminder and time out.
- The remote command guard (`apple_no_delete_guard.py`) admits only this exact
  helper command.
