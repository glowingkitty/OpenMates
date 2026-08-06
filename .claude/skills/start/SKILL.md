---
name: start
description: Start or reuse a top-level sessions.py session before mutating work. Use only in the main conversation, never inside a task child.
user-invocable: true
argument-hint: "<mode> <task description> [flags]"
---

## Instructions

Start a new session using sessions.py. Parse the user's arguments to determine:

1. **Mode** (required): `feature`, `bug`, `docs`, `question`, `testing`
2. **Task description** (required): Brief description of the work
3. **Optional flags**: Pass through any prefetch flags

Do not invoke this skill from a task child. Read-only research, review, and status commands do not need a repository session. Repeated calls for the same OpenCode chat are idempotent and reuse its existing mapping.

Normalize common intent words before invoking the command: `debug` to `bug`, `execute` to `feature`, and `plan`, `investigate`, or `investigation` to `question`.

```bash
python3 scripts/sessions.py start --mode <MODE> --task "<TASK>" [flags]
```

### Available Prefetch Flags

| Flag | When to use |
|------|-------------|
| `--issue <ID>` | Investigating a user-submitted issue |
| `--chat <ID>` | Debugging a specific chat |
| `--embed <ID>` | Debugging a specific embed |
| `--logs` | Check recent server logs (last 10 min) |
| `--logs "since=30,level=error"` | Custom log query |
| `--user <EMAIL>` | Debugging user-specific issue |
| `--debug-id <ID>` | Check debug session logs |
| `--vercel` | Check latest Vercel deployment |
| `--run-id <ID>` | Debug a test run |
| `--since-last-deploy` | Show commits since last deploy |
| `--task-id <ID>` | Resume a multi-session task |

### After Start

Read the session output carefully — it contains:
- Session ID (use for all subsequent commands)
- Mode-specific context (health, errors, project index, etc.)
- Backlog items (address if related)
- Instruction docs (loaded by tags)
