---
name: openmates:daily-meeting
description: Run the daily standup meeting — review yesterday, assess health, set priorities
user-invocable: true
argument-hint: "[dry-run]"
---

## Instructions

You are running the OpenMates daily standup meeting. This is a **step-by-step conversation**, not a report dump. Present one section at a time and wait for user input before proceeding.

### Step 1: Gather Data & Start Meeting

If the user passed `dry-run` as an argument:
```bash
python3 scripts/_daily_meeting_helper.py dry-run
```

Otherwise, gather live data and start the meeting session directly:
```bash
python3 scripts/_daily_meeting_helper.py run-meeting
```

This gathers data from 11 sources (nightly reports, test results, git log, provider health, OpenObserve errors, server stats, user issues, session quality, milestone state) and starts the meeting with all data injected into the prompt.

No subagents are used — the meeting session receives all raw data directly, avoiding unnecessary summarization layers.

### Step 2: Run the Meeting (Step by Step)

Follow the meeting agenda from `scripts/prompts/daily-meeting.md`. **Present ONE section at a time**, wait for user response, then proceed:

1. **STATUS CLEANUP 🧹** — stale/ghost tasks, ask user to confirm status changes
2. **YESTERDAY REVIEW 📋** — commits, priority scorecard, honest assessment
3. **SYSTEM HEALTH 🏥** — outages, test failures, errors, data gaps
4. **PROJECT TRAJECTORY 🗺️** — milestone progress, session quality
5. **CONTEXT QUESTIONS 🔍** — 5 rounds of targeted questions (one per round, wait for answer each time) to understand the user's current focus, blockers, energy, and upcoming commitments before suggesting priorities
6. **TODAY'S PRIORITIES 🎯** — present top 10 informed by all data + user answers, ask for confirmation
7. **MILESTONE CHECK 📐** — based on gathered context, suggest milestone changes (create new, update existing) if warranted
8. **CONFIRM & CLOSE ✅** — apply labels, save state, write summary

### Step 3: Apply Priorities & Milestone Changes

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

### Step 4: Spawn Planning Sessions

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
