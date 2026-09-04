---
description: Session lifecycle management — start, track, deploy, end
globs:
---

# Session Lifecycle

Use `sessions.py` for deploys, durable multi-session work, coordinated Docker restarts, and the short dev deploy push lock. Ordinary research, reviews, and focused edits do not need a session.

```bash
# 1. START (must include --mode):
python3 scripts/sessions.py start --mode <MODE> --task "brief description"
#   Modes: feature | bug | docs | question | testing
#   Private cloud overlay repo: add --repo openmatescloud
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
- **Use routed session worktrees:** OpenCode Web stays at the root project URL, but hooks force local file tools, searches, Bash, and Task children into the automatic session worktree. Run `sessions.py start` before mutating work, use repository-relative paths, and never override Bash `workdir` to root or another checkout. The root checkout remains the control plane; set `OPENMATES_ROOT_GUARD=off` only for an explicit manual emergency. If routing fails, follow the hook's `Next:` command instead of repeating the rejected call.
- **Import explicit pre-existing root work; never bypass isolation:** When the user asks about uncommitted files that predate the routed session, inspect metadata with `python3 scripts/sessions.py worktree root-dirty [--path-prefix <prefix>]`, then import only reviewed exact paths with `python3 scripts/sessions.py worktree import-root --session <ID> --file <path>`. The import refuses secrets, runtime/control-plane paths, symlinks, traversal, non-dirty sources, and targets already edited by the session. Never commit a broad root snapshot.
- **One source worktree per top-level chat and repository:** repeated starts, mode upgrades, and post-deploy follow-ups reuse the same repository session and physical worktree. A merged worktree remains the continuation baseline through `merged_commit`; never start a replacement worktree for verification, Docker restart, or follow-up edits.
- **OpenCode Web restarts are Zellij-only and preserve active chats:** run `scripts/server-restart.sh`. It captures every busy top-level chat, restarts the verified release through the existing `code` Zellij session, resumes each captured chat exactly once with its prior agent/model settings, and verifies acceptance. Never manually stop/start the pane while chats are busy, and do not launch or restart `opencode web` through systemd, `systemd-run`, `nohup`, detached shells, tmux, or another terminal session.
- **Use `--repo openmatescloud` for the private overlay repo:** OpenMates remains the control plane, but the active session routes normal file and shell tools into the sibling `/home/superdev/projects/OpenMatesCloud` checkout and `sessions.py deploy` commits/pushes its tracked files to `origin/main`. Keep using repository-relative paths inside that checkout; do not use raw `git commit` or `git push` there.
- **Scoped `dev` deploys are pre-authorized for verification:** do not ask before `sessions.py deploy` when the deployment is required to run dev-server, Vercel, GitHub Actions, Playwright, CLI/SDK, or Apple parity verification for the assigned task. Ask first for production deploys, raw git commit/push, broad/unscoped dirty deploys, destructive data/migrations, secrets, unclear privacy/billing/security scope, same-file overlap that cannot be safely staged, or planning/review-only work.
- **Deploy locks are atomic and short-lived:** `python3 scripts/sessions.py deploy` acquires the dev deploy push lock for root integration, commit, and push, then releases it immediately after push. Do not run a separate `wait-lock` before normal deploys; use it only for diagnostics/manual inspection. Vercel and test verification must be commit-scoped with `--expected-commit`, not protected by a long-lived global lock.
- **Forgotten mutating chats are recoverable by default:** idle or closed top-level OpenCode chats create a local checkpoint ref. After the grace period, the hourly controller may integrate only the unchanged checkpoint through the normal deploy gates. Explicit holds, live edits, sensitive paths, changed patches, conflicts, and failed gates remain visible; question chats, children, legacy state, and uncheckpointed work are never implicit auto-integration inputs.
- **Execution and workspace state are separate:** OpenCode presence reports whether a chat is busy, idle, stopped, or closed. Durable session metadata independently reports whether its worktree is clean, checkpointed, integrating, integrated, held, or needs recovery.
- **Active Plans are non-interruptible:** When the current work has an active `docs/plans/<slug>/plan.yml`, do not stop, summarize, or defer because the task is large, the turn is long, tests fail, the worktree is concurrent, or context is tight. Continue the smallest actionable Task, compact if needed, and use the durable handoff to resume. A success final response is allowed only after `python3 scripts/plan_verify.py <plan> --phase complete --json` reports `complete: true` and every proof publication's delivered `snippet_html` is pasted verbatim into that same response. A blocker response is allowed only after the current Task records a structured `handoff.blocker` with `task_id`, `requires_user_input: true`, `reason`, `question`, and `next_action`. Future-task gates never block the current Task.
- **File waits are not user blockers:** Temporary lock, deploy, Vercel, or test-dispatch waits are execution state, not a reason to stop unless the current task records a structured user-input blocker.
- If deploy fails due to a **pre-existing hook bug**, use `sessions.py deploy --no-verify`.
- **Concurrent sessions:** `modified_files` means a session touched a file; it is not ownership. OpenCode execute edits automatically acquire short-lived `edit-lease` records for exact files and block overlapping edits while the lease is live. Re-read before editing and proceed unless another session has a current `WRITING` claim or `edit-lease` on that exact file. Treat short session IDs as diagnostic only: check status, work on non-conflicting files, or retry after release. Do not ask the user to interpret IDs or choose an ownership boundary unless all useful progress is blocked. Manage the dev Docker lifecycle only with `openmates server start|stop|restart|update|status|logs|verify`; direct mutating `docker compose` commands are blocked. Acquire the `sessions.py` Docker lock before lifecycle mutations and release it immediately afterward. Use `openmates server restart --services ...` for scoped restarts and `openmates server restart --rebuild --services ...` when local source images must be rebuilt.

## On-Demand Tools

```bash
python3 scripts/sessions.py context --doc <name>     # Load full doc (e.g. debugging, sync)
python3 scripts/sessions.py code-quality --session <ID>
python3 scripts/sessions.py find-redundancy --tags frontend
python3 scripts/sessions.py check-tests --session <ID>
python3 scripts/sessions.py check-docs --session <ID>
python3 scripts/sessions.py docker restart --session <ID> --service api
python3 scripts/sessions.py docker restart --session <ID> --build --service api --service task-worker
python3 scripts/sessions.py stale-docs --tags frontend
python3 scripts/sessions.py chat read <ses_or_code_dev_url>
python3 scripts/sessions.py chat search <ses_or_code_dev_url> "worktree"
```

## Spawn Parallel Sessions

Spawn persisted OpenCode Web chats in the existing project sidebar for parallel work:
```bash
# Plan mode (default, read-only) — research and planning
python3 scripts/sessions.py spawn-chat --prompt "Research X" --name "research-X"

# Execute mode (full access) — only when user explicitly requests
python3 scripts/sessions.py spawn-chat --prompt-file prompt.txt --name "fix-task" --mode execute
```
**Always ask user confirmation before spawning.** No new Zellij session is created; use the returned OpenCode session ID or sidebar URL, and inspect with `sessions.py chat read/search` when debugging hooks, tools, or worktree setup.

## Multi-Session Tasks

For inline-Specification or work without a Plan spanning >1 session or touching >3 files:
```bash
python3 scripts/sessions.py task-create --session <ID> --title "..." --context "..."
python3 scripts/sessions.py task-step --id t001 --add "[ ] Step one"
python3 scripts/sessions.py task-ac --id t001 --add "[ ] Acceptance criterion"
# Resume: sessions.py start --mode <mode> --task "..." --task-id t001
# Complete: sessions.py task-update --id t001 --status done --summary "..."
```

For Plan work, `docs/plans/<slug>/plan.yml` is the durable Plan, Task, Check,
Run-evidence, and handoff ledger. A Plan requires only a user-authored goal;
optional fields never become implicit completion gates. Do not create a session
task file that duplicates explicit Plan Tasks or status. Start a session with the
Plan path in `--task`, then update its handoff before and after non-trivial actions.
