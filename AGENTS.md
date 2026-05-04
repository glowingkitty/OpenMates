# OpenMates Agent Instructions

This repository is optimized for OpenCode while preserving the existing Claude Code setup.
Do not remove or replace `CLAUDE.md`, `.claude/`, Claude skills, Claude hooks, or Claude session tooling unless the user explicitly asks.

## Project Overview

OpenMates is a Svelte 5/SvelteKit, TypeScript, Python/FastAPI, PostgreSQL, Directus, and Docker monorepo.

- `frontend/apps/web_app/`: SvelteKit web application
- `frontend/packages/ui/`: shared UI components, services, stores, and i18n
- `backend/apps/`: application modules
- `backend/core/`: core API, workers, and monitoring
- `backend/shared/`: shared Python utilities, schemas, and providers
- `docs/`: architecture and contributing documentation
- `scripts/`: session, lint, deployment, and test tooling

## Working Rules

- Make the smallest correct change. Avoid rewrites unless the task requires one.
- Search before adding shared logic. Prefer existing utilities, components, providers, and schemas.
- Do not hide errors behind silent fallbacks. Log or surface failures clearly.
- Remove dead code, unused imports, and unused helpers when touching nearby code.
- Add new reusable frontend utilities under `frontend/packages/ui/src/utils/`.
- Add new reusable frontend components under `frontend/packages/ui/src/components/`.
- Add backend shared logic under `backend/shared/python_utils/`, `backend/shared/python_schemas/`, or `backend/shared/providers/`.
- Do not import from another backend skill. Move shared behavior to `BaseSkill` or `backend/shared/`.
- New `.py`, `.ts`, and `.svelte` files need a short header comment matching repo conventions.

## Safety Rules

- Never delete, rewrite, or disable Claude Code setup files unless explicitly requested.
- Never use destructive git commands such as `git reset --hard` or `git checkout --` unless explicitly requested.
- Never create PRs, merge branches, publish releases, use `git stash`, or use git worktrees unless explicitly requested.
- Treat secrets, credentials, production keys, `.env` files, and private tokens as off-limits.
- This is open source. Use `<PLACEHOLDER>` values for domains, emails, SSH keys, IPs, API keys, and private repo URLs.

## OpenCode Behavior

- Prefer OpenCode-native config in `opencode.json` for this repo.
- Existing Claude Code skills in `.claude/skills/` are intentionally retained; OpenCode can discover them through Claude compatibility.
- Existing Claude Code hooks are bridged for OpenCode by `.opencode/plugins/openmates-claude-hooks.js`; update the bridge instead of duplicating hook logic.
- Do not add GSD/Get-Shit-Done workflows, commands, hooks, or agents to this repo.
- If GSD files appear from global OpenCode config, treat them as unrelated user-level tooling and keep them disabled for OpenMates work.

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

## Verification

- Use the repo scripts rather than ad hoc commands when available.
- For Playwright and Vitest, follow `.claude/rules/testing.md`; do not run local test commands that the repo forbids.
- For changed code, run the smallest relevant lint/test/build command that proves the change.
- If verification is not run, state why.
