# Concurrent work

Each independent Codex task owns an isolated repository workspace. Child agents
reuse the parent's binding unless explicitly assigned separate ownership. Do not
spawn workers without authorization. Use `sessions.py start` once before editing;
it reuses the current task binding. Never infer an owner from the newest activity.
Manual SSH commands pass the known `--session`.

`status` shows the bound session; `status --all` explicitly lists others. Status
reads do not prune records. Tracked files define commit scope, while explicit edit
leases and write claims protect active operations. Preserve other tasks' changes.

Deployment admission covers preparation through push, so updated agents cannot
invalidate each other's gates by overtaking. The separate push lock remains short.
External dev pushes can still force a bounded rebuild. On an actual conflict,
keep the workspace and explain the conflicting change before expanding scope.
Shared Docker operations retain their coordinator lease. Product E2E uses isolated
GitHub CI and does not require restarting the shared development stack.

Use cached Task deltas or completion events for coordination. Handoffs should fit
roughly 100–200 words. See `AGENTS.md` and `.claude/rules/session-lifecycle.md`.
