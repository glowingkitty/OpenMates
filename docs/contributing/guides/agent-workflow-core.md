# Agent workflow

`CLAUDE.md` and `.claude/rules/` hold policy. Use Claude Code and the installed OpenMates CLI.
Read only relevant source, tests and domain guidance. Read-only work needs no
repository session; before mutation use `sessions.py start --mode <mode> --task
<outcome>` and its returned workspace. Repeated starts reuse the task binding.

Use OpenMates Tasks for durable execution state. A handoff contains the outcome,
Task, binding, owned paths, evidence and unresolved decisions. Use task APIs or
installed `openmates` commands for conversations; no editor-specific transcript
reader or parallel Task bridge is part of the repository runtime.

To find where code lives, run `scripts/code_map.py find "<area>: <what changes>"`
before grepping. It searches an index of git-tracked source files (cached by blob
hash in `~/.cache/openmates-code-locate`, shared by all worktrees) and lets Jev
score the best 40 files 0..4; it prints 5 files and a confidence. Jev spend for
this tool has its own per-UTC-day cap (`OPENMATES_CODE_LOCATE_JEV_DAILY_USD`,
default USD 0.50, ledger `logs/code-locate/jev-spend.json`); after the cap, on a
failure, or when the query hits the operator-local blocklist it returns the local
search order. `code_map.py find-report` shows calls, spend, fallbacks and how often
a returned file was then opened. `scripts/code_locate_eval.py` re-measures quality
on recent commits with its own spend cap.

Run relevant focused checks, update E2E coverage for behavior changes, and use
isolated GitHub CI for full application tests. Follow `.claude/rules/testing.md`
for debugging bounds and user waivers. Proof media is an explicit deliverable.

Deploy with `sessions.py deploy --title <title>` from the task workspace; SSH
callers can pass `--session`. The coordinator owns isolation, integration,
checks, commit and dev push. Use bounded wait commands instead of repeated model
polls. `--json` is intended for parsers. See `agent-tooling-migration.md` for
command changes and preserved compatibility data.
