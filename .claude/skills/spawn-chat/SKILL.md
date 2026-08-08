---
name: spawn-chat
description: Spawn a persisted OpenCode Web chat in the existing project sidebar and ensure it starts its own sessions.py worktree. Use when the user explicitly asks for a new, separate, or parallel chat/session.
user-invocable: true
argument-hint: "<plan|execute> <short name> <task>"
---

# Spawn Chat

Create one independent OpenCode chat without duplicating work or leaving empty
sessions behind.

## Workflow

1. Require explicit user approval before spawning. A direct request to create,
   spawn, or parallelize chats is approval.
2. Confirm the work is independent from files being edited in the current chat.
   Do not spawn when tasks have sequential dependencies or likely file overlap.
3. Use `plan` by default. Use `execute` only when the user explicitly requests
   implementation or direct fixes.
4. Choose a unique lowercase chat name with hyphens, no secrets, and at most
   50 characters. It becomes the OpenCode chat title.
5. Include this as the spawned chat's first required action:

   ```text
   Before edits, Bash-heavy investigation, or child tasks, run:
   python3 scripts/sessions.py start --mode <feature|bug|docs|question|testing> --task "<task>"
   Use the returned short session ID for tracking, verification, deploy, and end.
   Do not spawn another chat.
   ```

6. Launch exactly once:

   ```bash
   python3 scripts/sessions.py spawn-chat --prompt "<complete prompt>" --name "<name>" --mode <plan|execute>
   ```

7. Verify the command prints an OpenCode session ID or a pending message. Then
   verify a matching repository session appears with
   `python3 scripts/sessions.py status --json`. Allow the chat time to execute
   its required start command.
8. If verification fails, inspect the spawned chat with
   `python3 scripts/sessions.py chat read <session-id>` or search it
   with `python3 scripts/sessions.py chat search <session-id> "error"`.
   Do not retry `spawn-chat` blindly because retries create duplicate chats.
9. Report the chat name, mode, OpenCode session ID/sidebar URL, repository
   session ID, and task.

## Guardrails

- `spawn-chat` must launch a persisted OpenCode Web chat, never the Claude Code runtime and never a new Zellij session.
- Never pass secrets, credentials, private logs, or user data in the prompt or
  chat name.
- Never give two execute chats overlapping file ownership.
- Never use a spawned chat to bypass approval, deployment, privacy, or security
  gates.
