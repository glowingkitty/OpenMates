# Agent workflow

`AGENTS.md` is the shared policy root. Use Codex and the installed OpenMates CLI.
Read only relevant source, tests and domain guidance. Read-only work needs no
repository session; before mutation use `sessions.py start --mode <mode> --task
<outcome>` and its returned workspace. Repeated starts reuse the task binding.

Use OpenMates Tasks for durable execution state. A handoff contains the outcome,
Task, binding, owned paths, evidence and unresolved decisions. Use task APIs or
installed `openmates` commands for conversations; no editor-specific transcript
reader or parallel Task bridge is part of the repository runtime.

Run relevant focused checks, update E2E coverage for behavior changes, and use
isolated GitHub CI for full application tests. Follow `.claude/rules/testing.md`
for debugging bounds and user waivers. Proof media is an explicit deliverable.

Deploy with `sessions.py deploy --title <title>` from the task workspace; SSH
callers can pass `--session`. The coordinator owns isolation, integration,
checks, commit and dev push. Use bounded wait commands instead of repeated model
polls. `--json` is intended for parsers. See `agent-tooling-migration.md` for
command changes and preserved compatibility data.
