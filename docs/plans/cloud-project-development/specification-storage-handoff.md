# Specification storage and client handoff

TASK-1989 is the first delivery package of `plan.yml`. Its backend foundation is
implemented in session `9de5`; the shared Rust operations, SDK/CLI conformance and
user-facing authoring flow remain required before the package is complete.

## Backend boundary

All routes are below `/v1/projects/{project_id}/specifications`. Personal scope
omits `team_id`; Team scope supplies it as a query parameter. Existing Project
authorization is checked before document access. Team viewers can read;
owners/admins/members can write. Existing approved paired-device credentials use
`project:read` or `project:write`; this does not classify ordinary unpaired public
API keys for the capability.

| Method and suffix | Input | Response |
| --- | --- | --- |
| GET `/` | `limit` (1–100), optional UUID `after` | `specifications`, `next_cursor` |
| POST `/` | Initial revision, `specification_id`, `key_wrappers` | `specification`, `revision`, optional `replayed`; HTTP 201 |
| GET `/{specification_id}` | Optional `revision_id` | Current `specification` head and exact requested/current `revision` |
| GET `/{specification_id}/revisions` | `limit` (1–100), optional integer `before` | Newest-first `revisions`, `next_cursor` |
| POST `/{specification_id}/revisions` | New revision and `base_revision_id` | Updated head and new draft revision |
| POST `/{specification_id}/approve` | `revision_id`, `content_hash` | Head and that exact approved revision |

A revision input contains client-generated UUID `revision_id`, lowercase SHA256
`content_hash`, `project_surface_catalog_revision_id`, `encrypted_title`,
`encrypted_summary` and `encrypted_specification_document`. The backend receives
opaque ciphertext, not the authored document or a raw encryption key. Scope,
actor, revision number, timestamps and approval attribution are server derived.
The head has a stable identity and current-revision pointer; historical content
is immutable. Approval updates only approval metadata for the exact current
revision and hash. A subsequent edit creates a new draft and preserves the old
approval.

Every Specification requires a Project wrapper with `key_type: project`,
`hashed_project_id: SHA256(project_id)` and `encrypted_specification_key`.
Personal records may additionally have a `master` wrapper. Team records may have
a `team` wrapper with matching `hashed_team_id` and positive `team_key_epoch`.
Raw identities are hashed in the existing server-field convention. The existing
Project move transaction moves Specification heads/history to the Team and drops
obsolete Personal wrappers while preserving the Project wrapper and ciphertext.

The client must retain one proposed revision identity and its exact encrypted
bytes for retry. Reusing an identity with different bytes is a 409
`revision_identity_conflict`. A new edit against an outdated base is a 409
`revision_conflict`; preserve the local proposal, load the current revision and
offer reconciliation. Do not silently overwrite or automatically rebase approval.
An identical successful retry returns `replayed: true`, possibly alongside a newer
current head, so callers must inspect both head and returned revision identity.

## Shared Rust integration prerequisite

At the source inspection for this slice, the authoritative client extension
points were in the active native migration's `packages/openmates-rust` and
`packages/openmates-session-bindings`, absent from this session's base and
`origin/dev`. Its published handoff is
`docs/plans/rust-tui/sdk-conformance-project-items-2026-10-22-build-handoff.json`.
Integrate an exact supported source handoff before extending these modules; do
not copy a second crypto/client implementation into TypeScript or Python, or
change another task's worktree. Full native UI parity is not the prerequisite.

Extend the existing Project operations and scope/key resolution in
`work/projects.rs` through a Specification module. Reuse
`crypto/server_fields.rs`, the encrypted-work backend in `work/mod.rs`, and the
existing bindings in `session_work.rs` plus the cookie/API-key SDK entry points.
Use one Rust document serializer and content-commitment codec with interop
fixtures; the backend treats the hash as a client commitment and cannot verify
plaintext. The existing reader shape is
`frontend/packages/ui/src/components/embeds/specifications/SpecificationDocument.ts`.

Required client proof remains: create, list, exact-revision read, edit, history,
approval, lossless conflict recovery, Personal/Team key restoration, retry after
transport interruption and reload. Synchronize Rust, npm and pip operations and
capability inventory using the migration's `tests/sdk-conformance` runners. Web
authoring must consume those operations through a thin adapter.

## Verification limits

Focused checks currently pass: 21 Python storage/privacy checks and three atomic
transaction checks. `specifications-api-flow.spec.ts` exercises real API/CMS
storage with disposable Projects and AES-GCM fixture ciphertext in isolated CI.
Its wrapped keys are deliberately opaque fixtures: it does not prove SDK key
restoration, a working editor or the complete agentic development journey.
Final CI receipts and deployment identity belong in the Plan handoff and Task
activity once the run completes.
