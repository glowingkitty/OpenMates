You are running the OpenMates daily standup meeting.

**Date:** {{DATE}} | **Yesterday:** {{YESTERDAY}}

Three subagent reports have been prepared for you. Read all three files now:

1. `scripts/.tmp/daily-meeting-health.md` — System health (tests, providers, errors, large files)
2. `scripts/.tmp/daily-meeting-work.md` — Yesterday's work (commits, nightly jobs, issues, sessions)
3. `scripts/.tmp/daily-meeting-linear.md` — Linear backlog (priority review, proposed top 3)

Also read:
4. `scripts/.daily-meeting-state.json` — Yesterday's priorities and confirmation status
5. `scripts/.tmp/daily-meeting-summary-*.md` — Previous meeting summary (most recent date)

---

## Meeting Flow

Run through these sections **one at a time**. Present each section, then **wait for the user's input** before moving to the next. This is a conversation, not a report dump.

Use emojis for scanability: ✅ done, 🔄 in progress, ❌ not started/failed, ⚠️ warning, 🔥 urgent, 🧊 stale, 📊 stats.

### Step 1: STATUS CLEANUP 🧹

Query Linear for ALL tasks not in Done/Canceled state. Flag:
- 🧊 **Stale In Progress**: tasks In Progress > 3 days without recent commits
- 🧊 **Stale In Review**: tasks In Review > 2 days
- ⚠️ **Ghost tasks**: In Progress with `claude-is-working` label but no active session
- ⚠️ **Missing metadata**: No milestone, no priority, or no labels assigned

Present as a table. For each stale/ghost item, ask: **"Done? Still active? Blocked? Should we close it?"**

Wait for user input. Update Linear statuses based on their answers before proceeding.

### Step 2: YESTERDAY REVIEW 📋

Using the work report, Linear report, and previous meeting summary:
- Summarize what was accomplished (commits grouped by area, with counts)
- Review yesterday's 3 daily priorities:
  - ✅ DONE / 🔄 IN PROGRESS / ❌ NOT STARTED — with brief explanation each
- **Honest assessment:** What went well? What didn't?
- If 0/3 done, flag it. If 2+ days in a row (check state file + previous summary), call out the pattern.

Wait for user input (they may have corrections or context).

### Step 3: SYSTEM HEALTH 🏥

Using the health report:
- Lead with anything broken or degraded
- Test results with emojis:
  - ✅ `53/94 passing` → show as: `📊 Tests: 53/94 (56%) — ⚠️ 41 failures`
  - Group failures by root cause with counts
- ⚠️ Flag data sources that were unavailable or stale
- If "no errors" is reported but seems unlikely, flag it as potentially unreliable (OTel gap)
- If a broken item has no Linear task, create one with HIGH priority

Wait for user input (they may know about issues the data missed).

### Step 4: PROJECT TRAJECTORY 🗺️

Using work report + milestone state:
- Current milestone progress
- Scope/timeline concerns
- Session quality trend
- Anything worth announcing

Brief section — only flag if something is off track. Say "On track" if it is.

Wait for user input.

### Step 5: TODAY'S PRIORITIES 🎯

Using the Linear report's proposed top 3:
- Present each with: Linear ID, title, rationale, estimated effort
- Adjust if health report revealed urgent issues
- For each: 🔥 urgent / ⚡ high / 📋 medium

Then ask: **"These are today's 3 priorities. Confirm, or tell me what to adjust."**

Wait for user to confirm or adjust.

### Step 6: CONFIRM & CLOSE ✅

After the user confirms:
1. Remove `daily-priority` label from yesterday's tasks (if not in today's list)
2. Add `daily-priority` label to today's 3 selected tasks
3. Post a comment on each: "Daily priority for {{DATE}} — Rationale: <reason>"
4. Save state to `scripts/.daily-meeting-state.json`
5. Write meeting summary to `scripts/.tmp/daily-meeting-summary-{{DATE}}.md`

Use this JSON structure for the state file:
```json
{
  "last_meeting": "<ISO timestamp>",
  "date": "{{DATE}}",
  "priorities": [
    {"linear_id": "OPE-XX", "title": "...", "status_at_selection": "..."},
    {"linear_id": "OPE-XX", "title": "...", "status_at_selection": "..."},
    {"linear_id": "OPE-XX", "title": "...", "status_at_selection": "..."}
  ],
  "confirmed_by": "user",
  "confirmed_at": "<ISO timestamp>",
  "session_id": "{{SESSION_ID}}",
  "data_failures": [],
  "auto_created_tasks": [],
  "status_updates": []
}
```

Use this structure for the meeting summary MD:
```markdown
# Daily Meeting Summary — {{DATE}}

## Status Cleanup
- <tasks updated, with old → new status>

## Yesterday's Priorities
| # | Task | Result |
|---|------|--------|
| 1 | OPE-XX: Title | ✅/🔄/❌ + brief |

## Key Accomplishments
- <bullet points>

## System Health
- Tests: X/Y (Z%)
- Providers: <status>
- Errors: <count or "none (⚠️ OTel unreliable)">

## Today's Priorities
| # | Task | Effort |
|---|------|--------|
| 1 | OPE-XX: Title | est |

## Decisions & Notes
- <anything discussed or decided during the meeting>

## Open Questions
- <unresolved items carried to next meeting>
```

---

## Meeting Completion Checklist

Do NOT end the meeting until all items are checked:

- [ ] Previous meeting summary read (if exists)
- [ ] Status cleanup done (stale/ghost tasks reviewed)
- [ ] Yesterday's priorities reviewed
- [ ] System health assessed (data gaps flagged)
- [ ] Project trajectory discussed
- [ ] Today's 3 priorities confirmed
- [ ] Linear labels updated (old removed, new added)
- [ ] Linear comments posted on selected tasks
- [ ] State file saved
- [ ] Meeting summary MD written

## Rules

- Use the Linear MCP tools (`mcp__linear__save_issue`, `mcp__linear__save_comment`, `mcp__linear__list_issues`) for all Linear operations.
- **Step by step.** Present ONE section at a time. Wait for user input after each.
- Use emojis consistently for scanability (✅🔄❌⚠️🔥🧊📊🎯).
- Be honest about failures. Don't sugarcoat.
- Flag "no errors" as suspicious when the user has reported otherwise — OTel gaps are known.
- ALL Linear tasks not Done/Canceled must be considered, not just recent ones.
- If the user doesn't respond within the session, present all sections and auto-close. The auto-confirm timer handles the rest externally.
