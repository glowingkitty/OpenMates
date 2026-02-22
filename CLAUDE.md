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

### Unexpected Failures During a Task (CRITICAL)

If you encounter a failure that is **not directly related to the task you were assigned**
(e.g. a broken feature you didn't touch, a test failing on something outside your scope):

1. **STOP immediately.** Do not attempt to fix it.
2. **Check git history first** — did your session or a concurrent session recently touch the broken code?
   ```bash
   git log -5 -- <file-that-contains-the-broken-code>
   ```
3. **If your session did NOT change the broken code:** report it to the user and ask for instructions. Do not attempt a fix.
4. **If your session DID change the broken code:** revert your change, verify the revert fixes it, then report what happened and ask how to proceed.

**Never spend more than 2 investigation attempts on a problem outside your assigned scope without explicit user approval to continue.**

### Debugging Attempt Limit (CRITICAL)

If you have tried the **same fix approach 2 times** and it has not worked:

- **STOP.**
- Summarize what you tried, what the symptoms are, and what you suspect the root cause is.
- Ask the user how to proceed.

Do not keep iterating with minor variations of the same approach (e.g. adding more diagnostic logs, increasing timeouts, trying different selectors for the same missing element). This wastes cycles and can mask the real problem.

### Task Completion Summary (CRITICAL)

**After completing every task (commit, lint, push — all done), end your final response with a structured summary.** Keep it concise — bullet points, not paragraphs. Use "N/A" for sections that don't apply.

```
## Task Summary

**Commit:** [abc1234](<commit-url>) (or "No commit" if nothing was committed)

**Problems Identified:** <root cause, error messages, symptoms — or "N/A" for feature work>

**Changes:** <what changed and why, with file:line references>

**Architecture Decisions:** <decision → reasoning → alternatives rejected and why — or "N/A">

**Testing:** <what was tested, how, results>

**Risks:** <what could break, untested edge cases, things to monitor — or "Low risk">
```

Rules: be honest about risks, be specific with file references, and always explain _why_ alternatives were rejected (not just list them).

### Auto-Commit After Every Task (CRITICAL)

- **ALWAYS commit and push to `dev` after completing a feature or bug fix** — do not wait for the user to ask.
- Only add files you actually modified in the current session (never `git add .`).
- Run the linter and fix all errors before committing.
- **After pushing frontend files (`frontend/`) or any `.yml` files**, wait for and verify the Vercel deployment succeeded before marking the task complete. Fix any build errors and re-deploy until the status is "● Ready". See `docs/claude/git-and-deployment.md` for the full verification procedure.
- See `docs/claude/git-and-deployment.md` for commit message format and full workflow.

### Research Before Implementing New Apps, Skills, or Features (CRITICAL)

**Before implementing any new app, skill, external API integration, or significant feature, you MUST:**

1. **Search for relevant official documentation** using web search tools — do NOT rely on training data, which may be months or years out of date. Look up:
   - Current API availability and pricing (free vs. paid tiers)
   - What the API can actually do (capabilities vs. limitations)
   - Authentication requirements
   - Rate limits and terms of service

2. **Read the relevant project docs** — check `docs/apps/` and `docs/architecture/` for any existing research or architecture decisions on the topic.

3. **Ask clarifying questions before writing any code.** Present your findings to the user and ask about:
   - Whether the API's actual capabilities match what the feature needs
   - Whether paid API access is acceptable (never assume)
   - Any ambiguous requirements that could affect design choices
   - Alternative approaches if the primary option has blockers

4. **Do not start implementation until the user confirms the approach.** Wasted implementation due to a misunderstood API or capability gap is much more costly than a short clarification exchange.

**Example triggers for this rule:**

- Integrating with a third-party API (events, maps, payments, social platforms, etc.)
- Implementing a new AI skill or tool
- Adding a new backend app or service
- Building a feature that touches external data sources

### Explicit Consent Required for Destructive/External Actions

- **NEVER create pull requests** unless the user explicitly asks for one. No exceptions.
- **NEVER merge branches** unless the user explicitly asks for it.
- **NEVER create or publish GitHub releases** unless the user explicitly asks for one — exception: when the user asks to create a PR, also preparing a draft release as part of that workflow is permitted.
- These actions affect production and other developers — they require clear, unambiguous user intent.

### Dependency Version Verification (CRITICAL)

**NEVER write a version number for any package or Docker image from memory.** LLM training data is outdated — the version you "know" may be months or years old. This applies to ALL dependency types without exception:

| Type             | How to verify                                                        |
| ---------------- | -------------------------------------------------------------------- |
| **pip**          | `pip index versions <package>` or web search `<package> pypi latest` |
| **pnpm/npm**     | `pnpm info <package> version` or web search `<package> npm latest`   |
| **Docker image** | Check Docker Hub tags via web search `<image> docker hub tags`       |

**Rules:**

- Always look up the version before writing it into any file
- Use exact pinned versions (e.g., `package==1.2.3`, `"package": "1.2.3"`, `image:1.2.3-slim`)
- Never use `latest`, `*`, or an unpinned dependency in committed files
- No exceptions for "well-known" packages — they change too

See `docs/claude/backend-standards.md` → "Package and Dependency Management" and `docs/claude/frontend-standards.md` → "Package and Dependency Management" for full details.

### No Private Infrastructure Details in Committed Files (CRITICAL)

**This is an open-source repository.** Never commit files containing real infrastructure details. ALL of the following must use generic placeholders (e.g., `<YOUR_DOMAIN>`, `<YOUR_EMAIL>`) in any committed file:

- **Domain names** — real project domains, subdomains, or internal hostnames
- **Email addresses** — ACME emails, personal emails, team emails
- **SSH keys** — public or private keys
- **GitHub repository URLs** — org/repo paths that identify the real project
- **IP addresses** — public or private server IPs
- **Server usernames** — real usernames used on servers
- **API keys, tokens, passwords** — even "example" ones that look real
- **Internal architecture details** — private network layouts, port mappings to specific services

**Template files** (`.example`, cloud-init templates, Caddyfile templates) are fine to commit, but ONLY with `<PLACEHOLDER>` values. Self-hosters should be able to use the templates by filling in their own values.

**If you are unsure whether a value is private:** treat it as private and use a placeholder.

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
- **If the API or a service appears down**, another assistant may be in the middle of rebuilding/restarting Docker containers. Before assuming a real failure, check whether a restart is in progress and wait for it to complete. See the "Service Unavailable During Concurrent Work" section in `docs/claude/debugging.md`.

#### Session Coordination (CRITICAL)

All concurrent sessions coordinate through a shared file: **`.claude/sessions.md`** (gitignored, lives only on the dev server). **You MUST use this file** to avoid duplicate work and conflicts.

**On session start:**

1. Generate a random 4-char hex session ID: `python3 -c "import secrets; print(secrets.token_hex(2))"`
2. Register yourself in the Active Sessions table in `.claude/sessions.md`

**Before fixing a Vercel deployment error:**

1. Read `.claude/sessions.md` → check the Vercel Deployment Lock
2. If another session holds the lock (and it's <5 min old) → **wait and poll every 30s**
3. If no lock is held → claim the lock, fix the error, then release the lock immediately

**Before rebuilding Docker containers:**

1. Read `.claude/sessions.md` → check the Docker Rebuild Lock
2. If another session holds the lock → **wait and poll every 30s**
3. If no lock is held → claim the lock, rebuild, then release the lock immediately

**Lock staleness:** If a lock's `Last updated` is 5+ minutes old, assume the holding session crashed and take over.

See `docs/claude/concurrent-sessions.md` for the full protocol, lock format, and file ownership tracking.

### Svelte 5 (CRITICAL)

**USE SVELTE 5 RUNES ONLY:**

- `$state()` for reactive state
- `$derived()` for computed values
- `$effect()` for side effects
- `$props()` for component props

**NEVER use `$:` reactive statements** - this is Svelte 4 syntax and must not be used.

### Docker Rebuild After Backend Changes (CRITICAL)

**Every time you modify Python files under `backend/`, you MUST rebuild and restart the affected Docker containers.** The backend runs inside Docker containers — editing files on disk does NOT update the running services. If you skip this step, your changes have no effect.

**Rebuild only the containers whose code you changed** — not the entire stack. See `docs/claude/backend-standards.md` for the full path-to-container mapping and commands.

```bash
# Example: rebuild and restart only what changed
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml build <container(s)> && \
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml up -d <container(s)>
```

---

## MANDATORY: Read Sub-Documents Before Working

**CRITICAL RULE: Before starting ANY task, you MUST determine which sub-documents below apply and READ THEM IN FULL using the Read tool. Do NOT skip this step. Do NOT assume you know the contents. These documents contain project-specific rules that override general knowledge. Failing to read them leads to incorrect code that must be rewritten.**

### Step 1: Determine which documents to read

For EVERY task, scan the trigger conditions below. If ANY condition matches, you MUST read that file before writing any code or making any changes.

### Step 2: Read all matching documents

Use the Read tool to load each matching file from `docs/claude/`. Do this BEFORE planning or writing code.

---

### Required Documents by Trigger

#### `docs/claude/frontend-standards.md`

**MUST READ when ANY of these are true:**

- You are editing, creating, or reviewing files under `frontend/`
- The task involves Svelte components, TypeScript, CSS, or stores
- You are touching `.svelte`, `.ts`, or `.css` files in the frontend

#### `docs/claude/backend-standards.md`

**MUST READ when ANY of these are true:**

- You are editing, creating, or reviewing files under `backend/`
- The task involves Python code, FastAPI routes, Pydantic models, or database queries
- You are touching `.py` files in the backend
- You are creating or modifying an app skill (includes REST API documentation requirements)

#### `docs/claude/debugging.md`

**MUST READ when ANY of these are true:**

- The user reports a bug, error, or unexpected behavior
- You need to read Docker logs or troubleshoot a service
- The task involves investigating why something doesn't work
- **You need to debug a production issue** (CRITICAL: use Admin Debug CLI, not local docker compose)

#### `docs/claude/inspection-scripts.md`

**MUST READ when ANY of these are true:**

- You need to inspect server state (chats, users, issues, cache, AI requests)
- You need to run diagnostic commands on the running services
- The user asks you to check or look up data on the server
- You need to debug production server state remotely (use Admin Debug CLI)

#### `docs/claude/git-and-deployment.md`

**MUST READ when ANY of these are true:**

- You are about to commit, push, or interact with git
- The task involves deployment, branch management, or PRs
- You need to understand the branch-to-server mapping

#### `docs/claude/testing.md`

**MUST READ when ANY of these are true:**

- You are creating, modifying, or running tests
- The user asks you to verify changes with tests

#### `docs/claude/figma-to-code.md`

**MUST READ when ANY of these are true:**

- The user provides a Figma link or references a Figma design
- The task involves implementing a UI design or matching a visual mockup

#### `docs/claude/i18n.md`

**MUST READ when ANY of these are true:**

- You are adding or modifying user-facing strings (labels, messages, errors shown to users)
- You are editing translation/i18n files

#### `docs/claude/planning.md`

**MUST READ when ANY of these are true:**

- You are implementing a new feature, significant refactor, or multi-file change
- The task is non-trivial and requires understanding data flow or component interaction
- You need to plan before writing code

#### `docs/claude/concurrent-sessions.md`

**MUST READ when ANY of these are true:**

- You are about to check or fix a Vercel deployment error
- You are about to rebuild or restart Docker containers
- You are starting a new session (to register yourself)
- Another assistant's work may conflict with yours (e.g., editing the same files)

#### `docs/claude/logging-and-docs.md`

**MUST READ when ANY of these are true:**

- You are adding logging statements or error handling
- You are updating project documentation

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
