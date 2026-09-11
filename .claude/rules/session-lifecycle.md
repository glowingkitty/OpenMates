---
description: Repository workspace ownership and scoped deployment
globs:
---

Read-only work needs no session. First mutation obtains or reuses an isolated
workspace with `sessions.py start --mode <bug|feature|docs|testing> --task <outcome>`.
The current Codex thread and execution host identify the binding. A child shares
the parent's binding. SSH/manual work uses the returned explicit `--session`.
Re-read files before editing and preserve other tasks' edits and live edit leases.
Do not create another worktree after deployment merely to continue the same task.

Deploy the scoped diff with `sessions.py deploy --title <title> --message <why>`.
Normal commands infer the binding; use `--session` when necessary. No mandatory
documentation dump, manual per-file tracking or separate wait-lock is needed.
Review `prepare-deploy` only when scope needs inspection. The helper validates the
integrated candidate, serializes admission and commits/pushes to `dev`. A scoped
dev deploy is authorized for implementation; production and destructive changes
retain their separate approval boundaries. Keep the canonical checkout on `dev`.

Run CI E2E in the isolated GitHub stack. Shared dev runtime mutations use
`sessions.py docker restart --session <id> --service <name>` and its resource
leases; they are for deployment, not a substitute CI runner. Wait inside the
process or use existing result events; do not poll through repeated model turns.

OpenMates Tasks owns status/dependencies/activity. Do not duplicate that ledger
with session task files or a final-answer lifecycle protocol. End/cleanup is an
explicit maintenance operation; it must not invent proof or approval requirements.
Preserve existing workspace records and pending deliveries during migrations.
