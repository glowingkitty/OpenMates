---
name: openmates:daily-meeting
description: Run the daily standup meeting — review yesterday, assess health, set priorities
user-invocable: true
argument-hint: "[dry-run]"
---

## Instructions

You are running the OpenMates daily standup meeting. This is a structured meeting with 5 sections that must all be completed before the meeting ends.

### Step 1: Run Data Gathering + Subagents

If the user passed `dry-run` as an argument:
```bash
DRY_RUN=true bash scripts/daily-meeting.sh
```

Otherwise, run the full pipeline — gather data and spawn subagents:
```bash
python3 scripts/_daily_meeting_helper.py gather
```

This writes 3 report files to `scripts/.tmp/`:
- `daily-meeting-health.md` — system health summary
- `daily-meeting-work.md` — yesterday's work summary
- `daily-meeting-linear.md` — Linear backlog + proposed priorities

### Step 2: Read All Reports

Read all 3 subagent reports:
```
scripts/.tmp/daily-meeting-health.md
scripts/.tmp/daily-meeting-work.md
scripts/.tmp/daily-meeting-linear.md
```

Also read the previous meeting state:
```
scripts/.daily-meeting-state.json
```

### Step 3: Run the Meeting

Follow the meeting agenda from `scripts/prompts/daily-meeting.md`. Present each section concisely:

1. **YESTERDAY REVIEW** — commits, priority achievement, honest assessment
2. **SYSTEM HEALTH** — outages, test failures, top errors, security alerts
3. **PROJECT TRAJECTORY** — milestone progress, session quality
4. **TODAY'S PRIORITIES** — present top 3, ask for confirmation
5. **CONFIRM & CLOSE** — apply Linear labels, save state

### Step 4: Apply Priorities

After the user confirms (or adjusts) the 3 priorities:

1. Query Linear for tasks with `daily-priority` label (yesterday's) — remove the label from tasks no longer selected
2. Add `daily-priority` label to today's 3 tasks
3. Post a comment on each: `"Daily priority for <DATE> — Rationale: <reason>"`
4. Save the meeting state to `scripts/.daily-meeting-state.json`

### Completion Checklist

Do NOT end the meeting until all items are done:
- [ ] All 3 reports read
- [ ] Yesterday's priorities reviewed
- [ ] System health presented
- [ ] Project trajectory assessed
- [ ] Today's 3 priorities confirmed
- [ ] Linear labels updated
- [ ] State file saved
