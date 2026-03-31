---
name: openmates:resume-tasks
description: Discover interrupted Claude Code sessions from a crash and restore them in Zellij tabs
user-invocable: true
argument-hint: "[--all] [session-id]"
---

## Current State

!`python3 scripts/sessions.py restore --list --hours 24 2>/dev/null || echo "restore command not available"`

## Instructions

You help the user recover interrupted Claude Code sessions after a server crash or restart.

### Step 1: Show Discovered Sessions

The dynamic output above lists recently interrupted sessions, **pre-filtered** by:
- **Linear task status**: Sessions whose Linear task is Done, Cancelled, or In Review are hidden by default
- **Git commit history**: Cross-referenced with recent commits mentioning the OPE-XXX ID
- **Completion heuristics**: Last assistant message checked for deploy/completion phrases

Present the **open sessions** (status `INTR`) as a numbered table to the user with:
- Session ID (short prefix)
- Last active timestamp
- Status: `INTR` (interrupted, needs resuming)
- Task hint (Linear issue ID, action, and title)

If any sessions were filtered out, mention how many and that `--all` shows them.

### Step 2: Ask Which to Restore

Ask the user which sessions to restore. They can:
- Pick specific numbers from the list (e.g., "1, 3, 5")
- Say "all" to restore all open `INTR` sessions
- Say "skip" to not restore any
- Provide a specific session ID directly

### Step 3: Restore Selected Sessions

For each session to restore, run:

```bash
python3 scripts/sessions.py restore <session-id> --name <descriptive-name>
```

Use a descriptive Zellij session name based on the task (e.g., `restore-OPE-155`, `restore-OPE-176-verify`).

Launch them sequentially (each takes ~3s for Zellij to initialize).

### Step 4: Summary

After restoring, print a summary table:

| Zellij Session | Claude Session | Task | Attach Command |
|---|---|---|---|
| restore-OPE-155 | 661bcc8f... | OPE-155 fix | `zellij attach restore-OPE-155` |

Remind the user they can also see all sessions at http://localhost:8082

### Rules

- **Never restore sessions marked `DONE` or `REVIEW`** unless the user explicitly asks.
- **Max 10 concurrent Zellij sessions** — check `zellij list-sessions` before restoring.
- **Short session IDs work** — `sessions.py restore` supports prefix matching.
- If the user provides a session ID as an argument, skip discovery and restore it directly.
