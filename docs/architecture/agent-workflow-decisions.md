# Scoped workflow decisions and runtime ownership

Implements the approved developer-tooling proposal WF-20260905-r2 (R1–R3).
No OpenMates product CLI, web app, SDK, API or database schema changes are involved.

## R1: existing Task and Plan records own scoped decisions

`scripts/_workflow_decisions.py` validates original user-message provenance before
`sessions.py decision` stores a receipt in the owning session and, optionally, its
Plan. Receipts contain source identifiers and a content hash, not private text.
OpenCode uses its read-only message store; Codex uses the current thread's JSONL.
An exact quote is supplied to the command for validation but is not persisted.

Use `python3 scripts/sessions.py decision --help` for arguments. Record the exact
Task/Plan target, surface (`appearance`, `proof`, or `task`), and revision. Task
context exposes `active.decision_revision`: a hash of title, description and latest
instruction, stable across status/Activity bookkeeping. Plans use
`implementation_state.subject_commit`. Use `--plan docs/plans/<slug>/plan.yml`
when the decision applies to that Plan's demonstration.

An appearance acceptance is never a proof waiver. A proof stop/waiver allows only
the matching demonstration to remain visibly `waived`, with its `decision_id`.
It cannot satisfy functional, auth, privacy or other required checks. Task context
projects scoped decisions after compaction; task reconciliation and delivery
consume the same matching logic. A whole-task stop cancels only that task's queued
continuation. An explicit `resume` supersedes a prior stop. A materially changed
subject needs new evidence/acceptance; original receipts remain history.

Rollback preserves receipts and explicit stops. Never relabel waived evidence as
passed or reactivate stopped work just because the consumer code was reverted.

## R2: sessions.py owns workspace transitions

Ordinary OpenCode file-tool routing reads existing descriptors; it never invokes
worktree repair. Recovery is an explicit lifecycle operation. The actual atomic
session temporary path, `.claude/sessions.tmp`, is excluded from snapshots.

Ensure, checkpoint, activate, repair, base refresh and restore use the existing
per-session file lock through one lifecycle wrapper. The wrapper records a bounded
operation history and a generation in the existing session record. Explicit
operation IDs coalesce duplicate requests; expected generations reject stale
writers before mutation. Nested helpers share their caller's lock/transaction.
Independent workspaces retain independent locks. Existing file conflict, child
permission, integration-manifest and short dev-push-lock checks remain in force.

An idle/closed checkpoint is preservation, not publication permission. It stays
`checkpointed` until `sessions.py worktree submit-ready --session <id> --patch-id
<fingerprint> --checkpoint-commit <sha>` explicitly submits those exact bytes.
Candidate selection and claim both recheck the submission. Normal explicit
`sessions.py deploy` remains available and keeps its existing gates.

First legitimate lifecycle operations adopt the new metadata under the owner
lock; there is no bulk rewrite of busy chats. Enrolled workspaces are excluded
from automatic reconciliation deletion. Old hook repair calls are removed, and
the runtime release selects the new helpers together. Retain current records and
source bytes during rollback; never restore an old session database snapshot.

## R3: one verified package, no tracked-root mirroring

`scripts/opencode_runtime_release.py` packages the canonical hook, installed plugin
dependencies, generated agents, and a config with explicit pinned instruction and
skill paths. Its manifest binds file hashes, the coordinator commit and required
Task actions. Preparation can validate a committed source worktree while naming
the final runtime checkout that the existing launcher activates.

Before activation, validate binary/storage identity, package checksums, helper
commit/cleanliness, actual instantiated Task schemas, root-write denial, and normal
read routing. `scripts/probe_opencode_workflow.mjs` uses an isolated state root,
without creating chats. Missing plugin dependencies fail closed in the runtime.

The launcher disables project config discovery and selects the release-owned
`OPENCODE_CONFIG_DIR`. `sync_opencode_runtime_hook.py` no longer writes root files;
its legacy mirror entry point fails explicitly. The canonical hook bridge and
notifier executable come from the pinned coordinator; shared session state and
product checkout identity remain separate. The existing product subject-commit
selection and repaired test catalog lookup are retained, not replaced.

Prepare with `--no-activate`, verify the artifact, then select it and use the
existing `scripts/server-restart.sh` Zellij capture/resume workflow at a safe
boundary. Do not create additional agent chats. Roll back the complete release
and compatible launcher together, retain newer Task/workspace data, and rerun
storage/isolation/capability checks. A database schema migration needs new review.

## Evidence and limits

Focused Python and Node tooling fixtures cover receipt scope, provenance,
continuation cancellation, checkpoints, stale generations, duplicate processes,
worktree restoration and integration, package tampering, and effective guards.
These are implementation checks. Fewer corrections, repair loops and handoffs
remain predicted benefits until comparable real work is available. No automatic
monitoring is scheduled by this implementation.
