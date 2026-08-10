---
status: draft
doc_type: architecture-decision
audience:
  - product
  - contributors
  - technical-users
related_specs:
  - docs/specs/tasks-v1/spec.yml
  - docs/specs/plans-v1/spec.yml
  - docs/specs/workflows-v1/spec.yml
related_issues:
  - https://github.com/glowingkitty/OpenMates/issues/447
last_updated: 2026-07-13
---

# Tasks V1 Architecture

## Purpose

Tasks are privacy-preserving, durable work items owned by one user. They give a
chat an explicit queue of work that a user or AI mate can execute, pause, resume,
and complete. Tasks are separate from Celery task polling and chat messages.

This document is the editable product and architecture decision record. The
executable implementation contract, task ledger, and verification evidence live
in `docs/specs/tasks-v1/spec.yml`.

## Current Foundation

- `user_tasks`, `user_task_activity`, and task-key-wrapper collections exist.
- Durable private content is encrypted client-side with one task key per task.
- The backend retains only ownership, status, routing, scheduling, ordering, and
  other minimal metadata.
- `/v1/user-tasks` supports list, create, update, proposal extraction, AI start,
  and key-wrapper operations.
- The CLI, npm SDK, and Python SDK contain initial task API contracts.
- The web app contains a disabled task board, chat task preview, project task
  section, and basic task detail page.
- AI requests launched from a task can mark the task done or blocked.

## First Working Release

### Goal

Prove that a user can operate reliable standalone and chat-scoped AI task queues
through the CLI before releasing broader web or Apple surfaces.

### In Scope

- Create, list, update, inspect, delete, block, unblock, skip, complete, reorder,
  and start encrypted tasks from account-wide CLI commands and chat-scoped CLI
  commands.
- Support standalone tasks, and automatically create a working chat when a
  standalone AI/OpenMates task starts.
- Render a terminal Kanban board and a keyboard-navigable Tasks workspace in the
  CLI TUI.
- Start one eligible AI-assigned task in a chat queue.
- Mark a completed task done and automatically start the next eligible task.
- Stop the queue when the active task needs user input, permissions, an account,
  file access, or another external dependency.
- Resume the queue after the user resolves the blocker.
- Prevent duplicate execution during retries, worker restarts, and concurrent
  task-start attempts.
- Provide CLI output that makes current task, queue position, status, blocker,
  and next eligible task observable.
- Enforce assistant continuation with explicit task tools so task-mode execution
  stops only after all eligible tasks finish/skip/backlog or a blocker requiring
  user input is recorded.

### Explicitly Deferred

- Due-date scheduling and recurring tasks.
- Public or shared task links.
- Voice recording and transcription UI.
- Workflow-run projections in the task board.
- Rich task history, custom Kanban columns, multi-assignee tasks, and team
  collaboration.
- Web and Apple release work.

## Decisions To Make

### Queue Ownership

Decision: tasks can be standalone or linked to a chat, project, and plan. Every
AI/OpenMates-executed task must have a working chat. Starting a standalone AI
task creates and links a new working chat before dispatch, so users can inspect
the work and synced devices can load the context later.

### Eligible Task Selection

Recommended first policy:

1. Only one task may be `in_progress` for a chat.
2. The next task is the earliest `todo` AI-assigned task by queue position.
3. `backlog`, `blocked`, `done`, user-assigned, and future-due tasks are not
   eligible.
4. A completed task starts the next task only after its completion update is
   durably committed.

Open decisions:

- Does priority override queue position?
- Can a user move a later task ahead of the queue while another task runs?
- Is a manually moved `in_progress` task allowed to preempt the active task?

### Blockers And Resume

Recommended first policy:

- The AI records a safe blocker code, never private task text.
- A blocked task prevents automatic continuation for the remaining chat queue.
- The user or assistant resumes explicitly after satisfying the missing requirement.
- Resume either retries the blocked task or allows the user to mark it done,
  skip it to backlog, or return it to todo.
- Skip keeps the task linked to the chat, sets queue metadata to skipped, moves
  the task to backlog, and starts the next eligible todo task.

Open decisions:

- Which blocker codes are stable in V1?
- Which user actions constitute a verified blocker resolution?

### Encryption And Execution Context

Durable title, description, tags, and instructions remain client-encrypted.
Task execution requires temporary plaintext context, so it must use a
short-lived Vault-encrypted execution context rather than durable task fields.

The context design must specify:

- Who creates the context and when it expires.
- The minimum plaintext required to execute one task.
- How a queued task is resumed after a worker restart.
- How context absence or expiry becomes `blocked: missing_execution_context`.
- How expiration cleanup avoids deleting active or blocked tasks.

### Idempotency

The queue transition must have one durable owner and an idempotency key or
equivalent atomic claim. Retry paths must not create duplicate AI requests,
working chats, or completion transitions.

## Required State Model

### Product Task Status

| Status | Meaning | Can Auto-Start |
| --- | --- | --- |
| `backlog` | Intentionally parked | No |
| `todo` | Ready when eligible | Yes, if assigned to AI |
| `in_progress` | Current work for the chat | Already running |
| `blocked` | Needs explicit user or external resolution | No |
| `done` | Completed work | No |

Queue metadata is separate from product status. V1 includes at least `none`,
`waiting`, `active`, `waiting_for_user`, and `skipped`; skipped tasks remain in
`backlog` rather than creating a sixth Kanban status.

### AI Execution State

The execution state is safe metadata, separate from the visible status. It
should describe queue and dispatch lifecycle without storing private task text.

Candidate states: `queued`, `running`, `waiting_for_previous_task`, `blocked`,
`completed`, `failed`, and `cancelled`.

## CLI Contract

The first release should support an observable workflow equivalent to:

```text
openmates tasks create --title "..." --assign openmates
openmates tasks list --project OM
openmates tasks board --project OM
openmates tasks show OM-6
openmates tasks start OM-6
openmates tasks block OM-6 --reason user_input_required
openmates tasks unblock OM-6
openmates tasks skip OM-6
openmates tasks reorder OM-8 --before OM-6
openmates chats <chat-id> tasks board
openmates chats <chat-id> tasks done OM-6
```

CLI output decrypts task content locally by default on authenticated devices.
Machine-readable `--json` output returns locally decrypted task content plus safe
metadata for scripts. The CLI TUI also exposes a Tasks workspace with
keyboard-navigable Kanban and task detail pages for the same actions.

## Verification Strategy

### Deterministic Backend Coverage

- Fake AI dispatcher proves only one task dispatches at a time.
- Completion starts exactly one next eligible task.
- A blocker stops continuation.
- A resume restarts the blocked task or continues according to the chosen policy.
- Retry and restart cases do not duplicate dispatches.
- Expired execution context blocks safely and cannot expose plaintext.

### Dev CLI Smoke Flow

1. Create one standalone OpenMates task and verify a working chat is created on start.
2. Create one chat and three chat-scoped AI tasks.
3. Render `openmates tasks board` and `openmates chats <chat> tasks board`.
4. Keyboard-navigate the CLI TUI Tasks workspace and open a task detail page.
5. Start the queue and inspect task 1 as active.
6. Complete task 1 and inspect task 2 as active.
7. Force task 2 to require input and inspect task 3 as unchanged.
8. Skip task 2 and verify it moves to backlog with skipped queue metadata while task 3 starts once.
9. Resolve/unblock a blocked task and verify the queue resumes.
10. Repeat a transition after a controlled worker restart.

## Delivery Sequence

1. Define and implement encrypted execution contexts and atomic queue claims.
2. Complete backend queue continuation and blocker/resume behavior.
3. Add deterministic backend tests, task tools, CLI commands, and CLI TUI tasks workspace.
4. Run the dev CLI/TUI smoke flow repeatedly until reliable.
5. Add due-date scheduling and cleanup only after the basic queue is stable.
6. Add SDK facades and parity tests.
7. Build the web MVP over the proven CLI/runtime contract.
8. Add Apple parity after web behavior is stable.

## Related Sources

- `backend/core/api/app/routes/user_tasks.py`
- `backend/core/api/app/services/user_task_service.py`
- `backend/core/api/app/services/user_task_scheduler_service.py`
- `backend/apps/ai/tasks/ask_skill_task.py`
- `backend/core/directus/schemas/user_tasks.yml`
- `frontend/packages/openmates-cli/src/client.ts`
- `frontend/packages/openmates-cli/src/cli.ts`
- `frontend/packages/openmates-cli/src/tui.ts`
- `frontend/packages/openmates-cli/src/tuiRenderer.ts`
- `frontend/packages/ui/src/services/userTaskService.ts`
