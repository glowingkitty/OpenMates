---
status: active
last_verified: 2026-04-02
key_files:
  - scripts/linear-poller.py
  - scripts/linear-enricher.py
  - scripts/session-cleanup.py
  - scripts/_linear_client.py
  - scripts/_zellij_utils.py
  - scripts/linear-cron-setup.sh
---

# Linear Auto-Processing Pipeline

> Automatically picks up Linear tasks labeled `claude-fix`, `claude-research`, or `claude-plan`, spawns Claude Code sessions in Zellij, tracks their lifecycle, and cleans up when done. All runs on the dev server only.

## Why This Exists

Manual task pickup is slow — labeling a Linear task should be enough to kick off work. This pipeline turns Linear labels into running Claude sessions, monitors their progress, and reclaims resources when tasks complete or crash.

## How It Works

### Lifecycle Overview

```
1. User adds "claude-fix" label to a Linear task
                    |
2. Poller detects it (every 30s)
                    |
3. Checks global session limit (max 6 Zellij sessions)
   |                              |
   | Under limit                  | At limit
   v                              v
4. Spawns Claude in Zellij    Posts "Queued" comment (once)
   - Writes prompt file        Retries next cycle
   - Captures session UUID
   - Tracks in poller-sessions.json
   - Swaps labels: claude-fix -> claude-is-working
   - Sets status: In Progress
                    |
5. Claude works (reads prompt, investigates, implements)
   - Posts progress comments to Linear via MCP
                    |
6. Claude finishes
   - Sets status: In Review (or Todo if blocked)
   - Removes claude-is-working label
                    |
7. Poller detects completion (next cycle, <=30s)
   - Kills Zellij session
   - Removes from tracking file
   - Freed slot -> queued task auto-starts
```

### Labels

| Label | Mode | Claude Permissions | What Happens |
|-------|------|-------------------|--------------|
| `claude-fix` | execute | Full read/write | Investigate + implement fix + deploy |
| `claude-research` | research | Read-only | Codebase + web research, post findings as comment |
| `claude-plan` | plan | Read-only | Investigate + propose approach, no implementation |

Priority order: fix > research > plan (if multiple labels exist).

### Session Limits

- **Hard cap: 6 concurrent Zellij sessions** (server has 30GB RAM, each Claude session uses ~500MB)
- The limit counts ALL Zellij sessions (manual claude1-4, poller-spawned, etc.)
- When at capacity, tasks are queued — a single "Queued" comment is posted (deduped, no spam)
- Queued tasks auto-start as slots free up

### Cleanup Layers

| Trigger | What | When |
|---------|------|------|
| **Poller (30s)** | Detects tasks moved to "In Review"/"Done", kills their Zellij sessions | Every poll cycle |
| **session-cleanup.py (5 min)** | Catches crashed sessions (EXITED/disappeared in Zellij), updates Linear, removes tracking | Every 5 min via systemd timer |
| **enforce_session_limit()** | Kills EXITED sessions first, then oldest idle sessions if over 6 | Called by both poller and cleanup |

## Key Files

### `scripts/linear-poller.py`
Main engine. Runs every 30s via systemd. Each cycle:
1. `_cleanup_completed_sessions()` — kill sessions whose tasks are done
2. `enforce_session_limit()` — free slots if over the cap
3. Collect candidates from `claude-fix`, `claude-research`, `claude-plan` labels
4. For each candidate under the limit: spawn session, track it, swap labels

### `scripts/_linear_client.py`
GraphQL client for the Linear API. All reads/writes go through `_graphql()`. Key functions:
- `list_issues_with_label()` — find tasks to process
- `get_issue_with_comments()` — fetch context for prompts (uses `comments(last: 10)` for newest)
- `post_comment()`, `add_label()`, `remove_label()`, `update_issue_status()`

### `scripts/_zellij_utils.py`
Zellij session management. Key functions:
- `spawn_claude_session()` — creates KDL layout, launches Claude with `--dangerously-skip-permissions`
- `count_active_sessions()` — counts all non-EXITED sessions (used for global limit)
- `enforce_session_limit()` — kills excess sessions
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
| `linear-enricher.service` + `.timer` | 03:00 UTC daily | Auto-research all open Todo/Backlog tasks |
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
