---
description: Linear task workflow — reading, updating status, and completing issues via Linear MCP
globs:
---

## Linear Task Workflow

Every session should be linked to a Linear task when possible — but **never auto-create**. Always search for an existing task first.

## When a Linear Issue Is Provided

When given a Linear issue (ID like OPE-42, URL, or title), you MUST follow every step below. Do not skip status updates — they are mandatory, not optional.

### Step 1: Read the Issue (before any code work)

1. **Read the issue** — call `mcp__linear__get_issue` with the issue ID for full context (title, description, status, labels)
2. **View images** — call `mcp__linear__extract_images` on the description markdown. Most bug reports include screenshots — always check.
3. **Read comments** — call `mcp__linear__list_comments` for prior discussion and follow-ups

### Step 2: Mark as In Progress (before any code work)

4. **Move to In Progress** — call `mcp__linear__save_issue` with `id: "OPE-XX"`, `state: "In Progress"`, `labels: ["claude-is-working"]`. This MUST happen before you write any code.
5. **Post pickup comment** — call `mcp__linear__save_comment` with the `claude --resume <session-id>` command so the task can be resumed later. Get the session ID from `sessions.py start` output.

### Design References

- **Figma URLs** in description: use Figma MCP to inspect the designs — check components, layout, spacing, colors to match the implementation
- **Other design links**: ask the user for screenshots or specs

### Step 3: During Work

- Post a `mcp__linear__save_comment` on **significant milestones only** — "Found root cause in X", "Fix implemented, testing". Not every step.
- If blocked or have questions: post a comment asking the user. Leave status as In Progress.

### Step 4: Complete the Task (after deploy)

This step is MANDATORY. Never finish a task without updating Linear.

1. **Post a summary comment** — call `mcp__linear__save_comment`:
   - What was done (1-3 sentences)
   - Key files changed
   - Commit hash (if any)

2. **Update status** — call `mcp__linear__save_issue` with `id: "OPE-XX"` and remove `claude-is-working` label:
   - `state: "In Review"` — code needs review
   - `state: "Done"` — confirmed complete or self-contained (docs, config)

## When No Linear Issue Is Provided — Search First

**NEVER auto-create a new task.** Always search for an existing task that this work belongs to.

### Step 0: Search for an existing task (MANDATORY — before any code work)

1. **Ask the user** — "Is there an existing Linear task for this work?"
2. **If user doesn't know or says no** — search Linear for related tasks:
   - Call `mcp__linear__list_issues` with states "In Progress", "Todo", and "Backlog" to find candidates
   - Look for tasks with related titles, descriptions, or labels
3. **Match found and clearly related** — use it. Update the task's description to append a checkbox for this sub-work:
   - Call `mcp__linear__get_issue` to read the current description
   - Append a checkbox item to the description via `mcp__linear__save_issue` with `id` + updated `description`
   - Then follow Steps 1-4 from "When a Linear Issue Is Provided"
4. **Match found but unclear** — ask the user: "Should this be added to OPE-XX (title) as a sub-task, or is it separate work?"
5. **No match found** — ask the user if they want a new task created, or if they know an existing task ID. Only create after explicit confirmation.

### Checkbox format when appending sub-tasks to existing descriptions

Append to the end of the existing description:

```markdown

## Sub-tasks
- [ ] Description of the new work
```

If a `## Sub-tasks` section already exists, append the new checkbox item to it.

## Rules

- **Always search for an existing task first.** Never auto-create without asking the user.
- **Always check images.** Call `mcp__linear__extract_images` before starting work.
- **Always update status.** Mark "In Progress" at start, "Done"/"In Review" at end. No exceptions.
- **Don't over-comment.** Max 3 comments per task: pickup, milestone/question, completion.
- **Keep comments concise.** No boilerplate. Just state what happened.
- **Status is source of truth.** Always update it — don't leave tasks stale.
- **Use exact MCP tool names.** All Linear operations use `mcp__linear__*` tools. If Linear MCP is not connected, tell the user immediately — do not silently skip status updates.
