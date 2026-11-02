# OpenMates repository guidance

OpenMates is developed with Claude Code. The authoritative agent guidance is
`CLAUDE.md`; domain rules live in `.claude/rules/`, skills in `.claude/skills/`,
sub-agents in `.claude/agents/` and hooks in `.claude/hooks/`.

Any other agent tool must read `CLAUDE.md` first and follow it, loading only the
`.claude/rules/` files whose `paths:` match the files it works on.
