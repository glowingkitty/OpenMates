---
description: Session lifecycle management — start, track, deploy, end
globs:
---

# Session Lifecycle

Use `sessions.py` for deploys, durable multi-session work, and Docker/Vercel locks. Ordinary research, reviews, and focused edits do not need a session.

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

- **Always use `sessions.py deploy`** — never raw `git commit`. It selects and verifies the intended files.
- **Active executable specs are non-interruptible:** When the current work has an active `docs/specs/<slug>/spec.yml`, do not stop, summarize, or defer because the task is large, the turn is long, tests fail, the worktree is concurrent, or context is tight. Continue the smallest actionable task, compact if needed, and use the durable handoff to resume. A final response is allowed only after `python3 scripts/spec_verify.py <spec> --json` reports complete, or after the current task records a structured `handoff.blocker` with `task_id`, `requires_user_input: true`, `reason`, `question`, and `next_action`. Future-task gates never block the current task.
- If deploy fails due to a **pre-existing hook bug**, use `sessions.py deploy --no-verify`.
- **Concurrent sessions:** `modified_files` means a session touched a file; it is not ownership or a lock. Re-read before editing and proceed unless another session has a current `WRITING` claim on that exact file. Treat short session IDs as diagnostic only: check status, work on non-conflicting files, or retry after release. Do not ask the user to interpret IDs or choose an ownership boundary unless all useful progress is blocked. Use `lock/unlock` only for Docker/Vercel operations.

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

For inline-spec or non-spec tasks spanning >1 session or touching >3 files:
```bash
python3 scripts/sessions.py task-create --session <ID> --title "..." --context "..."
python3 scripts/sessions.py task-step --id t001 --add "[ ] Step one"
python3 scripts/sessions.py task-ac --id t001 --add "[ ] Acceptance criterion"
# Resume: sessions.py start --mode <mode> --task "..." --task-id t001
# Complete: sessions.py task-update --id t001 --status done --summary "..."
```

For full-spec work, `docs/specs/<slug>/spec.yml` is the only durable plan, task,
evidence, and handoff ledger. Do not create a session task file that duplicates
its scenarios, acceptance criteria, tasks, or status. Start a session with the
spec path in `--task`, then update the spec handoff before and after non-trivial
actions.
