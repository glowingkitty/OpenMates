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
