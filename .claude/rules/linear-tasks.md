---
description: Linear task workflow — automated via sessions.py, with manual MCP for deep context
globs:
---

## Every Session Needs a Linear Task

Every Claude session MUST be linked to a Linear task — no exceptions. `sessions.py` handles the mechanical parts automatically:

- **`--linear-issue OPE-42`**: Fetches issue, marks In Progress, adds `claude-is-working` label, posts pickup comment
- **No `--linear-issue` but `--task` given**: Auto-creates a new issue with mode-based prefix (Feat/Fix/Docs/Research/Test)
- **`sessions.py end` / `deploy --end`**: Posts completion comment, removes label, updates status to In Review or Done

If `sessions.py` printed `Linear: OPE-XX` in the session header, the routine status/label/comment operations are already handled.

## Step 1: Read the Issue (before any code work)

`sessions.py` displays a summary, but you should still read the full issue for deep context:

1. **Read the issue** — call `mcp__linear__get_issue` with the issue ID for full context (title, description, status, labels)
2. **View images** — call `mcp__linear__extract_images` on the description markdown. Most bug reports include screenshots — always check.
3. **Read comments** — call `mcp__linear__list_comments` for prior discussion and follow-ups

### Design References

- **Figma URLs** in description: use Figma MCP to inspect the designs — check components, layout, spacing, colors to match the implementation
- **Other design links**: ask the user for screenshots or specs

## Step 2: During Work

- Post a `mcp__linear__save_comment` on **significant milestones only** — "Found root cause in X", "Fix implemented, testing". Not every step.
- If blocked or have questions: post a comment asking the user. Leave status as In Progress.

## Step 3: Completion (automated)

`sessions.py end` or `deploy --end` automatically:
- Posts a summary comment with session ID, commit SHA, and changed files
- Removes `claude-is-working` label
- Updates status: `In Review` (feature/bug/testing) or `Done` (docs/question)

**Manual override:** If you need to set a different status or add extra context to the completion comment, call the MCP tools directly before `sessions.py end`.

## Fallback: No sessions.py or Linear API Key Missing

If `sessions.py` printed a warning about Linear, handle it manually:

1. **Create/link issue** — call `mcp__linear__save_issue` with title, `state: "In Progress"`, `labels: ["claude-is-working"]`
2. **Post pickup comment** — call `mcp__linear__save_comment` with `claude --resume <session-id>`
3. **At completion** — call `mcp__linear__save_issue` to update status and remove label

## Archiving / Deleting Issues

The Linear MCP tools do NOT support archiving or deleting issues. Use `_linear_client.py` directly:

```python
from scripts._linear_client import _graphql

# 1. Get the internal UUID from the identifier
data = _graphql('query($id: String!) { issue(id: $id) { id } }', {'id': 'OPE-42'})
uuid = data['issue']['id']

# 2. Archive the issue
_graphql('mutation($id: String!) { issueArchive(id: $id) { success } }', {'id': uuid})

# 3. Delete permanently (use sparingly — prefer archive)
_graphql('mutation($id: String!) { issueDelete(id: $id) { success } }', {'id': uuid})
```

When asked to "clear" or "clean up" Done tasks, archive them — don't change their state.

## Rules

- **Always check images.** Call `mcp__linear__extract_images` before starting work.
- **Don't over-comment.** Max 3 comments per task: pickup (auto), milestone/question, completion (auto).
- **Keep comments concise.** No boilerplate. Just state what happened.
- **Status is source of truth.** `sessions.py` handles start/end status. Only intervene if you need a non-standard state.
- **Use exact MCP tool names.** All manual Linear operations use `mcp__linear__*` tools. If Linear MCP is not connected, tell the user immediately.
- **For archive/delete:** Use `_linear_client._graphql()` with `issueArchive` or `issueDelete` mutations — the MCP tools don't support these operations.
