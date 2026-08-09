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
3. Choose the least-capable mode that can complete the spawned task:
   - Use `plan` only for pure planning or review that can be completed without
     Bash, repository session start, file reads/searches, or test artifacts.
   - Use `execute` for read-only investigations that need Bash, repo scripts,
     `sessions.py start`, file reads/searches, or test artifacts. If the user
     did not approve implementation, make the prompt explicitly read-only.
   - Use `execute` for implementation or direct fixes only when the user
     explicitly requests code changes in the spawned chat.
4. Choose a unique lowercase chat name with hyphens, no secrets, and at most
   50 characters. It becomes the OpenCode chat title.
5. For every `execute` spawned chat, include this as the first required action:

   ```text
   Before edits, Bash-heavy investigation, or child tasks, run:
   python3 scripts/sessions.py start --mode <feature|bug|docs|question|testing> --task "<task>"
   Use the returned short session ID for tracking, verification, deploy, and end.
   Do not spawn another chat.
   ```

   For read-only investigations in `execute` mode, also include:

   ```text
   This is execute mode only so read-only Bash/status commands are available.
   Do not edit, write, create, delete, deploy, commit, apply patches, or modify files.
   ```

6. Launch exactly once:

   ```bash
   python3 scripts/sessions.py spawn-chat --prompt "<complete prompt>" --name "<name>" --mode <plan|execute>
   ```

7. Verify the command prints an OpenCode session ID/sidebar URL or a pending
   message. Spawned OpenCode Web chats appear in the project sidebar; they do
   not create Zellij sessions.
8. For `execute` chats, verify a matching repository session appears with
   `python3 scripts/sessions.py chat read <session-id>`, then inspect the
   mapped repository session with
   `python3 scripts/sessions.py status --session <repo-session-id>`. Allow the
   chat time to execute its required start command.
9. If verification fails, inspect the spawned chat with
   `python3 scripts/sessions.py chat read <session-id>` or search it
   with `python3 scripts/sessions.py chat search <session-id> "error"`.
   If a `plan` chat has no usable assistant response or shows a permission
   rejection for required Bash/session startup, report it as canceled/blocked
   and spawn at most one replacement `execute` read-only chat only when the
   user approved that investigation. Do not retry `spawn-chat` blindly because
   retries create duplicate chats.
10. Report the chat name, mode, OpenCode session ID/sidebar URL, repository
   session ID, and task.

## Guardrails

- `spawn-chat` must launch a persisted OpenCode Web chat, never the Claude Code runtime and never a new Zellij session.
- Never pass secrets, credentials, private logs, or user data in the prompt or
  chat name.
- Never give two execute chats overlapping file ownership.
- Never use a spawned chat to bypass approval, deployment, privacy, or security
  gates.
