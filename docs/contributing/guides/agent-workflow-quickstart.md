# Agent Workflow Quickstart

Use OpenCode for normal OpenMates coding. Claude Code files remain the canonical
source for project skills, agents, hooks, and shared rules. Codex and OpenCode
mirrors are generated or bridged from those canonical sources.

When changing skills or agents, edit `.claude/skills/` or `.claude/agents/`, then
run `python3 scripts/sync_agent_parity.py` and verify with
`python3 scripts/sync_agent_parity.py --check`.

When changing hook or config behavior, update the tracked parity inventory in
`docs/architecture/agent-tooling-parity.yml`, then run
`python3 scripts/audit_agent_tooling_parity.py`.

When changing OpenCode instructions or automation prompts, keep the default
context small and run `python3 scripts/audit_opencode_output_quality.py`.

Use `python3 scripts/sessions.py worktree ensure --session <id>` for orchestrated
agent worktrees when needed. Use `python3 scripts/sessions.py deploy --session
<id> --title "..." --message "..."` instead of raw git commit or push.
OpenCode Web remains root-addressed while hooks route local file tools, searches,
Bash, and Task children into the session worktree. Start the repository session
before mutating work, use relative paths, and follow a rejected hook call's
`Next:` action rather than retrying it. Overlapping edits use short-lived
`sessions.py edit-lease` records. Raw Docker Compose mutations require the
current session to hold the Docker lock.

For non-trivial OpenCode work, use the injected `openmates_task` tool. It creates one atomic `external_ai/opencode` Task before the first product mutation; use `assignee=user` only for work the user must perform personally or in the physical world. Post `activity_add` comments for meaningful completed milestones, durable learnings or decisions, important blockers, and completion. Do not post commands, routine test runs, retries, heartbeats, or internal subagent chatter. Task creation and status changes already produce backend-owned lifecycle events.

Deeper references:

- `AGENTS.md`
- `docs/architecture/agent-tooling-parity.md`
- `docs/contributing/guides/spec-driven-development.md`
- `docs/contributing/guides/testing.md`

Workflow decisions and runtime ownership are documented in
`docs/architecture/agent-workflow-decisions.md`. Use `sessions.py decision` for
scoped user instructions; a proof waiver does not waive functional checks.
Ordinary routing never repairs a workspace. Idle checkpoints require an explicit
`sessions.py worktree submit-ready` before automatic integration. The verified
release owns its config directory; startup never mirrors tracked root files.
