# Codebase Structure

**Analysis Date:** 2026-03-26

## Directory Layout

```
OpenMates/
├── frontend/
│   ├── apps/
│   │   └── web_app/                    # SvelteKit web application (Vercel)
│   │       ├── src/
│   │       │   ├── routes/             # SvelteKit file-based routes
│   │       │   │   ├── +page.svelte    # Root SPA shell (main app)
│   │       │   │   ├── +layout.svelte  # Global layout (styles, MetaTags)
│   │       │   │   ├── (minimal)/      # Minimal layout group (status page)
│   │       │   │   ├── admin/          # Admin panel routes
│   │       │   │   ├── share/          # Public chat/embed share routes
│   │       │   │   ├── docs/           # Documentation viewer
│   │       │   │   ├── dev/            # Dev-only preview pages (components, embeds, settings)
│   │       │   │   └── [...path]/      # Catch-all for short URLs
│   │       │   ├── lib/                # App-local overrides (stores, components, utils)
│   │       │   ├── hooks.server.ts     # Security headers middleware
│   │       │   └── app.html            # HTML shell
│   │       ├── tests/                  # Playwright E2E specs (94 files)
│   │       ├── playwright.config.ts
│   │       └── svelte.config.js
│   └── packages/
│       └── ui/                         # Shared UI package (@repo/ui)
│           └── src/
│               ├── app.ts              # initializeApp() — app bootstrap
│               ├── components/         # Shared Svelte components
│               │   ├── embeds/         # Embed preview/fullscreen components
│               │   ├── settings/       # Settings UI components
│               │   │   └── elements/   # 24 canonical settings primitives
│               │   ├── chats/          # Chat list components
│               │   ├── enter_message/  # Message input components
│               │   └── common/         # Generic shared components
│               ├── stores/             # Svelte stores (one per concern)
│               ├── services/           # TypeScript services
│               │   ├── db.ts           # IndexedDB facade
│               │   ├── db/             # DB operation modules
│               │   ├── encryption/     # Client-side E2E encryption
│               │   ├── chatSyncService.ts
│               │   ├── websocketService.ts
│               │   └── ...
│               ├── types/              # TypeScript type definitions
│               ├── config/             # API URLs, links, pricing, meta
│               ├── utils/              # Shared frontend utilities
│               ├── actions/            # Svelte actions (focusTrap, tooltip)
│               ├── i18n/
│               │   ├── sources/        # YAML translation source files (edit here)
│               │   └── locales/        # Auto-generated JSON (never edit)
│               └── styles/             # Global CSS files
├── backend/
│   ├── apps/                           # App microservices
│   │   ├── base_app.py                 # BaseApp class (shared entry point)
│   │   ├── base_main.py                # Generic Uvicorn runner for all apps
│   │   ├── Dockerfile.base             # Shared Dockerfile for app containers
│   │   ├── ai/                         # AI chat app (app-ai container)
│   │   │   ├── app.yml                 # App metadata & skills declaration
│   │   │   ├── skills/                 # Skill implementations (AskSkill)
│   │   │   ├── llm_providers/          # LLM client wrappers (OpenAI, Anthropic, Google, etc.)
│   │   │   ├── processing/             # Pipeline: preprocessor, main_processor, postprocessor, skill_executor
│   │   │   ├── tasks/                  # Celery tasks (ask_skill_task.py)
│   │   │   └── utils/                  # LLM utils, model selector, stream utils
│   │   ├── web/                        # Web search/read app
│   │   ├── news/                       # News search app
│   │   ├── images/                     # Image search/generation app
│   │   ├── videos/                     # Video search/transcript app
│   │   ├── maps/                       # Map/location search app
│   │   ├── events/                     # Events search app
│   │   ├── travel/                     # Travel (flights, stays) app
│   │   ├── audio/                      # Audio transcription app
│   │   ├── shopping/                   # Shopping search app
│   │   ├── health/                     # Health/medical app
│   │   ├── nutrition/                  # Nutrition lookup app
│   │   ├── math/                       # Math calculation app
│   │   ├── code/                       # Code execution/explanation app
│   │   ├── pdf/                        # PDF processing app (OCR, TOC)
│   │   ├── reminder/                   # Reminder management app
│   │   ├── mail/                       # Email skill app
│   │   ├── docs/                       # Documentation retrieval app
│   │   ├── jobs/                       # Job search app
│   │   └── openmates/                  # Platform-level skills (app settings, memories)
│   ├── core/
│   │   ├── api/                        # Central FastAPI gateway
│   │   │   ├── main.py                 # App factory, lifespan, router registration
│   │   │   ├── Dockerfile
│   │   │   ├── Dockerfile.celery       # Shared Dockerfile for Celery workers
│   │   │   └── app/
│   │   │       ├── routes/             # REST + WebSocket route handlers
│   │   │       │   ├── websockets.py   # WebSocket endpoint + Pub/Sub listeners
│   │   │       │   ├── auth.py         # Auth REST endpoints
│   │   │       │   ├── auth_routes/    # Auth sub-handlers (login, passkey, 2FA, sessions…)
│   │   │       │   ├── apps.py         # App/skill discovery endpoints
│   │   │       │   ├── apps_api.py     # External API (API-key authed skill execution)
│   │   │       │   ├── payments.py     # Payment routes
│   │   │       │   ├── admin.py        # Admin-only endpoints
│   │   │       │   ├── handlers/
│   │   │       │   │   └── websocket_handlers/  # One handler file per WS message type
│   │   │       │   └── ...
│   │   │       ├── routers/            # Additional router modules (webhooks, internal_tunnel)
│   │   │       ├── services/           # Core services
│   │   │       │   ├── cache.py        # CacheService (Dragonfly wrapper, mixin-based)
│   │   │       │   ├── directus/       # DirectusService (mixin-based Directus client)
│   │   │       │   ├── payment/        # Payment services (Stripe, Polar, Revolut)
│   │   │       │   ├── email/          # Email provider abstraction (Brevo, Mailjet)
│   │   │       │   ├── s3/             # S3 upload service
│   │   │       │   ├── invoiceninja/   # InvoiceNinja billing
│   │   │       │   └── ...
│   │   │       ├── tasks/              # Celery task definitions
│   │   │       │   ├── celery_config.py # Celery app + queue config + beat schedule
│   │   │       │   ├── persistence_tasks.py
│   │   │       │   ├── email_tasks/
│   │   │       │   └── ...
│   │   │       ├── models/             # Pydantic request/response models (user.py)
│   │   │       ├── schemas/            # Domain schemas (auth, chat, payment, settings)
│   │   │       ├── middleware/         # FastAPI middleware (LoggingMiddleware)
│   │   │       └── utils/              # Utilities (encryption, secrets_manager, config_manager…)
│   │   ├── directus/                   # Directus CMS setup
│   │   │   ├── schemas/                # YAML collection schemas (applied by cms-setup)
│   │   │   ├── setup/                  # cms-setup Docker container
│   │   │   └── extensions/             # Directus extensions
│   │   ├── monitoring/                 # Prometheus, Promtail, Alertmanager configs
│   │   ├── docker-compose.yml          # Full service mesh definition
│   │   ├── docker-compose.override.yml # Local dev overrides
│   │   └── docker-compose.no-webapp.yml # Without webapp container
│   ├── shared/
│   │   ├── python_schemas/             # Shared Pydantic models (AppYAML, embed status, etc.)
│   │   ├── python_utils/               # Pure utility functions (billing, hashing, geo, URL)
│   │   └── providers/                  # Pure API wrapper clients (Brave, SerpAPI, YouTube, etc.)
│   ├── admin_sidecar/                  # Admin sidecar process
│   └── config/
│       └── backend_config.yml          # Backend runtime configuration
├── deployment/                         # Caddy configs for dev/prod servers
│   ├── dev_server/
│   ├── prod_server/
│   └── upload_server/
├── docs/
│   ├── architecture/                   # Architecture decision docs (ai/, core/, frontend/, etc.)
│   └── contributing/                   # Coding standards and guides
├── scripts/
│   ├── sessions.py                     # Session lifecycle manager (start/deploy/end)
│   └── lint_changed.sh                 # Lint only changed files
├── shared/                             # Project-root shared assets (pricing.yml, urls.yml, etc.)
├── tests/                              # Root-level test configs
├── turbo.json                          # Turborepo task pipeline
├── pnpm-workspace.yaml                 # pnpm monorepo workspace
└── package.json                        # Root package.json
```

---

## Directory Purposes

### `frontend/apps/web_app/src/routes/`
- The SvelteKit file-based router. Almost the entire app renders at `/` (`+page.svelte`) as a SPA.
- **Route groups:** `(minimal)` for pages with a stripped layout (status page). `(seo)` for SEO landing pages.
- **Public pages:** `share/chat/[chatId]`, `share/embed/[embedId]`, `docs/[...slug]`, `s/` (short URLs).
- **Dev pages:** `dev/preview/` — component previews, settings preview at `/dev/preview/settings`, embed preview at `/dev/preview/embeds/[app]`.

### `frontend/packages/ui/src/components/embeds/`
- All embed rendering. Always use `UnifiedEmbedPreview.svelte` and `UnifiedEmbedFullscreen.svelte` as base components for any new embed type.
- Subdirectories by domain: `images/`, `videos/`, `maps/`, `news/`, `web/`, `pdf/`, `reminder/`, etc.

### `frontend/packages/ui/src/components/settings/elements/`
- 24 canonical settings UI primitives. All settings pages MUST use only these components. No custom inline CSS.
- Key components: `SettingsCard.svelte`, `SettingsInput.svelte`, `SettingsDropdown.svelte`, `SettingsToggle` (via `SettingsConsentToggle.svelte`), `SettingsButton.svelte`, `SettingsPageContainer.svelte`, `SettingsPageHeader.svelte`, etc.
- Preview at `/dev/preview/settings`.

### `frontend/packages/ui/src/stores/`
- One file per Svelte store. Many stores (e.g., `activeChatStore.ts`, `aiTypingStore.ts`). Import only via barrel exports — stores must NOT import from other stores' internal modules.

### `frontend/packages/ui/src/services/db/`
- Modular IndexedDB operations split by concern: `chatCrudOperations.ts`, `messageOperations.ts`, `chatKeyManagement.ts`, `appSettingsMemories.ts`, `newChatSuggestions.ts`, `offlineChangesAndUpdates.ts`.

### `frontend/packages/ui/src/i18n/sources/`
- YAML source files for all translations. This is where all edits go. Never touch `locales/` JSON directly.
- After editing, run: `cd frontend/packages/ui && npm run build:translations`

### `backend/apps/{app_name}/`
- Each app microservice. Required structure:
  - `app.yml` — metadata declaration (skills, focus modes, settings/memories)
  - `skills/` — one Python class per skill implementing `execute()`
  - Optional: `providers/` for app-local providers (only if not reusable across apps)
  - Optional: `tasks/` for Celery tasks specific to this app

### `backend/core/api/app/routes/handlers/websocket_handlers/`
- One handler file per WebSocket message type. Adding a new WebSocket message type means adding a file here and registering it in `websockets.py`.

### `backend/core/api/app/services/directus/`
- Mixin files group Directus operations by domain: `chat_methods.py`, `auth_methods.py`, `embed_methods.py`, `usage_methods.py`, `user/` subdirectory (CRUD for users). All assembled in `directus.py`.

### `backend/core/api/app/tasks/`
- Celery task files for the infrastructure worker. Email tasks in `email_tasks/`. Beat schedule defined in `celery_config.py`.

### `backend/shared/providers/`
- Pure API wrappers only. No skill-specific logic. Current providers: `brave/`, `fal/`, `firecrawl/`, `google/`, `google_maps/`, `recraft/`, `serpapi.py`, `youtube/`, `protonmail/`.

### `backend/core/directus/schemas/`
- YAML schema files applied to Directus on `cms-setup` container start. One file per Directus collection.

---

## Key File Locations

### Entry Points
- `frontend/apps/web_app/src/routes/+page.svelte` — Root SPA page
- `frontend/packages/ui/src/app.ts` — `initializeApp()` bootstrap
- `backend/core/api/main.py` — FastAPI gateway entry
- `backend/apps/base_main.py` — App microservice entry (all app containers)
- `backend/apps/ai/tasks/ask_skill_task.py` — AI pipeline Celery task

### Configuration
- `backend/core/docker-compose.yml` — Full service mesh
- `backend/config/backend_config.yml` — Backend runtime config (provider URLs, model configs)
- `backend/core/api/app/tasks/celery_config.py` — Celery queues, beat schedule
- `frontend/packages/ui/src/config/api.ts` — API URL resolution
- `frontend/packages/ui/src/config/links.ts` — All external links
- `frontend/apps/web_app/svelte.config.js` — SvelteKit adapter config
- `frontend/apps/web_app/playwright.config.ts` — E2E test config

### Core Logic
- `backend/apps/ai/processing/main_processor.py` — AI LLM call + tool dispatch loop
- `backend/apps/ai/processing/preprocessor.py` — Request enrichment, model selection
- `backend/apps/ai/processing/postprocessor.py` — Response categorization, follow-up suggestions
- `backend/apps/ai/processing/skill_executor.py` — HTTP dispatch to app skill endpoints
- `backend/apps/base_app.py` — `BaseApp` class powering all app microservices
- `backend/core/api/app/routes/websockets.py` — WebSocket endpoint + Redis listener tasks
- `backend/core/api/app/services/directus/directus.py` — Database access facade
- `backend/core/api/app/services/cache.py` — Cache facade (Dragonfly/Redis)
- `frontend/packages/ui/src/services/chatSyncService.ts` — Frontend sync orchestrator
- `frontend/packages/ui/src/services/websocketService.ts` — WebSocket connection manager

### Schemas and Types
- `backend/shared/python_schemas/app_metadata_schemas.py` — `AppYAML`, `AppSkillDefinition`
- `backend/core/api/app/schemas/chat.py` — Chat, message Pydantic schemas
- `backend/core/api/app/schemas/auth.py` — Auth request/response schemas
- `frontend/packages/ui/src/types/chat.ts` — Frontend chat/message TypeScript types
- `frontend/packages/ui/src/types/appSkills.ts` — App/skill TypeScript types

### Testing
- `frontend/apps/web_app/tests/` — 94 Playwright E2E spec files
- `backend/apps/ai/testing/` — Python unit tests for AI processing
- `backend/tests/` — Backend integration tests

---

## Naming Conventions

### Files — Frontend
- Svelte components: `PascalCase.svelte` (e.g., `ActiveChat.svelte`, `UnifiedEmbedPreview.svelte`)
- TypeScript services: `camelCase.ts` (e.g., `chatSyncService.ts`, `websocketService.ts`)
- Svelte stores: `camelCaseStore.ts` or `camelCaseState.ts` (e.g., `activeChatStore.ts`, `menuState.ts`)
- Test files: `*.test.ts` for unit, `*.spec.ts` for E2E
- Preview companion: `ComponentName.preview.ts` alongside `ComponentName.svelte`

### Files — Backend
- Python modules: `snake_case.py`
- Route handlers: `{domain}_handler.py` (e.g., `message_received_handler.py`)
- Service methods split into: `{domain}_methods.py` (e.g., `chat_methods.py`, `embed_methods.py`)
- Celery tasks: `{domain}_tasks.py`
- App skill classes: `{name}_skill.py` (e.g., `ask_skill.py`)

### Directories
- Frontend packages: kebab-case (`web_app`, `ui`)
- Backend apps: snake_case matching the app ID (`ai`, `web`, `news`, `maps`)
- Docker container names: `app-{name}` for app microservices, `app-{name}-worker` for their Celery workers

---

## Where to Add New Code

### New App Microservice
1. Create `backend/apps/{name}/` directory.
2. Add `app.yml` — declare `name_translation_key`, `description_translation_key`, skills list with `class_path`.
3. Implement skill class in `backend/apps/{name}/skills/{name}_skill.py`.
4. If providers are app-specific only, add to `backend/apps/{name}/providers/`. If reusable, add to `backend/shared/providers/`.
5. Add Docker service to `backend/core/docker-compose.yml` using `Dockerfile.base` with `APP_NAME={name}`.
6. Add i18n keys to `frontend/packages/ui/src/i18n/sources/app_skills/` and rebuild translations.
7. Add embed components in `frontend/packages/ui/src/components/embeds/{name}/` if the skill produces embeds.

### New Skill on Existing App
1. Add skill declaration to the app's `app.yml` (new entry in `skills:` with `id`, `name_translation_key`, `description_translation_key`, `class_path`).
2. Implement skill class at `class_path` (e.g., `backend/apps/web/skills/new_skill.py`).
3. Add i18n translation keys in `frontend/packages/ui/src/i18n/sources/app_skills/`.
4. Add embed component if needed at `frontend/packages/ui/src/components/embeds/{app}/{EmbedName}.svelte` using `UnifiedEmbedPreview.svelte` / `UnifiedEmbedFullscreen.svelte` as base.

### New WebSocket Message Type
1. Add message type to `KnownMessageTypes` union in `frontend/packages/ui/src/services/websocketService.ts`.
2. Add TypeScript payload type to `frontend/packages/ui/src/types/chat.ts`.
3. Create handler in `backend/core/api/app/routes/handlers/websocket_handlers/{type}_handler.py`.
4. Import and register handler in `backend/core/api/app/routes/websockets.py`.
5. Add sender function to `frontend/packages/ui/src/services/chatSyncServiceSenders.ts`.
6. Add incoming handler to appropriate `chatSyncServiceHandlers*.ts` file.

### New Settings Page
1. Add Svelte component in `frontend/packages/ui/src/components/settings/`.
2. Use only canonical elements from `frontend/packages/ui/src/components/settings/elements/` — no custom CSS.
3. Add route entry to settings navigation in the relevant settings navigation store.
4. Add i18n keys in `frontend/packages/ui/src/i18n/sources/settings/`.

### New API Route (REST)
1. Create or extend a route file in `backend/core/api/app/routes/`.
2. Register the router in `backend/core/api/main.py`.
3. Add Pydantic request/response schemas in `backend/core/api/app/schemas/` or inline in the route file.

### New Celery Task (Infrastructure)
1. Create task in `backend/core/api/app/tasks/{domain}_tasks.py`.
2. Register the queue in `celery_config.py` if needed.
3. For periodic tasks, add to the `beat_schedule` in `celery_config.py`.

### New Shared Backend Utility
1. Pure utility function → `backend/shared/python_utils/`.
2. Shared Pydantic schema → `backend/shared/python_schemas/`.
3. Pure API provider wrapper → `backend/shared/providers/`.

### New Frontend Shared Utility
1. Pure TypeScript utility → `frontend/packages/ui/src/utils/`.
2. Shared Svelte component → `frontend/packages/ui/src/components/`.
3. Svelte store → `frontend/packages/ui/src/stores/{name}Store.ts` or `{name}State.ts`.

---

## Special Directories

### `frontend/packages/ui/src/i18n/locales/`
- **Purpose:** Auto-generated JSON translation files used at runtime.
- **Generated:** Yes — by `npm run build:translations` in `frontend/packages/ui`.
- **Committed:** Yes.
- **Rule:** Never edit manually. Edit YAML sources only.

### `backend/core/directus/schemas/`
- **Purpose:** YAML definitions for all Directus CMS collections.
- **Generated:** No — hand-authored.
- **Committed:** Yes.
- **Applied:** Automatically by `cms-setup` container on every service start.

### `frontend/apps/web_app/tests/`
- **Purpose:** Playwright E2E tests (94 spec files).
- **Generated:** No.
- **Committed:** Yes.

### `.planning/codebase/`
- **Purpose:** GSD codebase map documents consumed by planning and execution tools.
- **Generated:** Yes — by `/gsd:map-codebase`.
- **Committed:** Yes.

### `backend/apps/ai/testing/fixtures/`
- **Purpose:** Recorded LLM fixtures for deterministic test replay.
- **Generated:** Partially (via `fixture_recorder.py`).
- **Committed:** Yes.

### `frontend/apps/web_app/src/lib/generated/`
- **Purpose:** Auto-generated TypeScript from build scripts (e.g., app metadata, model metadata).
- **Generated:** Yes — by Turborepo build tasks.
- **Committed:** Yes (output artifacts tracked by Turbo).

---

*Structure analysis: 2026-03-26*
