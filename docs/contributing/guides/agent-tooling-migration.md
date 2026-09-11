# Codex tooling migration

AGENTS.md is the shared policy root, kept below 6 KB. Claude skills are the source
for generated Codex mirrors. `sessions.py` retains workspace/lease coordination,
exact patch deployment and shared runtime ownership; full application E2E runs in
isolated GitHub CI. It no longer reads an editor transcript database, runs a second
Task bridge, creates local Task YAMLs from its CLI, or integrates idle chats.

Start and status emit compact, scoped text. Explicit `--json` preserves machine
interfaces; CI status/result/submit/wait support it. `ci_coordinator.py wait <id>`
reads the existing coordinator cache. `sessions.py wait-deploy --commit <sha>`
checks only Vercel statuses for that exact commit. Timeouts/failures never mean pass.

Deployment protocol 3 serializes preparation and gates through a host admission
lock, followed by the existing short push lock. External pushes can still advance
dev; retries stop after three preparations. A tiny `.opencode/deploy-protocol-version`
marker also contains 3, solely to stop already-running old worktrees from deploying
with protocol 2. It contains no executable integration and can be removed once all
old worktrees are gone. New code reads `.codex/deploy-protocol-version`.

`response_media.py` replaces the editor-named upload helper. Existing S3 bucket
names and keys remain stable so retained receipts and media keep working; the
helper still creates private expiring URLs. Historical import formats, persisted
provider IDs and old task records are data compatibility, not agent instructions.

Hooks emit a full Tasks snapshot at start/resume and only changes afterwards.
Task-specific local CLI source tests are allowed inside the bound workspace;
ordinary operations still use the installed `openmates` executable.

For fixes/features, maintain relevant E2E assertions even when execution is waived.
Use focused local checks, then isolated CI as appropriate. Inspect the first useful
failure, reassess after two unsuccessful attempts on the same blocker, and ask
before broadening into unrelated or uncertain repair. Videos are explicit
requested deliverables; UI review remains proportional to the changed behavior.
