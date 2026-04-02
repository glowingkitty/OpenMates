---
name: openmates:daily-meeting
description: Run the daily standup meeting — review yesterday, assess health, set priorities
user-invocable: true
argument-hint: "[dry-run]"
---

## Instructions

You are running the OpenMates daily standup meeting. This is a **step-by-step conversation**, not a report dump. Present one section at a time and wait for user input before proceeding.

### Step 1: Gather Data (Inline)

Gather all data sources directly using Bash and Read tools. Do NOT call `_daily_meeting_helper.py run-meeting` — that launches a separate Claude session.

**Error handling:** If any source fails, record `[DATA UNAVAILABLE: <source> — <error>]` and continue. Never abort the meeting due to a single data source failure.

#### Parallel Batch 1 — issue ALL of these as simultaneous tool calls:

1. **Git log (24h)** — Bash:
   ```bash
   git -C /home/superdev/projects/OpenMates log --since="24 hours ago" --oneline --no-color
   ```

2. **Test summary** (compact extraction from large JSON) — Bash:
   ```bash
   cd /home/superdev/projects/OpenMates && python3 -c "
   import json
   d = json.loads(open('test-results/last-run.json').read())
   compact = {
       'run_id': d.get('run_id'), 'git_sha': d.get('git_sha'),
       'duration_seconds': d.get('duration_seconds'),
       'summary': d.get('summary', {}), 'suites': {}
   }
   for n, s in d.get('suites', {}).items():
       failed = [{'name': t['name'], 'error': (t.get('error') or '')[:300]}
                 for t in s.get('tests', []) if t.get('status') != 'passed']
       compact['suites'][n] = {'status': s.get('status'), 'total': len(s.get('tests', [])), 'failed': failed}
   print(json.dumps(compact, indent=2))
   "
   ```

3. **Provider health** — Bash:
   ```bash
   curl -s --max-time 15 http://localhost:8000/v1/status
   ```

4. **OpenObserve dev errors** — Bash:
   ```bash
   docker exec api python /app/backend/scripts/debug.py logs --o2 --since 1440 --sql 'SELECT message, service, level, COUNT(*) as count FROM "default" WHERE compose_project = '"'"'openmates-core'"'"' AND (level = '"'"'ERROR'"'"' OR level = '"'"'CRITICAL'"'"' OR LOWER(message) LIKE '"'"'%traceback%'"'"') GROUP BY message, service, level ORDER BY count DESC LIMIT 15' --json --quiet-health
   ```

5. **OpenObserve prod errors** — Bash (same as #4 with `--prod`):
   ```bash
   docker exec api python /app/backend/scripts/debug.py logs --o2 --since 1440 --sql 'SELECT message, service, level, COUNT(*) as count FROM "default" WHERE compose_project = '"'"'openmates-core'"'"' AND (level = '"'"'ERROR'"'"' OR level = '"'"'CRITICAL'"'"' OR LOWER(message) LIKE '"'"'%traceback%'"'"') GROUP BY message, service, level ORDER BY count DESC LIMIT 15' --json --quiet-health --prod
   ```

6. **Server stats** — Bash:
   ```bash
   docker exec api python3 /app/backend/scripts/server_stats_query.py
   ```

7. **User-reported issues** — Bash:
   ```bash
   docker exec api python /app/backend/scripts/debug_issue.py --list --json --list-limit 15
   ```

8. **Large files** — Bash:
   ```bash
   bash scripts/check-file-sizes.sh --ci
   ```

9. **Session quality** — Bash:
   ```bash
   cd /home/superdev/projects/OpenMates/scripts && python3 -c "
   from _workflow_review_helper import build_session_digests
   from datetime import datetime, timezone, timedelta
   y = (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%d')
   t, c, ch = build_session_digests(y, verbose=False)
   if c == 0:
       print('(No sessions found for yesterday.)')
   else:
       print(f'({c} sessions, {ch:,} chars)\n\n' + t[:8000])
   "
   ```

10. **Previous meeting state** — Read: `scripts/.daily-meeting-state.json`

#### Parallel Batch 2 — file reads (issue simultaneously after batch 1):

11. **Failed tests** — Read: `test-results/last-failed-tests.json`
12. **Failed test reports** — Glob `test-results/reports/failed/*.md`, then Read each (limit 4000 chars per file)
13. **Vitest coverage** — Read: `test-results/coverage/vitest-coverage.json`
14. **Pytest coverage** — Read: `test-results/coverage/pytest-coverage.json`
15. **Prod smoke tests** — Read: `test-results/last-run-prod-smoke.json`
16. **Nightly reports** — Glob `logs/nightly-reports/*.json`, then Read each
17. **Milestone state** — Read: `.planning/PROJECT.md` (fallback: `.planning/ROADMAP.md`, `.planning/STATE.md`, `.planning/config.json`)
18. **Previous meeting summary** — Bash: `ls -t scripts/.tmp/daily-meeting-summary-*.md 2>/dev/null | head -1`, then Read the result

### Step 2: Read Prompt Template & Start Meeting

Read `scripts/prompts/daily-meeting.md` for the full meeting flow structure, state file format, and summary template.

If `dry-run` was passed: display all gathered data organized by section with headers, list any failures, then **STOP** — do not run the meeting.

Otherwise, proceed through the meeting flow using the gathered data as context.

### Step 3: Run the Meeting (Step by Step)

Follow the 8-step meeting agenda from the prompt template. **Present ONE section at a time**, wait for user response, then proceed:

1. **STATUS CLEANUP 🧹** — stale/ghost tasks, ask user to confirm status changes
2. **YESTERDAY REVIEW 📋** — commits, priority scorecard, honest assessment
3. **SYSTEM HEALTH 🏥** — outages, test failures, errors, data gaps
4. **PROJECT TRAJECTORY 🗺️** — milestone progress, session quality
5. **CONTEXT QUESTIONS 🔍** — 5 rounds of targeted questions (one per round, wait for answer each time) to understand the user's current focus, blockers, energy, and upcoming commitments before suggesting priorities
6. **TODAY'S PRIORITIES 🎯** — present top 10 informed by all data + user answers, ask for confirmation
7. **MILESTONE CHECK 📐** — based on gathered context, suggest milestone changes (create new, update existing) if warranted
8. **CONFIRM & CLOSE ✅** — apply labels, save state, write summary

### Step 4: Apply Priorities & Milestone Changes

After the user confirms (or adjusts) priorities and any milestone changes:

1. Query Linear for tasks with `daily-priority` label (yesterday's) — remove the label from tasks no longer selected
2. Add `daily-priority` label to today's tasks (up to 10)
3. **Set all daily priority tasks to Urgent priority** — daily priorities are always Urgent
4. Post a comment on each top 3: `"Daily priority for <DATE> — Rationale: <reason>"`
5. Apply confirmed milestone changes (create new, update existing) via Linear MCP tools
6. Save the meeting state to `scripts/.daily-meeting-state.json`
7. Write meeting summary to `scripts/.tmp/daily-meeting-summary-<DATE>.md`

### Priority Rules

- **Daily priority tasks MUST be set to Urgent priority.** If a task was lower priority before selection, escalate it when adding the `daily-priority` label.
- When a task is removed from daily priorities (next meeting), restore its original priority only if the user explicitly says to de-escalate.

### Step 5: Spawn Planning Sessions

After all labels are applied and state is saved, ask the user:

**"Want me to spawn planning sessions for today's priorities? Each will run in a separate Zellij tab researching and drafting an implementation plan."**

If the user confirms:
```bash
python3 scripts/_daily_meeting_helper.py spawn-planning
```

Present the attach commands from the output. Sessions are visible at http://localhost:8082.

If the user declines, skip this step.

### Completion Checklist

Do NOT end the meeting until all items are done:
- [ ] All gathered data reviewed + previous summary
- [ ] Status cleanup done (stale/ghost tasks reviewed)
- [ ] Yesterday's priorities reviewed
- [ ] System health presented
- [ ] Project trajectory assessed
- [ ] 5 context questions asked (one per round, answers collected)
- [ ] Today's priorities confirmed (up to 10 ranked, goal: complete top 3)
- [ ] Milestone changes evaluated and applied (if any)
- [ ] Daily priority tasks set to Urgent
- [ ] Linear labels updated
- [ ] State file saved
- [ ] Meeting summary MD written
- [ ] Planning sessions offered (spawn if user confirms)
