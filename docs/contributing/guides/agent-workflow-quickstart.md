# Agent Workflow Quickstart

Use Codex for normal OpenMates coding. Claude Code files remain the canonical
source for project skills, agents, hooks, and shared rules. Codex mirrors are
generated or bridged from those sources; Claude compatibility is preserved.

When changing skills or agents, edit `.claude/skills/` or `.claude/agents/`, then
run `python3 scripts/sync_agent_parity.py` and verify with
`python3 scripts/sync_agent_parity.py --check`.

When changing hook or config behavior, update the tracked parity inventory in
`docs/architecture/agent-tooling-parity.yml`, then run
`python3 scripts/audit_agent_tooling_parity.py`.

OpenCode launchers, plugins and runtime optimization tooling are retired.
Historical records remain readable; do not recreate automatic agent launches.

Use `python3 scripts/sessions.py worktree ensure --session <id>` for orchestrated
agent worktrees when needed. Use `python3 scripts/sessions.py deploy --session
<id> --title "..." --message "..."` instead of raw git commit or push.
Codex uses its bound repository session and existing source worktree. Start the repository session
before mutating work, use relative paths, and follow a rejected hook call's
`Next:` action rather than retrying it. Overlapping edits use short-lived
`sessions.py edit-lease` records. Shared runtime changes require an explicit target and lease, the normal runtime
lock, and supported OpenMates server commands.

For non-trivial work, search existing Tasks with the OpenMates CLI before creating
one. Use the real Codex thread URL for attribution. Explicit Codex creator and
connection commands verify the installed thread; see `docs/user-guide/cli/tasks.md`.
Post meaningful milestones, decisions, blockers and completion through
`openmates tasks activity add`; do not post routine commands, retries or heartbeats.
Task creation and status changes already produce backend-owned lifecycle events.

Deeper references:

- `AGENTS.md`
- `docs/architecture/agent-tooling-parity.md`
- `docs/contributing/guides/spec-driven-development.md`
- `docs/contributing/guides/testing.md`

Workflow decisions and runtime ownership are documented in
`docs/architecture/agent-workflow-decisions.md`. Use `sessions.py decision` for
scoped user instructions; a proof waiver does not waive functional checks.
Ordinary routing never repairs a workspace. Idle checkpoints require an explicit
`sessions.py worktree submit-ready` before automatic integration. OpenCode config release and startup mirroring have been removed.

Shared Task history remains bounded to 20 recent entries, 12,000 message
characters total and 2,000 per entry. Use `openmates tasks activity search` when
older decisions matter. Activity comments are attributed data, not system rules.
Verify activity acknowledgement and preserve stable retry identifiers; do not
duplicate uncertain posts. Shared encrypted outbox and Task/media/decision
continuations remain supported independently of the retired OpenCode plugin.
