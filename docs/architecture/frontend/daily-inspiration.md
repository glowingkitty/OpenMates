---
status: active
last_verified: 2026-03-24
key_files:
- backend/apps/ai/daily_inspiration/generator.py
- backend/apps/ai/daily_inspiration/video_processor.py
- backend/apps/ai/daily_inspiration/schemas.py
- backend/shared/config/corporate_channel_patterns.yml
- frontend/packages/ui/src/components/DailyInspirationBanner.svelte
- frontend/packages/ui/src/stores/dailyInspirationStore.ts
- frontend/packages/ui/src/services/dailyInspirationDB.ts
- backend/core/api/app/tasks/daily_inspiration_tasks.py
claims:
- id: arch-frontend-daily-inspiration-behavior
  type: unit
  claim: Daily Inspiration is grounded in current source-of-truth files that parse or resolve successfully.
  source:
  - backend/apps/ai/daily_inspiration/generator.py
  - backend/apps/ai/daily_inspiration/video_processor.py
  - backend/apps/ai/daily_inspiration/schemas.py
  - backend/shared/config/corporate_channel_patterns.yml
  - frontend/packages/ui/src/components/DailyInspirationBanner.svelte
  test:
    file: scripts/tests/test_architecture_behavioral_claims.py
    command: python3 -m pytest scripts/tests/test_architecture_behavioral_claims.py
    assertion: arch-frontend-daily-inspiration-behavior
  verified: '2026-06-11'
- id: arch-frontend-daily-inspiration-source-1
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-frontend-daily-inspiration-source-1
  anchors:
  - type: file_exists
    path: backend/apps/ai/daily_inspiration/generator.py
- id: arch-frontend-daily-inspiration-source-2
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-frontend-daily-inspiration-source-2
  anchors:
  - type: file_exists
    path: backend/apps/ai/daily_inspiration/schemas.py
- id: arch-frontend-daily-inspiration-source-3
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-frontend-daily-inspiration-source-3
  anchors:
  - type: file_exists
    path: backend/apps/ai/daily_inspiration/video_processor.py
---

# Daily Inspiration

> Delivers a daily 10-card mixed inspiration set: 3 videos, 3 Wikipedia article prompts, and 4 OpenMates feature tips, with zero LLM latency at display time.

## Why This Exists

Provides curiosity-driven content from independent educators, journalists, documentary makers, and Wikipedia articles, plus static OpenMates feature tips. Content inspirations include a phrase, pre-written assistant response, and follow-up suggestions so users can start a chat instantly. Feature tips deep-link to settings instead of creating chats.

## How It Works

### Generation Pipeline

Runs in `app-ai-worker` Celery container:

1. **Topic filtering** -- removes OpenMates refs, sensitive content, corporate/greenwashing framing via keyword blocklists in `generator.py`
2. **Brave Video Search** -- appends "educational independent creator" to bias toward independents; safesearch=strict, 20 results per slot
3. **YouTube-only + family-friendly filter** -- rejects non-YouTube and `family_friendly=False`
4. **Anti-corporate filter** -- seed blocklist (119 patterns in `corporate_channel_patterns.yml`) + Mistral Small LLM classifier for remaining channels (fails open)
5. **YouTube Data API enrichment** -- view count, duration, published_at, made-for-kids status
6. **Made-for-kids filter** -- rejects videos YouTube marks as Made for Kids before ranking or LLM selection
7. **Sort by view count** -- top 20 candidates per slot
8. **Main LLM call** -- single Mistral Small call for the 3 video slots; selects best videos and writes phrase/title/assistant_response/category/follow_up_suggestions
9. **Wiki generation** -- one cheap LLM call proposes Wikipedia article titles from the same recent topic pool, validates them via `batch_validate_topics()`, then fetches summaries through the Wikimedia provider
10. **Feature tips** -- four static OpenMates feature cards from `feature_suggestions.py`, no LLM/API cost
11. **Daily order** -- the 10-card set is shuffled once per user per UTC day before delivery and persisted in that order

### Generation Triggers

| Trigger | When | Count | File |
|---------|------|-------|------|
| First paid request | After first paid request post-processing | 10 | `daily_inspiration_tasks.py` |
| Scheduled daily | 06:00 UTC Celery Beat | 10 if viewed_count > 0 | `daily_inspiration_tasks.py` |
| Default selection | 06:30 UTC Celery Beat | Mixed top 10 per language | `default_inspiration_tasks.py` |

### Delivery

**Authenticated users:** Generated -> stored in Redis (7-day TTL) -> broadcast via WebSocket if online -> delivered on login if offline. Cross-device persistence via encrypted Directus `user_daily_inspirations` table.

**Unauthenticated users:** At 06:30 UTC, pool entries scored per language (`interaction_count / (age_hours + 1)`), top 3 written to `daily_inspiration_defaults` table. Frontend fetches via `GET /v1/default-inspirations?lang={code}` (public, 1h cache).

### Frontend

- `DailyInspirationBanner.svelte` -- carousel of up to 10 cards
- `dailyInspirationStore.ts` -- Svelte store for state/navigation
- `dailyInspirationDB.ts` -- IndexedDB with AES-GCM encryption, 72h TTL
- Chat creation: `handleStartChatFromInspiration()` in `ActiveChat.svelte`

## Data Structures

### Pydantic Models (`schemas.py`)

- `DailyInspirationVideo` -- youtube_id, title, thumbnail_url, channel_name, view_count, duration_seconds, published_at
- `DailyInspirationWiki` -- title, wiki_title, description, thumbnail_url, wikidata_id, extract
- `DailyInspirationFeature` -- feature_id, icon, title, description, settings_path
- `DailyInspiration` -- inspiration_id, phrase, title, assistant_response, category, content_type, video, wiki, feature, generated_at, follow_up_suggestions

### Directus Tables

| Table | Purpose |
|-------|---------|
| `daily_inspiration_pool` | Shared cleartext pool, capped at 100 |
| `daily_inspiration_defaults` | Top 3 per language per day |
| `user_daily_inspirations` | Per-user encrypted records |

### Cache Keys (Redis via `cache_inspiration_mixin.py`)

| Key | TTL | Purpose |
|-----|-----|---------|
| Topic suggestions | 72h | 3-day rolling window of user interests |
| Paid request tracking | 48h | Eligibility for next-day generation |
| Pending delivery | 7 days | Offline user inspiration queue |
| Sync cache | 10 min | Deduplication during multi-device sync |

## Edge Cases

- **LLM classifier failure:** Fails open -- candidates proceed unfiltered rather than dropping all content
- **Video cost remains capped:** existing 3-video/day budget is unchanged
- **Wiki cost:** one small LLM call plus free Wikimedia API requests
- **Feature cost:** static/no external API calls

## Related Docs

- [Message Processing](../messaging/message-processing.md) -- topic extraction via post-processing
- E2E test: `frontend/apps/web_app/tests/daily-inspiration-chat-flow.spec.ts`
