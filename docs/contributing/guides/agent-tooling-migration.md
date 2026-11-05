# Agent tooling migration (Codex to Claude Code)

Claude Code is the only engineering agent. `CLAUDE.md` and path-scoped
`.claude/rules/` hold policy; skills, agents and hooks live only in `.claude/`.
The retired Codex worker, hook-context, lifecycle and orchestration scripts were
removed; the OpenMates CLI's Codex Task adapter is product code and remains
(`docs/architecture/cli-codex-adapter.md`). `sessions.py` retains workspace/lease coordination,
exact patch deployment and shared runtime ownership; full application E2E runs in
isolated GitHub CI. It no longer reads an editor transcript database, runs a second
Task bridge, creates local Task YAMLs from its CLI, or integrates idle chats.

Start and status emit compact, scoped text. Explicit `--json` preserves machine
interfaces; CI status/result/submit/wait support it. `ci_coordinator.py wait <id>`
reads the existing coordinator cache. `sessions.py wait-deploy --commit <sha>`
checks only Vercel statuses for that exact commit. Timeouts/failures never mean pass.

Deployment protocol 3 serializes preparation and gates through a host admission
lock, followed by the existing short push lock. External pushes can still advance
dev; retries stop after three preparations. Current tooling reads
`scripts/deploy-protocol-version`, falling back to the legacy
`.codex/deploy-protocol-version` (kept for older checkouts during the transition).

`response_media.py` replaces the editor-named upload helper. Existing S3 bucket
names and keys remain stable so retained receipts and media keep working; the
helper still creates private expiring URLs. Historical import formats, persisted
provider IDs and old task records are data compatibility, not agent instructions.

Session records now use `agent_task_id`/`agent_host` (the Claude Code session ID
and host); legacy `codex_task_id`/`codex_host` fields are migrated when
`sessions.json` is loaded. `sessions.py worktree bind-task --agent-task` replaces
`bind-codex --codex-task` (still accepted). CI receipts expose
`ci_evidence_command` (`scripts/ci_evidence.py`); old `codex_evidence*` receipts
stay readable. Decision provenance reads Claude Code transcripts by default;
Codex transcripts remain readable for historical receipts. The daily meeting
collector is `scripts/daily_meeting.py` and no longer reads agent chat history.
Task-specific local CLI source tests are allowed inside the bound workspace;
ordinary operations still use the installed `openmates` executable.

For fixes/features, maintain relevant E2E assertions even when execution is waived.
Use focused local checks, then isolated CI as appropriate. Inspect the first useful
failure, reassess after two unsuccessful attempts on the same blocker, and ask
before broadening into unrelated or uncertain repair. Videos are explicit
requested deliverables; UI review remains proportional to the changed behavior.
