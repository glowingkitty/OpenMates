# Agent Tooling Parity

OpenMates supports Claude Code, Codex, and OpenCode from the same repository. Claude Code remains the canonical authoring format because the original project workflows, subagents, and deterministic hook scripts were written there first.

## Canonical Sources

- `.claude/skills/`: canonical project skills.
- `.claude/agents/`: canonical specialist subagents.
- `.claude/hooks/`: canonical deterministic policy scripts.
- `.claude/rules/`: canonical shared project rules.

## Compatibility Mirrors

- `.agents/skills/`: Agent Skills standard mirror for Codex and OpenCode. Skill names are normalized to lowercase hyphenated folder names.
- `.codex/agents/`: Codex TOML mirror generated from `.claude/agents/`.
- `.opencode/agents/`: OpenCode Markdown mirror generated from `.claude/agents/`.
- `.codex/hooks.json` and `.codex/hooks/claude-hook-bridge.sh`: Codex lifecycle bridge to `.claude/hooks/`.
- `.opencode/agents/` assigns each generated specialist an explicit GPT-5.6 Luna, Terra, or Sol route at medium reasoning effort. `opencode.json` routes built-in `explore` and `general` subagents to Terra at medium effort. OpenCode does not load the Claude Code provider.
- `docs/architecture/agent-tooling-parity.yml`: tracked shared-hook inventory for Claude Code, Codex, and OpenCode parity checks.

## Sync Workflow

After changing Claude skills or agents, run:

```bash
python3 scripts/sync_agent_parity.py
```

Before deploy or review, verify parity with:

```bash
python3 scripts/sync_agent_parity.py --check
```

The check verifies skill mirrors, explicit OpenCode model routes, Codex and OpenCode agent mirrors, copied Codex hook scripts, and Codex hook adapter references.

Also run the tracked hook/config parity audit when changing agent tooling:

```bash
python3 scripts/audit_agent_tooling_parity.py
```

## Hook Strategy

Hook scripts are not reimplemented per tool. Codex translates its native lifecycle payloads into the Claude hook payload shape and invokes the same shell scripts. This keeps policy behavior consistent and avoids drift between tools.

The shared hook baseline is listed in `docs/architecture/agent-tooling-parity.yml`. Tool-specific exceptions must include a reason there; otherwise the parity audit treats missing coverage as drift.

Some lifecycle events are tool-specific. Codex supports `UserPromptSubmit` directly, so the bridge runs prompt context hooks there. OpenCode uses its native plugin runtime and GPT subagent model, with a thin wrapper that invokes the shared `.codex/hooks/claude-hook-bridge.sh` only for deterministic shell hook compatibility.

## Session Worktrees

Agent edit sessions use automatic local worktrees managed by `scripts/sessions.py`. OpenCode is the primary runtime, but the durable Specification remains in `sessions.py` so Claude-compatible and Codex-compatible paths can share the same session metadata, blocked-deploy records, cleanup, and verification policy. OpenCode Web sessions remain root-addressed. Before each local tool executes, the plugin resolves the top-level OpenCode identity, follows child `parentID` when needed, and routes file/search arguments plus Bash `workdir` into the active session worktree. This route is reconstructed after restart and ignores obsolete native/pending labels when active worktree metadata is valid. Missing routing keeps reads and lifecycle recovery available and blocks only unresolved mutation with an exact next action.

The repository root checkout is the control plane. Use it for orchestration commands such as `sessions.py status`, `sessions.py worktree ensure`, `sessions.py deploy`, diagnostics, and deploy verification. Ordinary source edits should happen in the path printed by:

```bash
python3 scripts/sessions.py worktree ensure --session <SESSION_ID>
```

`dev` remains the only integration and deploy branch. Session worktrees are disposable local workspaces, not long-lived user-managed branches. Native deploys reproduce only the selected source patch in a unique detached integration worktree based on an exact fetched `origin/dev` commit. Source-dependent gates and commit hooks run there, leaving root unchanged on failure. Finalization briefly locks, refreshes `origin/dev`, and either pushes the validated detached `HEAD:refs/heads/dev` without force or releases the lock to rebuild and rerun gates on the newer base. Deployed source worktrees remain untouched; durable workspace metadata distinguishes integrated patches from residual or concurrent changes without risking an automatic destructive reset. Grandfathered sessions retain the legacy root path until they finish.

Top-level mutating OpenCode chats create a local `refs/openmates/checkpoints/<session>` commit when they become idle or close. This does not change `dev` or the source worktree. New mutating sessions opt into periodic recovery: after a grace period, the hourly controller rechecks the exact patch identity, live presence, edit leases, explicit holds, and sensitive paths, then invokes the normal `sessions.py deploy` transaction without test or hook waivers. Failed gates and conflicts remain durable `recovery_needed` state; legacy and uncheckpointed worktrees are never implicit integration inputs.

Worktree reconciliation compares the session registry, Git-linked worktrees, and physical agent-worktree directories against an exact `origin/dev` commit. It distinguishes native, pilot-fallback, grandfathered source worktrees, and nonce-shaped disposable integration worktrees. Report-only reconciliation is the default. Safe application may delete a source worktree only after 48 hours without activity when its content is integrated, duplicated, or review-approved as superseded; stale integration worktrees are reproducible and may be removed under the same idle threshold. Deletion retains a compact source-free manifest for 30 days; recent, unique, and uncertain source work remains visible.

Session finalization is transactional: a fully deployed worktree is removed before session metadata, while residual changes keep the session in a pending state. Pull-request preparation runs `sessions.py worktree release-readiness`; explicitly confirmed recent work may be excluded, but stale, blocked, orphaned, malformed, or unresolved work blocks the PR.

Verification has two modes. Fast latest-ready checks may use the newest Ready dev deployment when exact proof is unnecessary. Exact-SHA checks must wait for the deployment or test run tied to the requested commit and must not treat a stale Ready deployment as proof for a different commit.

Root guards are strict by default. OpenCode blocks root source edits unless `OPENMATES_ROOT_GUARD=off` is set for an explicit emergency, protects overlapping execute-mode file edits with short-lived `sessions.py edit-lease` records, and blocks raw Docker Compose mutations unless the current session holds the Docker lock. Codex continues to block raw `git worktree` while allowing orchestrated `sessions.py worktree ensure`, `sessions.py worktree reconcile`, and `sessions.py worktree release-readiness` commands.

## OpenCode Presence

OpenCode-specific lifecycle state is intentionally not mirrored into Claude or
Codex conversation hooks. `.opencode/plugins/openmates-hooks.js` consumes the
native event stream, reduces execution, attention, and turn outcome separately,
and debounces allowlisted records into `.opencode/presence.json` through
`scripts/opencode_presence_store.py`. The store is rooted in the shared control
plane, protected by `flock` plus atomic replacement, owner-only, and independent
from durable session/worktree metadata.

The installed `@opencode-ai/plugin` types declare the legacy
`permission.updated` event, while isolated OpenCode `1.17.20` runtime evidence
emits `permission.asked`. The reducer normalizes both and capability-gates V2
question events. Assistant completion, abort, late user-message replay, retries,
session closure, per-request resolution, and stale heartbeat expiry have explicit
deterministic transitions.

Presence never sends a prompt or system-transform message. A passive idle or
close event may launch only the bounded local worktree checkpoint command; it
cannot integrate code or start another assistant turn. Status, completed read
output, pre-edit guards, and explicit atomic task-claim commands are the only
coordination channels. Parent routing permits bounded Git history/diff, issue,
test-status, GitHub-run, and Docker-log inspection. Inherited children default
to read-only even before role metadata arrives; edits, test execution, service
mutation, shell expansion/redirection, and deploys remain blocked. Writable
children need their own repository session/worktree and disjoint ownership.

`scripts/verify_opencode_presence_live.py --isolated` is the runtime parity gate.
It creates concurrent top-level sessions plus an explicit child against a local
deterministic streaming provider and proves event delivery, permission handling,
tool-hook dispatch, relevant collision output, unchanged owner-chat messages,
resume, abort, and scoped cleanup without accessing normal OpenCode state.
