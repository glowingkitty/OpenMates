# OpenMates AI Assistant Instructions

This document provides essential guidelines for AI assistants working on the OpenMates codebase. For detailed standards, see the linked documentation in each area.

---

## Project Overview

OpenMates is a multi-platform application with:

- **Frontend**: Svelte 5/SvelteKit, TypeScript, CSS Custom Properties
- **Backend**: Python with FastAPI
- **Database**: PostgreSQL with Directus CMS
- **Architecture**: Microservices with Docker

### Project Structure

```
OpenMates/
├── frontend/
│   ├── apps/web_app/           # SvelteKit web application
│   └── packages/ui/            # Shared UI components and services
│       └── src/
│           ├── components/     # Svelte components
│           ├── services/       # TypeScript services
│           ├── stores/         # Svelte stores
│           ├── styles/         # CSS files (theme.css, buttons.css, etc.)
│           └── i18n/           # Translation files
├── backend/
│   ├── apps/                   # Application modules (ai, web, etc.)
│   ├── core/                   # Core API, workers, and monitoring
│   │   ├── api/               # FastAPI routes and handlers
│   │   └── directus/          # Directus schema definitions
│   ├── shared/                # Shared utilities and schemas
│   └── tests/                 # Backend tests
├── docs/
│   └── architecture/          # Architecture documentation
└── scripts/                   # Utility scripts
```

---

## Core Principles

### Code Quality

- Write clean, readable, and maintainable code
- Follow existing patterns in the codebase
- Add comprehensive comments explaining business logic and architecture decisions
- Use meaningful variable and function names
- Keep functions small and focused on single responsibility

### Design Philosophy

- **KISS Principle**: Keep it simple - avoid over-engineering and unnecessary complexity
- **Extensibility**: Design code to be easily extended later without major refactoring
- **Clean Code**: Remove all unused functions, variables, imports, and dead code
- **No Silent Failures**: Never hide errors with fallbacks - all errors must be visible and logged

### Comments and Documentation

- Ensure every file has detailed comments explaining what the code does
- Explain key architecture decisions in comments
- Link to relevant architecture docs where appropriate

### Explicit Consent Required for Destructive/External Actions

- **NEVER create pull requests** unless the user explicitly asks for one. No exceptions.
- **NEVER merge branches** unless the user explicitly asks for it.
- These actions affect production and other developers — they require clear, unambiguous user intent.

### Logging Rule

- **Only remove debugging logs after the user confirms the issue is fixed**
- Do not remove logs assuming you fixed the issue - wait for confirmation

### Issue Resolution

- **After an issue is completed and the user confirms it is fixed**, delete the issue entry so it no longer appears in the list and storage is cleaned (Directus + S3). Use one of:
  - **Server (preferred):** `docker exec api python /app/backend/scripts/inspect_issue.py <issue_id> --delete --yes`
  - **Admin Debug API:** `DELETE /v1/admin/debug/issues/<issue_id>` with admin API key
  - **Admin Debug CLI:** `docker exec api python /app/backend/scripts/admin_debug_cli.py issue-delete <issue_id>`

### Multiple Assistants (Concurrent Work)

- **Several assistants may work on the codebase at the same time.** File content or git state can change between your turns.
- **Re-read files before editing** if you haven't touched them recently — another assistant may have changed them.
- **Check git status** before committing; files may already be committed by another assistant. Only add and commit what you actually changed this session.

### Svelte 5 (CRITICAL)

**USE SVELTE 5 RUNES ONLY:**

- `$state()` for reactive state
- `$derived()` for computed values
- `$effect()` for side effects
- `$props()` for component props

**NEVER use `$:` reactive statements** - this is Svelte 4 syntax and must not be used.

---

## Detailed Standards

Load these documents when working on the relevant area:

### Code Standards

- **docs/claude/frontend-standards.md** — Load when modifying Svelte components, TypeScript services, CSS, or stores under `frontend/`
- **docs/claude/backend-standards.md** — Load when modifying Python code, FastAPI routes, or Pydantic models under `backend/`

### Debugging & Inspection

- **docs/claude/debugging.md** — Load when investigating bugs, reading logs, or troubleshooting Docker services
- **docs/claude/inspection-scripts.md** — Load when you need to inspect chats, users, issues, cache, or AI requests on the server

### Workflow & Testing

- **docs/claude/git-and-deployment.md** — Load when committing code, creating PRs, deploying changes, or understanding branch/server mapping
- **docs/claude/testing.md** — Load when creating or running tests

### Translations & Documentation

- **docs/claude/i18n.md** — Load when adding or modifying user-facing strings or translation files
- **docs/claude/logging-and-docs.md** — Load when adding logging, error handling, or updating documentation

---

## Linting (ALWAYS run before commit)

```bash
# Python changes
./scripts/lint_changed.sh --py --path backend/

# Frontend changes
./scripts/lint_changed.sh --ts --svelte --path frontend/packages/ui

# Mixed changes
./scripts/lint_changed.sh --py --ts --svelte --path backend --path frontend/
```

**CRITICAL**: Before every git commit, run the linter on all modified files and fix all errors. Only commit when the linter shows NO errors.