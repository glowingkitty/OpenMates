# Workflow decisions and workspace ownership

User instructions, approvals and scoped waivers persist. They are not invalidated
by a routine tool failure or a change of task description. Ask only for a material
unresolved decision, and pause the work that depends on it. A test execution waiver
does not waive maintaining coverage unless the user says so.

`_workflow_decisions.py` retains optional scoped receipts for exact target,
surface and revision. New receipts validate original Codex user-message provenance
through the thread's JSONL. Missing history cannot grant a pass or silently resume
stopped work. Historical receipt/provider fields remain preserved as data.
Ordinary authorized work does not require manufacturing an approval artifact.

A repository session binds a Codex task UUID, host and repository to a workspace.
Resolve exact identity, never the most recently active session. Supported hook
payloads are anchored to that workspace. Explicit write claims/edit leases retain
shared-operation ownership; a hook is routing assistance, not an OS sandbox.

For an approved transfer from a stopped owner, use canonical `sessions.py worktree
bind-codex` with `--session`, `--codex-task`, `--expected-worktree` and
`--previous-owner-stopped`. It preserves the workspace and historical metadata.
Never reset or recreate a workspace simply to resolve a routing mismatch.

Deployment protocol 3 uses admission before preparation and the existing short
push lock. It preserves isolated integration, exact patch selection, required
checks and normal dev push. The compatibility marker described in
`../contributing/guides/agent-tooling-migration.md` stops old worktree deploy code.

Product intent belongs in Specifications when it changes. A lightweight
engineering Plan can use id/title/status/goal; strict product-contract fields are
opt-in. Videos are explicit deliverables, and debugging remains bounded by the
original task. Full application E2E executes in isolated GitHub CI.
