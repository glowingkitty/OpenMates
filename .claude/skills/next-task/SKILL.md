---
name: openmates:next-task
description: Pick the next Linear task to work on — checks daily priorities, ranks backlog, auto-starts session
user-invocable: true
argument-hint: "[filter: bug|feature|frontend|backend|small|medium|large]"
---

## Instructions

You are helping the user pick their next task from Linear and start a session with it.

### Step 1: Check Daily Priorities

Read `scripts/.daily-meeting-state.json` to see today's selected priorities:
```bash
cat scripts/.daily-meeting-state.json 2>/dev/null || echo "no daily meeting state"
```

If the file exists and `date` matches today, these are the user's pre-selected priorities.

### Step 2: Fetch Tasks from Linear

**First**, fetch today's daily-priority tasks that aren't done:
```
mcp__linear__list_issues with label: "daily-priority", state: "started"
```

Also fetch In Progress tasks (may have been started but not finished):
```
mcp__linear__list_issues with state: "started", team: "OpenMates"
```

**If all daily priorities are done** (or no daily meeting today), fetch the broader backlog:
```
mcp__linear__list_issues with state: "unstarted", team: "OpenMates", limit: 20
```

### Step 3: Filter & Rank

**Exclude** tasks with the `claude-is-working` label (already claimed by another session).

If the user passed `$ARGUMENTS`, use them as filters:
- `bug` → only show issues with Bug label
- `feature` → only Improvement/Feature labels
- `frontend` / `backend` → match by label or project
- `small` / `medium` / `large` → match by point estimate or effort label

**Rank remaining tasks** (highest priority first):
1. **In Progress** — resume unfinished work before starting new
2. **Urgent/High priority** (Linear priority field: 1=Urgent, 2=High)
3. **User-reported** — `user-feedback` label
4. **Age** — older unattended tasks ranked higher
5. **Todo over Backlog** status

### Step 4: Present Options

Show the user a ranked list with key details for each task:

```
1. OPE-XX: Title (Priority: High, Status: In Progress, Labels: [Bug, frontend])
2. OPE-XX: Title (Priority: Medium, Status: Todo, Labels: [Improvement])
3. OPE-XX: Title (Priority: Normal, Status: Todo, Labels: [user-feedback])
```

If there are more than 5 candidates, ask the user to filter by:
- **Priority**: Urgent/High vs Medium/Low
- **Status**: Resume in-progress vs start fresh
- **Effort**: Small (quick fix) vs Medium/Large (deep work)

### Step 5: User Picks a Task

Use `AskUserQuestion` to let the user select which task to work on. Show the top 3-4 options.

After selection, fetch the full issue details:
```
mcp__linear__get_issue with the selected OPE-XX identifier
```

Read the full description, check for images (`mcp__linear__extract_images`), and read comments (`mcp__linear__list_comments`).

### Step 6: Auto-Start Session

Infer the session mode from the task's labels:

| Linear Label | Mode |
|---|---|
| Bug | `bug` |
| Improvement | `feature` |
| Feature | `feature` |
| Documentation | `docs` |
| Testing | `testing` |
| _(default)_ | `feature` |

Then start the session:
```bash
python3 scripts/sessions.py start --mode <MODE> --task "<issue title>" --linear-issue <OPE-XX>
```

Read the session output and proceed with the task.

## Rules

- **Never skip Step 1** — always check daily-meeting state first to respect pre-selected priorities
- **Always exclude `claude-is-working`** tasks — another session owns them
- **Always show task details** before auto-starting — don't blindly pick
- **Infer mode from labels**, don't ask the user unless ambiguous (e.g., task has both Bug and Improvement labels)
