# OpenMates repository guidance

OpenMates is developed with Claude Code. The authoritative agent guidance is
`CLAUDE.md`; domain rules live in `.claude/rules/`, skills in `.claude/skills/`,
sub-agents in `.claude/agents/` and hooks in `.claude/hooks/`.

Any other agent tool must read `CLAUDE.md` first and follow it, loading only the
`.claude/rules/` files whose `paths:` match the files it works on.

Feature status per surface (web, Apple, CLI, TUI, REST API, SDKs) lives in
`specifications/features.yml`; the readable table is
`specifications/generated/features.md`. Every change that adds or changes a
feature, a surface or an E2E test updates its entry in the same commit
(`python3 scripts/feature_overview.py --check`).
