---
name: debug-issue
description: Investigate a user-submitted issue with timeline and debug data
user-invocable: true
argument-hint: "<issue-id>"
---

## Instructions

You are investigating a user-submitted issue. The issue ID was provided as an argument.

### Step 1: Start from the reported issue database

The reported issue database is the source of truth. Do not start from Linear or GitHub unless the issue note links there.

```bash
python3 scripts/issues.py show $ARGS --env prod
python3 scripts/issues.py findings $ARGS --env prod
```

If the issue is known to be from dev, use `--env dev`. The findings command creates a local-only, gitignored note at `docs/findings/issues/<env>/<YYYY>/...md`. Update this note with the first anomaly, root-cause hypothesis, related reports, attempts, tests, and final status before changing product code. Do not store reported-issue findings elsewhere.

Use these workflow helpers before raw debug commands:

```bash
python3 scripts/issues.py list --env prod --limit 20
python3 scripts/issues.py cluster --env prod --limit 100
python3 scripts/issues.py timeline $ARGS --env prod --compact
python3 scripts/issues.py mark $ARGS --env prod --status investigating
```

### Step 2: Delegate forensics to the `issue-forensics` subagent

Launch the `issue-forensics` agent with this prompt:

> Investigate issue `$ARGS`. Use `scripts/issues.py show`, `scripts/issues.py timeline`, and the created findings note as the workflow entry points. Run raw `debug.py issue` only when the wrapper lacks a needed low-level view. Follow any trace IDs, identify the first anomaly, and return the structured JSON + narrative. Use `--env prod` when this is a prod issue.

The agent runs all `debug.py` commands, correlates browser↔backend events, git-blames suspects, and returns a compact report with `first_anomaly`, `root_cause_hypothesis`, `suspect_files[]`, `reproduction_steps`, and `related_recent_commits`.

**If the symptom looks like encryption / decryption / chat sync:** after `issue-forensics` returns, also launch `encryption-flow-tracer` with the first anomaly message as the symptom — it will pinpoint the broken invariant in the E2EE/sync data flow.

**Do NOT run raw `debug.py` commands yourself unless `scripts/issues.py` cannot expose the needed low-level view** — raw timelines flood main context. Trust the agents' compact reports.

### Step 3: Write the Fix

Using the agent's `suspect_files` and narrative:
1. Read the suspect code (20–40 lines around the reported line)
2. Confirm the hypothesis fits
3. Update the findings note with the confirmed hypothesis and intended test
4. Apply the minimal fix

### Step 4: Debugging Attempt Limit

**2 tries max** with the same approach. If the agent's first hypothesis fails, re-launch it with your new context ("the fix at X did not resolve the issue because Y — look for a different root cause"). On the 3rd attempt, STOP and load `sessions.py context --doc debugging`.

### Step 5: After Fix Confirmed

Update the findings note and mark it verified:

```bash
python3 scripts/issues.py mark $ARGS --env prod --status verified
```

Only delete the issue report after the user confirms the fix is verified:

```bash
docker exec api python /app/backend/scripts/debug.py issue $ARGS --delete --yes
```

### Default Assumptions

- Issues are on the **prod server** unless the user says dev or the report was discovered in dev
- Check if another session is rebuilding Docker containers if services appear down
