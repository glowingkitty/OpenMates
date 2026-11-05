---
name: resume-tasks
description: Resume interrupted agent work from its existing Task and workspace.
user-invocable: true
---

Read the interrupted task's latest outcome and cached OpenMates Task state.
Inspect only its known session/workspace; use `sessions.py status --all` once if
ownership is unknown. Reuse the binding and preserved changes. Do not launch a
replacement terminal, invoke a retired restore command, or redo completed work.
Ask only if an unresolved decision blocks the remaining work. Ownership transfer
requires confirmation that the prior owner has stopped, then
`sessions.py worktree bind-task --session <id> --agent-task "$CLAUDE_CODE_SESSION_ID"
--expected-worktree <path> --previous-owner-stopped` (binds it to this conversation). Follow `CLAUDE.md` and `.claude/rules/testing.md`.
