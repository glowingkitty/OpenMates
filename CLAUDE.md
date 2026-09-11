# OpenMates agent guidance

Read and follow `AGENTS.md` for the shared workflow and policy. Domain rules live
in `.claude/rules/`; load only the rules relevant to the task. Author shared
skills in `.claude/skills/` and regenerate Codex mirrors with
`python3 scripts/sync_agent_parity.py`.

For Claude terminal sessions, `sessions.py start` records the unique terminal
owner. Codex uses its durable task binding. Use the returned workspace before
editing and the globally installed `openmates` CLI for Tasks and inspection.
