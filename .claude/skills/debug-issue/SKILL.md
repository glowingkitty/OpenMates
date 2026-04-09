---
name: debug-issue
description: Investigate a user-submitted issue with timeline and debug data
user-invocable: true
argument-hint: "<issue-id>"
---

## Instructions

You are investigating a user-submitted issue. The issue ID was provided as an argument.

### Step 1: Delegate forensics to the `issue-forensics` subagent

Launch the `issue-forensics` agent with this prompt:

> Investigate issue `$ARGS`. Run `debug.py issue --timeline` + the full metadata dump, follow any trace IDs, identify the first anomaly, and return the structured JSON + narrative. Add `--production` if this is a prod issue.

The agent runs all `debug.py` commands, correlates browser↔backend events, git-blames suspects, and returns a compact report with `first_anomaly`, `root_cause_hypothesis`, `suspect_files[]`, `reproduction_steps`, and `related_recent_commits`.

**If the symptom looks like encryption / decryption / chat sync:** after `issue-forensics` returns, also launch `encryption-flow-tracer` with the first anomaly message as the symptom — it will pinpoint the broken invariant in the E2EE/sync data flow.

**Do NOT run `debug.py` commands yourself** — that floods main context with timeline noise. Trust the agents' compact reports.

### Step 2: Write the Fix

Using the agent's `suspect_files` and narrative:
1. Read the suspect code (20–40 lines around the reported line)
2. Confirm the hypothesis fits
3. Apply the minimal fix

### Step 3: Debugging Attempt Limit

**2 tries max** with the same approach. If the agent's first hypothesis fails, re-launch it with your new context ("the fix at X did not resolve the issue because Y — look for a different root cause"). On the 3rd attempt, STOP and load `sessions.py context --doc debugging`.

### Step 4: After Fix Confirmed

```bash
docker exec api python /app/backend/scripts/debug.py issue $ARGS --delete --yes
```

### Default Assumptions

- Issues are on the **dev server**, reported by an **admin**
- Check if another session is rebuilding Docker containers if services appear down
