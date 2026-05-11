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
---

# Daily Inspiration

> Delivers up to 3 curated, video-based inspiration cards per day from independent creators, with zero LLM latency at display time.

## Why This Exists

Provides curiosity-driven content from independent educators, journalists, and documentary makers -- never from corporate channels. Each inspiration includes a YouTube video, a phrase, a pre-written assistant response, and follow-up suggestions so users can start a chat instantly.

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
8. **Main LLM call** -- single Mistral Small call per user for all slots; selects best video, writes phrase/title/assistant_response/category/follow_up_suggestions

### Generation Triggers

| Trigger | When | Count | File |
|---------|------|-------|------|
| First paid request | After first paid request post-processing | 3 | `daily_inspiration_tasks.py` |
| Scheduled daily | 06:00 UTC Celery Beat | min(viewed_count, 3) | `daily_inspiration_tasks.py` |
| Default selection | 06:30 UTC Celery Beat | Top 3 per language | `default_inspiration_tasks.py` |

### Delivery

**Authenticated users:** Generated -> stored in Redis (7-day TTL) -> broadcast via WebSocket if online -> delivered on login if offline. Cross-device persistence via encrypted Directus `user_daily_inspirations` table.

**Unauthenticated users:** At 06:30 UTC, pool entries scored per language (`interaction_count / (age_hours + 1)`), top 3 written to `daily_inspiration_defaults` table. Frontend fetches via `GET /v1/default-inspirations?lang={code}` (public, 1h cache).

### Frontend

- `DailyInspirationBanner.svelte` -- carousel of up to 3 cards
- `dailyInspirationStore.ts` -- Svelte store for state/navigation
- `dailyInspirationDB.ts` -- IndexedDB with AES-GCM encryption, 72h TTL
- Chat creation: `handleStartChatFromInspiration()` in `ActiveChat.svelte`

## Data Structures

### Pydantic Models (`schemas.py`)

- `DailyInspirationVideo` -- youtube_id, title, thumbnail_url, channel_name, view_count, duration_seconds, published_at
- `DailyInspiration` -- inspiration_id, phrase, title, assistant_response, category, content_type, video, generated_at, follow_up_suggestions

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
- **Cost per inspiration:** ~$0.018 (Brave search + YouTube API + two Mistral Small calls)
- **Per active user/month (3/day):** ~$1.60, absorbed by platform

## Related Docs

- [Message Processing](../messaging/message-processing.md) -- topic extraction via post-processing
- E2E test: `frontend/apps/web_app/tests/daily-inspiration-chat-flow.spec.ts`
