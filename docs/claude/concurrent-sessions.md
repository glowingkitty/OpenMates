# Concurrent Session Coordination

Load this document when multiple assistants may be working simultaneously, when checking Vercel deployments, or when rebuilding Docker containers.

---

## Overview

Multiple Claude Code sessions can work on the codebase at the same time. To avoid conflicts (duplicate Vercel fixes, simultaneous Docker rebuilds, file edit collisions), all sessions coordinate through a shared file: **`.claude/sessions.md`**.

This file is **gitignored** — it lives only on the dev server and is never committed.

---

## Session Identity

Each session must identify itself with a unique short ID.

### Generating Your Session ID

On your **first interaction** in a new session, generate a random 4-character hex ID:

```bash
# Generate a random session ID
python3 -c "import secrets; print(secrets.token_hex(2))"
```

This gives you something like `a7f3` or `e1b2`. Use this as your session ID for the entire conversation.

### Registering Your Session

After generating your ID, add yourself to the **Active Sessions** table in `.claude/sessions.md`:

```markdown
| a7f3 | 2026-02-20T10:00:00Z | 2026-02-20T10:00:00Z | - |
```

Update the `Last Active` timestamp whenever you make a significant action (commit, push, start a build).

---

## Lock Protocol

Locks are used to prevent multiple sessions from performing the same operation simultaneously. There are two locks:

1. **Vercel Deployment Lock** — claimed when fixing a Vercel build error
2. **Docker Rebuild Lock** — claimed when rebuilding/restarting Docker containers

### Acquiring a Lock

Before attempting a Vercel fix or Docker rebuild:

1. **Read** `.claude/sessions.md`
2. **Check the relevant lock section:**
   - If `Status: NONE` → proceed to step 3
   - If `Status: IN_PROGRESS`:
     - Parse the `Last updated` timestamp
     - If it is **less than 5 minutes old** → another session is actively working. **Do NOT claim the lock.** Go to step 4.
     - If it is **5 minutes or older** → the lock is stale (the holding session likely crashed). Proceed to step 3 to take over.
3. **Claim the lock** by editing the file:

   ```markdown
   ## Vercel Deployment Lock

   - **Status:** IN_PROGRESS
   - **Claimed by:** a7f3
   - **Error:** Type error in ChatMessage.svelte line 42
   - **Since:** 2026-02-20T10:35:00Z
   - **Last updated:** 2026-02-20T10:35:00Z
   ```

4. **If another session holds the lock (step 2, <5 min):**
   - Wait 30 seconds
   - Re-read `.claude/sessions.md`
   - Check if the lock has been released or if it's now stale
   - Repeat until the lock is available (up to ~5 minutes of waiting)
   - If you've waited 5+ minutes and the lock was never updated, treat it as stale and claim it

### Holding a Lock

While holding a lock:

- **Update the `Last updated` timestamp at least every 60 seconds**, or at each meaningful step (e.g., after committing a fix, after pushing, while waiting for Vercel)
- This tells other sessions you're still alive and working

### Releasing a Lock

**Immediately** after the fix is confirmed (Vercel shows "Ready", Docker containers are up), release the lock:

```markdown
## Vercel Deployment Lock

- **Status:** NONE
- **Claimed by:** -
- **Error:** -
- **Since:** -
- **Last updated:** -
```

### Staleness Timeout

- A lock is considered **stale** if `Last updated` is **5 minutes or older**
- Stale locks can be overwritten by any session — the holding session is assumed to have crashed
- This prevents deadlocks from crashed sessions

---

## Vercel Deployment Coordination

### When You Push Frontend Changes

After pushing and waiting for the Vercel build:

1. Check `vercel ls open-mates-webapp 2>&1 | head -5`
2. If the status is **"Ready"** → done, no lock needed
3. If the status is **"Error"**:
   - **Read `.claude/sessions.md`** and check the Vercel lock
   - If another session already claimed the lock → wait and poll (see "Acquiring a Lock" above)
   - If no lock is held → claim the lock, then proceed to fix the error
   - After fixing, pushing, and confirming "Ready" → release the lock

### When Another Session Is Fixing a Vercel Error

If you see `Status: IN_PROGRESS` on the Vercel lock:

1. **Do NOT attempt your own fix** — this would create conflicting commits
2. Wait 30 seconds, then re-read the file
3. Repeat until the lock is released
4. Once released, run `vercel ls` again to confirm the deployment is now "Ready"
5. If the deployment is still broken after the lock was released, you may claim the lock and attempt your own fix

---

## Docker Rebuild Coordination

### Before Rebuilding Containers

1. **Read `.claude/sessions.md`** and check the Docker Rebuild Lock
2. If another session holds the lock → wait (same polling protocol as Vercel)
3. If no lock is held → claim the lock with the services you're rebuilding:

   ```markdown
   ## Docker Rebuild Lock

   - **Status:** IN_PROGRESS
   - **Claimed by:** a7f3
   - **Services:** api, task-worker
   - **Since:** 2026-02-20T11:00:00Z
   - **Last updated:** 2026-02-20T11:00:00Z
   ```

4. Rebuild and restart the containers
5. Verify they're healthy
6. **Release the lock immediately**

### Why This Matters

Simultaneous Docker rebuilds can:

- Cause services to restart mid-operation, breaking other sessions' API calls
- Create race conditions where one rebuild overwrites another's container state
- Produce confusing "service unavailable" errors for all sessions

---

## File Ownership Tracking

The **Active Sessions** table helps avoid merge conflicts by showing which files each session is editing.

### Updating Your Entry

Before editing a file, update your `Currently Editing` column:

```markdown
| a7f3 | 2026-02-20T10:00:00Z | 2026-02-20T10:35:00Z | frontend/packages/ui/src/components/ChatMessage.svelte |
```

For multiple files, separate with commas:

```markdown
| a7f3 | 2026-02-20T10:00:00Z | 2026-02-20T10:35:00Z | ChatMessage.svelte, ChatInput.svelte |
```

### After Committing

After you commit and push, clear your `Currently Editing` to `-` (since those files are now committed and available to others).

### When You See a Conflict

If another session is editing a file you need:

- **If it's a minor overlap** (e.g., different functions in the same file): proceed carefully, re-read the file before editing
- **If it's a major overlap** (e.g., same component, same function): wait for the other session to commit first, then pull and continue

---

## Session Cleanup

### When Your Session Ends

Remove your row from the Active Sessions table. If you forget, other sessions will treat entries with `Last Active` older than 30 minutes as inactive.

### Stale Session Entries

Any session may clean up Active Sessions entries where `Last Active` is more than 30 minutes old — these sessions are assumed to have ended.

---

## Quick Reference

| Action                   | Protocol                                                 |
| ------------------------ | -------------------------------------------------------- |
| Starting a session       | Generate ID, register in Active Sessions                 |
| Pushing frontend changes | Check Vercel → if error, check lock → claim or wait      |
| Rebuilding Docker        | Check Docker lock → claim or wait                        |
| Editing a file           | Update `Currently Editing` column                        |
| After committing         | Clear `Currently Editing` to `-`                         |
| Seeing a lock held       | Wait 30s, re-read, repeat. After 5 min stale → take over |
| Finishing a fix          | Release lock immediately (set Status to NONE)            |
| Session ending           | Remove your row from Active Sessions                     |

---

## File Location

The coordination file is at: **`.claude/sessions.md`** (project root)

This file is gitignored. If it doesn't exist, create it from the template. The template is documented in this file — see the sections above for the expected format, or copy from a fresh state:

```markdown
# Claude Session Coordination

> This file is used by concurrent Claude Code sessions to avoid conflicts.
> It is gitignored and lives only on the dev server.
> DO NOT commit this file. See docs/claude/concurrent-sessions.md for the full protocol.

## Vercel Deployment Lock

- **Status:** NONE
- **Claimed by:** -
- **Error:** -
- **Since:** -
- **Last updated:** -

## Docker Rebuild Lock

- **Status:** NONE
- **Claimed by:** -
- **Services:** -
- **Since:** -
- **Last updated:** -

## Active Sessions

| Session ID | Started | Last Active | Currently Editing |
| ---------- | ------- | ----------- | ----------------- |
```
