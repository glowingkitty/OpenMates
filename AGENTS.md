# OpenMates repository guidance

OpenMates is developed with Claude Code. The authoritative agent guidance is
`CLAUDE.md`; domain rules live in `.claude/rules/`, skills in `.claude/skills/`,
sub-agents in `.claude/agents/` and hooks in `.claude/hooks/`.

Any other agent tool must read `CLAUDE.md` first and follow it, loading only the
`.claude/rules/` files whose `paths:` match the files it works on.

Feature status per surface (web, Apple, CLI, TUI, REST API, SDKs) lives in
`specifications/features.yml` (grouping and intent; cells with tests are derived
from assertions, tests and CI results); the readable table is
`specifications/generated/features.md`, gaps per surface:
`python3 scripts/feature_overview.py gaps --surface apple`. Every change that adds or changes a
feature, a surface or an E2E test updates its entry in the same commit
(`python3 scripts/feature_overview.py --check`).

"Done" means committed, tested and deployed to dev (`python3 scripts/sessions.py
deploy`); an agent never ends its work with uncommitted changes in its worktree.
Work that must wait is parked with a reason (`python3 scripts/worktree_wip.py park
--session <id> --reason "<why>"`) and noted in its Task. Dirty worktrees are
snapshotted to `refs/openmates/wip/<session>`, and the nightly readiness check
(`scripts/worktree_wip.py nightly`) wakes owners of unfinished work.
