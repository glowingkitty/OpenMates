---
status: active
last_verified: 2026-04-02
key_files:
- scripts/linear-poller.py
- scripts/session-cleanup.py
- scripts/_linear_client.py
- scripts/_zellij_utils.py
- scripts/linear-cron-setup.sh
claims:
- id: arch-infrastructure-linear-auto-processing-behavior
  type: unit
  claim: Linear Auto-Processing Pipeline is grounded in current source-of-truth files that parse or resolve successfully.
  source:
  - scripts/linear-poller.py
  - scripts/session-cleanup.py
  - scripts/_linear_client.py
  - scripts/_zellij_utils.py
  test:
    file: scripts/tests/test_architecture_behavioral_claims.py
    command: python3 -m pytest scripts/tests/test_architecture_behavioral_claims.py
    assertion: arch-infrastructure-linear-auto-processing-behavior
  verified: '2026-06-11'
- id: arch-infrastructure-linear-auto-processing-source-1
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-infrastructure-linear-auto-processing-source-1
  anchors:
  - type: file_exists
    path: scripts/_linear_client.py
- id: arch-infrastructure-linear-auto-processing-source-2
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-infrastructure-linear-auto-processing-source-2
  anchors:
  - type: file_exists
    path: scripts/_zellij_utils.py
- id: arch-infrastructure-linear-auto-processing-source-3
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-infrastructure-linear-auto-processing-source-3
  anchors:
  - type: file_exists
    path: scripts/linear-cron-setup.sh
---

# Linear Auto-Processing Pipeline

> Automatically picks up Linear tasks labeled `claude-fix`, `claude-research`, or `claude-plan`, spawns persisted OpenCode Web chats, tracks their lifecycle, and cleans up when done. The legacy label names remain for compatibility. All runs on the dev server only.

## Why This Exists

Manual task pickup is slow — labeling a Linear task should be enough to kick off work. This pipeline turns Linear labels into running OpenCode chats, monitors their progress, and reclaims legacy resources when tasks complete or crash.

## How It Works

### Lifecycle Overview

```
1. User adds "claude-fix" label to a Linear task
                    |
2. Poller detects it (every 30s)
                    |
3. Starts a persisted OpenCode Web chat
   - Passes prompt directly through the running OpenCode server
   - Tracks in poller-sessions.json
   - Swaps labels: claude-fix -> claude-is-working
   - Sets status: In Progress
                    |
4. OpenCode works (reads prompt, investigates, implements)
   - Posts progress comments to Linear via MCP
                    |
5. OpenCode finishes
   - Sets status: In Review (or Todo if blocked)
   - Removes claude-is-working label
                    |
6. Poller detects completion (next cycle, <=30s)
   - Removes tracking record
   - Removes any legacy Zellij session with the same name
```

Legacy records created before sidebar chat spawning may still point at Zellij
sessions. Cleanup keeps reclaiming those records, but new work launches into the
existing OpenCode Web project sidebar instead of creating terminal sessions.

### Labels

| Label | Mode | OpenCode Permissions | What Happens |
|-------|------|-------------------|--------------|
| `claude-fix` | execute | Full read/write | Investigate + implement fix + deploy |
| `claude-research` | research | Read-only | Codebase + web research, post findings as comment |
| `claude-plan` | plan | Read-only | Investigate + propose approach, no implementation |

Priority order: fix > research > plan (if multiple labels exist).

### Worker Limits

- New poller workers launch as persisted OpenCode Web chats instead of consuming Zellij slots.
- Legacy Zellij cleanup still enforces the historical session cap for older records and manual sessions.
- If a future chat-worker cap is added, queued tasks should keep the existing deduped "Queued" comment behavior.
- There is intentionally no blanket nightly enricher: open Todo/Backlog tasks only spawn OpenCode chats when explicitly labeled for automation.

### Cleanup Layers

| Trigger | What | When |
|---------|------|------|
| **Poller (30s)** | Detects tasks moved to "In Review"/"Done", removes tracking, and kills any legacy Zellij session with the same name | Every poll cycle |
| **session-cleanup.py (5 min)** | Catches crashed sessions (EXITED/disappeared in Zellij), updates Linear, removes tracking | Every 5 min via systemd timer |
| **enforce_session_limit()** | Kills EXITED sessions first, then oldest idle sessions if over 6 | Called by both poller and cleanup |

## Key Files

### `scripts/linear-poller.py`
Main engine. Runs every 30s via systemd. Each cycle:
1. `_cleanup_completed_sessions()` — clean tracking for tasks whose work is done
2. `enforce_session_limit()` — free slots if over the cap
3. Collect candidates from `claude-fix`, `claude-research`, `claude-plan` labels
4. For each candidate: spawn an OpenCode Web chat, track it, swap labels

### `scripts/_linear_client.py`
GraphQL client for the Linear API. All reads/writes go through `_graphql()`. Key functions:
- `list_issues_with_label()` — find tasks to process
- `get_issue_with_comments()` — fetch context for prompts (uses `comments(last: 10)` for newest)
- `post_comment()`, `add_label()`, `remove_label()`, `update_issue_status()`

### `scripts/_zellij_utils.py`
Legacy Zellij session management plus OpenCode chat launch. Key functions:
- `spawn_opencode_session()` — launches a persisted OpenCode Web chat with explicit plan or execute mode
- `count_active_sessions()` — counts all non-EXITED legacy Zellij sessions
- `enforce_session_limit()` — kills excess legacy Zellij sessions
- `list_sessions_with_state()` — returns `{name: "ACTIVE"|"EXITED"}` for cleanup

### `scripts/session-cleanup.py`
Runs every 5 min via systemd timer. Three cleanup passes:
1. `cleanup_stale_sessions()` — kills sessions.json entries with stale Linear activity (>2h)
2. `cleanup_dead_poller_sessions()` — detects EXITED/disappeared poller sessions, updates Linear
3. `enforce_session_limit()` — enforces the global cap

### `scripts/linear-cron-setup.sh`
Installs all systemd services. Run once on the dev server:
```bash
bash scripts/linear-cron-setup.sh
```

## Session Tracking

Poller sessions are tracked in `scripts/.tmp/poller-sessions.json`:
```json
{
  "fix-OPE-123": {
    "issue_id": "<linear-uuid>",
    "identifier": "OPE-123",
    "mode": "execute",
    "started": "2026-04-02T12:00:00Z",
    "claude_session_id": "<claude-jsonl-uuid>"
  }
}
```

The `claude_session_id` maps to the JSONL transcript at `~/.claude/projects/-home-superdev-projects-OpenMates/<uuid>.jsonl`, enabling the `/task-status` skill to show what each session is doing.

## Systemd Services

| Service | Schedule | Purpose |
|---------|----------|---------|
| `linear-poller.service` | Every 30s (loop with flock) | Poll for labeled tasks, spawn sessions, cleanup completed |
| `session-cleanup.service` + `.timer` | Every 5 min | Catch crashed sessions, enforce limits |
| `linear-archive.service` + `.timer` | Daily | Archive old closed issues (free plan limit) |

Check status:
```bash
systemctl --user status linear-poller.service
systemctl --user list-timers
journalctl --user -u linear-poller.service -n 20
```

## Prompt Structure

Each spawned session reads a prompt file from `scripts/.tmp/poller-prompt-OPE-XXX.txt` containing:
1. **Mode instructions** — what the session can/cannot do (execute vs read-only)
2. **Task context** — identifier, title, description, recent comments
3. **Work instructions** — research, identify root cause, implement (or summarize)
4. **Linear tracking instructions** — post progress comments, update status on completion, handle failures

## Troubleshooting

### Sessions not spawning
```bash
# Check poller logs
journalctl --user -u linear-poller.service -n 30

# Check session count
python3 -c "import sys; sys.path.insert(0,'scripts'); from _zellij_utils import count_active_sessions; print(count_active_sessions())"

# Manual dry run
python3 scripts/linear-poller.py --dry-run
```

### Sessions stuck as "In Progress"
```bash
# Check tracking file
cat scripts/.tmp/poller-sessions.json

# Run cleanup manually
python3 scripts/session-cleanup.py --dry-run
python3 scripts/session-cleanup.py
```

### OOM / too many sessions
```bash
# Check memory
free -h

# Check all sessions
zellij list-sessions --no-formatting

# Force cleanup
python3 -c "import sys; sys.path.insert(0,'scripts'); from _zellij_utils import enforce_session_limit; enforce_session_limit()"
```

### Systemd user bus crashed (after OOM)
```bash
systemctl --user daemon-reexec
# Or reboot the server
```
