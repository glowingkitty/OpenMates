---
name: openmates:daily-meeting
description: Run the daily standup meeting — review yesterday, assess health, set priorities
user-invocable: true
argument-hint: "[dry-run]"
---

## Instructions

You are running the OpenMates daily standup meeting. This is a **step-by-step conversation**, not a report dump. Present one section at a time and wait for user input before proceeding.

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

Also read:
```
scripts/.daily-meeting-state.json          # yesterday's priorities
scripts/.tmp/daily-meeting-summary-*.md    # previous meeting summary (most recent)
```

### Step 3: Run the Meeting (Step by Step)

Follow the meeting agenda from `scripts/prompts/daily-meeting.md`. **Present ONE section at a time**, wait for user response, then proceed:

1. **STATUS CLEANUP 🧹** — stale/ghost tasks, ask user to confirm status changes
2. **YESTERDAY REVIEW 📋** — commits, priority scorecard, honest assessment
3. **SYSTEM HEALTH 🏥** — outages, test failures, errors, data gaps
4. **PROJECT TRAJECTORY 🗺️** — milestone progress, session quality
5. **CONTEXT QUESTIONS 🔍** — 5 rounds of targeted questions (one per round, wait for answer each time) to understand the user's current focus, blockers, energy, and upcoming commitments before suggesting priorities
6. **TODAY'S PRIORITIES 🎯** — present top 3 informed by all data + user answers, ask for confirmation
7. **MILESTONE CHECK 📐** — based on gathered context, suggest milestone changes (create new, update existing) if warranted
8. **CONFIRM & CLOSE ✅** — apply labels, save state, write summary

### Step 4: Apply Priorities & Milestone Changes

After the user confirms (or adjusts) the 3 priorities and any milestone changes:

1. Query Linear for tasks with `daily-priority` label (yesterday's) — remove the label from tasks no longer selected
2. Add `daily-priority` label to today's 3 tasks
3. **Set all daily priority tasks to Urgent priority** — daily priorities are always Urgent
4. Post a comment on each: `"Daily priority for <DATE> — Rationale: <reason>"`
5. Apply confirmed milestone changes (create new, update existing) via Linear MCP tools
6. Save the meeting state to `scripts/.daily-meeting-state.json`
7. Write meeting summary to `scripts/.tmp/daily-meeting-summary-<DATE>.md`

### Priority Rules

- **Daily priority tasks MUST be set to Urgent priority.** If a task was lower priority before selection, escalate it when adding the `daily-priority` label.
- When a task is removed from daily priorities (next meeting), restore its original priority only if the user explicitly says to de-escalate.

### Step 5: Spawn Planning Sessions

After all labels are applied and state is saved, ask the user:

**"Want me to spawn planning sessions for today's 3 priorities? Each will run in a separate Zellij tab researching and drafting an implementation plan."**

If the user confirms:
```bash
python3 scripts/_daily_meeting_helper.py spawn-planning
```

Present the attach commands from the output. Sessions are visible at http://localhost:8082.

If the user declines, skip this step.

### Completion Checklist

Do NOT end the meeting until all items are done:
- [ ] All 3 reports read + previous summary
- [ ] Status cleanup done (stale/ghost tasks reviewed)
- [ ] Yesterday's priorities reviewed
- [ ] System health presented
- [ ] Project trajectory assessed
- [ ] 5 context questions asked (one per round, answers collected)
- [ ] Today's 3 priorities confirmed (informed by user answers)
- [ ] Milestone changes evaluated and applied (if any)
- [ ] Daily priority tasks set to Urgent
- [ ] Linear labels updated
- [ ] State file saved
- [ ] Meeting summary MD written
- [ ] Planning sessions offered (spawn if user confirms)
