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
- `.opencode/plugins/openmates-claude-hooks.js`: OpenCode plugin bridge to `.claude/hooks/`.

## Sync Workflow

After changing Claude skills or agents, run:

```bash
python3 scripts/sync_agent_parity.py
```

Before deploy or review, verify parity with:

```bash
python3 scripts/sync_agent_parity.py --check
```

The check verifies skill mirrors, Codex and OpenCode agent mirrors, copied Codex hook scripts, and hook adapter references.

## Hook Strategy

Hook scripts are not reimplemented per tool. Codex and OpenCode adapters translate their native lifecycle payloads into the Claude hook payload shape and invoke the same shell scripts. This keeps policy behavior consistent and avoids drift between tools.

Some lifecycle events are tool-specific. Codex supports `UserPromptSubmit` directly, so the bridge runs prompt context hooks there. OpenCode exposes hooks through plugin events, so the bridge maps supported events such as tool execution and session idle to the closest Claude hook equivalents.
