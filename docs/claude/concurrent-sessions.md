# Concurrent Session Coordination

Load this document when multiple assistants may be working simultaneously, when checking Vercel deployments, or when rebuilding Docker containers.

---

## Overview

Multiple Claude Code sessions can work on the codebase at the same time. To avoid conflicts (duplicate Vercel fixes, simultaneous Docker rebuilds, file edit collisions), all sessions coordinate through **`scripts/sessions.py`**, which manages state in **`.claude/sessions.json`** (gitignored).

File edit tracking is automated via the **OpenCode plugin** (`.opencode/plugins/session-tracker.ts`) — every Edit/Write operation is automatically recorded to the active session's `modified_files` list.

> **Note:** If you are using Claude Code (not OpenCode), file tracking is handled by `.claude/settings.json` hooks instead. The behaviour is identical from the agent's perspective.

---

## Quick Reference

| Action | Command |
| --- | --- |
| Start session | `python3 scripts/sessions.py start --task "description"` |
| End session | `python3 scripts/sessions.py end --session <ID>` |
| Check status | `python3 scripts/sessions.py status` |
| Update task | `python3 scripts/sessions.py update --session <ID> --task "new desc"` |
| Claim file for writing | `python3 scripts/sessions.py claim --session <ID> --file <path>` |
| Release file claim | `python3 scripts/sessions.py release --session <ID> --file <path>` |
| Track file as modified | `python3 scripts/sessions.py track --session <ID> --file <path>` |
| Acquire lock | `python3 scripts/sessions.py lock --session <ID> --type docker\|vercel` |
| Release lock | `python3 scripts/sessions.py unlock --session <ID> --type docker\|vercel` |
| Preview deployment | `python3 scripts/sessions.py prepare-deploy --session <ID>` |
| Deploy (lint+commit+push) | `python3 scripts/sessions.py deploy --session <ID> --title "msg" --message "body"` |

---

## Session Lifecycle

### Starting a Session

```bash
python3 scripts/sessions.py start --task "fix embed decryption for shared chats"
```

This command:

1. Generates a random 4-char hex session ID
2. Registers the session in `.claude/sessions.json`
3. Prunes stale sessions older than 24 hours
4. Clears stale locks older than 5 minutes
5. Outputs context to stdout:
   - Your session ID (save this for all subsequent commands)
   - Other active sessions and what files they own
   - Active locks
   - Stale architecture docs (code newer than doc by >24h)
   - Compact project index (backend apps, frontend components, API routes, providers)

### Ending a Session

```bash
python3 scripts/sessions.py end --session <ID>
```

This command:

1. Warns about any uncommitted modified files
2. Lists architecture docs that may need updating based on files you modified
3. Removes the session from `.claude/sessions.json`

---

## File Tracking

### Automatic Tracking (via OpenCode plugin)

The `.opencode/plugins/session-tracker.ts` plugin handles two operations automatically:

- **After edit/write**: Records every file you edit to your session's `modified_files` list (async, non-blocking). Calls `sessions.py track --file <path>` using the most-recently-active session.
- **Before edit/write**: Checks if another session has claimed the file for writing — throws an error to block the edit if so. Calls `sessions.py check-write --file <path>`.

This means **you do not need to manually track most files**. The plugin handles it.

The plugin is loaded automatically from `.opencode/plugins/` when OpenCode starts. It requires Bun (bundled with OpenCode) and the `@opencode-ai/plugin` package (installed via `.opencode/package.json` at startup).

### Manual Tracking

If you modify a file through Bash or other indirect means:

```bash
python3 scripts/sessions.py track --session <ID> --file path/to/file.py
```

### Write Claims (Exclusive Locks)

For operations where you need exclusive write access to a file (e.g., a complex multi-step edit):

```bash
# Claim before editing
python3 scripts/sessions.py claim --session <ID> --file path/to/file.py

# Release after editing
python3 scripts/sessions.py release --session <ID> --file path/to/file.py
```

If another session has claimed the file, `claim` exits with code 2 and prints which session owns it.

**Note:** Write claims are for the `writing` lock (active editing protection). The `modified_files` list is separate — it tracks all files touched in the session, regardless of write claims.

---

## Lock Protocol

Locks prevent multiple sessions from performing the same infrastructure operation simultaneously.

### Lock Types

| Lock | When to use |
| --- | --- |
| `docker` (→ `docker_rebuild`) | Before rebuilding/restarting Docker containers |
| `vercel` (→ `vercel_deploy`) | Before fixing a Vercel build error |

### Acquiring a Lock

```bash
python3 scripts/sessions.py lock --session <ID> --type docker
```

- If the lock is free → acquired
- If held by another session for <5 minutes → **BLOCKED** (exit code 1). Wait and retry.
- If held for >5 minutes → treated as stale, automatically taken over with a warning.

### Releasing a Lock

```bash
python3 scripts/sessions.py unlock --session <ID> --type docker
```

**Release locks immediately** after the operation completes.

### Why Locks Matter

Simultaneous Docker rebuilds can:

- Cause services to restart mid-operation, breaking other sessions' API calls
- Create race conditions where one rebuild overwrites another's container state
- Produce confusing "service unavailable" errors for all sessions

---

## Deployment Workflow

### Preview (prepare-deploy)

```bash
python3 scripts/sessions.py prepare-deploy --session <ID>
```

This shows:

- Files to be committed (tracked + git-dirty)
- Files already committed
- Files excluded from commit
- Dirty files not tracked by this session (other sessions' work)
- Lint results
- Related architecture docs to verify
- Exact git commands to run manually if preferred

### Deploy (lint + commit + push)

```bash
python3 scripts/sessions.py deploy --session <ID> \
  --title "fix: prevent duplicate messages after reconnect" \
  --message "Symptom: users saw duplicates after WebSocket reconnect\nCause: handler re-subscribed without clearing\nFix: clear subscriptions before re-establishing"
```

This:

1. Runs the linter on all files to be committed — **aborts if lint fails**
2. `git add` each file in the session's `modified_files` (minus exclusions)
3. `git commit` with the provided title and message
4. `git push origin dev`
5. Lists related architecture docs that may need updating

To exclude specific files from the commit:

```bash
python3 scripts/sessions.py deploy --session <ID> --title "..." --exclude path/to/skip.py
```

---

## Data Format

The `.claude/sessions.json` file has this structure:

```json
{
  "locks": {
    "docker_rebuild": {
      "status": "NONE"
    },
    "vercel_deploy": {
      "status": "NONE"
    }
  },
  "sessions": {
    "a3f2": {
      "task": "Fix embed decryption for shared chats",
      "started": "2026-03-06T18:00:00Z",
      "last_active": "2026-03-06T18:15:00Z",
      "modified_files": [
        "backend/apps/ai/skills/embed_resolve/skill.py",
        "frontend/packages/ui/src/components/embeds/EmbedCard.svelte"
      ],
      "writing": null
    }
  }
}
```

When a lock is held:

```json
{
  "docker_rebuild": {
    "status": "IN_PROGRESS",
    "claimed_by": "a3f2",
    "since": "2026-03-06T18:00:00Z",
    "last_updated": "2026-03-06T18:05:00Z"
  }
}
```

---

## Stale Architecture Doc Detection

The session start command automatically checks for stale architecture docs by comparing:

- Last modified date of each `docs/architecture/*.md` file
- Last modified dates of related code files (mapped in `docs/architecture/code-mapping.yml`)

If code files are newer than their architecture doc by more than 24 hours, the doc is flagged as potentially stale.

The session end command also checks which architecture docs are related to the files you modified, and reminds you to verify they are still accurate.

---

## Migration from sessions.md

The old `.claude/sessions.md` markdown-based coordination file has been replaced by `.claude/sessions.json`. The old file is no longer used. Key improvements:

- **Automatic file tracking** via OpenCode plugin (no manual "Currently Editing" updates)
- **Structured JSON** instead of fragile markdown tables
- **Automatic stale cleanup** (sessions >24h, locks >5min)
- **Integrated deployment** (lint + commit + push with file tracking)
- **Architecture doc staleness detection** built in
- **Write collision prevention** via PreToolUse hooks
