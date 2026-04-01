---
description: Session lifecycle management — start, track, deploy, end
globs:
---

# Session Lifecycle (Mandatory)

Every session must call `sessions.py start` as the **very first action** and `sessions.py end` (or `deploy --end`) as the last.

```bash
# 1. START (must include --mode):
python3 scripts/sessions.py start --mode <MODE> --task "brief description"
#   Modes: feature | bug | docs | question | testing
#   Prefetch: --issue ID, --chat ID, --embed ID, --logs, --user EMAIL,
#             --debug-id ID, --vercel, --run-id ID, --since-last-deploy, --task-id ID

# 2. TRACK (auto-tracked by hook, but manual tracking also available):
python3 scripts/sessions.py track --session <ID> --file path/to/file.py

# 3. DEPLOY (lint + commit + push):
python3 scripts/sessions.py deploy-docs
python3 scripts/sessions.py prepare-deploy --session <ID>
python3 scripts/sessions.py deploy --session <ID> --title "type: description" --message "body" --end

# 4. END (if not using --end above):
python3 scripts/sessions.py end --session <ID>
```

## Key Rules

- **Always use `sessions.py deploy`** — never raw `git commit`. It bypasses session tracking.
- If deploy fails due to a **pre-existing hook bug**, use `sessions.py deploy --no-verify`.
- **Mode escalation:** If a `--mode question` session needs file edits, end it and restart with `--mode feature` or `--mode bug`.
- **Concurrent sessions:** Re-read files before editing. Check git status before committing. Use `lock/unlock` for Docker/Vercel.

## On-Demand Tools

```bash
python3 scripts/sessions.py context --doc <name>     # Load full doc (e.g. debugging, sync)
python3 scripts/sessions.py code-quality --session <ID>
python3 scripts/sessions.py find-redundancy --tags frontend
python3 scripts/sessions.py check-tests --session <ID>
python3 scripts/sessions.py check-docs --session <ID>
python3 scripts/sessions.py lock --session <ID> --type docker
python3 scripts/sessions.py stale-docs --tags frontend
```

## Spawn Parallel Sessions

Spawn Claude Code sessions in separate Zellij tabs for parallel work:
```bash
# Plan mode (default, read-only) — research and planning
python3 scripts/sessions.py spawn-chat --prompt "Research X" --name "research-X"

# Execute mode (full access) — only when user explicitly requests
python3 scripts/sessions.py spawn-chat --prompt-file prompt.txt --name "fix-task" --mode execute
```
**Always ask user confirmation before spawning.** Attach: `zellij attach <name>` or localhost:8082.

## Multi-Session Tasks

For tasks spanning >1 session or touching >3 files:
```bash
python3 scripts/sessions.py task-create --session <ID> --title "..." --context "..."
python3 scripts/sessions.py task-step --id t001 --add "[ ] Step one"
python3 scripts/sessions.py task-ac --id t001 --add "[ ] Acceptance criterion"
# Resume: sessions.py start --mode <mode> --task "..." --task-id t001
# Complete: sessions.py task-update --id t001 --status done --summary "..."
```
