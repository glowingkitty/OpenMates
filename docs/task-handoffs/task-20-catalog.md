# TASK-20 / TASK-5238 catalog handoff

Session: `4f00`; actual thread: `01a080f6-e8f2-7032-a4e4-2204c189d088`.
Worktree: `.openmates-agent-worktrees/agent-4f00`, distinct from coordinator `agent-4aa6` and other workers. Task thread connection is pending; API attempts returned HTTP 429. Per coordinator, no further task reads/connect/posts until serialized recovery.

## Implemented removal patch

- Removed both urban sports examples, dermatology, PDF encryption, product-launch mindmap, old career, OpenMates get-docs, private-workspace demo video: eight fixtures, translations, registry entries and interest references.
- Removed those landing references and missing learning ID. Local-AI compression and Svelte remain in the catalog outside landing.
- Existing workshops remains mapped. Other slide arrays await approved candidates. No replacements registered and no candidate approval inferred.
- `backend/apps/openmates/app.yml`: sparse `default_enabled: false` for `openmates.get-docs`. Separate `code.get_docs` remains enabled.
- Removed rejected-fixture-only mindmap test and video fixture cases. Updated ranking fixture to preserved local-AI; settings shell test to preserved Svelte; focus leak test to existing Framework reputation. Shared focus/video implementation stays with assigned owners.

## Verification and remaining gates

- SDK/CLI parity in this worktree: 89 commands and 4 workflow templates passed.
- `git diff --check` passed.
- Earlier focused checks passed 17 tests and generated settings metadata excluded `openmates.get-docs`, but ran from canonical checkout containing this exact patch before routing recovery. Worktree rerun pending dependency bootstrap.
- Earlier structural audit identified one content gap: `mindmaps.mindmap` has no example after requested rejection. Keep visible until accepted replacement; do not weaken audit.
- Specification source-path check passed; changed-test check reported stale generated assertion index. Recheck against current coordinated Specification artifacts before integration.
- Queued CI request `fae4df5ff544e058c39969522cfa4246bb4050d29e5e117b3cdaf635d8f5d95c`, candidate `dad7eefcc84ff2a68060daac5130d569275af651`, is INVALID as patch evidence: created before routing recovery, with no implementation diff. Do not use its result for acceptance.
- No dev deployment, reviewed browser/video proof, live runtime restart or task completion claimed. Runtime changes require explicit target and coordinator lease.

## Replacement handoff required

Coordinator/example owners must supply candidate source/i18n paths and passing review records (real CLI, phone/laptop, required speech admission), then catalog owner can integrate. None supplied yet. Mindmap category currently lacks an admissible example. Keep assignment open.

## Routing recovery

Final directory check found default exec calls had used canonical root despite session binding. Stopped writes; inspected exact root-dirty metadata; imported all 27 reviewed task paths with sessions.py worktree import-root; checked identical bytes; reversed only the exact task patch in canonical root. Recovery backup: `/tmp/task20-root-routing-recovery.patch`. Canonical root retained only an unrelated untracked `config.json`, not read or staged. Every subsequent command sets explicit workdir to agent-4f00.

Agent process retrospective: repeated Tasks API attempts before coordinator backoff and an unsupported skill-prescribed --dry-run wasted calls. More seriously, relying on binding without explicit exec workdir required patch recovery and invalidated CI evidence. Existing session instructions already require isolation; recommend a deterministic pre-exec hook/audit that rejects mutating shell calls whose actual cwd differs from the bound worktree. Inspection confirms scripts/codex_hook_context.py route() handles Bash/bash and apply_patch, but returns unchanged for other tool names. Smallest hook fix: support exec_command cmd/workdir payloads, including orchestrated calls, with a regression test that a bound chat cannot mutate canonical root. No product-scope workflow tooling edits made.

## Verified worktree rerun

Offline frozen-lockfile dependency installation completed in agent-4f00. Focused Vitest rerun explicitly reported agent-4f00 as its root: 2 files, 17 tests passed. Apps and embed metadata generated in agent-4f00. Direct assertion verifies sparse disabled `openmates.get-docs` is absent from generated Apps/settings metadata while `code.get_docs` remains. Structural audit rerun confirms exactly one issue: absent mindmap example. SDK/CLI parity and diff whitespace checks passed in agent-4f00.

Worktree source-path Specification check rerun passed for all three affected product-source paths.

Final scoped lint: ActiveChat contract guards, changed TypeScript lint and Svelte lint passed. Aggregate wrapper skipped tsc because it searched the tests directory for a binary, and initially failed token validation because generated tokens were missing. Generated tokens locally; reran token validator with explicit --file. Broad accidental validator invocation showed unrelated existing token errors; those are not assigned changes. No assertion of a full application typecheck or browser proof.

## Explicit deletion deployment instruction

User confirms rejected-example deletion is independently deployable; replacement readiness is not a prerequisite. Missing mindmaps.mindmap coverage is an intentional temporary consequence of approved removal. Preserve the audit and record its finding; do not restore rejected content or weaken unrelated guards. Deploy cleanup and sparse OpenMates get-docs disable now, splitting get-docs if combined cleanup is gated. Registration of unreviewed replacements remains forbidden.
