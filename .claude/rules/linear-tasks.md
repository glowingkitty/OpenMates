---
description: Linear task workflow — reading, updating status, and completing issues via MCP
globs:
---

## Working on a Linear Task

When given a Linear issue (ID like OPE-42, URL, or title):

1. **Read the issue** — `get_issue` for full context (title, description, status, labels)
2. **View images** — `extract_images` on the description markdown. Most bug reports include screenshots — always check.
3. **Read comments** — `list_comments` for prior discussion and follow-ups
4. **Move to In Progress** — `save_issue` with `state: "In Progress"` (run `list_issue_statuses` first if unsure of valid state names)

## Design References

- **Figma URLs** in description: use Figma MCP to inspect the designs — check components, layout, spacing, colors to match the implementation
- **Other design links**: ask the user for screenshots or specs

## During Work

- Post a `save_comment` on **significant milestones only** — "Found root cause in X", "Fix implemented, testing". Not every step.
- If blocked or have questions: post a comment asking the user. Leave status as In Progress.

## Completing the Task

Post a summary comment (`save_comment`):
- What was done (1-3 sentences)
- Key files changed
- Commit hash (if any)

Update status (`save_issue`):
- **"In Review"** — code needs review
- **"Done"** — confirmed complete or self-contained (docs, config)

## Rules

- **Always check images.** Use `extract_images` before starting work.
- **Don't over-comment.** Max 3 comments per task: pickup, milestone/question, completion.
- **Keep comments concise.** No boilerplate. Just state what happened.
- **Status is source of truth.** Always update it — don't leave tasks stale.
