---
name: new-task
description: Create an OpenMates Task for a concrete engineering outcome, linked to this Claude conversation.
user-invocable: true
---

1. Reuse a matching Task when one exists:
   `openmates tasks list --external-chat "claude:$CLAUDE_CODE_SESSION_ID"` shows Tasks
   already linked to this conversation; otherwise search the engineering Project.
2. Otherwise create and link in one step:
   `openmates tasks create --title "<outcome>" --project <project-id>
   --external-chat "claude:$CLAUDE_CODE_SESSION_ID" --external-chat-title "<short chat title>"`.
   The CLI only links the conversation it runs in (the ID must equal
   `CLAUDE_CODE_SESSION_ID`); a Task has one owning conversation.
3. Include only the context, acceptance criteria and dependencies needed to
   execute. Record later changed outcomes with `openmates tasks activity add`.

Ask for a material missing decision; do not run a fixed questionnaire. GitHub
issues only when the user explicitly assigns issue-tracker work. Shared policy:
`.claude/rules/task-management.md` and `CLAUDE.md`.
