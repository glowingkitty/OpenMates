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

#### Parallel Batch 1a — issue ALL of these as simultaneous tool calls:

These are safe, reliable commands that should never fail. Issue them all in parallel.

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
       passed = [t['name'] for t in s.get('tests', []) if t.get('status') == 'passed']
       compact['suites'][n] = {'status': s.get('status'), 'total': len(s.get('tests', [])), 'failed': failed, 'passed': passed}
   print(json.dumps(compact, indent=2))
   "
   ```

3. **Provider health** — Bash:
   ```bash
   curl -s --max-time 15 http://localhost:8000/v1/status
   ```

4. **OpenObserve dev errors** — Bash:
   ```bash
   docker exec api python /app/backend/scripts/debug.py logs --o2 --query-json '{"stream":"default","mode":"count_by","group_by":["message","service","level"],"filters":[{"field":"compose_project","op":"eq","value":"openmates-core"},{"field":"level","op":"in","value":["ERROR","CRITICAL"]}],"since_minutes":1440,"limit":15}' --json
   ```
   Note: the LIKE '%traceback%' catch from the prior SQL-based variant is dropped —
   Python tracebacks are always logged at ERROR level via `logger.error(..., exc_info=True)`
   so the level-based filter covers them.

5. **Server stats** — Bash:
   ```bash
   docker exec api python3 /app/backend/scripts/server_stats_query.py
   ```

6. **User-reported issues** — Bash:
   ```bash
   docker exec api python /app/backend/scripts/debug_issue.py --list --json --list-limit 15
   ```

7. **Large files** — Bash:
   ```bash
   bash scripts/check-file-sizes.sh --ci
   ```

8. **Session quality** — Bash:
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

9. **Previous meeting state** — Read: `scripts/.daily-meeting-state.json`

10. **Daily inspiration audit** — Bash:
    ```bash
    docker exec api python /app/backend/scripts/audit_inspiration_pool.py --include-defaults --json 2>/dev/null
    ```

#### Parallel Batch 1a-linear — Linear tasks (issue simultaneously with batch 1a):

11. **All Linear tasks** — call `mcp__linear__list_issues` with **no limit** (or limit: 200) for states: Todo, In Progress, In Review, Backlog, Triage. If the result count equals the limit, paginate with `after` cursor to get ALL remaining tasks. **Every non-Done/non-Canceled task must be fetched — never truncate.** Sort for display: **Todo before Backlog**, then by priority (Urgent → High → Medium → Low → No priority), then by age. Collect the title of every task.

#### Parallel Batch 1b — potentially-failing commands (issue separately from batch 1a)

These commands may fail due to missing config. Issue them in a SEPARATE parallel batch from 1a so failures here don't cascade and cancel the reliable commands above.

12. **OpenObserve prod errors** — Bash:
   ```bash
   docker exec api python /app/backend/scripts/debug.py logs --o2 --prod --query-json '{"stream":"default","mode":"count_by","group_by":["message","service","level"],"filters":[{"field":"compose_project","op":"eq","value":"openmates-core"},{"field":"level","op":"in","value":["ERROR","CRITICAL"]}],"since_minutes":1440,"limit":15}' --json
   ```

13. **Production server stats** — Bash:
   ```bash
   docker exec api python3 /app/backend/scripts/server_stats_query.py --prod
   ```

#### Parallel Batch 2 — file reads (issue simultaneously after batch 1):

13. **Failed tests** — Read: `test-results/last-failed-tests.json`
14. **Failed test reports** — Glob `test-results/reports/failed/*.md`, then Read each (limit 4000 chars per file)
15. **Vitest coverage** — Read: `test-results/coverage/vitest-coverage.json`
16. **Pytest coverage** — Read: `test-results/coverage/pytest-coverage.json`
17. **Prod smoke tests** — Read: `test-results/last-run-prod-smoke.json`
18. **Nightly reports** — Glob `logs/nightly-reports/*.json` (path: `/home/superdev/projects/OpenMates`), then Read each
19. **Legal & compliance top 10** — Read: `docs/architecture/compliance/top-10-recommendations.md` (the human-readable ranked findings that back `logs/nightly-reports/legal-compliance.json`)
20. **Milestone state** — call `mcp__linear__list_projects` (includeMilestones=false), then for each project call `mcp__linear__list_milestones` with the project name. This is the source of truth for milestones — NOT `.planning/PROJECT.md`.
21. **Previous meeting summary** — Bash: `ls -t scripts/.tmp/daily-meeting-summary-*.md 2>/dev/null | head -1`, then Read the result

### Step 2: Read Prompt Template & Start Meeting

Read `scripts/prompts/daily-meeting.md` for the full meeting flow structure, state file format, and summary template.

If `dry-run` was passed: display all gathered data organized by section with headers, list any failures, then **STOP** — do not run the meeting.

Otherwise, proceed through the meeting flow using the gathered data as context.

### Step 3: Run the Meeting (Step by Step)

Follow the 9-step meeting agenda from the prompt template. **Present ONE section at a time**, wait for user response, then proceed:

1. **STATUS CLEANUP 🧹** — stale/ghost tasks, ask user to confirm status changes
2. **YESTERDAY REVIEW 📋** — commits, priority scorecard, honest assessment
3. **SYSTEM HEALTH 🏥** — outages, test failures, errors, data gaps
3b. **DAILY INSPIRATIONS REVIEW 📰** — show current public default inspirations from the audit data (pool violations count, defaults violations count, and list the titles of today's 3 English defaults). Flag any entries that look low-quality, off-topic, or borderline even if they passed the keyword filter. Ask the user if any should be removed or if the keyword blocklist needs updates.
3c. **LEGAL & COMPLIANCE ⚖️** — read `docs/architecture/compliance/top-10-recommendations.md` and surface the scan metadata (scan type, date, HEAD SHA, counts line) plus every CRITICAL and HIGH finding (rank, title, score, framework, one-line why). List MEDIUM/LOW items by title only. Mention any items resolved since last run and any tier activation alerts. Ask the user which findings (if any) should be promoted to today's top 10 priorities, and whether any should be filed as Linear tasks if they are not already tracked. If the file is missing or the date is older than 7 days, flag that the scan is stale and the cronjob may be broken.
4. **PROJECT TRAJECTORY 🗺️** — milestone progress, session quality
5. **CONTEXT QUESTIONS 🔍** — 5 rounds of targeted questions (one per round, wait for answer each time) to understand the user's current focus, blockers, energy, and upcoming commitments before suggesting priorities
6. **TODAY'S PRIORITIES 🎯** — present top 10 informed by all data + user answers, ask for confirmation
7. **MILESTONE CHECK 📐** — based on gathered context, suggest milestone changes (create new, update existing) if warranted
8. **CONFIRM & CLOSE ✅** — apply labels, save state, write summary
9. **WORKFLOW IMPROVEMENTS 💡** — reflect on how this meeting went, suggest 1-3 concrete improvements for next time

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
- [ ] Daily inspirations reviewed
- [ ] Legal & compliance top 10 reviewed (critical/high findings surfaced, promotion to priorities decided)
- [ ] Project trajectory assessed
- [ ] 5 context questions asked (one per round, answers collected)
- [ ] Today's priorities confirmed (up to 10 ranked, goal: complete top 3)
- [ ] Milestone changes evaluated and applied (if any)
- [ ] Daily priority tasks set to Urgent
- [ ] Linear labels updated
- [ ] Workflow improvement suggestions discussed and saved
- [ ] State file saved
- [ ] Meeting summary MD written
- [ ] Planning sessions offered (spawn if user confirms)
