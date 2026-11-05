---
name: daily-meeting-and-orchestration
description: Apply a pasted daily meeting decisions note (DECISIONS YYYY-MM-DD …) on the dev server — update FOCUS.md, move/complete/create Apple Reminders, create or update OpenMates Tasks, and start the approved work chats. Also explains the briefing pipeline.
---

# Daily meeting write-back

The meeting itself happens by voice in the Claude app, from the briefing that
`scripts/daily_meeting_briefing.py` uploads at 10:00 Berlin on weekdays (link
posted to Discord). Its output is a decisions note the user pastes here:

```
DECISIONS 2026-11-04
Focus: …
Tasks:
1. … (done when: …)
Reminders:
- "<exact title>" -> done | move YYYY-MM-DD HH:MM | keep
New reminders:
- "<title>" (OpenMates|Personal Tasks, YYYY-MM-DD HH:MM)
Cleanup:
- <GitHub #123 | Linear ABC-1 | TASK-123> -> close | delete | merge <other id> | delay | keep
Parking lot:
+ … | - …
Week goals: unchanged | …
Notes: …
```

The note is the user's approved decision: apply it without re-asking, and ask
only when an item is ambiguous (e.g. a reminder title matches none or several).

## Apply
0. **Save the note** verbatim as `logs/daily-meetings/<date>-decisions.md`
   (chmod 600, private); the next briefing shows it as the previous meeting.
   Personal notes (health, authorities, private links) stay there, never in FOCUS.md.
1. **FOCUS.md** (repo root, work-related only): set *Today's focus* (focus + the
   tasks with done-criteria, dated), apply parking-lot additions/removals (tag
   each addition with the date), replace *Current week's goals* if changed.
   Personal items never go into FOCUS.md. Publish with `sessions.py start --mode
   docs` → edit → `sessions.py deploy --title "docs: focus for <date>"`.
2. **Reminders** via `scripts/mac_reminders.py`: match titles against
   `mac_reminders.py list` (or `logs/daily-meetings/<date>-context.json` when
   the Mac is offline); build one JSON change list (`complete`, `set-due`,
   `create` with `list`) and run `mac_reminders.py batch --file <json>`. Report
   failures by title. Mac offline: save the list as
   `logs/daily-meetings/<date>-pending-reminders.json`, tell the user, and apply
   it when they say the Mac is online. No deletes; writes only to OpenMates and
   Personal Tasks. A move keeps the reminder's time of day unless the note names one.
   **Rule: never a date-only reminder.** Every due has a time (`YYYY-MM-DD HH:MM`,
   Berlin); if the note gives only a date, pick a sensible time and report it.
   The tools refuse bare dates; the Mac helper sets due, start and one alarm together.
3. **OpenMates Tasks** are the agents' work queue (Reminders are the user's
   inbox). For each agreed task that agents work on: find the existing Task
   (`openmates tasks list --json`; Tasks created by chats are often not linked to
   the project) or create it (`openmates tasks create --project
   96033196-e4b1-431e-b773-ba221e952fed --title … --description
   "<goal, done-criterion, date>" --priority … --assign external-ai`). Parking-lot
   items that already have Tasks move to `backlog`. Never mark incomplete work Done.
4. **Cleanup** (the `Cleanup:` lines; the meeting also tidies the to-do lists):
   - Tasks: `close`/`delete` → `openmates tasks delete <id> --confirm` only if the note
     says delete, else mark obsolete work via `tasks edit --status backlog` plus an
     activity note (`tasks history`/`restore` can undo a delete); `merge X` → add an
     activity note on both pointing at each other, then delete or close the duplicate;
     `delay` → `--status backlog --add-label build-week-<date>` and a parking-lot line;
     `keep` → leave as is.
   - GitHub: `close`/`delete` → `gh issue close <n> --reason "not planned" --comment
     "Closed in the daily backlog cleanup: <reason>"` (`gh issue delete` only when the
     note says delete); `merge X` → comment "Duplicate of #X" and close; `delay` → add
     the label `later` (create if missing) with a comment.
   - Linear: needs `LINEAR_API_KEY`; archive via the GraphQL `issueArchive` mutation, or
     list the Linear ids in the closing summary for the user to do by hand if no key.
   - Record every `keep` in `logs/daily-meetings/cleanup-reviewed.json` (`{"<id>":
     "YYYY-MM-DD"}`, private) so it is not offered again for 30 days.
   Report counts and any failures by id.
5. **Work chats** (optional, ask once with a recommendation): one Claude chat per
   agent task — `create_session` with the `dev-server:OpenMates…` bridge
   environment and a handoff naming the Task ID, goal, done-criterion and "read
   FOCUS.md and run `sessions.py start` first"; resume an existing chat with
   `send_message`. Respect the current phase in FOCUS.md.

Close with ≤6 lines: focus, tasks with Task IDs, reminders changed, items cleaned up,
parking-lot changes, chats started.

## Pipeline reference
- `mac_reminders.py sync` (cron, every 30 min) keeps a private copy in
  `~/.local/state/openmates/reminders-cache.json`; the Mac is often offline.
- `daily_meeting_briefing.py [--force] [--no-send] [--no-upload]` rebuilds and
  resends today's briefing (Gemini Flash in the `api` container summarizes the
  Claude chats).
- Docs: `docs/contributing/guides/daily-meeting.md`.

## Alerts
The briefing's "Alerts" section (production and dev reported issues, repeating errors of the last 24 h) comes first. Production reports outrank all other work: if the note says to investigate one, start it via `/debug-issue` or the `issue-forensics` agent. Never copy emails or share links from issue records into notes.
