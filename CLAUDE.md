# Claude AI Assistant Instructions

This document consolidates all coding standards, guidelines, and instructions for AI assistants working on the OpenMates codebase.

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Core Principles](#core-principles)
3. [Frontend Standards (Svelte/TypeScript)](#frontend-standards-sveltetypescript)
4. [Backend Standards (Python/FastAPI)](#backend-standards-pythonfastapi)
5. [Linting and Code Quality](#linting-and-code-quality)
6. [Git Commit Best Practices](#git-commit-best-practices)
7. [Debugging Backend Issues](#debugging-backend-issues)
8. [Server Inspection Scripts](#server-inspection-scripts)
9. [Testing Policy](#testing-policy)
10. [Documentation Standards](#documentation-standards)
11. [Logging and Error Handling](#logging-and-error-handling)
12. [Internationalization (i18n)](#internationalization-i18n)
13. [Key Files by Domain](#key-files-by-domain)
14. [Docker Debug Mode](#docker-debug-mode)
15. [Frontend Development Workflow](#frontend-development-workflow)
16. [Auto-Commit and Deployment Workflow](#auto-commit-and-deployment-workflow)
17. [Branch and Server Mapping](#branch-and-server-mapping)

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

### Logging Rule

- **Only remove debugging logs after the user confirms the issue is fixed**
- Do not remove logs assuming you fixed the issue - wait for confirmation

---

## Frontend Standards (Svelte/TypeScript)

### Svelte 5 Requirements (CRITICAL)

**USE SVELTE 5 RUNES ONLY:**

- `$state()` for reactive state
- `$derived()` for computed values
- `$effect()` for side effects
- `$props()` for component props

**NEVER use `$:` reactive statements** - this is Svelte 4 syntax and must not be used.

### Component Structure

```svelte
<script lang="ts">
  // Imports first
  import { onMount } from 'svelte';

  // Props interface
  interface Props {
    title: string;
    isVisible?: boolean;
  }

  // Props with defaults using Svelte 5 runes
  let { title, isVisible = true }: Props = $props();

  // Local state using Svelte 5 runes
  let isLoading = $state(false);

  // Derived/computed values using Svelte 5 runes (NOT $:)
  let displayTitle = $derived(title.toUpperCase());
</script>

<div class="component-wrapper">
  {#if isVisible}
    <h1>{displayTitle}</h1>
  {/if}
</div>

<style>
  .component-wrapper {
    padding: 1rem;
    background-color: var(--color-grey-20);
  }
</style>
```

### TypeScript Standards

- Use strict type checking
- Define interfaces for all props and data structures
- Use type assertions sparingly
- Prefer `interface` over `type` for object shapes

### Styling Guidelines

- Use CSS custom properties defined in `frontend/packages/ui/src/styles/theme.css`
- Follow the existing design system with predefined color variables
- Reference existing CSS files: `theme.css`, `buttons.css`, `cards.css`, `chat.css`, `fields.css`
- Create custom CSS only when the existing design system doesn't suffice
- Follow mobile-first responsive design

### State Management

- Use Svelte stores for global state
- Prefer local component state when possible
- Use derived stores for computed values
- Implement proper store subscriptions and cleanup

### Error Handling

- **NEVER use fallback values to hide errors**
- Use try-catch blocks for async operations
- Always log errors with `console.error()` for debugging
- Display user-friendly error messages to users

---

## Backend Standards (Python/FastAPI)

### Python Code Style

- Follow PEP 8 style guidelines
- Use type hints for all function parameters and return values
- Use `logger.debug()` or `logger.info()` instead of `print()` statements
- Add comprehensive docstrings for all functions and classes

### FastAPI Best Practices

- Use dependency injection for database connections and services
- Implement proper request/response models with Pydantic
- Use async/await for I/O operations
- Implement proper error handling with HTTPException
- Use background tasks for non-critical operations

### Error Handling (CRITICAL)

- **NEVER use fallback values to hide errors** - all errors must be visible
- **NO silent failures** - if an operation fails, log it and raise an exception
- Always use proper exception handling with logging
- Never catch exceptions without logging them

```python
# ❌ WRONG - hides errors
try:
    data = read_file()
except:
    data = None

# ✅ CORRECT - errors are visible
try:
    data = read_file()
except Exception as e:
    logger.error(f"Failed to read file: {e}", exc_info=True)
    raise
```

### Database Patterns

- Use repository pattern for data access
- Implement proper connection pooling
- Use transactions for multi-step operations
- Follow database naming conventions (snake_case)
- Define Directus models in YAML files under `backend/core/directus/schemas/`

### Security Best Practices

- Validate all input data
- Use environment variables for sensitive configuration
- Implement proper authentication and authorization
- Sanitize user inputs
- Implement rate limiting where appropriate

---

## Linting and Code Quality

**ALWAYS run the lint script after making code changes** to verify that your changes haven't introduced any errors.

### Lint Script Usage

The `scripts/lint_changed.sh` script checks uncommitted changes for linting and type errors.

**File type options:**

- `--py` - Python files (.py)
- `--ts` - TypeScript files (.ts, .tsx)
- `--svelte` - Svelte files (.svelte)
- `--css` - CSS files (.css)
- `--html` - HTML files (.html)

**Targeting options (always use these):**

- `--path <file|dir>` - Limit checks to a specific file or directory (repeatable)
- `-- <file|dir> ...` - Treat remaining args as target paths

**Examples:**

```bash
./scripts/lint_changed.sh --py --path backend/core/api              # Only Python changes in API
./scripts/lint_changed.sh --ts --svelte --path frontend/packages/ui # Only UI frontend changes
./scripts/lint_changed.sh --py --ts --path backend --path frontend/apps/web_app # Mixed changes
```

### Best Practices

- Always limit checks to the specific files or folders you touched
- Limit checks to changed file types (don't check TypeScript if you only modified Python)
- **CRITICAL**: Before every git commit, run the linter on all modified files and fix all errors
- **CRITICAL**: Only commit when the linter shows NO errors for modified files

---

## Git Commit Best Practices

### Commit Message Format

Follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

**Format:** `<type>: <description>`

**Types:**

- `feat`: A new feature
- `fix`: A bug fix
- `docs`: Documentation only changes
- `style`: Formatting changes (no code meaning change)
- `refactor`: Code change that neither fixes a bug nor adds a feature
- `perf`: Performance improvement
- `test`: Adding or correcting tests
- `build`: Build system or dependency changes
- `ci`: CI configuration changes
- `chore`: Other changes that don't modify src or test files
- `revert`: Reverts a previous commit

**Rules:**

- **Scope**: NEVER add all files (`git add .`). Only add files modified in the current session.
- **No Co-authors**: NEVER add `--trailer` flags or `Co-authored-by` lines.
- Use imperative present tense: "change" not "changed"
- Don't capitalize the first letter of the description
- No dot (.) at the end of the title

**Example:**

```bash
feat: add user authentication flow

- Implement JWT token generation and validation
- Add login and registration endpoints
- Secure existing API routes with auth middleware
```

### Pre-commit Checklist

- [ ] Run linter: `./scripts/lint_changed.sh --path <your_changes>`
- [ ] Fix all linter and type errors
- [ ] Remove temporary `console.log` or `print` statements (unless permanent)
- [ ] Only add files changed/created in this chat (no `git add .`)

---

## Debugging Backend Issues

**ALWAYS use docker compose terminal commands to check logs** when debugging backend issues.

### Basic Log Commands

```bash
docker compose --env-file .env -f backend/core/docker-compose.yml logs <service-name>              # View logs
docker compose --env-file .env -f backend/core/docker-compose.yml logs -f <service-name>          # Follow logs
docker compose --env-file .env -f backend/core/docker-compose.yml logs --tail=100 <service-name>  # Last 100 lines
docker compose --env-file .env -f backend/core/docker-compose.yml logs -f -t <service-name>       # With timestamps
```

### Time-Based Log Filtering

```bash
# Logs from the last N minutes
docker compose --env-file .env -f backend/core/docker-compose.yml logs --since 5m api task-worker

# Logs from the last hour
docker compose --env-file .env -f backend/core/docker-compose.yml logs --since 1h api
```

### Log Level Filtering

```bash
# Only errors and warnings
docker compose --env-file .env -f backend/core/docker-compose.yml logs --tail 500 api | rg -E "ERROR|WARNING|CRITICAL"

# Errors with context
docker compose --env-file .env -f backend/core/docker-compose.yml logs --since 10m api task-worker | rg -B3 -A3 "ERROR"
```

### Where to Look First (by Problem Type)

| Problem Type            | Check First                    | Then Check                 |
| ----------------------- | ------------------------------ | -------------------------- |
| AI response issues      | `task-worker`, `app-ai-worker` | `api` (WebSocket logs)     |
| Login/auth failures     | `api`                          | `cms` (Directus logs)      |
| Payment issues          | `api`                          | `task-worker` (async jobs) |
| Sync/cache issues       | `api` (PHASE1, SYNC_CACHE)     | `cache` (Dragonfly)        |
| WebSocket disconnects   | `api`                          | Browser console            |
| Scheduled task failures | `task-scheduler`               | `task-worker`              |
| User data issues        | `cms`, `cms-database`          | `api`                      |

### Quick Debug Commands

```bash
# Check if AI response updated sync cache
docker compose --env-file .env -f backend/core/docker-compose.yml logs task-worker --since 5m | rg "SYNC_CACHE_UPDATE.*AI response"

# Monitor Phase 1 sync in real-time
docker compose --env-file .env -f backend/core/docker-compose.yml logs -f api | rg "PHASE1"

# Trace full request lifecycle for a specific chat
docker compose --env-file .env -f backend/core/docker-compose.yml logs api task-worker --since 10m | rg -E "chat_id=<ID>|SYNC_CACHE|PHASE1" | head -100
```

### Rebuilding and Restarting Services

If a container might have outdated code after a simple restart, or if you need to ensure a clean state (including clearing the cache volume), use this full rebuild and restart command:

```bash
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml down && \
docker volume rm openmates-cache-data && \
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml build api cms cms-database cms-setup task-worker task-scheduler app-ai app-code app-web app-videos app-news app-maps app-ai-worker app-web-worker cache vault vault-setup prometheus cadvisor loki promtail grafana && \
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml up -d
```

### Available Docker Containers

**Core services:** `api`, `cms`, `cms-database`, `cms-setup`, `task-worker`, `task-scheduler`

**App services:** `app-ai`, `app-web`, `app-videos`, `app-news`, `app-maps`, `app-code`, `app-ai-worker`, `app-web-worker`

**Infrastructure:** `cache`, `vault`, `vault-setup`, `prometheus`, `cadvisor`, `loki`, `promtail`, `grafana`

---

## Server Inspection Scripts

Use these scripts to inspect server state directly. Run from the repo root.

### Chat, Embed and User Inspection

```bash
# Inspect a specific chat (cache, storage, Directus)
docker exec api python /app/backend/scripts/inspect_chat.py <chat_id>

# Inspect a specific demo chat
docker exec -i api python /app/backend/scripts/inspect_demo_chat.py demo-1

# Inspect a specific embed
docker exec api python /app/backend/scripts/inspect_embed.py <embed_id>

# Inspect a specific issue report (decrypts all fields, fetches S3 YAML report)
docker exec api python /app/backend/scripts/inspect_issue.py <issue_id>

# List recent unprocessed issues
docker exec api python /app/backend/scripts/inspect_issue.py --list

# List issues with search and include processed
docker exec api python /app/backend/scripts/inspect_issue.py --list --search "login" --include-processed

# Inspect issue without fetching S3 logs (faster)
docker exec api python /app/backend/scripts/inspect_issue.py <issue_id> --no-logs

# Inspect a specific user by email
docker exec api python /app/backend/scripts/inspect_user.py <email_address>
```

### AI Request Debugging

```bash
# Save all recent AI requests to YAML file
docker exec -it api python /app/backend/scripts/inspect_last_requests.py

# Filter by specific chat ID
docker exec -it api python /app/backend/scripts/inspect_last_requests.py --chat-id <chat_id>

# Copy output file to host machine
docker cp api:/app/backend/scripts/debug_output/last_requests_<timestamp>.yml ./debug_output.yml
```

### User Debugging

```bash
# Show user statistics
docker exec -it api python /app/backend/scripts/show_user_stats.py

# Show all chats for a specific user
docker exec -it api python /app/backend/scripts/show_user_chats.py <user_id>

# Show most recent user
docker exec -it api python /app/backend/scripts/show_last_user.py
```

### Cache Inspection (Dragonfly)

```bash
# Connect to Dragonfly cache CLI
docker exec -it cache redis-cli

# Common commands (inside redis-cli):
KEYS *sync:*    # List sync cache keys
KEYS *debug:*   # List debug entries
GET <key>       # Get value for a key
TTL <key>       # Check time-to-live
DBSIZE          # Total number of keys
```

### Celery Task Queue Inspection

```bash
docker exec -it task-worker celery -A backend.core.api.worker inspect active      # Active tasks
docker exec -it task-worker celery -A backend.core.api.worker inspect reserved    # Queued tasks
docker exec -it task-worker celery -A backend.core.api.worker inspect registered  # Registered types
docker exec -it task-worker celery -A backend.core.api.worker inspect scheduled   # Scheduled tasks
```

---

## Admin Debug API (Remote Debugging)

Remote debugging endpoints when SSH access is unavailable. Requires admin API key.

**IMPORTANT:** On the **dev server** (where we have SSH/docker access), always prefer the [Server Inspection Scripts](#server-inspection-scripts) over these API endpoints. For example, use `docker exec api python /app/backend/scripts/inspect_issue.py <id>` instead of `curl .../admin/debug/issues/<id>`. The scripts provide richer output, decrypt all fields, and fetch S3 reports directly. Reserve the Admin Debug API for **production debugging** or when you don't have shell access.

**Base URLs:** `https://api.openmates.org` (prod) or `https://api.dev.openmates.org` (dev)

### Query Logs

```bash
# Get logs from specific services
curl -H "Authorization: Bearer <admin-api-key>" \
  "https://api.openmates.org/v1/admin/debug/logs?services=api,task-worker&lines=50&since_minutes=30"

# Search for errors
curl -H "Authorization: Bearer <admin-api-key>" \
  "https://api.openmates.org/v1/admin/debug/logs?search=ERROR&since_minutes=60"
```

**Allowed services:** `api`, `cms`, `cms-database`, `task-worker`, `task-scheduler`, `app-ai`, `app-web`, `app-videos`, `app-news`, `app-maps`, `app-code`, `app-images`, `app-ai-worker`, `app-web-worker`, `app-images-worker`, `cache`

### Inspect Data

```bash
# Inspect a chat
curl -H "Authorization: Bearer <admin-api-key>" \
  "https://api.openmates.org/v1/admin/debug/inspect/chat/<chat_id>"

# Inspect a user by email
curl -H "Authorization: Bearer <admin-api-key>" \
  "https://api.openmates.org/v1/admin/debug/inspect/user/<email>"

# Inspect an embed
curl -H "Authorization: Bearer <admin-api-key>" \
  "https://api.openmates.org/v1/admin/debug/inspect/embed/<embed_id>"

# Inspect last AI requests (filter by chat_id optional)
curl -H "Authorization: Bearer <admin-api-key>" \
  "https://api.openmates.org/v1/admin/debug/inspect/last-requests?chat_id=<chat_id>"
```

### Issue Reports

```bash
# List issues
curl -H "Authorization: Bearer <admin-api-key>" \
  "https://api.openmates.org/v1/admin/debug/issues?search=login&include_processed=true"

# Get issue with logs
curl -H "Authorization: Bearer <admin-api-key>" \
  "https://api.openmates.org/v1/admin/debug/issues/<issue_id>?include_logs=true"

# Delete issue
curl -X DELETE -H "Authorization: Bearer <admin-api-key>" \
  "https://api.openmates.org/v1/admin/debug/issues/<issue_id>"
```

---

## Testing Policy

### Test Creation Consent Requirements

**NEVER create test files without the user's explicit consent.** This applies to:

- Unit tests (pytest, vitest)
- Integration tests
- End-to-end tests (Playwright)
- Test fixtures or mocks

**What to do instead:**

1. When you identify a situation where tests might be valuable, make a **brief natural-language suggestion** describing what the tests could cover
2. Do NOT include code examples in test suggestions
3. Wait for the user to explicitly ask you to create the tests before writing any test code
4. If the user says "yes" or "go ahead", only then create the test files

**Exception - When user explicitly requests TDD:**
If the user says "use TDD" or explicitly asks to write tests first, follow the full TDD cycle:

1. 🔴 **Red**: Write a failing test that describes the desired behavior
2. 🟢 **Green**: Write the minimal code to make the test pass
3. 🔵 **Refactor**: Improve the code while keeping tests green

### What Makes Tests Actually Useful

When creating tests (with consent), ensure they meet these criteria:

#### Good Tests Should:

- **Test behavior, not implementation**: Verify _what_ happens, not _how_
- **Be independent**: Each test runs in isolation, no shared state
- **Cover edge cases**: Empty inputs, null values, boundary conditions, error paths
- **Use descriptive names**: `test_encrypt_message_with_empty_content_returns_empty_encrypted_blob`
- **Follow AAA pattern**: Arrange → Act → Assert (clearly separated)
- **Be fast**: Unit tests should run quickly (< 100ms each)
- **Use meaningful assertions**: Verify the specific behavior you care about

#### Tests to AVOID (Low Value):

- Testing private implementation details that may change
- Tests that duplicate framework/library tests
- Mocking so heavily that nothing real is tested
- Tests that pass with any implementation (too loose assertions)
- Trivial getter/setter tests with no logic

#### End-to-End Tests Should:

- **Test user journeys**, not individual components
- **Use stable selectors**: `data-testid` attributes, not CSS classes
- **Be deterministic**: No flaky timing-dependent assertions
- **Cover critical paths**: Signup, login, payment, core features

### Test Location Standards

| Test Type               | Location                                               | Naming               |
| ----------------------- | ------------------------------------------------------ | -------------------- |
| Python unit tests       | `backend/apps/<app>/tests/` or `backend/core/*/tests/` | `test_*.py`          |
| TypeScript unit tests   | `frontend/packages/ui/src/**/__tests__/`               | `*.test.ts`          |
| Playwright E2E tests    | `frontend/apps/web_app/tests/`                         | `*.spec.ts`          |
| REST API external tests | `backend/tests/`                                       | `test_rest_api_*.py` |

### Running Tests After Changes

| Change Type            | Run These Tests                                     |
| ---------------------- | --------------------------------------------------- |
| Backend API endpoint   | `pytest -s backend/tests/test_rest_api_external.py` |
| Backend business logic | `pytest backend/apps/<app>/tests/`                  |
| Frontend component     | `npm run test:unit -- <component>.test.ts`          |
| Full user flow         | Playwright E2E for that flow                        |

### Test Commands

**Backend:**

```bash
# Run all external REST API tests
/OpenMates/.venv/bin/python3 -m pytest -s backend/tests/test_rest_api_external.py

# Run specific skill tests
/OpenMates/.venv/bin/python3 -m pytest -s backend/tests/test_rest_api_external.py -k ask
```

**Frontend:**

```bash
# Run frontend unit tests
cd frontend/apps/web_app && npm run test:unit

# Run with coverage
npm run test:unit -- --coverage
```

**End-to-End (Playwright):**

```bash
docker compose -f docker-compose.playwright.yml run --rm \
  -e SIGNUP_TEST_EMAIL_DOMAINS \
  -e MAILOSAUR_API_KEY \
  -e PLAYWRIGHT_TEST_BASE_URL \
  -e PLAYWRIGHT_TEST_FILE="signup-flow.spec.ts" \
  playwright
```

### Pre-Commit Test Checklist (When Tests Exist)

- [ ] Tests actually fail when the code is broken (not just passing trivially)
- [ ] Tests cover the happy path AND at least one error path
- [ ] Tests don't depend on external services (mock them)
- [ ] Test names describe the scenario being tested
- [ ] No `time.sleep()` or arbitrary waits (use proper async/await)

---

## Documentation Standards

### Document Structure

Every documentation file MUST include:

1. **Title** (H1) - Clear, descriptive title
2. **Status Badge** - Implementation status
3. **Last Updated** - Date of last significant update
4. **Overview** - Brief description of what the document covers

```markdown
# Feature Name

> **Status**: ✅ Implemented | ❌ Not Yet Implemented  
> **Last Updated**: 2024-10-01

Brief overview of what this document describes.
```

### Code-Documentation Synchronization

#### When Modifying Code

When modifying functions, classes, or modules that are referenced in architecture docs:

1. **Search for references**: `rg "filename.ts" docs/architecture/`
2. **Update any stale references**: If you renamed, moved, or deleted the referenced code
3. **Update doc descriptions**: If the behavior changed significantly

#### Documentation Reference Format

Use relative paths with function/class anchors (NOT line numbers, NO copy & pasted code blocks):

- ✅ `[cryptoService.ts#decryptChatData()](../../frontend/packages/ui/src/services/cryptoService.ts)`
- ❌ `cryptoService.ts:200-250` (line numbers become stale)

#### Critical Architecture Docs to Keep in Sync

- `docs/architecture/sync.md` → Sync and encryption flows
- `docs/architecture/message_processing.md` → AI message handling
- `docs/architecture/payment_processing.md` → Billing flows

### DRY Principle for Documentation

**Link Instead of Repeating:**

```markdown
<!-- ❌ BAD: Repeating details -->

## How Messages Are Processed

The message processing system uses a multi-phase approach...

<!-- ✅ GOOD: Link to canonical source -->

## Message Processing

For details, see [Message Processing Architecture](../architecture/message_processing.md)
```

### Navigation

Every document MUST end with "Read Next" links to related documentation.

---

## Logging and Error Handling

### Backend (Python)

- **Use `logging`**: Always use `logger.debug()` or `logger.info()` instead of `print()`
- **Initialization**: Use `logger = logging.getLogger(__name__)` at the module level
- **No Silent Failures**: Never use silent fallbacks. Log errors or raise exceptions.

### Frontend (Svelte/TypeScript)

- **Use `console.log()`**: Preferred for debugging
- **Error visibility**: Ensure errors are visible in the console

### Correlation IDs

**Always include in logs:**

```python
logger.info(f"[Task ID: {task_id}] Processing message {message_id} for chat {chat_id}")
logger.error(f"Error in task {task_id}: {e}", exc_info=True)
```

### Structured Logging Prefixes

- `[PERF]` - Timing
- `[TASK]` - Celery tasks
- `[SYNC]` - Sync operations
- `[CACHE]` - Cache operations
- `[ERROR]` - Errors

### Guidelines

- **Keep Logs**: Only remove debugging logs after the user confirms the issue is fixed
- **Comments**: Add extensive comments explaining complex logic and architectural choices
- **Cache First**: Update server cache BEFORE Directus/disk to ensure data consistency

---

## Internationalization (i18n)

### Guidelines

- **NEVER use hardcoded text** for user-facing strings in frontend or backend
- **ALWAYS use the translation system** for all user-facing content
- **Source of Truth**: `.yml` files in `frontend/packages/ui/src/i18n/sources/`

### Adding Translations (CRITICAL - READ CAREFULLY)

**FLAT KEYS ONLY - NEVER USE NESTED YAML STRUCTURES**

Translation files use **dot notation IN THE KEY NAME** as a flat structure. Each translation entry is a top-level key.

```yaml
# ✅ CORRECT - flat keys with dots in the key name
button.submit:
  context: Submit button text
  en: Submit
  de: Absenden

button.cancel:
  context: Cancel button text
  en: Cancel
  de: Abbrechen

dialog.title:
  context: Dialog title
  en: Confirm Action
  de: Aktion bestätigen
```

```yaml
# ❌ WRONG - nested YAML structure (NEVER DO THIS)
button:
  submit:
    context: Submit button text
    en: Submit
    de: Absenden
  cancel:
    context: Cancel button text
    en: Cancel
    de: Abbrechen

dialog:
  title:
    context: Dialog title
    en: Confirm Action
    de: Aktion bestätigen
```

**Why this matters:** Nested structures break the translation build system. The key `button.submit` is looked up as a literal string, not as `button` → `submit`.

### Translation Entry Structure

Every translation entry MUST have this exact structure:

```yaml
key_name:
  context: Description of how/where the text is used
  en: English text
  de: German translation
  # ... other languages
  verified_by_human: []
```

### Adding New Translations - Step by Step

1. Open the appropriate `.yml` file in `frontend/packages/ui/src/i18n/sources/`
2. Add your new key as a **top-level entry** (not nested under another key)
3. Include `context`, `en`, and ideally `de` at minimum
4. Run `npm run build:translations` in `frontend/packages/ui`

### Usage

- **Frontend**: Use the `$text` store: `$text('filename.key_name.text')` (e.g., `$text('chats.context_menu.download.text')`)
- **Backend**: Use `TranslationService` to resolve translations
- **Metadata**: Use `name_translation_key` instead of hardcoded strings

---

## Key Files by Domain

### Authentication & Security

- Login flow: `backend/core/api/app/routes/auth_routes/auth_login.py`
- Crypto service: `frontend/packages/ui/src/services/cryptoService.ts`
- Key storage: `frontend/packages/ui/src/services/cryptoKeyStorage.ts`

### Chat & Sync

- Sync architecture: `docs/architecture/sync.md`
- Phased sync service: `frontend/packages/ui/src/services/PhasedSyncService.ts`
- Cache warming: `backend/core/api/app/tasks/user_cache_tasks.py`
- WebSocket handlers: `backend/core/api/app/routes/websockets.py`

### AI Processing

- Message processing: `backend/core/api/app/services/message_processor.py`
- AI handlers: `backend/apps/ai/handlers/`
- AI app config: `backend/apps/ai/config.yml`

### Payments & Usage

- Payment processing: `backend/core/api/app/services/payment_service.py`
- Usage tracking: `backend/core/api/app/services/usage_service.py`

### Frontend Components

- Chat components: `frontend/packages/ui/src/components/chats/`
- Message components: `frontend/packages/ui/src/components/messages/`
- App store: `frontend/packages/ui/src/components/apps/`

---

## Docker Debug Mode

### Overview

When debugging in Docker Compose environments, debug logging instrumentation must account for containerized execution paths and volume mounts.

### Volume Mount Configuration

Add this mount to services that may execute code with debug instrumentation:

```yaml
volumes:
  - ../../.cursor:/app/.cursor
```

### Log Path in Containers

- **Container path**: `/app/.cursor/debug.log`
- **Host path**: `{workspace_root}/.cursor/debug.log`

### Non-Blocking Debug Logging

All debug logging instrumentation MUST be wrapped in try-except blocks:

```python
# #region agent log
try:
    import json
    import os
    log_path = '/app/.cursor/debug.log'
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, 'a') as f:
        f.write(json.dumps({...})+'\n')
except Exception:
    pass  # Non-blocking: debug logging failure should not break functionality
# #endregion
```

### Verification

After adding volume mounts:

1. Restart affected services: `docker-compose restart <service-name>`
2. Verify the mount: `docker exec <container-name> ls -la /app/.cursor`
3. Test debug logging by triggering the instrumented code path

---

## Frontend Development Workflow

### No Local Dev Server (CRITICAL)

**DO NOT run `pnpm dev` or `npm run dev`** - there is no local development server running on the server.

**Default deployment workflow:**

1. Make frontend code changes
2. Run linter to verify changes: `./scripts/lint_changed.sh --ts --svelte --path frontend/`
3. Commit and push changes to git
4. The web app is **automatically built and deployed** when changes are pushed

**Only start a dev server if:**

- The user **explicitly and specifically** requests running a local dev server
- The user says something like "start the dev server" or "run pnpm dev"

**Never assume** a dev server is needed - the CI/CD pipeline handles building and deploying frontend changes automatically.

---

## Auto-Commit and Deployment Workflow

**After completing any task**, automatically commit and push to `dev`:

1. Run linter and fix errors
2. `git add <modified_files>` (never `git add .`)
3. `git commit -m "<type>: <description>"`
4. `git push origin dev`

**If backend files were modified** (`.py`, `Dockerfile`, `docker-compose.yml`, config `.yml`), rebuild affected services:

```bash
# Rebuild specific services
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml build <services> && \
docker compose --env-file .env -f backend/core/docker-compose.yml -f backend/core/docker-compose.override.yml up -d <services>
```

| Files Modified                | Services to Rebuild                         |
| ----------------------------- | ------------------------------------------- |
| `backend/core/api/`           | `api`                                       |
| `backend/core/api/app/tasks/` | `api`, `task-worker`, `task-scheduler`      |
| `backend/apps/<app>/`         | `app-<app>`, `app-<app>-worker` (if exists) |
| `backend/shared/`             | All services using shared code              |
| Directus schema files         | `cms`, `cms-setup`                          |

---

## Branch and Server Mapping

### Branch → Server Mapping

| Branch | Server      | URL                                                           |
| ------ | ----------- | ------------------------------------------------------------- |
| `dev`  | Development | `https://dev.openmates.org` / `https://api.dev.openmates.org` |
| `main` | Production  | `https://openmates.org` / `https://api.openmates.org`         |

- The **development server** runs the `dev` branch — this is where we work and push changes.
- The **production server** runs the `main` branch — this is the live server that users interact with.

### Debugging Production Issues

When debugging issues that occur on the **production server**, the code running there may differ from the `dev` branch. To inspect the production code without switching branches, use `git show`:

```bash
# View a specific file as it exists on the main (production) branch
git show main:backend/core/api/app/routes/settings.py

# View a specific file at a specific line range (pipe through head/tail)
git show main:backend/core/api/app/routes/settings.py | head -200

# Compare a file between dev and main
git diff main..dev -- backend/core/api/app/routes/settings.py

# Check what's different between dev and main overall
git diff main..dev --stat

# View the last few commits on main
git log main --oneline -10
```

**Key rules:**

- Always use `git show main:<path>` to check production code — **do NOT switch branches** on the dev server
- Use the [Admin Debug API](#admin-debug-api-remote-debugging) with the **production base URL** (`https://api.openmates.org`) to inspect production data and logs
- When a user reports a production issue, first check if the relevant code differs between `dev` and `main`

---

## Package and Dependency Management

- **Verify Versions**: ALWAYS check for the latest stable version of a package before installing
- **No Hallucinations**: NEVER assume or hallucinate version numbers. Verify using terminal tools or web search.
