# Daily Inspiration — Architecture

This document describes how the Daily Inspiration feature works end-to-end: the generation pipeline, content policy enforcement, delivery, storage, and the frontend display. For a user-facing description, see `docs/user-guide/daily-inspiration.md`.

---

## Overview

Daily Inspiration delivers up to 3 curated, curiosity-driven video-based inspiration cards to each active user per day. Each inspiration consists of a thought-provoking phrase, a YouTube video from an **independent creator** (never corporate), a pre-written assistant message, and follow-up suggestions — allowing the user to start a chat with zero LLM latency.

### Core Principle

Inspirations come from **independent humans** — educators, journalists, universities, documentary makers — never from corporate PR channels. A four-layer content policy (topic filter, search bias, seed blocklist, LLM channel classifier) enforces this.

---

## System Architecture

### Generation Pipeline

The pipeline runs in the `app-ai-worker` Celery container and produces `DailyInspiration` objects for each user.

```
User topic suggestions (3-day pool)
        │
        ▼
┌─────────────────────────────┐
│  1. Topic Filtering         │  Removes OpenMates refs, sensitive content,
│                             │  and corporate/greenwashing framing
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  2. Brave Video Search      │  "{topic} educational independent creator"
│     (per slot, 1-3 slots)   │  safesearch=strict, 20 results each
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  3. YouTube-Only Filter     │  Extract video IDs, reject non-YouTube
│  4. Family-Friendly Filter  │  Reject family_friendly=False
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  5. Anti-Corporate Filter   │
│     Layer A: Seed blocklist │  119 patterns (fast, no LLM)
│     Layer B: LLM classifier │  Mistral Small classifies remaining
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  6. YouTube Data API        │  Enrich with view count, duration,
│     Enrichment              │  published_at
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  7. Sort by view count      │  Top 20 candidates per slot
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  8. Main LLM Call           │  Single Mistral Small call for ALL slots.
│     (one per user)          │  Selects best video, writes phrase,
│                             │  title, assistant_response, category,
│                             │  follow_up_suggestions per slot.
└──────────┬──────────────────┘
           │
           ▼
     DailyInspiration objects (1-3)
```

### Generation Triggers

| Trigger             | When                                                        | Count                        | File                                                      |
| ------------------- | ----------------------------------------------------------- | ---------------------------- | --------------------------------------------------------- |
| First paid request  | After a user's first paid request completes post-processing | 3                            | `backend/core/api/app/tasks/daily_inspiration_tasks.py`   |
| Scheduled daily job | 06:00 UTC via Celery Beat                                   | min(viewed_count, 3)         | `backend/core/api/app/tasks/daily_inspiration_tasks.py`   |
| Default selection   | 06:30 UTC via Celery Beat                                   | Top 3 per language from pool | `backend/core/api/app/tasks/default_inspiration_tasks.py` |

---

## Content Policy (Anti-Corporate / Anti-Greenwashing)

Four layers prevent corporate PR and greenwashing content from appearing:

### Layer 1 — Topic Suggestion Filter

**Where:** `backend/apps/ai/daily_inspiration/generator.py`

Three keyword blocklists filter topic suggestions **before** they become search queries:

- `_OPENMATES_TOPIC_KEYWORDS` — blocks platform self-promotion
- `_SENSITIVE_TOPIC_KEYWORDS` — blocks drugs, violence, explicit content
- `_CORPORATE_GREENWASHING_KEYWORDS` — blocks industry/corporate narrative framing (e.g. "automotive sustainability", "oil company green", "corporate responsibility")

### Layer 2 — Search Query Bias

**Where:** `backend/apps/ai/daily_inspiration/video_processor.py`

The Brave search query appends `"educational independent creator"` to bias results toward individual educators and away from corporate official channels.

### Layer 3 — Seed Channel Blocklist (Fast-Path)

**Where:** `backend/apps/ai/daily_inspiration/video_processor.py` + `backend/shared/config/corporate_channel_patterns.yml`

A YAML seed list of 119 corporate channel name patterns across 8 categories (automotive, oil/gas, pharma, big tech, defense, tobacco, fast fashion, agri-chemical). Case-insensitive substring matching instantly rejects obvious corporate channels (BMW, Shell, Pfizer, etc.) with zero LLM cost.

### Layer 4 — LLM Channel Classification

**Where:** `backend/apps/ai/daily_inspiration/video_processor.py`

A lightweight Mistral Small call classifies remaining channel names as `corporate` or `independent`. Catches channels not in the seed list (e.g. "Bayer Science", "Shell Energy"). Fails open — if the LLM call fails, candidates proceed unfiltered rather than dropping all content.

### Layer 5 — Main LLM Prompt Rules

**Where:** `backend/apps/ai/daily_inspiration/generator.py`

The main generation LLM receives channel names in the candidate list and has explicit anti-corporate rules in both prompt locations (tool definition + user message):

- "NEVER select videos from corporate channels"
- "ALWAYS prefer independent creators, educators, journalists, universities"
- "Corporate PR dressed up as education is never acceptable"

---

## Delivery Flow

### Personalized Inspirations (authenticated users)

1. **Generation** completes in `app-ai-worker`
2. **Stored** in Redis pending cache (7-day TTL)
3. **Broadcast** via WebSocket pubsub if user is online
4. **Copied** to the shared pool (`daily_inspiration_pool` Directus table) for default selection
5. On login, pending inspirations are delivered via WebSocket and removed from cache

### Default Inspirations (unauthenticated / new users)

1. At 06:30 UTC, a Celery task scores pool entries per language: `interaction_count / (age_hours + 1)`
2. Top 3 are written to `daily_inspiration_defaults` Directus table (per language, per date)
3. Frontend fetches via `GET /v1/default-inspirations?lang={code}` (public, 1h cache)
4. Avoids repeating yesterday's defaults when possible

### Cross-Device Persistence

Inspirations are persisted to Directus (`user_daily_inspirations` table) encrypted with the user's master key. On login from a new device, the client recovers inspirations via REST API.

---

## Data Schemas

### Pydantic Models

**File:** `backend/apps/ai/daily_inspiration/schemas.py`

- `DailyInspirationVideo` — youtube_id, title, thumbnail_url, channel_name, view_count, duration_seconds, published_at
- `DailyInspiration` — inspiration_id, phrase, title, assistant_response, category, content_type, video, generated_at, follow_up_suggestions

### Directus Tables

| Table                        | Purpose                                        | File                                                           |
| ---------------------------- | ---------------------------------------------- | -------------------------------------------------------------- |
| `daily_inspiration_pool`     | Shared cleartext pool (no PII), capped at 100  | `backend/core/directus/schemas/daily_inspiration_pool.yml`     |
| `daily_inspiration_defaults` | Top 3 per language per day (denormalized)      | `backend/core/directus/schemas/daily_inspiration_defaults.yml` |
| `user_daily_inspirations`    | Per-user encrypted records (cross-device sync) | `backend/core/directus/schemas/user_daily_inspirations.yml`    |

### Cache Keys (Redis)

Managed via `backend/core/api/app/services/cache_inspiration_mixin.py`:

| Key Pattern           | TTL    | Purpose                                |
| --------------------- | ------ | -------------------------------------- |
| Topic suggestions     | 72h    | 3-day rolling window of user interests |
| Paid request tracking | 48h    | Eligibility for next-day generation    |
| Pending delivery      | 7 days | Offline user inspiration queue         |
| Sync cache            | 10 min | Deduplication during multi-device sync |

---

## API Surface

### REST Endpoints

| Method | Path                                 | Auth     | Purpose                                   | File                                                    |
| ------ | ------------------------------------ | -------- | ----------------------------------------- | ------------------------------------------------------- |
| GET    | `/v1/default-inspirations`           | Public   | Fetch default inspirations for a language | `backend/core/api/app/routes/default_inspirations.py`   |
| POST   | `/v1/daily-inspirations`             | Required | Persist encrypted inspirations            | `backend/core/api/app/routes/daily_inspirations_api.py` |
| GET    | `/v1/daily-inspirations`             | Required | Fetch persisted inspirations on login     | `backend/core/api/app/routes/daily_inspirations_api.py` |
| POST   | `/v1/daily-inspirations/{id}/opened` | Required | Mark opened + increment pool counter      | `backend/core/api/app/routes/daily_inspirations_api.py` |

### WebSocket Events

| Event                   | Direction        | Purpose                                   | File                                                                                       |
| ----------------------- | ---------------- | ----------------------------------------- | ------------------------------------------------------------------------------------------ |
| `inspiration_viewed`    | Client -> Server | Record view for next-day generation quota | `backend/core/api/app/routes/handlers/websocket_handlers/inspiration_viewed_handler.py`    |
| `inspiration_received`  | Client -> Server | Client ACK (now a no-op)                  | `backend/core/api/app/routes/handlers/websocket_handlers/inspiration_received_handler.py`  |
| `sync_inspiration_chat` | Client -> Server | Sync inspiration-created chat to server   | `backend/core/api/app/routes/handlers/websocket_handlers/sync_inspiration_chat_handler.py` |

---

## Frontend

### Components

| Component                       | Purpose                                                                                                | File                                                                |
| ------------------------------- | ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------- |
| `DailyInspirationBanner.svelte` | Carousel of up to 3 inspiration cards (gradient bg, mate image, video preview, CTA)                    | `frontend/packages/ui/src/components/DailyInspirationBanner.svelte` |
| Inspiration chat creation       | `handleStartChatFromInspiration()` in ActiveChat — creates local chat, sets assistant response + embed | `frontend/packages/ui/src/components/ActiveChat.svelte`             |

### State Management

| Store/Service              | Purpose                                                                  | File                                                       |
| -------------------------- | ------------------------------------------------------------------------ | ---------------------------------------------------------- |
| `dailyInspirationStore.ts` | Svelte store: inspirations array, currentIndex, navigation               | `frontend/packages/ui/src/stores/dailyInspirationStore.ts` |
| `dailyInspirationDB.ts`    | IndexedDB persistence: AES-GCM encrypted, 72h TTL, cross-device recovery | `frontend/packages/ui/src/services/dailyInspirationDB.ts`  |

### i18n

Translation keys: `frontend/packages/ui/src/i18n/sources/daily_inspiration.yml`

---

## Scheduling

Defined in `backend/core/api/app/tasks/celery_config.py`:

| Task                                | Schedule  | Purpose                                             |
| ----------------------------------- | --------- | --------------------------------------------------- |
| `daily_inspiration.generate_daily`  | 06:00 UTC | Generate personalized inspirations for active users |
| `daily_inspiration.select_defaults` | 06:30 UTC | Select top 3 from pool per language for defaults    |

---

## Cost Model

| Component                         | Cost per Inspiration | Notes                                 |
| --------------------------------- | -------------------- | ------------------------------------- |
| Topic filtering                   | Free                 | Keyword matching, no API              |
| Brave Video Search                | ~$0.005              | 1 search per slot                     |
| YouTube Data API                  | Free                 | 1 quota unit per batch, 10k units/day |
| Channel classifier LLM            | ~$0.001              | Mistral Small, ~400 tokens            |
| Main generation LLM               | ~$0.012              | Mistral Small, one call per user      |
| **Total per inspiration**         | **~$0.018**          |                                       |
| **Per active user/month** (3/day) | **~$1.60**           | Absorbed by platform                  |

---

## Key Design Decisions

| Decision                                       | Reasoning                                                                  | Alternatives Rejected                                               |
| ---------------------------------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| One LLM call per user (not per slot)           | Saves tokens and latency; avoids duplicate video selection                 | Per-slot calls: higher cost, risk of duplicates                     |
| Mistral Small for generation                   | Cheapest model that reliably follows tool schemas                          | Larger models: unnecessary cost for structured extraction           |
| LLM channel classifier (separate call)         | Dedicated filter is more reliable than bundling into main prompt           | Bundle into main call: single point of failure, prompt already long |
| Fail-open on classifier errors                 | Better to occasionally surface a corporate video than show no inspirations | Fail-closed: one API hiccup could leave all users without content   |
| Blanket anti-corporate rule (not per-industry) | More maintainable and future-proof than industry-specific lists            | Industry-specific: constantly outdated, requires manual updates     |
| Topic suggestions cached 72h (3-day pool)      | Ensures enough variety across days; prevents stale single-day bias         | 24h: too narrow, repetitive; 7d: too much noise from old topics     |

---

## Related Files (Quick Reference)

### Backend — Generation

- `backend/apps/ai/daily_inspiration/generator.py` — LLM orchestrator, topic filtering, prompt construction
- `backend/apps/ai/daily_inspiration/video_processor.py` — Brave search, YouTube enrichment, corporate channel filtering
- `backend/apps/ai/daily_inspiration/schemas.py` — Pydantic models (DailyInspiration, DailyInspirationVideo)
- `backend/shared/config/corporate_channel_patterns.yml` — Seed blocklist of corporate channel patterns

### Backend — Scheduling and Delivery

- `backend/core/api/app/tasks/daily_inspiration_tasks.py` — Celery tasks for generation + delivery
- `backend/core/api/app/tasks/default_inspiration_tasks.py` — Celery task for default selection
- `backend/core/api/app/services/cache_inspiration_mixin.py` — Redis cache key management and TTLs

### Backend — API and WebSocket

- `backend/core/api/app/routes/daily_inspirations_api.py` — REST endpoints for persistence
- `backend/core/api/app/routes/default_inspirations.py` — Public REST endpoint for defaults
- `backend/core/api/app/routes/handlers/websocket_handlers/inspiration_viewed_handler.py` — View tracking
- `backend/core/api/app/routes/handlers/websocket_handlers/sync_inspiration_chat_handler.py` — Chat sync

### Backend — Database

- `backend/core/api/app/services/directus/daily_inspiration_pool_methods.py` — Pool CRUD
- `backend/core/api/app/services/directus/daily_inspiration_defaults_methods.py` — Defaults CRUD
- `backend/core/api/app/services/directus/user_daily_inspiration_methods.py` — User inspirations CRUD
- `backend/core/directus/schemas/daily_inspiration_pool.yml` — Pool table schema
- `backend/core/directus/schemas/daily_inspiration_defaults.yml` — Defaults table schema
- `backend/core/directus/schemas/user_daily_inspirations.yml` — User inspirations table schema

### Backend — Topic Collection

- `backend/apps/ai/base_instructions.yml` — Post-processing prompt that extracts `daily_inspiration_topic_suggestions`

### Frontend

- `frontend/packages/ui/src/components/DailyInspirationBanner.svelte` — Banner carousel component
- `frontend/packages/ui/src/components/ActiveChat.svelte` — Chat creation from inspiration
- `frontend/packages/ui/src/stores/dailyInspirationStore.ts` — Svelte store
- `frontend/packages/ui/src/services/dailyInspirationDB.ts` — IndexedDB persistence
- `frontend/packages/ui/src/i18n/sources/daily_inspiration.yml` — Translation keys

### Scripts

- `backend/scripts/trigger_daily_inspiration.py` — Manual trigger for testing
- `backend/scripts/debug_daily_inspiration.py` — Debug/inspection utility

### Tests

- `frontend/apps/web_app/tests/daily-inspiration-chat-flow.spec.ts` — E2E test for chat initiation from inspiration
