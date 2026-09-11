# Agent tooling parity

`AGENTS.md` is the shared policy root (maximum 6000 bytes). `CLAUDE.md` points to
it. Canonical shared skills and agent profiles live in `.claude/`; generated
Codex mirrors live in `.agents/skills/` and `.codex/agents/`.

After authoring shared guidance, run `scripts/sync_agent_parity.py`, then its
`--check` mode and `scripts/audit_agent_tooling_parity.py`. The audit checks the
explicit hook matrix in `agent-tooling-parity.yml`, generated files and the root
instruction budget. Hook stdout is merged into one Codex response; a shared
policy denial takes precedence over routing permission.

Codex task/host identity selects the repository workspace. The shared bridge
routes tools and applies existing guards. Cached Task context is full at
start/resume and incremental afterwards. Installed hook changes require review
through `/hooks`; repository deployment does not bypass that trust boundary.

No editor-specific transcript reader, presence daemon, duplicate Task bridge,
message/media delivery queue or idle-chat integration is part of this runtime.
The CLI owns Task state; `sessions.py` owns workspace/lease/deployment coordination.
See `../contributing/guides/agent-tooling-migration.md` for compatibility details.
