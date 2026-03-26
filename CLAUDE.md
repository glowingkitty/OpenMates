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

<!-- GSD:project-start source:PROJECT.md -->
## Project

**Encryption & Sync Architecture Rebuild**

A comprehensive audit and rebuild of OpenMates' client-side encryption, key management, and real-time chat sync architecture. The current system suffers from recurring "content decryption failed" errors caused by inconsistent key management, race conditions in cross-device sync, and a codebase that grew through incremental patches without a coherent design. This project replaces the messy, fragile encryption/sync code with a clean, well-structured, fully documented architecture — while preserving backwards compatibility with all existing encrypted chats.

**Core Value:** Every encrypted chat must decrypt successfully on every device, every time — no exceptions, no race conditions, no key mismatches.

### Constraints

- **Backwards compatibility**: All existing encrypted chats must remain decryptable after the rebuild
- **Same crypto primitives**: Use the same encryption algorithms currently in use — this is an architecture/code-quality project, not a cryptography upgrade
- **Brownfield**: This is a running production system (dev server) with real data — changes must be incremental and verifiable
- **Frontend-first**: The encryption bugs originate in frontend code; backend changes should be minimal and only where the interface requires it
<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->
## Technology Stack

## Languages
- TypeScript ~5.9.2 - Frontend (SvelteKit app + shared UI package)
- Python 3.13 - Backend (all FastAPI services, Celery workers, scripts)
- JavaScript (ES Module) - Build scripts, metadata generators in `frontend/packages/ui/scripts/`
- CSS Custom Properties - Frontend styling (no Tailwind, no CSS-in-JS)
- YAML - Config files (`shared/config/`, `backend/apps/*/app.yml`, i18n sources)
## Runtime
- Node.js >=18 (frontend builds and dev server)
- Python 3.13 (Docker image: `python:3.13-slim` — all backend containers)
- pnpm 10.23.0 (frontend monorepo)
- Lockfile: `pnpm-lock.yaml` (present, committed)
- pip (backend, via `requirements.txt` files per service)
## Frameworks
- Svelte 5.54+ with Runes (`compilerOptions.runes: true`) — reactive UI
- SvelteKit 2.55+ — routing, SSR/prerendering, adapter-vercel deployment
- Vite 7.3+ — build tool (`frontend/apps/web_app/vite.config.ts`)
- Turbo 2.7+ — monorepo task runner (`turbo.json`)
- FastAPI 0.128 — REST API (`backend/core/api/`)
- Uvicorn 0.40 (standard) — ASGI server
- Pydantic v2 2.11 — data validation and schemas
- Celery 5.5 — async task queue (`backend/core/api/app/tasks/`)
- Vitest 3.2+ — frontend unit tests (`frontend/packages/ui/src/services/__tests__/`)
- Playwright 1.49 — E2E tests (`frontend/apps/web_app/tests/`)
- pytest (asyncio_mode=auto) — backend unit + integration tests (`backend/tests/`)
- `@vite-pwa/sveltekit` 1.0 — PWA manifest + Workbox service worker
- `prettier` 3.7 + `prettier-plugin-svelte` 3.4 — formatting
- `ruff` 0.14.11 — Python linting
- `yamllint` 1.37.1 — YAML linting
## Key Dependencies
- `@tiptap/core` 3.4 + extensions — rich text message editor (ProseMirror-based)
- `svelte-i18n` 4.0 — i18n runtime (21 locales, YAML sources auto-compiled to JSON)
- `tweetnacl` 1.0 — client-side NaCl crypto (end-to-end encryption)
- `@stripe/stripe-js` 7.9 — Stripe checkout SDK
- `@polar-sh/checkout` 0.2 — Polar.sh checkout SDK
- `@revolut/checkout` 1.1 — Revolut checkout SDK
- `leaflet` 1.9 + `@types/leaflet` — maps rendering
- `katex` 0.16 — math formula rendering
- `jspdf` 4.2 + `jszip` 3.10 — PDF/ZIP export
- `dompurify` 3.3 — HTML sanitization
- `@lucide/svelte` 0.545 — icon library
- `date-fns` 4.1 — date utilities
- `lodash-es` 4.17 — utility functions
- `function-plot` 1.25 — mathematical function plotting
- `httpx` 0.28 — async HTTP client (used everywhere instead of requests)
- `redis` 5.2 — Dragonfly/Redis client
- `boto3` 1.37 — AWS S3 storage
- `celery` 5.5 — async task queue with beat scheduler
- `argon2-cffi` 23.1 — password hashing
- `cryptography` 46.0 — AES-256-GCM encryption
- `pynacl` 1.6 — NaCl crypto (server-side)
- `webauthn` 2.7 — WebAuthn/Passkey authentication
- `pyotp` 2.9 — TOTP-based 2FA
- `pywebpush` 2.3 — Web Push (VAPID) notifications
- `openai` 2.15 — OpenAI API client
- `anthropic` 0.57 — Anthropic Claude API client
- `google-genai` 1.58 — Google Gemini API client
- `groq` 0.34 — Groq API client
- `stripe` 12.2 — Stripe server-side SDK
- `polar-sdk` 0.29 — Polar.sh server-side SDK
- `c2pa-python` 0.28 — Content authenticity (C2PA) for image watermarking
- `toon-format` (git) — custom binary encoding for AI response embeds
- `pymupdf` 1.27 — PDF page screenshot rendering
- `sympy` 1.14 + `mpmath` 1.3 — symbolic/numeric math
- `Pillow` 12.1 + `cairosvg` 2.9 — image processing
- `reportlab` 4.3 — PDF generation
- `mjml-python` 1.3 + `jinja2` 3.1 — transactional email templating
- `tiktoken` 0.9 — token counting for LLM requests
- `timezonefinder` 8.2 + `pytz` 2025.2 — timezone resolution
- `staticmap` 0.5 — static map image generation
- `maxminddb` 3.1 — MaxMind GeoIP database (local lookup)
- `airports-py` 3.0 — offline airport IATA database (~28k airports)
- `user-agents` 2.2 — user-agent string parsing
- `youtube-transcript-api` 1.2 — YouTube transcript fetching (via Webshare proxy)
- `google-api-python-client` 2.187 — YouTube Data API v3
## Configuration
- All secrets injected via `.env` file at project root (read by Docker Compose `env_file`)
- Runtime secrets fetched from HashiCorp Vault at `http://vault:8200` via `SecretsManager` class (`backend/core/api/app/utils/secrets_manager.py`)
- Shared YAML configs at `shared/config/` (mounted to `/shared` in all containers)
- `turbo.json` — monorepo build pipeline (frontend)
- `frontend/apps/web_app/vite.config.ts` — Vite config with PWA, chunk splitting
- `frontend/apps/web_app/svelte.config.js` — adapter-vercel, Runes mode
- `backend/core/docker-compose.yml` — all production services definition
- `backend/core/docker-compose.override.yml` — local dev overrides
- `backend/pytest.ini` — pytest configuration
## Platform Requirements
- Docker + Docker Compose (all backend services run in containers)
- Node.js >=18 + pnpm 10.23 (frontend)
- cloudflared binary at `/home/superdev/.local/bin/cloudflared` (ephemeral tunnel for E2E tests)
- Backend: Docker on a Linux VPS, reverse-proxied by Caddy (`deployment/Caddyfile.example`)
- Frontend: Vercel (adapter-vercel, `@sveltejs/adapter-vercel` 6.3)
- PWA: Workbox service worker, standalone display mode
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

## Naming Patterns
- Python: `snake_case.py` (e.g., `rate_limiting.py`, `chat_compressor.py`, `skill_executor.py`)
- TypeScript services: `camelCase.ts` (e.g., `chatListCache.ts`, `embedStore.ts`)
- Svelte components: `PascalCase.svelte` (e.g., `ChatMessage.svelte`, `ReminderSetterPanel.svelte`)
- TypeScript types: `camelCase.ts` placed in `types/` directory (e.g., `chat.ts`, `apps.ts`)
- Test files (Python): `test_<module>.py` (e.g., `test_rate_limiting.py`, `test_encryption_service.py`)
- Test files (TypeScript unit): `<module>.test.ts` co-located in `__tests__/` subdirectory
- E2E specs: `<feature>-flow.spec.ts` or `skill-<app>-<skill>.spec.ts` (e.g., `signup-flow.spec.ts`, `skill-web-read.spec.ts`)
- Preview files: `ComponentName.preview.ts` co-located with every shared component in `frontend/packages/ui/src/components/`
- Python: `snake_case` for all functions and methods (e.g., `get_provider_rate_limit`, `check_rate_limit`)
- TypeScript: `camelCase` for all functions (e.g., `setCache`, `upsertChat`, `loginToTestAccount`)
- Python async functions use `async def` with `await` (no special naming suffix)
- Python: `snake_case` for all variables (e.g., `plan_env_var`, `rate_limits_config`)
- TypeScript: `camelCase` for variables; `UPPER_SNAKE_CASE` for module-level constants
- Python: `UPPER_SNAKE_CASE` for module-level constants (e.g., `MAX_RESULTS_PER_REQUEST`, `DEFAULT_APP_INTERNAL_PORT`)
- Python classes: `PascalCase` (e.g., `EncryptionService`, `TestEncryptionService`, `RateLimitScheduledException`)
- TypeScript interfaces: `PascalCase` with `interface` keyword preferred over `type` for object shapes (e.g., `PreprocessorStepResult`, `Props`)
- TypeScript type aliases: `PascalCase` (e.g., `MessageStatus`, `TiptapJSON`, `ProcessingPhase`)
- Pydantic models: `PascalCase` ending with `Request` or `Response` for auto-discovery (e.g., `SkillRequest`, `OpenAICompletionResponse`)
## File Headers
#
## Code Style
- PEP 8 style (no formatter config found — assumed enforced via CI)
- 4-space indentation
- Type hints on all function parameters and return values
- `Optional[T]` from `typing` for optional parameters (not `T | None` form)
- Imports from `typing`: `Dict`, `Any`, `Optional`, `Tuple`, `List` (not the lowercase generics form)
- Config: `frontend/apps/web_app/.prettierrc`
- Tabs (not spaces) for indentation
- Single quotes (`singleQuote: true`)
- No trailing commas (`trailingComma: "none"`)
- 100-character print width
- Svelte files use `prettier-plugin-svelte`
- ESLint config at `frontend/apps/web_app/eslint.config.js` and `frontend/packages/ui/eslint.config.js`
- Extends `@repo/eslint-config` shared config
- `@typescript-eslint/no-explicit-any` and `@typescript-eslint/no-require-imports` are commonly suppressed in Playwright spec files (acceptable — Playwright Docker image provides the module at runtime only)
## Svelte 5 Component Structure
## Import Organization
- Frontend packages use relative paths within `frontend/packages/ui/src/`
- App-level code imports from `@repo/` monorepo packages
## Error Handling
## Logging
- Use `logging.getLogger(__name__)` — never `print()` in production code
- Pattern: `logger = logging.getLogger(__name__)` at module level
- Use `logger.debug()`, `logger.info()`, `logger.warning()`, `logger.error()`
- `logger.error(..., exc_info=True)` for exception context
- Debug logs are only removed after the user confirms an issue is fixed
- Use `console.debug()` for cache/state internals (e.g., `[ChatListCache] Cache updated: ...`)
- Use `console.error()` for errors
- Prefix with `[ClassName]` or `[ServiceName]` for traceability
## Comments
- Explain business logic and architecture decisions, not syntax
- Link to `docs/architecture/` for complex design decisions
- Add `// Bug history this test suite guards against:` block at top of test files, referencing specific commit SHAs and the bug that was fixed
- Explain non-obvious invariants inline
- `/** ... */` JSDoc on all public class methods and exported functions
- Include `@param` and explanation of edge cases
- Used consistently in services and cache classes
- Required on all functions and classes
- Include `Args:` and `Returns:` sections for non-trivial functions
- Reference architecture docs inline (e.g., `# Architecture: docs/architecture/app_skills.md`)
## Constants — No Magic Values
## Module Boundaries
- Skills must NOT import from other skills. Shared logic → `BaseSkill` or `backend/shared/`
- Providers (`backend/shared/providers/`) must NOT depend on skill-specific code — pure API wrappers only
- Shared Python utilities: `backend/shared/python_utils/`
- Shared Pydantic models: `backend/shared/python_schemas/`
- Stores must NOT import from other stores' internal modules — use barrel exports only
- Shared components: `frontend/packages/ui/src/components/`
- Shared services/utils: `frontend/packages/ui/src/services/` and `src/utils/`
- External images must use `proxyImage()` / `proxyFavicon()` from `imageProxy.ts`
## Pydantic Models (Backend)
## Styling (Frontend)
- All colors use CSS custom properties from `frontend/packages/ui/src/styles/theme.css`
- NEVER use raw color literals (`white`, `#fff`, `black`, `#000`) — dark mode inverts the grey scale
- NEVER use `px` for font sizes — use `rem` (respects browser zoom/accessibility settings)
- Font size variables: `var(--font-size-p)`, `var(--font-size-h1)` through `var(--font-size-h4)`
- Color variables: `var(--color-grey-0)` through `var(--color-grey-30)`, `var(--color-font-primary)`, `var(--color-error)`, etc.
- All settings visual elements use canonical components from `settings/elements/` (29 components)
## Function Design
- Python: Return `None` for "not found" cases when documented; raise exceptions for unexpected failures
- TypeScript: Return `null` for "not present" cache misses; throw for unexpected errors
- Never return empty fallbacks that silently swallow errors
## Dependency Management
- npm: `pnpm info <package-name> version`
- pip: `pip index versions <package-name>`
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

## Pattern Overview
- Frontend is a pure client-side SPA: all data lives in IndexedDB, synced to the backend through a single persistent WebSocket connection. REST is used only for auth, payments, and public endpoints.
- Backend consists of a central FastAPI gateway (`api`) and many independent app microservices (`app-ai`, `app-web`, `app-news`, etc.), each running their own Uvicorn process. The gateway proxies skill execution to app services via internal HTTP.
- Async task execution is handled by dedicated Celery workers (`app-ai-worker`, `app-images-worker`, `app-pdf-worker`, `task-worker`), with Dragonfly (Redis-compatible) as the message broker and result backend.
- End-to-end encryption: chat content is encrypted client-side before syncing. Server-side stores only encrypted ciphertext except in specific admin contexts.
- Secrets are managed by HashiCorp Vault; the API waits for Vault to be unsealed before starting.
## Layers
### Frontend — SvelteKit SPA
- **Purpose:** Renders the UI, manages local state, encrypts/decrypts chat data, maintains the WebSocket connection.
- **Location:** `frontend/apps/web_app/src/`
- **Contains:** SvelteKit routes, Svelte 5 components, Svelte stores, client services.
- **Depends on:** `@repo/ui` package for all shared components, stores, services, and i18n.
- **Used by:** End users via browser. Deployed to Vercel.
### Shared UI Package (`@repo/ui`)
- **Purpose:** Single source of truth for all reusable frontend logic — components, stores, services, utilities, i18n translations.
- **Location:** `frontend/packages/ui/src/`
- **Contains:** Svelte components, TypeScript services (`chatSyncService`, `websocketService`, `db`, `encryption`), Svelte stores, i18n YAML sources.
- **Depends on:** Nothing internal; imports only npm packages.
- **Used by:** `frontend/apps/web_app`, and any future frontend apps.
### Central API Gateway
- **Purpose:** Single backend entry point for the frontend. Handles authentication, WebSocket connections, chat sync, payments, app discovery, and internal API calls to app services.
- **Location:** `backend/core/api/`
- **Entry point:** `backend/core/api/main.py`
- **Contains:** FastAPI app, route handlers, services (DirectusService, CacheService, PaymentService, S3, etc.), Celery task definitions, middleware.
- **Depends on:** Directus CMS, Dragonfly cache, HashiCorp Vault, app microservices (via internal HTTP).
- **Used by:** SvelteKit frontend (WebSocket + REST), app microservices (internal API), Celery workers.
### App Microservices
- **Purpose:** Each domain app (AI, web search, news, maps, images, etc.) runs as an isolated FastAPI service. They expose `/skills/{skill_id}/execute` endpoints and receive execution requests from `app-ai-worker`.
- **Location:** `backend/apps/{app_name}/` (e.g., `backend/apps/ai/`, `backend/apps/web/`, `backend/apps/news/`)
- **Entry point:** `backend/apps/base_main.py` (shared), instantiates `BaseApp` from `backend/apps/base_app.py`
- **Contains:** `app.yml` (metadata), `skills/` (skill implementations), optional `providers/`, `tasks/`, `utils/`.
- **Depends on:** `backend/shared/`, `backend/core/api/` services (via internal HTTP), Dragonfly cache, Directus.
- **Used by:** `app-ai-worker` Celery tasks via internal HTTP; the API gateway for skill dispatch.
### Shared Backend (`backend/shared/`)
- **Purpose:** Code shared across the API gateway and all app microservices. No skill-specific logic here.
- **Location:** `backend/shared/`
- **Contains:**
- **Depends on:** Only Python stdlib and third-party packages.
- **Used by:** `backend/core/api/` and all `backend/apps/` microservices.
### Celery Workers
- **Purpose:** Background async task execution. The `app-ai-worker` runs the AI processing pipeline; `task-worker` handles infrastructure tasks (email, persistence, push); `app-images-worker` and `app-pdf-worker` are dedicated workers for heavy processing.
- **Location:** Tasks defined in `backend/core/api/app/tasks/` and `backend/apps/ai/tasks/`
- **Celery config:** `backend/core/api/app/tasks/celery_config.py`
- **Queue mapping:**
- **Scheduler:** `task-scheduler` container runs `celery beat` for periodic tasks.
### Directus CMS (Data Layer)
- **Purpose:** PostgreSQL-backed CMS acting as the primary application database. Accessed exclusively by the API gateway via `DirectusService`.
- **Location:** `backend/core/directus/`
- **Schemas:** Defined as YAML in `backend/core/directus/schemas/` — applied by the `cms-setup` container on startup. Key collections: `users`, `chats`, `messages`, `embeds`, `reminders`, `usage`, `api_keys`, `webhooks`, and many others.
- **Access:** `backend/core/api/app/services/directus/directus.py` — mixin-based service with method groups: `auth_methods.py`, `chat_methods.py`, `embed_methods.py`, `usage_methods.py`, etc.
## Data Flow
### Chat Message (Happy Path)
### Skill Execution Inside AI Pipeline
### Initial Page Load / Sync
### State Management
- Frontend reactive state: Svelte stores in `frontend/packages/ui/src/stores/` — one file per concern (e.g., `activeChatStore.ts`, `aiTypingStore.ts`, `websocketStatusStore.ts`).
- Local persistence: IndexedDB via `chatDB` (`frontend/packages/ui/src/services/db.ts`) and `userDB` (`frontend/packages/ui/src/services/userDB.ts`).
- Server-side cache: `CacheService` wraps Dragonfly (Redis) — split into mixins: `cache_chat_mixin.py`, `cache_user_mixin.py`, `cache_inspiration_mixin.py`, etc. (`backend/core/api/app/services/`).
## Key Abstractions
### `BaseApp` and `app.yml`
- **Purpose:** Every app microservice is an instance of `BaseApp` (`backend/apps/base_app.py`). Metadata (name, skills, focus modes, settings/memories schema, pricing) is declared in `app.yml` (parsed into `AppYAML` from `backend/shared/python_schemas/app_metadata_schemas.py`). `BaseApp` auto-registers skill routes from the YAML on startup.
- **Examples:** `backend/apps/ai/app.yml`, `backend/apps/web/`, `backend/apps/news/`, etc.
- **Pattern:** `BaseApp.__init__` loads `app.yml`, initializes `FastAPI`, registers `/health`, `/metadata`, and `/skills/{skill_id}/execute` routes dynamically.
### WebSocket Handlers
- **Purpose:** All real-time client-server interaction is handled by per-message-type handler functions registered in `websockets.py`.
- **Examples:** `backend/core/api/app/routes/handlers/websocket_handlers/` — one file per message type (`message_received_handler.py`, `initial_sync_handler.py`, `draft_update_handler.py`, etc.).
- **Pattern:** Each handler is an `async def handle_*` function taking `(websocket, payload, manager, services...)` parameters.
### `ChatSynchronizationService` (Frontend)
- **Purpose:** Central front-end service managing the full chat sync lifecycle over WebSocket.
- **Location:** `frontend/packages/ui/src/services/chatSyncService.ts`
- **Pattern:** Extends `EventTarget`. Delegates to handler modules by WebSocket message type (`chatSyncServiceHandlersAI.ts`, `chatSyncServiceHandlersCoreSync.ts`, etc.) and sender module (`chatSyncServiceSenders.ts`).
### `DirectusService` (Backend)
- **Purpose:** All reads/writes to the Directus CMS database go through this service. It is mixin-based, with methods split by domain.
- **Location:** `backend/core/api/app/services/directus/directus.py` — assembles mixins from `auth_methods.py`, `chat_methods.py`, `embed_methods.py`, `user/` subdirectory, etc.
- **Pattern:** Async methods using `httpx` to call the Directus REST API.
### Embed System
- **Purpose:** AI responses can produce "embeds" — typed rich content objects (maps, search results, images, PDF views, etc.) stored encrypted and rendered client-side.
- **Backend:** `backend/core/api/app/services/embed_service.py`
- **Frontend:** `frontend/packages/ui/src/components/embeds/UnifiedEmbedPreview.svelte`, `UnifiedEmbedFullscreen.svelte` — always use these as base. Specific embed types live in `frontend/packages/ui/src/components/embeds/` subdirectories.
- **State machine:** `frontend/packages/ui/src/services/embedStateMachine.ts`
## Entry Points
### SvelteKit App (Frontend)
- **Location:** `frontend/apps/web_app/src/routes/+page.svelte`
- **Triggers:** Browser navigation to `/`
- **Responsibilities:** Root application shell — mounts `Chats`, `ActiveChat`, `Header`, `Settings` components; initializes auth, WebSocket, deep link handling, and phased sync.
### App Initialization
- **Location:** `frontend/packages/ui/src/app.ts` (`initializeApp`)
- **Triggers:** Called from `+page.svelte` on mount.
- **Responsibilities:** Opens IndexedDB, initializes auth store, sets up debug utilities, starts permission listeners.
### FastAPI API Gateway
- **Location:** `backend/core/api/main.py`
- **Triggers:** Docker container start (Uvicorn); waits for Vault via `wait-for-vault.sh`.
- **Responsibilities:** Registers all route routers, initializes services (Directus, Cache, Payment, S3, etc.) in the lifespan context, starts Redis Pub/Sub background listeners for WebSocket relay.
### App Microservice
- **Location:** `backend/apps/base_main.py`
- **Triggers:** Docker container start for each `app-*` service.
- **Responsibilities:** Instantiates `BaseApp` for the given `APP_NAME` env var, registers routes from `app.yml`, starts Uvicorn.
### Celery AI Task
- **Location:** `backend/apps/ai/tasks/ask_skill_task.py`
- **Triggers:** Enqueued by `message_received_handler.py` when user sends a chat message.
- **Responsibilities:** Runs the complete AI pipeline (preprocess → LLM → skill tool calls → postprocess → stream response to Redis).
## Error Handling
- API routes raise `HTTPException` with explicit status codes and detail messages.
- Celery tasks catch exceptions, log them, and update task state to `FAILURE`.
- LLM failures use `AllServersFailedError` → send `STANDARDIZED_USER_ERROR_MESSAGE` to the user.
- Cache misses MUST have a database fallback (never treat a miss as fatal).
- AI skill execution has a `HARD_LIMIT_SKILL_CALLS = 5` guard against infinite tool call loops.
- `SoftTimeLimitExceeded` from Celery is handled in task code to send graceful cancellation messages.
## Cross-Cutting Concerns
<!-- GSD:architecture-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd:profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
