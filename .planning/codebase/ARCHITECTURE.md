# Architecture

**Analysis Date:** 2026-03-26

## Pattern Overview

**Overall:** Polyrepo-style monorepo. Backend is a microservices mesh of Docker containers; frontend is a SvelteKit SPA deployed to Vercel. All services communicate via internal Docker network (not exposed externally except `api:8000`).

**Key Characteristics:**
- Frontend is a pure client-side SPA: all data lives in IndexedDB, synced to the backend through a single persistent WebSocket connection. REST is used only for auth, payments, and public endpoints.
- Backend consists of a central FastAPI gateway (`api`) and many independent app microservices (`app-ai`, `app-web`, `app-news`, etc.), each running their own Uvicorn process. The gateway proxies skill execution to app services via internal HTTP.
- Async task execution is handled by dedicated Celery workers (`app-ai-worker`, `app-images-worker`, `app-pdf-worker`, `task-worker`), with Dragonfly (Redis-compatible) as the message broker and result backend.
- End-to-end encryption: chat content is encrypted client-side before syncing. Server-side stores only encrypted ciphertext except in specific admin contexts.
- Secrets are managed by HashiCorp Vault; the API waits for Vault to be unsealed before starting.

---

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
  - `python_schemas/` — Pydantic models for `AppYAML`, `AppSkillDefinition`, embed status, software update schemas.
  - `python_utils/` — Pure utilities: `billing_utils.py`, `content_hasher.py`, `domain_filter.py`, `geo_utils.py`, `url_normalizer.py`.
  - `providers/` — Pure API wrapper clients: `brave/`, `fal/`, `firecrawl/`, `google/`, `google_maps/`, `serpapi.py`, `youtube/`, etc. No skill-specific logic.
- **Depends on:** Only Python stdlib and third-party packages.
- **Used by:** `backend/core/api/` and all `backend/apps/` microservices.

### Celery Workers
- **Purpose:** Background async task execution. The `app-ai-worker` runs the AI processing pipeline; `task-worker` handles infrastructure tasks (email, persistence, push); `app-images-worker` and `app-pdf-worker` are dedicated workers for heavy processing.
- **Location:** Tasks defined in `backend/core/api/app/tasks/` and `backend/apps/ai/tasks/`
- **Celery config:** `backend/core/api/app/tasks/celery_config.py`
- **Queue mapping:**
  - `app_ai` → `app-ai-worker`
  - `app_images` → `app-images-worker`
  - `app_pdf` → `app-pdf-worker`
  - `email, user_init, persistence, health_check, server_stats, demo, reminder, push` → `task-worker`
- **Scheduler:** `task-scheduler` container runs `celery beat` for periodic tasks.

### Directus CMS (Data Layer)
- **Purpose:** PostgreSQL-backed CMS acting as the primary application database. Accessed exclusively by the API gateway via `DirectusService`.
- **Location:** `backend/core/directus/`
- **Schemas:** Defined as YAML in `backend/core/directus/schemas/` — applied by the `cms-setup` container on startup. Key collections: `users`, `chats`, `messages`, `embeds`, `reminders`, `usage`, `api_keys`, `webhooks`, and many others.
- **Access:** `backend/core/api/app/services/directus/directus.py` — mixin-based service with method groups: `auth_methods.py`, `chat_methods.py`, `embed_methods.py`, `usage_methods.py`, etc.

---

## Data Flow

### Chat Message (Happy Path)
1. User types a message in `frontend/apps/web_app/src/routes/+page.svelte` (the single SPA page).
2. `ChatSynchronizationService` (`frontend/packages/ui/src/services/chatSyncService.ts`) sends `message_received` over the WebSocket.
3. `websockets.py` route handler (`backend/core/api/app/routes/websockets.py`) receives the message, invokes `handle_message_received` from `backend/core/api/app/routes/handlers/websocket_handlers/message_received_handler.py`.
4. The handler enqueues an `ask_skill_task` Celery task onto the `app_ai` queue via `backend/core/api/app/tasks/celery_config.py`.
5. `app-ai-worker` picks up the task from `backend/apps/ai/tasks/ask_skill_task.py`.
6. Task runs the AI pipeline: `preprocessor.py` → `main_processor.py` → tool calls to app skill services → `postprocessor.py`.
7. Streaming AI response tokens are published to Redis Pub/Sub channels (`listen_for_ai_chat_streams`).
8. The API's `listen_for_ai_chat_streams` background task relays tokens to the frontend over the WebSocket.
9. Frontend `chatSyncServiceHandlersAI.ts` receives tokens and updates IndexedDB + reactive stores.
10. Persisted chat data is written to Directus by `persistence_tasks.py` Celery tasks.

### Skill Execution Inside AI Pipeline
1. `main_processor.py` generates LLM tool calls using `tool_generator.py`.
2. `skill_executor.py` dispatches HTTP requests to the appropriate app microservice (e.g., `http://app-web:8000/skills/search/execute`).
3. App microservice skill class processes the request (calling an external API via a provider in `backend/shared/providers/`).
4. Result is returned to `main_processor.py`, injected as a tool result, and the LLM continues.

### Initial Page Load / Sync
1. User opens the SPA; `app.ts` `initializeApp()` initializes IndexedDB, auth store, and loads the user profile.
2. `authStore.initialize()` verifies the JWT cookie with `GET /v1/auth/me`.
3. If authenticated, `chatSyncService.connect()` opens the WebSocket (`/v1/ws/chat`).
4. Client sends `initial_sync_request` with local chat version map.
5. Server (`initial_sync_handler.py`) responds with a phased sync plan.
6. Phased sync handlers progressively load chats; encrypted chat content is decrypted by the client using keys from IndexedDB.

### State Management
- Frontend reactive state: Svelte stores in `frontend/packages/ui/src/stores/` — one file per concern (e.g., `activeChatStore.ts`, `aiTypingStore.ts`, `websocketStatusStore.ts`).
- Local persistence: IndexedDB via `chatDB` (`frontend/packages/ui/src/services/db.ts`) and `userDB` (`frontend/packages/ui/src/services/userDB.ts`).
- Server-side cache: `CacheService` wraps Dragonfly (Redis) — split into mixins: `cache_chat_mixin.py`, `cache_user_mixin.py`, `cache_inspiration_mixin.py`, etc. (`backend/core/api/app/services/`).

---

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

---

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

---

## Error Handling

**Strategy:** Raise exceptions at the point of failure; never swallow errors silently. FastAPI exception handlers surface errors as HTTP responses. WebSocket errors send typed error messages to the client.

**Patterns:**
- API routes raise `HTTPException` with explicit status codes and detail messages.
- Celery tasks catch exceptions, log them, and update task state to `FAILURE`.
- LLM failures use `AllServersFailedError` → send `STANDARDIZED_USER_ERROR_MESSAGE` to the user.
- Cache misses MUST have a database fallback (never treat a miss as fatal).
- AI skill execution has a `HARD_LIMIT_SKILL_CALLS = 5` guard against infinite tool call loops.
- `SoftTimeLimitExceeded` from Celery is handled in task code to send graceful cancellation messages.

---

## Cross-Cutting Concerns

**Logging:** JSON structured logging via `python-json-logger`. Configured in `backend/core/api/app/utils/setup_logging.py`. All logs flow to OpenObserve (monitoring service). `SensitiveDataFilter` scrubs secrets before log emission.

**Validation:** Pydantic models throughout the backend. Frontend uses TypeScript types from `frontend/packages/ui/src/types/`. App metadata validated against `AppYAML` schema at service startup.

**Authentication:** JWT-based. Cookies set by auth routes (`backend/core/api/app/routes/auth_routes/`). WebSocket auth uses a short-lived `ws_token`. Admin operations require `admin` role checked in Directus user record.

**Encryption:** Client-side AES-GCM for chat content. Key management in `frontend/packages/ui/src/services/encryption/ChatKeyManager.ts`. Server-side encryption (`backend/core/api/app/utils/encryption.py`) for server-stored settings. Secrets (API keys, payment keys) stored in HashiCorp Vault, accessed via `SecretsManager` (`backend/core/api/app/utils/secrets_manager.py`).

**Rate Limiting:** `slowapi` on the API gateway (`backend/core/api/app/services/limiter.py`). AI task queue depth enforced per user in `backend/apps/ai/processing/rate_limiting.py`.

**Internationalization:** YAML source files in `frontend/packages/ui/src/i18n/sources/`, compiled to JSON via `npm run build:translations`. Never edit generated JSON directly. The compiled locales are also mounted into all backend containers for server-side translation resolution.

---

*Architecture analysis: 2026-03-26*
