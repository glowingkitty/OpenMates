# OpenMates AI Assistant Instructions

This document provides essential guidelines for AI assistants working on the OpenMates codebase. For detailed standards, see the linked documentation in each area.

---

## MANDATORY: Session Lifecycle (Do This First and Last)

**Every session — no exceptions — must run these commands:**

```bash
# 1. FIRST thing, before any work:
python3 scripts/sessions.py start --task "brief description of what you are doing"
# → Saves your session ID (e.g. "a3f2"). You MUST use this ID in all subsequent commands.
# → Tags are auto-inferred from the task description (e.g. "fix button" → frontend,debug).
#   Override with --tags "frontend,test" if auto-inference is wrong.
# → Relevant instruction docs (from docs/claude/) are printed inline based on tags.
#   READ THEM — they contain project-specific rules that override general knowledge.
# → Architecture doc index is printed so you can load specific ones later with:
#   python3 scripts/sessions.py context --doc <name>

# 2. After EVERY file you edit or create (manually — automation is not reliable):
python3 scripts/sessions.py track --session <ID> --file path/to/file.py

# 3. Before deploying (loads git/deployment docs deferred from session start):
python3 scripts/sessions.py deploy-docs

# 4. LAST thing, after committing:
python3 scripts/sessions.py end --session <ID>
```

**Why this matters:** Multiple assistants work on this codebase simultaneously. Without registering, your files are invisible to other sessions — risking edit collisions and broken deployments. The `start` output gives you active session info, lock status, stale docs, a project index, and **all relevant instruction docs inline** — so you don't need separate Read calls.

### Available Tags

Tags control which instruction docs are preloaded. They are auto-inferred from the task description, or set explicitly with `--tags`:

| Tag | Loads |
| --- | --- |
| `frontend` | frontend-standards.md |
| `backend` | backend-standards.md |
| `debug` | debugging.md |
| `test` | testing.md |
| `i18n` | i18n.md, manage-translations.md |
| `figma` | figma-to-code.md |
| `embed` | embed-types.md |
| `api` | add-api.md |
| `planning` | planning.md |
| `feature` | planning.md, feature-workflow.md |
| `logging` | logging-and-docs.md |
| `concurrent` | concurrent-sessions.md |
| `security` | backend-standards.md |

Git/deployment docs (`git-and-deployment.md`) are **deferred to deploy phase** — load them with `python3 scripts/sessions.py deploy-docs` before committing.

### On-Demand Doc Loading

To load any doc mid-session (instruction or architecture):

```bash
python3 scripts/sessions.py context --doc <name>
# Examples:
python3 scripts/sessions.py context --doc sync           # → docs/architecture/sync.md
python3 scripts/sessions.py context --doc debugging       # → docs/claude/debugging.md
python3 scripts/sessions.py context --doc embed-types     # → docs/claude/embed-types.md
```

### Session Summary (for handoff)

To see a compact summary of a session (useful when picking up another session's work):

```bash
python3 scripts/sessions.py summary --session <ID>
```

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

### DRY Principle — Mandatory Deduplication Check (CRITICAL)

Before writing any new function, class, Pydantic model, or Svelte component:

1. **Search for existing implementations first** — grep/glob for similar logic in the shared locations below. If it exists, use it.
2. **If similar code exists in 2+ places, extract it** before adding a third copy:
   - Backend shared logic → `backend/shared/python_utils/` or `BaseSkill`/`BaseApp`
   - Backend shared models → `backend/shared/python_schemas/`
   - Backend shared API clients → `backend/shared/providers/`
   - Frontend shared logic → `frontend/packages/ui/src/utils/` or `src/services/`
   - Frontend shared components → `frontend/packages/ui/src/components/`
3. **Shared architecture decision comments** — Write once in `docs/architecture/`, reference with a one-line comment: `# See docs/architecture/<topic>.md for design rationale`. Do NOT copy multi-line decision blocks across files.
4. **Pydantic model reuse** — If multiple skills need similar Request/Response shapes, create base models in `backend/shared/python_schemas/` and extend per-skill.
5. **Unified Svelte components first** — Always use `UnifiedEmbedPreview.svelte` and `UnifiedEmbedFullscreen.svelte` as the base for embed components. Only add app-specific logic in the `details`/`content` snippets. See `docs/claude/embed-types.md`.

### Architecture Decision Documentation

When making architecture decisions:

- **In code**: 1-2 line summary + reference link:
  ```python
  # Architecture: Direct async execution for app skills (not Celery).
  # See docs/architecture/app-skills.md#execution-model
  ```
- **In `docs/architecture/`**: Full decision with context, decision, alternatives rejected (and why), consequences.
- **NEVER copy multi-line decision blocks** across files. Write once, reference everywhere.
- Add new decisions to the relevant `docs/architecture/` file in the same commit as the implementation.

### Test File Cross-References

Source files with associated tests MUST include a comment linking to test file(s):

**Python** (after module docstring):

```python
# Tests: backend/tests/test_encryption_service.py
# Tests: backend/tests/test_integration_encryption.py
```

**TypeScript/Svelte** (in file header comment):

```typescript
// Tests: src/services/__tests__/db.test.ts
// E2E:   apps/web_app/tests/chat-flow.spec.ts
```

Rules:

- Use paths relative to project root
- Separate unit tests (`Tests:`) from E2E tests (`E2E:`)
- When creating a new test, add the cross-reference to all source files it covers
- When modifying a source file, verify test references are still accurate

### File Headers

Every new `.py`, `.ts`, `.svelte` file MUST start with a header comment (5-10 lines max):

1. **Purpose** — what this file does (1-2 sentences)
2. **Architecture context** — link to relevant `docs/architecture/` doc
3. **Test references** — paths to associated test files (if any)

### Module Boundaries

- **Skills** must NOT import from other skills. Shared logic → `BaseSkill`, `base_app.py`, or `backend/shared/`.
- **Frontend stores** must NOT import from other stores' internal modules. Use barrel exports (e.g., import from `authStore.ts`, not `authSessionActions.ts`).
- **Providers** (`backend/shared/providers/`) must NOT depend on skill-specific code — they are pure API wrappers.

### Constants — No Magic Values

Never use raw strings or numbers in logic. Extract to named constants:

```python
# Wrong
if len(results) > 50:
    results = results[:50]

# Correct
MAX_RESULTS_PER_REQUEST = 50
if len(results) > MAX_RESULTS_PER_REQUEST:
    results = results[:MAX_RESULTS_PER_REQUEST]
```

Module-level constants for single-file use. Shared constants → dedicated config/constants module.

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

**After completing every task (commit, lint, push — all done), end your final response with a structured summary using the exact emoji format below.** Keep each section concise. Use "N/A" for sections that don't apply.

```
## Task Summary

🏷️ Type: <Bug Fix | Feature | Refactor | Docs | Test>

🔗 Commit: <short-sha> (or "No commit" if nothing was committed)

✨ Goal: <1–2 sentence description of what was done and why>

❌ Broken Flow (Before): *(Bug fixes only — omit for features)*
1. User does X → Y happens (expected: Z)
2. Request reaches <service/endpoint>
3. Fails at <file:line> because <root cause>

✅ Flow After:
1. User does X
2. <service/component> handles it by doing Y
3. User sees/gets Z

📝 Changes:

| File | Change | Why |
|------|--------|-----|
| `path/to/file.ts:123` | Short description | Reason |

🏛️ Architecture Decisions: *(omit if N/A)*
- <decision> → <reasoning> → alternatives rejected: <why rejected>

🧪 Testing: <what was tested, how, results>

⚠️ Risks: <what could break, untested edge cases — or "Low risk">

💸 Cost Impact: <N/A — no cost-impacting changes — OR:>
- API(s) affected: <name>
- Pricing model: <free tier / pay-per-request / flat rate>
- Request limits: <e.g., "500 requests/day free tier">
- Estimated usage: <requests per user action / job frequency>
- Cost risk: <Low / Medium / High — with reasoning>
- Mitigation: <caching, rate limiting, fallback — or "None needed">
```

Rules: use the emoji headers exactly as shown. For bug fixes, always include the "❌ Broken Flow (Before)" section. For features, omit it. The Changes table must use `file:line` references. Be honest about risks. Always explain _why_ alternatives were rejected (not just list them). For the Cost Impact section, research actual pricing — never guess from training data.

### Auto-Commit After Every Task (CRITICAL)

- **ALWAYS commit and push to `dev` after completing a feature or bug fix** — do not wait for the user to ask.
- **Use `sessions.py` for deployment** — it commits only the files you tracked and handles lint + commit + push:
  ```bash
  python3 scripts/sessions.py prepare-deploy --session <ID>   # preview + lint
  python3 scripts/sessions.py deploy --session <ID> --title "fix: description" --message "body"
  ```
  Make sure you have called `sessions.py track --session <ID> --file <path>` for every file you modified before deploying.
- If deploying manually: only add files you actually modified (never `git add .`). Run the linter (`lint_changed.sh`) first.
- For significant routing, adapter, or Vite config changes, also run `pnpm build` in `frontend/apps/web_app/` to catch bundler-level errors.
- **When a commit resolves or attempts to fix a reported issue**, include the issue ID and a short anonymous description in the commit body (no PII). See `docs/claude/git-and-deployment.md` → "Issue-Linked Commits" for format.
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

### Privacy Policy Must Be Updated When a New Provider Is Added (CRITICAL)

**Every time a new third-party service provider is integrated** (payment processor, AI provider, hosting, email, analytics, etc.), you **MUST** update the privacy policy across all four files:

1. **`shared/docs/privacy_policy.yml`** — Add the provider entry with `privacy_policy`, `provider_location`, `used_for`, and optionally `data_shared` fields.
2. **`frontend/packages/ui/src/i18n/sources/legal/privacy.yml`** — Add three keys for the new provider: `<provider>.heading`, `<provider>.description`, and `<provider>.privacy_policy_link`. Each key must include all 20 supported locales (en, de, zh, es, fr, pt, ru, ja, ko, it, tr, vi, id, pl, nl, ar, hi, th, cs, sv) plus `verified_by_human: []`. Follow the existing section numbering (e.g., if last provider is 3.14, new one is 3.15).
3. **`frontend/packages/ui/src/legal/buildLegalContent.ts`** — Add a new section block after the last provider section (before "Section 4: Security Measures"), following the pattern of existing sections.
4. **`frontend/packages/ui/src/config/links.ts`** — Add the provider's privacy policy URL to the `privacyPolicyLinks` object.

**Also update the `lastUpdated` date** in `frontend/packages/ui/src/legal/documents/privacy-policy.ts` → `metadata.lastUpdated` to today's date whenever the privacy policy content changes.

### Explicit Consent Required for Destructive/External Actions

- **NEVER create pull requests** unless the user explicitly asks for one. No exceptions.
- **NEVER merge branches** unless the user explicitly asks for it.
- **NEVER create or publish GitHub releases** unless the user explicitly asks for one — exception: when the user asks to create a PR, also preparing a draft release as part of that workflow is permitted.
- **NEVER use `git stash`** under any circumstances. Stashes are invisible to the user, easily forgotten, and accumulate silently across sessions. If you have uncommitted changes that would block a git operation, commit them to a WIP branch instead, or ask the user how to proceed.
- These actions affect production and other developers — they require clear, unambiguous user intent.

### PR to Main — Test Gate (CRITICAL)

Before creating any PR from `dev` to `main`, you **MUST** check whether all tests have passed recently:

1. Read `test-results/last-run.json` (if it exists)
2. Check the `run_id` timestamp — it must be **within the last 30 minutes**
3. Check `summary.failed` — it must be **0**
4. Check `summary.total` — must be **> 0** (a run with zero tests is not valid)

**If any condition is not met, DO NOT create the PR.** Instead, stop and ask the user:

> "The last test run was [X minutes ago / not found / had N failures]. Before creating the PR, should I:
>
> 1. Run all tests now (`./scripts/run-tests.sh --all`) and wait for results?
> 2. Proceed anyway (skipping the test gate)?
> 3. Something else?"

Wait for an explicit answer before proceeding. Never silently skip this check.

See `docs/claude/testing.md` → "Pre-PR Test Checklist" for the full procedure.

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
  - **Server (preferred):** `docker exec api python /app/backend/scripts/debug.py issue <issue_id> --delete --yes`
  - **Admin Debug API:** `DELETE /v1/admin/debug/issues/<issue_id>` with admin API key
  - **debug.py:** `docker exec api python /app/backend/scripts/debug.py issue --delete <issue_id>`

### Multiple Assistants (Concurrent Work)

- **Several assistants may work on the codebase at the same time.** File content or git state can change between your turns.
- **Re-read files before editing** if you haven't touched them recently — another assistant may have changed them.
- **Check git status** before committing; files may already be committed by another assistant. Only add and commit what you actually changed this session.
- **If the API or a service appears down**, another assistant may be in the middle of rebuilding/restarting Docker containers. Before assuming a real failure, check whether a restart is in progress and wait for it to complete. See the "Service Unavailable During Concurrent Work" section in `docs/claude/debugging.md`.

#### Session Coordination via `scripts/sessions.py` (CRITICAL)

All concurrent sessions coordinate through **`.claude/sessions.json`** (gitignored), managed by `scripts/sessions.py`. **File tracking is manual — you must call `track` after every edit.**

**On session start** (absolute first action):

```bash
python3 scripts/sessions.py start --task "brief task description"
# Tags auto-inferred from task. Override: --tags "backend,test"
# Save the 4-char session ID printed — required for all other commands.
# READ the instruction docs printed in the output — they are loaded based on tags.
```

**After every file edit or creation:**

```bash
python3 scripts/sessions.py track --session <ID> --file path/to/modified/file.py
```

**Before rebuilding Docker containers:**

```bash
python3 scripts/sessions.py lock --session <ID> --type docker
# ... rebuild ...
python3 scripts/sessions.py unlock --session <ID> --type docker
```

**Deploying (lint + commit + push):**

```bash
python3 scripts/sessions.py deploy-docs                                       # load deferred git docs
python3 scripts/sessions.py prepare-deploy --session <ID>
python3 scripts/sessions.py deploy --session <ID> --title "fix: description" --message "body"
```

**On session end** (after committing):

```bash
python3 scripts/sessions.py end --session <ID>
```

See `docs/claude/concurrent-sessions.md` for the full protocol.

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

## Instruction Docs (Loaded Automatically via Tags)

**The `sessions.py start` command automatically loads relevant instruction docs based on tags.** You do NOT need to manually determine which docs to read — the tag system handles this.

If you need a doc that wasn't loaded at session start, use:

```bash
python3 scripts/sessions.py context --doc <name>
```

### Special Cases

- **Vercel deployment failures:** Run `python3 scripts/sessions.py debug-vercel` — it auto-starts a session and prints build logs. Most common cause: failed `pnpm prepare` validation.
- **Default assumption:** All reported issues are on the **dev server**, reported by an **admin**, unless stated otherwise.
- **Git/deployment docs:** Deferred to deploy phase. Run `python3 scripts/sessions.py deploy-docs` before committing.

### Available Instruction Docs

| Document | Tags that load it | When it applies |
| --- | --- | --- |
| `frontend-standards.md` | frontend | Svelte, TypeScript, CSS, stores |
| `backend-standards.md` | backend, security | Python, FastAPI, Pydantic, Docker |
| `debugging.md` | debug | Bugs, errors, server inspection, Docker logs |
| `testing.md` | test | Creating/running tests |
| `i18n.md` | i18n | User-facing strings, translations |
| `manage-translations.md` | i18n | Translation management, coverage stats |
| `figma-to-code.md` | figma | Implementing Figma designs |
| `embed-types.md` | embed | Embed preview/fullscreen components |
| `add-api.md` | api | External API integrations |
| `planning.md` | planning, feature | Implementation planning |
| `feature-workflow.md` | feature | Full feature lifecycle (requirements to deploy) |
| `logging-and-docs.md` | logging | Logging statements, error handling |
| `concurrent-sessions.md` | concurrent | Docker rebuilds, session conflicts |
| `git-and-deployment.md` | *(deploy phase)* | Commit format, deployment, PRs |

---

## Linting (ALWAYS run before commit)

```bash
# Python changes
./scripts/lint_changed.sh --py --path backend/

# Frontend changes
./scripts/lint_changed.sh --ts --svelte --path frontend/packages/ui

# i18n / YAML changes
./scripts/lint_changed.sh --yml --path frontend/packages/ui/src/i18n

# Mixed changes
./scripts/lint_changed.sh --py --ts --svelte --path backend --path frontend/
```

**CRITICAL**: Before every git commit, run the linter on all modified files and fix all errors. Only commit when the linter shows NO errors.
