---
status: active
last_verified: 2026-11-20
key_files:
- backend/apps/ai/daily_inspiration/generator.py
- backend/apps/ai/daily_inspiration/video_processor.py
- backend/apps/ai/daily_inspiration/schemas.py
- backend/shared/config/corporate_channel_patterns.yml
- frontend/packages/ui/src/components/DailyInspirationBanner.svelte
- frontend/packages/ui/src/stores/dailyInspirationStore.ts
- frontend/packages/ui/src/services/dailyInspirationDB.ts
- frontend/packages/ui/src/utils/startScreenRow.ts
- frontend/packages/ui/src/components/welcome/StartScreenChatCard.svelte
- frontend/packages/ui/src/services/dailyInspirationViewed.ts
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

> Delivers a daily 6-card inspiration set (3 videos, 3 Wikipedia article prompts) with zero LLM latency at display time. Signed-in users and signed-out visitors see the cards inside the start-screen row; no start screen of Chats, Apps or Workflows has a banner.

## Why This Exists

Provides curiosity-driven content from independent educators, journalists, documentary makers, and Wikipedia articles, Each inspiration includes a phrase, pre-written assistant response, and follow-up suggestions so users can start a chat instantly. Static feature-tip cards were removed in TASK-1321 (2026-11-20): legacy `content_type: feature` rows are dropped on read by the backend, the Rust client core and the web store, and none are generated.

## How It Works

### Generation Pipeline

Runs in `app-ai-worker` Celery container:

1. **Topic filtering** -- deterministic shared content-policy filters remove prohibited/promotional interests.
2. **Brave Video Search** -- localized YouTube discovery, strict SafeSearch, up to 20 candidates per video slot.
3. **Source enrichment** -- retain descriptions, publication dates and audience metadata; reject made-for-kids and over-age videos.
4. **Jev editorial decisions** -- pinned Jev 1.14 screens eligibility, ranks educational relevance and assigns categories. Conspiracy promotion, misleading clickbait and instruction injection are prohibited. Evidence-based debunking and honest curiosity are allowed. Uncertain or failed decisions withhold new candidates.
5. **Video writing** -- Mercury 3 is the sole LLM and writes the exact preselected sources. Provider failures or malformed/missing rows may retry that same model once, requesting only unresolved identities. Editorial rejections are terminal. Approved source-bound objects are retained; no cross-model fallback or separate LLM review is permitted.
6. **Wikipedia discovery and writing** -- search real localized article titles, validate them and fetch summaries/Wikidata before Jev selection. The writer paraphrases only the selected public summaries; it cannot invent article targets.
7. **Final review** -- Jev alone checks policy, semantic subject coherence, field grounding/language and each follow-up’s source relevance across locales. Source-preserving paraphrases and unspaced Japanese do not require word overlap. Failed/uncertain checks withhold a draft. Video admission also requires actual bounded JPEG thumbnail pixels, with no text-only visual fallback.
8. **Delivery** -- shuffle once per user/UTC day; only complete 3-video/3-wiki sets replace personalized delivery. Reviewed partial stock may enter the pool; clients retain existing recovery when a complete new set is unavailable.
9. **Public selection** -- existing shared-pool external cards are reviewed before defaults selection, including legacy rows. Public video descriptions are retained for later source review.

The production writer is fixed to `inception/mercury-3`: one generation stage,
at most two same-model attempts for provider/schema failures, a 30-second timeout
per attempt, LOW reasoning, temperature 0.5 and no facade fallbacks or nested retries. Jev is
the only decision provider. Gemini and Flash-Lite remain historical diagnostic
models only. This does not change account settings or ordinary assistant routing.

### Generation Triggers

| Trigger | When | Count | File |
|---------|------|-------|------|
| First active request | Post-processing with recent tracked request and no completed-first-run flag | 6 | `daily_inspiration_tasks.py` |
| Scheduled daily | 06:00 UTC Celery Beat | 6 for paid activity in the last 24h and viewed_count > 0 | `daily_inspiration_tasks.py` |
| Default selection | 06:30 UTC Celery Beat | Mixed top 6 (3 video, 3 wiki) per language | `default_inspiration_tasks.py` |

### Delivery

**Authenticated users:** Generated -> stored in Redis (7-day TTL) -> broadcast via WebSocket if online -> delivered on login if offline. Cross-device persistence via encrypted Directus `user_daily_inspirations` table.

**Unauthenticated web users:** The ordinary new-chat screen immediately shows a locale-aware, guest-safe Daily Inspirations fallback. A complete public 3-video, 3-wiki set can replace it through the public defaults endpoint; authenticated-only or promotional cards are rejected. Guests retain interest selection and the full example-chat catalog, independently of the selected inspiration. Marketing content belongs to the separate scrolling website. Guest data remains isolated from authenticated Daily Inspirations; the internal `guest-onboarding` source marker lets login recover the account-specific source.

**Guest fallback content:** Guests and signed-in users share the same six built-in fallback cards (3 video, 3 wiki); none are authenticated-only.

**Public and authenticated fallback clients:** At 06:30 UTC, pool entries are scored per language (`interaction_count / (age_hours + 1)`) and a 3-video, 3-wiki target is written to `daily_inspiration_defaults`. `GET /v1/default-inspirations?lang={code}` exposes the credit-free public fallback with a 1-hour cache. Authenticated clients use it only when personalized IndexedDB, Phase 1, live WebSocket, and account API recovery provide no usable records.

### Frontend

- `DailyInspirationBanner.svelte` -- carousel still used by the Projects and Tasks start screens; Chats, Apps and Workflows no longer render it
- `startScreenRow.ts` -- `interleaveStartRow()` (row rhythm), `selectChatRowInspirations()` (surface chats, video/wiki, unopened) and `selectWorkflowRowInspirations()` (the recommended-workflow hook, see below)
- `welcome/StartScreenChatCard.svelte` -- the one large card used by every start-row entry (own chats, priority chats, drafts, inspirations, guest examples); inspiration cards show the video/article image with a small "Daily inspiration" label
- `welcome/StartScreenUpcomingEntry.svelte` -- compact entry for an upcoming saved event (signed in) or the next OpenMates event (signed out) below the row (events are no longer row cards)
- `welcome/StartScreenRowActions.svelte` -- the browse actions tile, always the last item of the row
- `welcome/StartScreenChatSuggestions.svelte` + `services/startScreenSuggestions.ts` -- three new-chat suggestions below the row in the follow-up style; the synced-suggestion loader is shared with the composer rail (`NewChatSuggestions.svelte`)
- `dailyInspirationViewed.ts` -- `inspiration_viewed` WebSocket event, once per id per session, sent when half of a card is visible (row card)
- `dailyInspirationStore.ts` -- Svelte store for state/navigation and explicit guest/personalized/public/fallback source priority
- `dailyInspirationDB.ts` -- IndexedDB with AES-GCM encryption, 72h TTL
- Chat creation: `handleStartChatFromInspiration()` in `ActiveChat.svelte`

### Start-screen row (Chats, Apps, Workflows; signed in and signed out)

No start screen has a banner. Order from the top: greeting ("Hey <name>" or
"Hey there" plus one call to action), the row, the upcoming-event entry when
one exists, the suggestions, the message input. The row holds at most ten
large cards in total (`START_ROW_MAX_CARDS`); its first card is centred and its
last item is the browse actions tile (Chats: Show all, Search; guests: Select
interests, Show all; Apps: Show all apps, Search; Workflows: Show templates).
Chats shows own chats (reminder-priority chats, then the last opened chat, then
recent chats; guests: the example chats) with today's unopened inspirations
interleaved: two own chats, one inspiration, then one inspiration after every
third own chat, never repeating. A user without chats sees only the
inspirations. "Show all" lists only real chats. Apps shows its own items as
large cards with no inspirations and no tip.

**Recommended-workflow hook.** The Workflows row uses the same rhythm and label
with records that satisfy this contract (`DailyInspiration.workflow`):
`surface: "workflows"`, `content_type: "workflow"`, and
`workflow: { template_id: string, summary?: string, icon?: string }`. Opening
one calls the existing start-from-inspiration handler. No producer exists yet:
a future generator only has to deliver such records into the store; the
shells need no change. Until then the Workflows row shows only the user's
workflows (Specification `daily-inspiration.workflow-recommendation-hook`).

## Data Structures

### Pydantic Models (`schemas.py`)

- `DailyInspirationVideo` -- youtube_id, title, thumbnail_url, channel_name, view_count, duration_seconds, published_at
- `DailyInspirationWiki` -- title, wiki_title, source_language (source edition, independent of card language), description, thumbnail_url, wikidata_id, extract
- Legacy `content_type: feature` rows (the former `DailyInspirationFeature`) are dropped on read by `drop_unsupported_inspirations()` and no longer produced
- `DailyInspiration` -- inspiration_id, phrase, title, assistant_response, category, content_type (video or wiki), video, wiki, generated_at, follow_up_suggestions

### Directus Tables

| Table | Purpose |
|-------|---------|
| `daily_inspiration_pool` | Shared cleartext public-source pool, capped at 500 |
| `daily_inspiration_defaults` | Up to 6 reviewed public defaults per language per day |
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
- **Video output budget:** targets three generated videos; each writing batch has at most three provider attempts, independent of source/thumbnail decision calls
- **Wiki cost:** one initial writing call with up to two bounded repair calls, source/final Jev decisions and Wikimedia API traffic; do not conflate supplier usage with measured total infrastructure cost

## Related Docs

- [Message Processing](../messaging/message-processing.md) -- topic extraction via post-processing
- E2E test: `frontend/apps/web_app/tests/daily-inspiration-chat-flow.spec.ts`
- Component spec: `frontend/apps/web_app/tests/components/start-screen-row.spec.ts` (`/dev/preview/welcome/StartScreenRowPreviewHarness`)
- Specification: `specifications/features/daily-inspiration/` (start-row assertions) and `specifications/features/continue-carousel/` (upcoming entry)

### Multilingual and visual editorial admission

Jev 1.14 checks source policy, educational fit/category, semantic subject
coherence, field grounding/language and follow-up source relevance. Mercury 3
writes the copy; no LLM is called to review it. Negative/uncertain Jev admission
is terminal for that draft and cannot trigger another writer call.
Both generators use one consistent source-whitelisted request and cleaned schema.
Jev's language questions explicitly name the requested language and allow short
headings and fragments; English is valid when English is requested. Criteria and
confidence thresholds remain unchanged.
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
approved video/wiki copy, language, source metadata and thumbnail identity. Wiki proof additionally binds the actual canonical article, retrieval edition and complete fetched metadata; missing evidence is withheld. The anonymous
endpoint verifies this hash and never invokes a paid model. Modified/unreviewed rows
use static recovery. Semantic uncertainty does not delete historical pool data.

All fifteen backend static cards share the frontend fallback translation YAML catalog,
compiled into a backend-only JSON artifact for offline use. All twenty feed languages
are covered (plus Hebrew in the UI catalog). Missing native-language stock uses localized
static cards instead of relabeled English pool rows. Static Wikipedia cards retain English
canonical article IDs and explicitly mark their source edition as English; generated
Wikipedia cards carry their actual retrieval edition. The card copy remains localized.


### Granular recovery and cost accounting (2026-10-21)

The review proof is versioned `daily-editorial-v10`; public cache keys use `v20` (v20: six-card sets without feature records, TASK-1321).
Older video/wiki approvals cannot satisfy the stronger gate. Jev confidence remains an
abstention heuristic at the existing threshold, not a calibrated correctness
probability. Field-level repair codes contain no arbitrary provider prose and
are never part of the public response. Repairs bind to source IDs rather than
array positions, so a single pending video can be repaired safely.

```mermaid
flowchart TD
    A[Recent topics or generic seeds] --> B[Brave videos / localized Wikipedia discovery]
    B --> C[Source identity, age and deterministic policy checks]
    C --> D[Jev source policy, fit and categories; video pixels]
    D --> E[Mercury 3 writes source-backed fields]
    E --> F[Jev policy, coherence, grounding, language and follow-up relevance]
    F --> G[Retain approved source-bound cards]
    E --> H[Provider or missing/malformed source rows only]
    H --> I[One same-Mercury retry for unresolved IDs]
    I --> F
    G --> J[Personal complete set / reviewed public pool]
    J --> K[Background source/copy review and shared defaults selection]
    K --> L[Cached public delivery; localized static recovery]
```

The retry arrow is bounded to two same-model writing attempts. Editorial
rejections do not enter the retry path. No fresh generation occurs on anonymous page loads. Shared
background review cost depends on actual eligible pool rows, whereas personal
generation depends on eligible users/first-run events. Twenty display languages
do not imply twenty new daily generation jobs.

The original pre-Jev/Mercury baseline is commit
`c94ebe85a14f87aa3223eacfe129aa85ec93d939`: normal successful personal generation
used three Mistral channel-classification calls, one video writer, three video
validators and one wiki writer; static tips and public pool selection required
no inference. Original validation failed open on errors and wiki copy preceded
source-summary fetching. The new source, grounding and image checks add work as
well as changing writer prices. Cost comparisons must therefore include actual
source selection, all retries, visual review and shared revalidation, not just
compare one Mercury call with one historical Mistral call.

See the historical baseline and qualification receipts in
`docs/plans/daily-inspiration-jev/`. Historical production spend is unmeasured;
opt-in native replay uses exact historical application sources with explicitly
recorded current provider wrappers/tariffs. Supplier estimates precede provider
credits and omit unmeasured infrastructure/third-party charges. Generation yield
is reported separately from accepted-copy quality and ten-card fallback delivery.

The scoped English/German release and corrected live measurements are documented
in [the single-LLM release overview](../../plans/daily-inspiration-jev/single-llm-release-2026-10-21.md).
Scheduled personalization requires request activity within 24 hours and at least
one recorded inspiration view; first-run seeds require recent tracked activity
but no prior views. Missing or unavailable activity skips first-run generation.
The completion guard lasts seven days. Login/signup/public reads do not generate
new personal sets; background shared-pool Jev review is independent of activity.
