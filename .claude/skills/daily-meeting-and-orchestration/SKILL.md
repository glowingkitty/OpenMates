---
name: daily-meeting-and-orchestration
description: Apply a pasted daily meeting decisions note (DECISIONS YYYY-MM-DD …) on the dev server — update FOCUS.md, move/complete/create Apple Reminders, create or update OpenMates Tasks, and start the approved work chats. Also explains the briefing pipeline.
---

# Daily meeting write-back

The meeting itself happens by voice in the Claude app, from the briefing that
`scripts/daily_meeting_briefing.py` uploads at 11:30 Berlin on weekdays (link
posted to Discord). Its output is a decisions note the user pastes here:

```
DECISIONS 2026-11-04
Check-in: progress <1-5>, energy <1-5>; did: …; priorities: …
Drift: ~<n>% of the work since the last meeting served <milestone>; the rest: …; founder's conclusion: …
Focus: …
Focus tasks:
1. … (done when: …; milestone: …)
Reminder changes:      (table: Action | Reminder (exact title) | List | New due | New title | Notes)
Task changes:          (table: Action | Task (exact title) | New title | Priority | Status | Label | Due | Description)
Goals:                 (table: Level | Item | Action | Done when | By)
Chats:
- <chat title> -> reply: <text> | park | archive | done | keep
Cleanup:
- <plain title> (<GitHub #123 | Linear ABC-1 | TASK-123>) -> close | delete | merge <other id> | delay | keep
Parking lot:
+ … | - …
Week goals: unchanged | …
Meeting: <one change> -> adopt | adjust | revert | none (trial until YYYY-MM-DD)
Notes: …
```

The note is the user's approved decision: apply it without re-asking, and ask
only when an item is ambiguous (e.g. a reminder title matches none or several).

## Apply
0. **Save the note** verbatim (the `Check-in:` and `Drift:` lines are context only: nothing to apply) as `logs/daily-meetings/<date>-decisions.md`
   (chmod 600, private); the next briefing shows it as the previous meeting.
   Personal notes (health, authorities, private links) stay there, never in FOCUS.md.
1. **FOCUS.md** (repo root, work-related only): set *Today's focus* (focus + the
   tasks with done-criteria, dated), apply parking-lot additions/removals (tag
   each addition with the date), replace *Current week's goals* if changed.
   Personal items never go into FOCUS.md. Publish with `sessions.py start --mode
   docs` → edit → `sessions.py deploy --title "docs: focus for <date>"`.
1b. **Reminder and Task tables: one command, every row proven.** Run
   `python3 scripts/daily_meeting_apply.py plan --note logs/daily-meetings/<date>-decisions.md`
   first (reads the live Mac and live Tasks, shows what each row would do), fix every
   `NEEDS ATTENTION` row (wrong title, missing time, ambiguity: ask the user only if it cannot be
   resolved from the live data), then `... apply --note ...`. It applies the ready rows, re-reads
   both lists and prints one result per row (OK verified on live data / FAILED / NEEDS ATTENTION);
   exit code 1 means something is not applied and verified. **Never say the reminders and Tasks are
   done unless the report shows OK for every row**; put the report (or its failures) in the closing
   summary. Old-format notes (`- "title" -> move ...`) are still parsed. If the Mac is offline the
   reminder ops are saved to `<date>-pending-reminders.json` and the script says so.
   The manual steps below (2, 3) remain only for what the script cannot do. A Task's `Due` cell works on
   `create` and `edit` rows (`openmates tasks edit <id> --due <date>`; a due date can be replaced, not cleared).
2. **Reminders** via `scripts/mac_reminders.py` (manual fallback; the script above does this): FIRST run `mac_reminders.py sync` and
   `mac_reminders.py list` to read the live reminders from the Mac (titles, times and
   lists may have changed since the briefing; decide from the live state, not the note's
   titles alone; renamed or already-finished items are reported, not guessed). After the
   batch, `sync`/`list` again and verify every due and completion. Match titles against
   `mac_reminders.py list` (or `logs/daily-meetings/<date>-context.json` when
   the Mac is offline); build one JSON change list (`complete`, `set-due`,
   `create` with `list`) and run `mac_reminders.py batch --file <json>`. Report
   failures by title. Mac offline: save the list as
   `logs/daily-meetings/<date>-pending-reminders.json`, tell the user, and apply
   it when they say the Mac is online. `-> delete` in the note = `mac_reminders.py delete --id` (batch action `delete`;
   irreversible, only for an explicit delete; anything else is `complete`); writes and
   deletes only in OpenMates and Personal Tasks. A move keeps the reminder's time of day unless the note names one.
   **Rule: never a date-only reminder.** Every due has a time (`YYYY-MM-DD HH:MM`,
   Berlin); if the note gives only a date, pick a sensible time and report it.
   The tools refuse bare dates; the Mac helper sets due, start and one alarm together.
3. **OpenMates Tasks** (read live; `daily_meeting_tasks_cache.py sync` refreshes the private copy; if the CLI fails say so and use the copy) are the agents' work queue (Reminders are the user's
   inbox). For each agreed task that agents work on: find the existing Task
   (`openmates tasks list --json`; Tasks created by chats are often not linked to
   the project) or create it (`openmates tasks create --project
   96033196-e4b1-431e-b773-ba221e952fed --title … --description
   "<goal, done-criterion, date>" --priority … --assign external-ai`). Parking-lot
   items that already have Tasks move to `backlog`. Never mark undeployed or incomplete work Done (deployed to dev counts as done).
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
Plain-language rule: whenever you report to the user (summaries, printed replies, parking-lot lines),
name every ID, agent or task with a few plain words first and the ID only in brackets after it; if a
briefing line shows a bare ID, say what it is before using it.
4a. **Goals** (the `Goals:` table, from the Monday block; plain wording, never bare IDs): edit
   `GOALS.md` (repo root of the canonical checkout, private, gitignored, never committed): `add`/`edit`
   milestones with their done-when and date, `done` moves a milestone to the done list with the date,
   `drop` removes it with a one-line reason, mission/goal rows only when the note says so. Set the
   `Last weekly review: <date>` line whenever the weekly goals block ran (Monday, or the carried-over day). Tasks created for a milestone carry
   the label `milestone:<name>` (use the `Label` column of the Task table); add one reminder with a
   time on the milestone's due date. Update the "Current milestone" line in FOCUS.md.
4c. **Meeting** (the `Meeting:` line): `adopt`/`adjust` a change: small tuning (order, length, wording,
   skipping a block on some days) goes into the private `logs/daily-meetings/meeting-settings.md`
   (the briefing injects it as "Agreed meeting adjustments"); structural changes edit
   `MEETING_SCRIPT` in `scripts/daily_meeting_briefing.py` with tests and a deploy. Append one line to
   `logs/daily-meetings/meeting-changelog.md` (`- <date> <plain change> (trial until <date>)`). `revert`
   removes the change from the settings file and logs it; `none` does nothing. Every change is a
   one-week trial; never two at once.
4b. **Chats** (the `Chats:` lines, from the briefing's "Chats waiting on you"): `reply: <text>`
   → send the reply yourself to that chat (`send_message` to its Remote session, matched by title/last prompt; the user never pastes into chats you can answer), then report each result; if a chat cannot be reached, say so and print the reply; a reply that would need a production or other user-only action (e.g. 3FA SSH) is not carried out: report it to the user instead; `park` →
   parking-lot line; `archive`/`done` → archive the chat via `archive_session` when it has a
   session id, otherwise just record it; `keep` → nothing. Record every non-reply decision in
   `logs/daily-meetings/waiting-reviewed.json` (`{"<full session id>": "YYYY-MM-DD"}`, private)
   so the chat is not offered again for 14 days. Never message or stop the Rust chat.
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

## Meeting conduct (from the 06 Nov decisions)
- Always ask about yesterday's tasks (done / not done / moved). Skip the question only when
  git commits make the answer obvious, and even then ask for a one-line confirmation.
- Keep Claude usage low: Sonnet for most work, Rust work excepted.
- Check-in, question 1 (permanent, from 13 Nov): no open "what have you been up to?". Claude
  first sums up what the commits and chats since the last meeting show, then asks what else
  was done, using open reminders and Tasks as grouped memory prompts ("Did you get to X?").
- Mentor stance: the meeting is run as a critical mentor (honest, constructive, evidence only). Block 1
  ends with the daily drift check: share of the commits and chats since the last meeting that served
  the current milestone, drift named plainly, exactly one question, approved background migrations
  named separately. The milestone task gets the first work slot of the day.
- Voice mode has no repo access: checks of the repo ("is bug X already fixed?") are done by
  the dev server when the note is applied, and the result goes into the closing summary.
