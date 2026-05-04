# OpenMates AI Assistant Instructions

This repository is optimized for Codex/OpenCode while preserving the existing Claude Code setup.
Do not remove or replace `CLAUDE.md`, `.claude/`, Claude skills, Claude hooks, or Claude session tooling unless the user explicitly asks.

Domain-specific rules are in `.Codex/rules/` and `.claude/rules/` depending on the active assistant tooling.
Full contributing docs are in `docs/contributing/` and can be loaded on demand via `sessions.py context --doc <name>`.

---

## Project Overview

**Frontend:** Svelte 5/SvelteKit, TypeScript, CSS Custom Properties
**Backend:** Python/FastAPI, PostgreSQL/Directus CMS, Docker microservices

```
OpenMates/
├── frontend/
│   ├── apps/web_app/           # SvelteKit web application
│   └── packages/ui/            # Shared UI components, services, stores, i18n
├── backend/
│   ├── apps/                   # Application modules (ai, web, etc.)
│   ├── core/                   # Core API, workers, monitoring
│   ├── shared/                 # Shared utilities, schemas, providers
│   └── tests/
├── docs/
│   ├── architecture/           # Architecture decision docs
│   └── contributing/           # Coding standards, guides
└── scripts/                    # sessions.py, lint_changed.sh, test runners
```

---

## Core Principles

- **KISS:** Small, focused, well-named functions. No over-engineering.
- **Clean Code:** Remove unused functions, variables, imports, dead code.
- **No Silent Failures:** Never hide errors with fallbacks. All errors must be visible and logged.
- **No Magic Values:** Extract raw strings/numbers to named constants.
- **Comments:** Explain business logic and architecture decisions. Link to `docs/architecture/`.
- **File headers:** Every new `.py`, `.ts`, `.svelte` file needs a header comment matching repo conventions.

### DRY: Search Before Writing

| Shared location                        | What goes there                            |
| -------------------------------------- | ------------------------------------------ |
| `backend/shared/python_utils/`         | Backend shared logic                       |
| `backend/shared/python_schemas/`       | Shared Pydantic models                     |
| `backend/shared/providers/`            | Pure API wrappers (no skill-specific code) |
| `frontend/packages/ui/src/utils/`      | Frontend shared utilities                  |
| `frontend/packages/ui/src/components/` | Shared Svelte components                   |
| `settings/elements/`                   | Settings UI components (29 canonical)      |

Architecture decisions: write once in `docs/architecture/`, reference in code.

---

## Working Rules

- Make the smallest correct change. Avoid rewrites unless the task requires one.
- Search before adding shared logic. Prefer existing utilities, components, providers, and schemas.
- Add backend shared logic under `backend/shared/python_utils/`, `backend/shared/python_schemas/`, or `backend/shared/providers/`.
- Do not import from another backend skill. Move shared behavior to `BaseSkill` or `backend/shared/`.
- Use the repo scripts rather than ad hoc commands when available.
- For Playwright and Vitest, follow `.claude/rules/testing.md`; do not run local test commands that the repo forbids.
- For changed code, run the smallest relevant lint/test/build command that proves the change.
- If verification is not run, state why.

---

## Safety Rules

- Never delete, rewrite, or disable Claude Code setup files unless explicitly requested.
- Never use destructive git commands such as `git reset --hard` or `git checkout --` unless explicitly requested.
- Never create PRs, merge branches, publish releases, use `git stash`, or use git worktrees unless explicitly requested.
- Treat secrets, credentials, production keys, `.env` files, and private tokens as off-limits.
- This is open source. Use `<PLACEHOLDER>` values for domains, emails, SSH keys, IPs, API keys, and private repo URLs.
- Committing and pushing to `dev` via `sessions.py deploy` is not destructive; it is expected after every task.

---

## OpenCode Behavior

- Prefer OpenCode-native config in `opencode.json` for this repo.
- Existing Claude Code skills in `.claude/skills/` are intentionally retained; OpenCode can discover them through Claude compatibility.
- Existing Claude Code hooks are bridged for OpenCode by `.opencode/plugins/openmates-claude-hooks.js`; update the bridge instead of duplicating hook logic.
- Do not add GSD/Get-Shit-Done workflows, commands, hooks, or agents to this repo.
- If GSD files appear from global OpenCode config, treat them as unrelated user-level tooling and keep them disabled for OpenMates work.

---

## Lazy-Load Rules

Use the repo rule files when the task touches relevant areas. In OpenCode, these are also listed in `opencode.json` instructions.

- Frontend work: `.claude/rules/frontend.md`
- Backend work: `.claude/rules/backend.md`
- Tests or test failures: `.claude/rules/testing.md`
- Privacy/legal/provider work: `.claude/rules/privacy.md`
- Settings UI: `.claude/rules/settings-ui.md`
- i18n: `.claude/rules/i18n.md`
- Deployment/session lifecycle: `.claude/rules/deployment.md` and `.claude/rules/session-lifecycle.md`
- Debugging: `.claude/rules/debugging.md`
- Embeds: `.claude/rules/embed.md`

---

## Parallel Work: Spawning Separate Sessions

You can suggest spawning parallel Codex sessions for independent tasks.
Always ask the user for confirmation before spawning.

```bash
# Spawn a planning/research session (default: plan mode, read-only)
python3 scripts/sessions.py spawn-chat --prompt "Research how X works" --name "research-X"

# Spawn with a prompt file
python3 scripts/sessions.py spawn-chat --prompt-file scripts/.tmp/prompt.txt --name "plan-task"

# Spawn with full edit access (only when user explicitly requests direct fix/implementation)
python3 scripts/sessions.py spawn-chat --prompt-file scripts/.tmp/fix-prompt.txt --name "fix-OPE-42" --mode execute
```

The user attaches via `zellij attach <name>` or the web UI at localhost:8082.

**When to suggest:** Multiple independent tasks, post-meeting planning, parallel research.
**When NOT to:** Tasks with file conflicts, sequential dependencies, or when the user prefers focused work.
**Default is plan mode.** Only use `--mode execute` when the user makes it very clear the task should be directly implemented by the spawned session.

---

## Research Before New Integrations

Before any new app, skill, API integration, or significant feature:

1. Search for official docs (never rely on training data for APIs/pricing).
2. Check `docs/architecture/apps/`, `docs/architecture/`, and `docs/user-guide/apps/` for existing research.
3. Ask clarifying questions before writing code. Wait for confirmation.
