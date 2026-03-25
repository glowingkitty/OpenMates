---
name: debug-issue
description: Investigate a user-submitted issue with timeline and debug data
user-invocable: true
argument-hint: "<issue-id>"
---

## Instructions

You are investigating a user-submitted issue. The issue ID was provided as an argument.

### Step 1: Fetch Issue Data

Run both commands to get the full picture:

```bash
# Timeline view (browser + backend events merged chronologically)
docker exec api python /app/backend/scripts/debug.py issue $ARGS --timeline

# Full metadata, decrypted fields, S3 YAML (IndexedDB, HTML snapshots, runtime state, screenshot)
docker exec api python /app/backend/scripts/debug.py issue $ARGS
```

For **production** issues, add `--production`:
```bash
docker exec api python /app/backend/scripts/debug.py issue $ARGS --timeline --production
```

### Step 2: Analyze

1. Read the timeline chronologically — identify the first error/anomaly
2. Check if the issue is frontend (browser) or backend (API/worker)
3. Look for related error patterns in the last 30 minutes
4. Check `git log -5 -- <suspected-file>` to see recent changes

### Step 3: Debugging Attempt Limit

**2 tries max** with the same approach. On the 3rd attempt, STOP, load the full debugging guide (`sessions.py context --doc debugging`), and propose a fundamentally different approach.

### Step 4: After Fix Confirmed

```bash
docker exec api python /app/backend/scripts/debug.py issue $ARGS --delete --yes
```

### Default Assumptions

- Issues are on the **dev server**, reported by an **admin**
- Check if another session is rebuilding Docker containers if services appear down
