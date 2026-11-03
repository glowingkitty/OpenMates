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
- "<exact title>" -> done | move YYYY-MM-DD | keep
New reminders:
- "<title>" (OpenMates|Personal Tasks, YYYY-MM-DD)
Parking lot:
+ … | - …
Week goals: unchanged | …
Notes: …
```

The note is the user's approved decision: apply it without re-asking, and ask
only when an item is ambiguous (e.g. a reminder title matches none or several).

## Apply
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
   Personal Tasks.
3. **OpenMates Tasks** are the agents' work queue (Reminders are the user's
   inbox). For each agreed task that agents work on: find the existing Task
   (`openmates tasks list --project 96033196-e4b1-431e-b773-ba221e952fed --json`)
   or create it (`openmates tasks create --project <id> --title … --description
   "<goal, done-criterion, date>" --priority … --assign external-ai`). Parking-lot
   items that already have Tasks move to `backlog`. Never mark incomplete work Done.
4. **Work chats** (optional, ask once with a recommendation): one Claude chat per
   agent task — `create_session` with the `dev-server:OpenMates…` bridge
   environment and a handoff naming the Task ID, goal, done-criterion and "read
   FOCUS.md and run `sessions.py start` first"; resume an existing chat with
   `send_message`. Respect the current phase in FOCUS.md.

Close with ≤6 lines: focus, tasks with Task IDs, reminders changed, parking-lot
changes, chats started.

## Pipeline reference
- `mac_reminders.py sync` (cron, every 30 min) keeps a private copy in
  `~/.local/state/openmates/reminders-cache.json`; the Mac is often offline.
- `daily_meeting_briefing.py [--force] [--no-send] [--no-upload]` rebuilds and
  resends today's briefing (Gemini Flash in the `api` container summarizes the
  Claude chats).
- Docs: `docs/contributing/guides/daily-meeting.md`.
