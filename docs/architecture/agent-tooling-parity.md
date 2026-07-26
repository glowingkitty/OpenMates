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
- `.opencode/agents/` pins generated subagents to `openai/gpt-5.5`; OpenCode does not load the Claude Code provider or Claude hook bridge.

## Sync Workflow

After changing Claude skills or agents, run:

```bash
python3 scripts/sync_agent_parity.py
```

Before deploy or review, verify parity with:

```bash
python3 scripts/sync_agent_parity.py --check
```

The check verifies skill mirrors, Codex and OpenCode agent mirrors, copied Codex hook scripts, and Codex hook adapter references.

## Hook Strategy

Hook scripts are not reimplemented per tool. Codex translates its native lifecycle payloads into the Claude hook payload shape and invokes the same shell scripts. This keeps policy behavior consistent and avoids drift between tools.

Some lifecycle events are tool-specific. Codex supports `UserPromptSubmit` directly, so the bridge runs prompt context hooks there. OpenCode intentionally has no Claude Code hook bridge so it uses its native runtime and configured GPT subagent model only.

## Session Worktrees

Agent edit sessions use automatic local worktrees managed by `scripts/sessions.py`. OpenCode is the primary runtime, but the durable contract remains in `sessions.py` so Claude-compatible and Codex-compatible paths can share the same session metadata, deploy queue, cleanup, and verification policy.

The repository root checkout is the control plane. Use it for orchestration commands such as `sessions.py status`, `sessions.py worktree ensure`, `sessions.py deploy`, diagnostics, and deploy verification. Ordinary source edits should happen in the path printed by:

```bash
python3 scripts/sessions.py worktree ensure --session <SESSION_ID>
```

`dev` remains the only integration and deploy branch. Session worktrees are disposable local workspaces, not long-lived user-managed branches. Deploy integration reads the session worktree diff, applies only the intended file set to `dev` in a short guarded window, commits through `sessions.py deploy`, and records the resulting commit for verification.

Verification has two modes. Fast latest-ready checks may use the newest Ready dev deployment when exact proof is unnecessary. Exact-SHA checks must wait for the deployment or test run tied to the requested commit and must not treat a stale Ready deployment as proof for a different commit.

Root guards are transitional by default. OpenCode warns on root source edits and can switch to strict blocking with `OPENMATES_ROOT_GUARD=strict`; Codex continues to block raw `git worktree` while allowing orchestrated `sessions.py worktree ensure` and `sessions.py worktree cleanup` commands.
