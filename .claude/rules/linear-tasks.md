---
description: Linear task workflow — reading, updating status, and completing issues via Linear MCP
globs:
---

## Every Session Needs a Linear Task

Every Claude session MUST be linked to a Linear task — no exceptions. This includes features, bugs, refactors, research, docs, and questions. If the user provides a task ID, use it. If not, create one.

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

## When No Linear Issue Is Provided

If the user requests work without referencing a Linear issue, you MUST create one before starting:

1. **Create a new issue** — call `mcp__linear__save_issue` with:
   - `title`: concise description of the work (e.g., "Research: WebSocket reconnection strategies", "Fix: settings page crash on mobile")
   - `state`: "In Progress"
   - `labels`: ["claude-is-working"]
2. **Post pickup comment** — call `mcp__linear__save_comment` with the `claude --resume <session-id>` command
3. **Tell the user** — mention the created task ID (e.g., "Created OPE-XX to track this work")
4. Follow Steps 3-4 from the existing task workflow as normal

**Title conventions by session mode:**
- `feature` → "Feat: ..."
- `bug` → "Fix: ..."
- `docs` → "Docs: ..."
- `question` / research → "Research: ..."
- `testing` → "Test: ..."

## Rules

- **Every session needs a task.** No exceptions — features, bugs, research, docs, questions. Create one if not provided.
- **Always check images.** Call `mcp__linear__extract_images` before starting work.
- **Always update status.** Mark "In Progress" at start, "Done"/"In Review" at end. No exceptions.
- **Don't over-comment.** Max 3 comments per task: pickup, milestone/question, completion.
- **Keep comments concise.** No boilerplate. Just state what happened.
- **Status is source of truth.** Always update it — don't leave tasks stale.
- **Use exact MCP tool names.** All Linear operations use `mcp__linear__*` tools. If Linear MCP is not connected, tell the user immediately — do not silently skip status updates.
