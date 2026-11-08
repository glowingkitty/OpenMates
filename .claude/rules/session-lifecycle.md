---
paths:
  - "scripts/sessions.py"
  - "scripts/ci_coordinator.py"
---
# Session lifecycle

- Read-only work needs no session. First mutation:
  `sessions.py start --mode <bug|feature|docs|testing> --task <outcome>`; it
  reuses an existing binding for this Claude terminal. Sub-agents share it.
  SSH/manual work passes the returned `--session`.
- Parallel lanes: the parent runs `python3 scripts/lane_start.py --task "<outcome>"`
  per lane (fresh session, `lane-open` flag so the edit gate admits sub-agents
  in that worktree only) and gives each agent its `session=` and `worktree=`.
  Lane agents `cd` into the worktree, pass `--session <id>` and never run
  `start`/`end`. `start` refuses a stale or ended binding; use `start --new`.
- Lanes never hand-regenerate or stage generated outputs
  (`specifications/generated/*`, `docs/migration/rust/{overview,web-app,
  shared-client,cli,sdk}.yml`): deploy rebuilds them in the integration
  checkout. To catch up with dev run `sessions.py worktree refresh-base
  --rebase --session <id>` (fast-forward, rebuilds generated files; refuses
  when dirty edits overlap). Deploy also auto-fast-forwards a stale lane and
  recreates empty or stale checkpoints; never delete checkpoint refs by hand.
- Saved patches: the rtk filter turns `git diff` into a stat summary; use
  `rtk proxy git diff --binary`.
- Other running Claude chats (task, workspace, recent files) are injected at
  session start and whenever they change (`.claude/hooks/peer-chats.sh`).
  Inspect one with `python3 scripts/agent_peers.py history <chat-id>`.
- Re-read files before editing; preserve other tasks' edits and edit leases.
  Do not create another worktree after deployment to continue the same task.
- `sessions.py deploy --title <title> --message <why>` validates, serializes and
  pushes the scoped diff to `dev`. Use `prepare-deploy` only to inspect scope.
  Keep the canonical checkout on `dev`.
- Shared dev runtime mutations: `sessions.py docker restart --session <id>
  --service <name>` with its resource leases; not a substitute CI runner.
- OpenMates Tasks owns status; no local task ledgers. `sessions.py end` is
  optional maintenance and invents no proof or approval requirements.
