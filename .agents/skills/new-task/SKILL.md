---
name: new-task
description: Create an OpenMates Task for a concrete engineering outcome.
user-invocable: true
---

Reuse a matching linked Task when one exists. Otherwise use installed `openmates
tasks create --title <outcome> --project <id>` and link the current host's Codex
thread with `--external-chat codex:<thread-id>` when available. Include only the
context, acceptance criteria and dependencies needed to execute. Ask for a
material missing decision; do not run a fixed questionnaire. Use GitHub/Linear
only when the user specifically assigns issue-tracker work. Shared policy:
`.claude/rules/task-management.md` and `AGENTS.md`.
