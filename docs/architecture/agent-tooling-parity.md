# Agent Tooling Parity

OpenMates supports Claude Code and Codex from the same repository. Claude Code remains the canonical authoring format because the original project workflows, subagents, and deterministic hook scripts were written there first.

## Canonical Sources

- `.claude/skills/`: canonical project skills.
- `.claude/agents/`: canonical specialist subagents.
- `.claude/hooks/`: canonical deterministic policy scripts.
- `.claude/rules/`: canonical shared project rules.

## Compatibility Mirrors

- `.agents/skills/`: Agent Skills standard mirror for Codex. Skill names are normalized to lowercase hyphenated folder names.
- `.codex/agents/`: Codex TOML mirror generated from `.claude/agents/`.
- `.codex/hooks.json` and `.codex/hooks/claude-hook-bridge.sh`: Codex lifecycle bridge to `.claude/hooks/`.
- `docs/architecture/agent-tooling-parity.yml`: tracked shared-hook inventory for Claude Code and Codex parity checks.

## Sync Workflow

After changing Claude skills or agents, run:

```bash
python3 scripts/sync_agent_parity.py
```

Before deploy or review, verify parity with:

```bash
python3 scripts/sync_agent_parity.py --check
```

The check verifies shared skill mirrors, Codex agents, copied Codex hooks, and bridge references. Retired OpenCode-only skill mirrors are excluded; their Claude source files remain available for compatibility.

Also run the tracked hook/config parity audit when changing agent tooling:

```bash
python3 scripts/audit_agent_tooling_parity.py
```

## Hook Strategy

Hook scripts are not reimplemented per tool. Codex translates its native lifecycle payloads into the Claude hook payload shape and invokes the same shell scripts. This keeps policy behavior consistent and avoids drift between tools.

The shared hook baseline is listed in `docs/architecture/agent-tooling-parity.yml`. Tool-specific exceptions must include a reason there; otherwise the parity audit treats missing coverage as drift.

The shared Codex bridge preserves native routing, edit guards and terminal Mac
stop decisions. OpenCode plugin generation and registration have been removed.

## Session Worktrees

Agent sessions use existing routed source worktrees managed by `scripts/sessions.py`.
Session metadata and reconciliation remain shared with Claude-compatible tooling.
Codex hooks resolve the owning session; ordinary source edits use its worktree.

The repository root checkout is the control plane. Use it for orchestration commands such as `sessions.py status`, `sessions.py worktree ensure`, `sessions.py deploy`, diagnostics, and deploy verification. Ordinary source edits should happen in the path printed by:

```bash
python3 scripts/sessions.py worktree ensure --session <SESSION_ID>
```

`dev` remains the only integration and deploy branch. Session worktrees are disposable local workspaces, not long-lived user-managed branches. Native deploys reproduce only the selected source patch in a unique detached integration worktree based on an exact fetched `origin/dev` commit. Source-dependent gates and commit hooks run there, leaving root unchanged on failure. Finalization briefly locks, refreshes `origin/dev`, and either pushes the validated detached `HEAD:refs/heads/dev` without force or releases the lock to rebuild and rerun gates on the newer base. Deployed source worktrees remain untouched; durable workspace metadata distinguishes integrated patches from residual or concurrent changes without risking an automatic destructive reset. Grandfathered sessions retain the legacy root path until they finish.

Worktree reconciliation compares the session registry, Git-linked worktrees, and physical agent-worktree directories against an exact `origin/dev` commit. It distinguishes native, pilot-fallback, grandfathered source worktrees, and nonce-shaped disposable integration worktrees. Report-only reconciliation is the default. Safe application may delete a source worktree only after 48 hours without activity when its content is integrated, duplicated, or review-approved as superseded; stale integration worktrees are reproducible and may be removed under the same idle threshold. Deletion retains a compact source-free manifest for 30 days; recent, unique, and uncertain source work remains visible.

Session finalization is transactional: a fully deployed worktree is removed before session metadata, while residual changes keep the session in a pending state. Pull-request preparation runs `sessions.py worktree release-readiness`; explicitly confirmed recent work may be excluded, but stale, blocked, orphaned, malformed, or unresolved work blocks the PR.

Verification has two modes. Fast latest-ready checks may use the newest Ready dev deployment when exact proof is unnecessary. Exact-SHA checks must wait for the deployment or test run tied to the requested commit and must not treat a stale Ready deployment as proof for a different commit.

Root guards and exact-file edit leases remain enforced by the Codex bridge.
Runtime mutations require the applicable target and lease. Use orchestrated
worktree commands; do not replace a preserved source worktree after deployment.

## Retained history and explicit review

Historical OpenCode chat readers and persisted presence/worktree records remain.
The shared presence store still supports atomic task claims; no retired plugin
feeds new OpenCode lifecycle events or launches continuations.

Proof review prepares a bounded frame/caption request. An existing Codex
conversation reviews it and writes `review-result-round-N.json`, including its
actual Codex URL and exact request hash. Rerunning `proof_video_workflow.py review`
validates the receipt through the existing frame, assertion, caption and
publication gates. Preparation does not spawn an agent or consume review budget.
Use `start --current --session <existing-id>` for an explicit existing binding.
