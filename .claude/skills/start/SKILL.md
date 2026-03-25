---
name: start
description: Start a new sessions.py session with appropriate mode and context
user-invocable: true
argument-hint: "<mode> <task description> [flags]"
---

## Instructions

Start a new session using sessions.py. Parse the user's arguments to determine:

1. **Mode** (required): `feature`, `bug`, `docs`, `question`, `testing`
2. **Task description** (required): Brief description of the work
3. **Optional flags**: Pass through any prefetch flags

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
