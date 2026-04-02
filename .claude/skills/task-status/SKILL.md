---
name: openmates:task-status
description: Show status overview of all auto-processed Linear tasks (poller sessions)
user-invocable: true
argument-hint: "[--all]"
---

## Current Poller Sessions

!`cat scripts/.tmp/poller-sessions.json 2>/dev/null || echo "{}"`

## Zellij Session States

!`zellij list-sessions --no-formatting 2>/dev/null | grep -E '^(fix-|plan-|research-)' || echo "(no poller sessions)"`

## Instructions

You provide a quick status overview of all auto-processed Linear tasks spawned by the linear-poller.

### Step 1: Parse the Data

1. Parse the JSON from "Current Poller Sessions" above — this is the tracking file written by `linear-poller.py`
2. Parse the Zellij output to determine each session's state (ACTIVE or EXITED)
3. For each session that has a `claude_session_id`, read the last 5 lines of the JSONL transcript to extract the latest activity:

```bash
tail -5 ~/.claude/projects/-home-superdev-projects-OpenMates/<claude_session_id>.jsonl
```

Parse each line as JSON. Look for entries with `type: "assistant"` and extract the text content (may be a string or a list of `{type: "text", text: "..."}` objects). Take the last ~300 chars of the most recent assistant message.

### Step 2: Present the Overview

Display a summary table:

```
| Task    | Mode     | Status  | Duration | Last Activity                          |
|---------|----------|---------|----------|----------------------------------------|
| OPE-265 | execute  | ACTIVE  | 12m      | "Deploying fix for race condition..." |
| OPE-264 | research | EXITED  | 45m      | "Research complete, posted findings..."  |
```

- **Duration**: Calculate from the `started` timestamp to now
- **Status**: ACTIVE (running), EXITED (finished/crashed), MISSING (not in Zellij at all)
- **Last Activity**: Truncated last assistant message (max 60 chars in table)

### Step 3: Show Details (if requested)

If `--all` is passed or user asks for details, show the full last assistant message for each session (up to 500 chars).

### No Sessions

If the tracking file is empty or missing, say:
"No auto-processed tasks currently tracked. Tasks appear here when the linear-poller spawns sessions for issues labeled `claude-fix`, `claude-research`, or `claude-plan`."
