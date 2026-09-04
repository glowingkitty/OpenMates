---
status: active
last_verified: 2026-08-05
---

# Concurrent Session Coordination

Load this document when multiple assistants may be working simultaneously, when checking Vercel deployments, or when rebuilding Docker containers.

---

## Overview

Multiple agent sessions can work on the codebase at the same time. Use **`scripts/sessions.py`** for deploy selection, Docker locks, and the short dev deploy push lock. Its `.claude/sessions.json` file is gitignored and records work already touched; it does not reserve ordinary source files.

File edit tracking is automated via hooks in `.claude/settings.json` — every Edit/Write operation is automatically recorded to the active session's `modified_files` list.

New mutating OpenCode Web chats begin through the normal **New session** button
and remain at the root project URL. After `sessions.py start`, hooks route local
reads, searches, edits, Bash commands, generators, tests, and Task children into
the direct `agent-<session>` worktree. Routing is reconstructed from durable
session and parent metadata after restart. Missing routing never blocks reads or
lifecycle recovery; mutation errors include one `Reason:` and exact `Next:` step.

---

## Quick Reference

| Action                    | Command                                                                            |
| ------------------------- | ---------------------------------------------------------------------------------- |
| Start session             | `python3 scripts/sessions.py start --task "description"`                           |
| End session               | `python3 scripts/sessions.py end --session <ID>`                                   |
| Check status              | `python3 scripts/sessions.py status`                                               |
| Show all history          | `python3 scripts/sessions.py status --all`                                         |
| Show active conflicts     | `python3 scripts/sessions.py status --conflicts`                                   |
| Show one identity chain   | `python3 scripts/sessions.py status --session <ID>`                                |
| Claim executable task     | `python3 scripts/sessions.py presence claim-task --spec <spec.yml> --task <TASK-ID> --owner <OpenCode-ID> --role implementation` |
| Update task               | `python3 scripts/sessions.py update --session <ID> --task "new desc"`              |
| Release file claim        | `python3 scripts/sessions.py release --session <ID> --file <path>`                 |
| Track file as modified    | `python3 scripts/sessions.py track --session <ID> --file <path>`                   |
| Acquire lock              | `python3 scripts/sessions.py lock --session <ID> --type docker\|vercel`            |
| Release lock              | `python3 scripts/sessions.py unlock --session <ID> --type docker\|vercel`          |
| Preview deployment        | `python3 scripts/sessions.py prepare-deploy --session <ID>`                        |
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
   - Other active sessions and files they have touched (advisory only)
   - Active locks
   - Stale architecture docs (code newer than doc by >24h)
    - Compact project index (backend apps, frontend components, API routes, providers)

For a new mutating OpenCode Web chat, hooks bind the OpenCode identity to this
session record without moving the chat. Use repository-relative paths; the hook
overwrites Bash `workdir` and local file/search paths with the active worktree.
Run `python3 scripts/sessions.py worktree repair --opencode-session <id>` only
when an actionable routing message requests it.

### Ending a Session

```bash
python3 scripts/sessions.py end --session <ID>
```

This command:

1. Warns about any uncommitted modified files
2. Lists architecture docs that may need updating based on files you modified
3. Removes the session from `.claude/sessions.json`

### Live Presence

The OpenCode plugin observes native lifecycle events without sending messages or
starting assistant turns. `sessions.py status` therefore defaults to current
runtime state instead of treating a recent or merged worktree as live work:

- **Currently working:** busy or retrying sessions with a fresh heartbeat.
- **Waiting for required user input:** supported pending permission or question IDs.
- **Idle after completed response:** completed turns that are not collision owners.
- **Stopped or failed:** explicit abort and error outcomes.

Use `--all` for durable and historical repository sessions, `--conflicts` for
active path/task conflicts, and `--session <short-or-OpenCode-ID>` for one parent,
child, repository-session, and worktree identity chain. Busy records become
`unknown` after two minutes without a heartbeat. Terminal records, child-role
markers, and expired task claims have bounded retention.

Presence lives in owner-only `.opencode/presence.json`, separate from
`.claude/sessions.json`. It stores structured IDs, states, timestamps,
capabilities, and repository-relative paths only. It does not store titles,
prompts, responses, reasoning, todos, question text, permission details, tool
input/output, logs, patches, environment values, or credentials.

---

## File Tracking

### Tracking And OpenCode Edit Leases

The `.claude/settings.json` configures two hooks:

- **PostToolUse** on `Edit|Write`: Automatically records every file you edit to your session's `modified_files` list (async, non-blocking)
- **PreToolUse**: warns when another session has touched the file.

Tracking remains advisory for historical `modified_files` ownership. Re-read the file immediately before editing and resolve an actual diff if one exists. Do not wait merely because another session touched it earlier.

OpenCode execute-mode source edits add a stricter guard: before an edit tool writes a repository file, `.opencode/plugins/openmates-hooks.js` acquires a short-lived `sessions.py edit-lease` for every edited file. A live lease blocks other OpenCode sessions from editing the same file until the first edit finishes or the stale 5-minute window expires. Use `python3 scripts/sessions.py status` to inspect active edit leases.

### Manual Tracking

If you modify a file through Bash or other indirect means:

```bash
python3 scripts/sessions.py track --session <ID> --file path/to/file.py
```

### Write Claims (Rare Manual Locks)

For an unusually long, manually coordinated multi-step edit:

```bash
# Claim before editing
python3 scripts/sessions.py claim --session <ID> --file path/to/file.py

# Release after editing
python3 scripts/sessions.py release --session <ID> --file path/to/file.py
```

If another session has an active manual claim or OpenCode edit lease, `claim` exits with code 2. OpenCode edit tools acquire short-lived leases automatically; manual claims are still only for unusually long human-coordinated edits.

**Note:** `modified_files` tracks all files touched in a session for deployment selection. It is not ownership and must not block another session's edit.

### Plan Task Claims

Claim an implementation task before starting its feature code:

```bash
python3 scripts/sessions.py presence claim-task \
  --plan docs/plans/<slug>/plan.yml --task TASK-2 \
  --owner <OpenCode-session-ID> --role implementation --ttl 900
```

Renew with `presence renew-task` and release with `presence release-task` using
the same `--plan`, `--task`, and `--owner`. A second live implementation claim
exits with code 2. Explicit `reviewer` and `read_only` claims remain non-blocking.
Expired claims can be taken over deterministically.

Child hierarchy does not imply ownership. A child may read through its parent's
route, but `unknown`, `read_only`, and `reviewer` children cannot mutate the
parent worktree. Even an explicitly `writable` child must first own a separate
repository session/worktree with disjoint file and task ownership.

Conflict delivery stays local and relevant. Concurrent reads and unrelated work
add no context. A read overlapping a fresh live edit may append one concise
warning to that read's tool output; exact write conflicts remain blocked by the
existing edit lease and stale-read guards. No coordination message is inserted
into either chat.

Run the isolated real-runtime gate after changing lifecycle behavior:

```bash
python3 scripts/verify_opencode_presence_live.py --isolated
```

The verifier uses temporary XDG state, a temporary Git fixture, random ports,
and a deterministic local streaming provider. It never uses the normal OpenCode
server or an external model.

---

## Docker Restart Protocol

Coordinated restarts prevent infrastructure changes from interrupting tests that depend on the local dev stack.

### Restarting Services

```bash
python3 scripts/sessions.py docker restart --session <ID> --service api
python3 scripts/sessions.py docker restart --session <ID> --build --service api --service task-worker
```

- New Playwright, CLI, and aggregate runs wait once a restart is queued.
- Already-running dependent tests drain before Compose changes containers.
- The command acquires, heartbeats, and releases the Docker lock automatically.
- Completion requires every selected service to be running and healthy.
- `sessions.py status` shows active test leases, restart progress, and recent outcomes.
- Crashed test/restart owners are detected so stale work cannot block the stack indefinitely.

Manual `lock/unlock` remains available for non-restart Docker maintenance. Raw Compose restarts are rejected by the OpenCode hook because they bypass test draining and health evidence.

### Why Locks Matter

Uncoordinated Docker rebuilds can:

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
- The exact scoped deploy command to run next

### Deploy (lint + commit + push)

```bash
python3 scripts/sessions.py deploy --session <ID> \
  --title "fix: prevent duplicate messages after reconnect" \
  --message "Symptom: users saw duplicates after WebSocket reconnect\nCause: handler re-subscribed without clearing\nFix: clear subscriptions before re-establishing"
```

This:

1. Fetches the exact current `origin/dev` commit and creates a unique detached `integration-<session>-<nonce>` worktree
2. Applies and stages only the selected source-worktree patch there, including deletions, binary changes, executable bits, and untracked files
3. Runs lint, generated-prerequisite, translation, parity, pytest, SDK, and embed gates in that integration checkout; a failure leaves root, source, and `dev` unchanged
4. Takes the short dev deploy push lock, refreshes `origin/dev`, and rebuilds plus reruns gates outside the lock if the validated base advanced
5. Commits in the detached integration checkout and pushes `HEAD:refs/heads/dev` without force
6. Records the patch, source base, final base, integration identity, and resulting commit for reconciliation and commit-scoped verification
7. Removes disposable integration state while retaining any unique or uncertain source worktree state

Every managed session worktree, including a restored grandfathered session,
deploys through the disposable integration checkout. Deployment never copies a
session patch into the shared root checkout. A local root that cannot
fast-forward after a successful push is informational and does not downgrade the
deployment result.

Use `--use-staged` when the staged file set is the intended exact scope, or
`--only <path> [...]` for an explicit tracked-dirty file set. `prepare-deploy`
prints a deterministic manifest ID; pass it back with
`--expected-manifest-id <id>` to reject source or selection drift.

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

- **Automatic file tracking** via hooks (no manual "Currently Editing" updates)
- **Structured JSON** instead of fragile markdown tables
- **Automatic stale cleanup** (sessions >24h, locks >5min)
- **Integrated deployment** (lint + commit + push with file tracking)
- **Architecture doc staleness detection** built in
- **Write collision prevention** via PreToolUse hooks
