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
- frontend/packages/ui/src/data/product_features.yml
- frontend/packages/ui/src/demo_chats/loadDefaultInspirations.ts
- frontend/packages/ui/src/demo_chats/hardcodedInspirations.ts
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

Provides curiosity-driven content from independent educators, journalists, documentary makers, and Wikipedia articles, plus static OpenMates feature tips. Content inspirations include a phrase, pre-written assistant response, and follow-up suggestions so users can start a chat instantly. Logged-out product feature cards use concise editorial headlines from `product_features.yml`; authenticated feature tips can deep-link to settings instead of creating chats.

## How It Works

### Generation Pipeline

Runs in `app-ai-worker` Celery container:

1. **Topic filtering** -- deterministic shared content-policy filters remove prohibited/promotional interests.
2. **Brave Video Search** -- localized YouTube discovery, strict SafeSearch, up to 20 candidates per video slot.
3. **Source enrichment** -- retain descriptions, publication dates and audience metadata; reject made-for-kids and over-age videos.
4. **Jev editorial decisions** -- pinned Jev 1.14 screens eligibility, ranks educational relevance and assigns categories. Conspiracy promotion, misleading clickbait and instruction injection are prohibited. Evidence-based debunking and honest curiosity are allowed. Uncertain or failed decisions withhold new candidates.
5. **Video writing** -- Mercury 3 LOW writes the exact preselected sources. Failed, malformed or editorially rejected drafts get one second Mercury attempt, then one Gemini 3.5 Flash-Lite attempt. Every attempt is assembled and reviewed against the same public evidence; accepted HTTP alone is insufficient.
6. **Wikipedia discovery and writing** -- search real localized article titles, validate them and fetch summaries/Wikidata before Jev selection. The writer paraphrases only the selected public summaries; it cannot invent article targets.
7. **Final review** -- Jev separately checks editorial policy and material factual grounding for both content types, including follow-ups. Missing/failed/uncertain reviews withhold the card. A material grounding check targets invented specific claims while allowing ordinary explanatory paraphrases.
8. **Feature tips** -- four static feature cards, no inference.
9. **Delivery** -- shuffle once per user/UTC day; only complete 3-video/3-wiki/4-feature sets replace personalized delivery. Reviewed partial stock may enter the pool; clients retain existing recovery when a complete new set is unavailable.
10. **Public selection** -- existing shared-pool external cards are reviewed before defaults selection, including legacy rows. Public video descriptions are retained for later source review. Static feature auth/guest checks remain deterministic.

The primary writer is restricted to `inception/mercury-3`; Mistral is no longer an allowed primary. Recovery uses `google/gemini-3.5-flash-lite`. The chain has at most three logical writing attempts, a 30-second writer timeout per attempt (explicitly propagated through the preprocessing adapter), and no facade fallback or Mercury SDK retries. It does not change account settings or ordinary assistant routing. See `docs/plans/daily-inspiration-jev/` for the paired benchmark and selected default.

### Generation Triggers

| Trigger | When | Count | File |
|---------|------|-------|------|
| First paid request | After first paid request post-processing | 10 | `daily_inspiration_tasks.py` |
| Scheduled daily | 06:00 UTC Celery Beat | 10 if viewed_count > 0 | `daily_inspiration_tasks.py` |
| Default selection | 06:30 UTC Celery Beat | Mixed top 10 per language | `default_inspiration_tasks.py` |

### Delivery

**Authenticated users:** Generated -> stored in Redis (7-day TTL) -> broadcast via WebSocket if online -> delivered on login if offline. Cross-device persistence via encrypted Directus `user_daily_inspirations` table.

**Unauthenticated web users:** The ordinary new-chat screen immediately shows a locale-aware, guest-safe Daily Inspirations fallback. A complete public 3-video, 3-wiki, 4-feature set can replace it through the public defaults endpoint; authenticated-only or promotional cards are rejected. Guests retain interest selection and the full example-chat catalog, independently of the selected inspiration. Marketing content belongs to the separate scrolling website. Guest data remains isolated from authenticated Daily Inspirations; the internal `guest-onboarding` source marker lets login recover the account-specific source.

**Guest fallback content:** The built-in authenticated fallback retains its chat-export feature. For guests, that authenticated-only card is replaced with a public Events search inspiration while the other nine cards remain the same.

**Public and authenticated fallback clients:** At 06:30 UTC, pool entries are scored per language (`interaction_count / (age_hours + 1)`) and a 3-video, 3-wiki, 4-feature target is written to `daily_inspiration_defaults`. `GET /v1/default-inspirations?lang={code}` exposes the credit-free public fallback with a 1-hour cache. Authenticated clients use it only when personalized IndexedDB, Phase 1, live WebSocket, and account API recovery provide no usable records.

### Frontend

- `DailyInspirationBanner.svelte` -- carousel of up to 10 cards
- `dailyInspirationStore.ts` -- Svelte store for state/navigation and explicit guest/personalized/public/fallback source priority
- `dailyInspirationDB.ts` -- IndexedDB with AES-GCM encryption, 72h TTL
- `product_features.yml` -- fallback product-feature headline registry
- Chat creation: `handleStartChatFromInspiration()` in `ActiveChat.svelte`

## Data Structures

### Pydantic Models (`schemas.py`)

- `DailyInspirationVideo` -- youtube_id, title, thumbnail_url, channel_name, view_count, duration_seconds, published_at
- `DailyInspirationWiki` -- title, wiki_title, source_language (source edition, independent of card language), description, thumbnail_url, wikidata_id, extract
- `DailyInspirationFeature` -- feature_id, icon, title, description, settings_path
- `DailyInspiration` -- inspiration_id, phrase, title, assistant_response, category, content_type, video, wiki, feature, generated_at, follow_up_suggestions

### Directus Tables

| Table | Purpose |
|-------|---------|
| `daily_inspiration_pool` | Shared cleartext public-source pool, capped at 500 |
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

- **Editorial decision failure:** Withhold new external candidates; preserve existing feed recovery instead of publishing unreviewed cards
- **Video cost remains capped:** existing 3-video/day budget is unchanged
- **Wiki cost:** one writing call, bounded Jev decisions and free Wikimedia API requests
- **Feature cost:** static/no external API calls

## Related Docs

- [Message Processing](../messaging/message-processing.md) -- topic extraction via post-processing
- E2E test: `frontend/apps/web_app/tests/daily-inspiration-chat-flow.spec.ts`

### Multilingual and visual editorial admission

Jev 1.14 separately checks source policy, educational fit/category, factual grounding,
semantic subject coherence, follow-up source relevance and the requested copy language.
Semantic checks accept translations and unspaced Japanese; lexical overlap is not an
admission rule. Every follow-up must use an explicit source concept. A merely related
scenario, such as wind for a source mentioning only bridge compression/tension, is rejected.

Video candidates also require a direct TypeSafe image decision over bounded decoded
YouTube thumbnail pixels. Downloads use a validated video ID and a fixed YouTube image
host, no arbitrary caller URL or redirects. Missing, rejected, uncertain or unavailable
visual decisions withhold the candidate. Ordinary curiosity, faces and arrows alone
are allowed; deceptive claims, conspiracy/miracle bait and material source mismatch are
not. Image support is experimental; this is a daily metadata/image screen, not verification
of watched video content or a guarantee against a thumbnail changing after review.

Daily public selection re-reviews legacy pool rows, then stores a versioned hash binding
approved video copy, language, source metadata and thumbnail identity. The anonymous
endpoint verifies this hash and never invokes a paid model. Modified/unreviewed rows
use static recovery. Semantic uncertainty does not delete historical pool data.

All fifteen backend static cards share the frontend fallback translation YAML catalog,
compiled into a backend-only JSON artifact for offline use. All twenty feed languages
are covered (plus Hebrew in the UI catalog). Missing native-language stock uses localized
static cards instead of relabeled English pool rows. Static Wikipedia cards retain English
canonical article IDs and explicitly mark their source edition as English; generated
Wikipedia cards carry their actual retrieval edition. The card copy remains localized.
