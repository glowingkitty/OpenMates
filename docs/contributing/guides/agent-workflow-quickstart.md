# Agent workflow

`AGENTS.md` is the concise entry point. Codex owns conversations; the installed
OpenMates CLI owns Tasks and synchronization; GitHub CI owns isolated application
stacks and E2E runs. Repository helpers own workspace safety and scoped publishing.

1. Read relevant source/tests. First mutation: `python3 scripts/sessions.py start
   --mode bug --task "<outcome>"`. Reuse its workspace and binding.
2. Implement and update relevant E2E coverage. Run focused local checks. Publish
   an immutable source with `sessions.py ci-source`, submit through
   `ci_coordinator.py submit`, and wait with `ci_coordinator.py wait <id>` or use
   existing completion events. JSON is opt-in when another program needs it.
3. Publish with `sessions.py deploy --title "type: description" --message "why"`.
   Use `--session` for SSH/manual work. For frontend readiness use
   `sessions.py wait-deploy --commit <sha>` and wait on that process.

Update OpenMates Tasks only at meaningful changes; successful acknowledged writes
need no follow-up read. Preserve queued deliveries. Handoffs contain the outcome,
Task, binding, owned paths, evidence and unresolved decisions in 100–200 words.
Use canonical `codex_worker.py` and stable operation IDs for authorized dev-host
workers; preserve explicit per-turn permissions.

Read `.claude/rules/testing.md` for E2E maintenance and bounded debugging. Ask
before a materially broader or uncertain repair. Explicit user waivers persist.
Keep Claude source skills/agents and run `sync_agent_parity.py` plus `--check` after
editing them. Hook changes require parity validation and one installed
`codex_cached_context.py doctor` check; use `/hooks` to review changed definitions.

Legacy conversation records are historical data, not executable workflow rules.
See `docs/architecture/codex-task-cache.md` for task transport and recovery.

After editing shared skills/hooks, run `python3 scripts/sync_agent_parity.py --check`
and `python3 scripts/audit_agent_tooling_parity.py`.
