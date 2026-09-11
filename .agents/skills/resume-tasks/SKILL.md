---
name: resume-tasks
description: Resume interrupted Codex work from its existing Task and workspace.
user-invocable: true
---

Read the interrupted task's latest outcome and cached OpenMates Task state.
Inspect only its known session/workspace; use `sessions.py status --all` once if
ownership is unknown. Reuse the binding and preserved changes. Do not launch a
replacement terminal, invoke a retired restore command, or redo completed work.
Ask only if an unresolved decision blocks the remaining work. Ownership transfer
requires the existing bind-codex procedure and confirmation that the prior owner
has stopped. Follow `AGENTS.md` and `.claude/rules/testing.md`.
