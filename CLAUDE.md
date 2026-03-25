# OpenMates AI Assistant Instructions

Domain-specific rules are in `.claude/rules/` — loaded automatically by file path context.
Full contributing docs are in `docs/contributing/` — loaded on demand via `sessions.py context --doc <name>`.

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
│   └── contributing/           # Coding standards, guides (loaded by rules via @import)
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

### DRY — Search Before Writing

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

## Destructive Actions — Explicit Consent Only

- **NEVER** create PRs, merge branches, publish releases, or use `git stash` unless the user explicitly asks.
- **NEVER** use git worktrees (`git worktree add`) — all work happens in the main working directory.
- **Committing and pushing to `dev` via `sessions.py deploy` is NOT destructive** — it is expected after every task.
- This is **open-source**: use `<PLACEHOLDER>` values for domains, emails, SSH keys, IPs, API keys, repo URLs.

---

## Research Before New Integrations

Before any new app, skill, API integration, or significant feature:
1. Search for official docs (never rely on training data for APIs/pricing).
2. Check `docs/architecture/apps/`, `docs/architecture/`, and `docs/user-guide/apps/` for existing research.
3. Ask clarifying questions before writing code. Wait for confirmation.
