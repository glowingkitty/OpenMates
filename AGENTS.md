# OpenMates AI Assistant Instructions

This repository is optimized for Codex/OpenCode while preserving the existing Claude Code setup.
Do not remove or replace `CLAUDE.md`, `.claude/`, Claude skills, Claude hooks, or Claude session tooling unless the user explicitly asks.

Domain-specific rules are in `.claude/rules/`. OpenCode loads the same rules through `opencode.json`; Codex should follow this file plus those shared Claude-compatible rules.
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
├── vaults/
│   └── memory/                 # Obsidian vault for notes, research, memory, and attachments
└── scripts/                    # sessions.py, lint_changed.sh, test runners
```

---

## Core Principles

- **KISS:** Small, focused, well-named functions. No over-engineering.
- **Clean Code:** Remove unused functions, variables, imports, dead code.
- **No Silent Failures:** Never hide errors with fallbacks. All errors must be visible and logged.
- **No Magic Values:** Extract raw strings/numbers to named constants.
- **Comments:** Explain business logic and architecture decisions. Link to `docs/architecture/`.
- **File headers:** Every new `.py`, `.ts`, `.svelte` file needs a header comment (5-10 lines).
- **Deterministic guardrails:** When repeated bugs, flaky tests, security/privacy risks, provider metadata drift, or OpenCode workflow issues cost debugging time or inference tokens, prefer creating or updating a deterministic script, audit, hook, or focused test guard that prevents the same issue from recurring.

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

## Obsidian Vault

- The Obsidian vault lives at `/home/superdev/projects/OpenMates/vaults/memory/` (`vaults/memory/` from the repo root).
- Create user-requested notes in that vault, using existing folders such as `Resources/research/`, `Areas/`, or `Projects/` when appropriate.
- Put PDFs, images, and other attachments in `vaults/memory/assets/` unless the user asks for a different location.

---

## Working Rules

- Make the smallest correct change. Avoid rewrites unless the task requires one.
- Search before adding shared logic. Prefer existing utilities, components, providers, and schemas.
- Add backend shared logic under `backend/shared/python_utils/`, `backend/shared/python_schemas/`, or `backend/shared/providers/`.
- Do not import from another backend skill. Move shared behavior to `BaseSkill` or `backend/shared/`.
- Use the repo scripts rather than ad hoc commands when available.
- App metadata must not use `stage`. Apps, skills, embeds, focus modes, memory fields, and platform features are enabled by default; add sparse `default_enabled: false` only when a feature intentionally ships off by default.
- Treat deterministic scripts as a first-class outcome of bug fixes and code-quality work. Prefer updating an existing script over adding a new one; wire checks into hooks only when they are path-scoped, fast, and low-noise, otherwise expose them as on-demand scripts from the relevant skill.
- For Playwright and Vitest, follow `.claude/rules/testing.md`; do not run local test commands that the repo forbids.
- For `*.spec.ts` Playwright verification, deploy the change to `dev` first, wait for the deployment to be live, then run the spec. Do not run E2E specs against undeployed local code.
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
- Existing Claude Code skills in `.claude/skills/` are intentionally retained; OpenCode uses the `.agents/skills/` mirror and must not call the Claude Code runtime.
- Codex discovers repo skills from `.agents/skills/`. Keep `.agents/skills/` as the Codex/OpenCode-compatible mirror of `.claude/skills/`, using Agent Skills compliant names (`lowercase-hyphenated`, matching the folder name).
- Do not add project skills under `.codex/skills/` or `.opencode/skills/` unless a tool-specific override is explicitly needed; use `.agents/skills/` for shared skills.
- OpenCode must not load the Claude Code provider or Claude hook bridge; generated `.opencode/agents/` subagents use `openai/gpt-5.5`.
- Existing Claude Code hooks are bridged for Codex by `.codex/hooks/claude-hook-bridge.sh` and `.codex/hooks.json`; update that bridge instead of duplicating hook logic.
- Claude Code remains the canonical authoring format for project skills, subagents, and hook scripts. Run `python3 scripts/sync_agent_parity.py` after changing `.claude/skills/` or `.claude/agents/`, and run `python3 scripts/sync_agent_parity.py --check` to verify `.agents/skills/`, `.codex/agents/`, `.opencode/agents/`, and hook adapters are in sync.
- Do not add GSD/Get-Shit-Done workflows, commands, hooks, or agents to this repo.
- If GSD files appear from global OpenCode config, treat them as unrelated user-level tooling and keep them disabled for OpenMates work.

### Skill Auto-Selection

Use OpenCode skills proactively when the task matches their purpose. Do not wait
for the user to name the skill if the intent is clear.

Spec-driven development:
- Auto-select `specify` before implementing complex, risky, multi-session, or multi-system work. Do not wait for the user to name the skill when the intent is clearly implementation.
- Full specs are required for auth, encryption, billing, privacy, teams, sharing, permissions, sync, AI pipeline changes, provider integrations, migrations, new API routes, app skills, embed types, background jobs, cron jobs, and Directus schema changes.
- Full specs use one executable YAML source of truth at `docs/specs/<slug>/spec.yml`; do not create separate Markdown spec, plan, or task files for new specs.
- Before writing `spec.yml`, discover existing GitHub Issues, relevant Linear tasks only when appropriate, docs, source patterns, and tests; then ask up to five rounds of clarifying questions, one question per message. Wait for the user's response before asking the next question, then wait for the user's vision confirmation before writing the final full spec.
- Use `plan-from-spec` and `tasks-from-spec` after a full spec is approved; they update `implementation_plan` and `tasks` inside `spec.yml`.
- Write or update the tests listed in `spec.yml` before feature code. Record red-phase evidence before implementation. For Playwright, red and green runs target live `app.dev.openmates.org`; green evidence is only valid after deploy and Vercel is Ready.
- Run `python3 scripts/spec_validate.py docs/specs/<slug>/spec.yml` after spec edits and `python3 scripts/spec_verify.py docs/specs/<slug>/spec.yml` before marking the spec complete or deploying full-spec work.
- Use an inline spec instead of a full spec for small behavior changes; skip specs for trivial or mechanical work. See `docs/contributing/guides/spec-driven-development.md` for the boundary.

Common routing:
- New external API/provider: use `add-api`.
- New backend app skill: use `add-app-skill`.
- New embed type: use `add-embed-type`.
- New hardcoded example chat from a share URL: use `add-example-chat`.
- User-visible bug with reproducible behavior: use `reproduce-first` before fix code.
- Latest failing tests or daily-run failures: use `fix-tests` or `fix-next-test`.
- User-reported issue ID or debugging timeline: use `debug-issue`; for encryption/key/sync symptoms, use the encryption/debug specialist subagents from the available agent list.
- Vercel deployment failure: use `fix-vercel`.
- Production SSH request: use `prod-ssh`.
- Newsletter creation/publishing: use `create-newsletter` or `publish-newsletter`.
- iOS/macOS parity work: use `ios`.
- Task creation or prioritization: use `new-task` or `next-tasks`.

If multiple skills apply, choose the earliest workflow gate first. For example,
for a new provider-backed app skill, run `specify` or `add-api` research before
scaffolding with `add-app-skill`; for a bug, reproduce with a failing test
before implementation.

### Reported Issue Workflow

- The reported issue database is the source of truth for user-submitted issue IDs; GitHub and Linear are secondary links, not the starting point.
- Use `python3 scripts/issues.py show <issue-id> --env prod` and `python3 scripts/issues.py findings <issue-id> --env prod` before product-code changes. Use `--env dev` only when the report is known to be from dev.
- Store durable investigation notes under `docs/findings/issues/<env>/<YYYY>/` and update them with first anomaly, root-cause hypothesis, related reports, attempts, tests, and status.
- Prefer `scripts/issues.py list`, `cluster`, `recent`, and `timeline` over raw `debug.py issue` commands. Keep `debug.py` for low-level forensic/admin actions that the workflow wrapper does not expose.
- Redact private user data and share URL `#key=` fragments in findings notes.

---

## Lazy-Load Rules

Use the repo rule files when the task touches relevant areas. In OpenCode, these are also listed in `opencode.json` instructions.

- Frontend work: `.claude/rules/frontend.md`
- Design/UI/media work: `DESIGN.md`
- Backend work: `.claude/rules/backend.md`
- Tests or test failures: `.claude/rules/testing.md`
- Privacy/legal/provider work: `.claude/rules/privacy.md`
- Settings UI: `.claude/rules/settings-ui.md`
- i18n: `.claude/rules/i18n.md`
- Deployment/session lifecycle: `.claude/rules/deployment.md` and `.claude/rules/session-lifecycle.md`
- Debugging: `.claude/rules/debugging.md`
- Embeds: `.claude/rules/embed.md`
- Apple UI: `.claude/rules/apple-ui.md`
- Planning and acceptance criteria: `.claude/rules/planning.md`
- Task tracking workflow: `.claude/rules/task-management.md` — GitHub Issues by default; Linear only for programmatically stored/recorded issues, marketing work, sensitive/private work, or explicitly provided Linear issues.

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

1. Search existing tracker entries before creating new ones. Use GitHub Issues by default. Use `python3 scripts/linear.py` only for programmatically stored/recorded issues, marketing work, sensitive/private work, or explicitly provided Linear issues.
2. Search for official docs (never rely on training data for APIs/pricing).
3. Check `docs/architecture/apps/`, `docs/architecture/`, and `docs/user-guide/apps/` for existing research.
4. Ask clarifying questions before writing code. Wait for confirmation.
