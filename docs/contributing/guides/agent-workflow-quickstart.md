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

Deeper references:

- `AGENTS.md`
- `docs/architecture/agent-tooling-parity.md`
- `docs/contributing/guides/spec-driven-development.md`
- `docs/contributing/guides/testing.md`
