# Original daily-inspiration baseline before Jev/Mercury

Native follow-up: [granular qualification and cost results](granular-qualification-2026-10-21.md) records the exact-timing replay and a declared 30-second historical timing sensitivity. Both returned incomplete sets; no successful-refresh price or historical invoice is inferred. The sensitivity averaged $0.019273155 per attempted original-architecture refresh, versus $0.029581853 current at Mercury launch pricing.

Reconstructed 2026-10-21 from repository history and retained benchmark receipts.
This is an architectural and tariff baseline, not a measurement of historical
production spend. The initial reconstruction made no provider calls or user/pool
writes; the subsequent native replay is linked above and also performs no user
or pool writes.

## Exact baseline

Use **`c94ebe85a14f87aa3223eacfe129aa85ec93d939`**, the parent of
`a0def9059fa52494fca903a5732c35bf19e17902` (2026-10-20, “screen daily inspirations
with Jev and compare writers”). The parent still has the original Mistral channel
classifier, video writer, adversarial validator and wiki writer. Its media coherence
check is deterministic. There is no Jev source/copy/image gate or Mercury recovery
chain in these generation paths. An earlier baseline is not needed to remove
partial Jev/Mercury changes from these paths.

Historical source references, all at that parent:

- `backend/apps/ai/daily_inspiration/{generator,video_processor,validator,wiki_generator,media_coherence}.py`
- `backend/core/api/app/tasks/{daily_inspiration_tasks,default_inspiration_tasks,celery_config}.py`
- `backend/apps/ai/utils/llm_utils.py`, `backend/providers/{mistral,brave}.yml`

[Historical generator](https://github.com/glowingkitty/OpenMates/blob/c94ebe85a14f87aa3223eacfe129aa85ec93d939/backend/apps/ai/daily_inspiration/generator.py),
[historical task orchestration](https://github.com/glowingkitty/OpenMates/blob/c94ebe85a14f87aa3223eacfe129aa85ec93d939/backend/core/api/app/tasks/daily_inspiration_tasks.py),
[historical default selection](https://github.com/glowingkitty/OpenMates/blob/c94ebe85a14f87aa3223eacfe129aa85ec93d939/backend/core/api/app/tasks/default_inspiration_tasks.py).

## Model roles and successful-path call counts

All four generative/classification roles requested **`mistral/mistral-small-latest`**.
The historical Mistral catalog labels that alias **Mistral Small 4**, with direct
Mistral as default and `openrouter/mistralai/mistral-small-2603` as an alternative
server. The literal request is an alias, not an immutable dated model identifier;
repository comments do not prove which weights a historical provider served.
The callers left facade retries enabled and did not supply an empty fallback list.
Consequently logical calls below are not a guaranteed bound on billable transport
attempts. Record the actual route/model on any replay.

| Stage | Original behavior | Normal three-video + three-wiki refresh |
| --- | --- | --- |
| Video discovery | Brave search for each topic, up to 20 results; YouTube IDs and public metadata | 3 logical searches |
| Channel classification | Mistral batch classifies named candidate channels, rejects corporate/religious/review channels and blocked tags; deterministic seed/keyword filters also apply | Up to 3 Mistral calls, one per nonempty classifiable search set |
| YouTube enrichment | Data API metadata, audience and blanket age filtering; candidates sorted by views, top 20 per slot retained | Up to 3 enrichment batches when a key and candidates exist |
| Video selection + copy | One Mistral tool call chooses among candidates and writes up to 3 cards | 1 Mistral call |
| Video assembly/coherence | Candidate identity, metadata/content/age checks and deterministic token overlap against media title | 0 model calls |
| Video adversarial validator | One Mistral call per assembled video, using title/phrase/intro/video title/channel; errors fail open | Up to 3 Mistral calls |
| Wiki discovery + copy | One Mistral call chooses article titles and writes up to 3 cards **before** fetching Wikipedia summaries | 1 Mistral call |
| Wiki validation | Wikimedia title existence/canonical identity, summary and optional Wikidata entity; deterministic policy check | 0 model calls |
| Four feature tips | Static templates | 0 model calls |

Thus a full successful refresh has **8 logical Mistral calls**: 3 channel
classifiers + 1 video writer + 3 video validators + 1 wiki writer. It targets
**6 generated cards and 4 static tips**, rather than ten generated cards. If no
classifiable channels exist, classifier calls are skipped; empty searches,
assembly rejections and provider failures change call/admission counts. A video
writer call is skipped when every candidate slot is empty. Do not divide a
failed refresh by ten and call that the price of ten admitted cards.

For an independently generated three-video batch the normal count is 7 calls,
or 7/3 logical calls per video when fully admitted. A three-wiki batch has one
call, or 1/3 per wiki card. Static cards have no marginal inference cost.
These fractions allocate shared work; they are not independent per-card requests.

The original wiki writer did **not** receive the later fetched source extract.
Its article existence checks cannot establish factual support for its earlier
copy. The original video validator did not review all follow-ups or actual
thumbnail pixels. Its fail-open behavior differs materially from Jev withholding
unresolved decisions. Source/copy safety, candidate ranking and thumbnail review
are therefore part of the before/after behavior change, not just writer prices.

## Scheduling and shared versus personal volume

The executable orchestration, rather than stale comments about “1–3 viewed”,
sets these volumes:

- At **06:00 UTC**, scan paid-request tracking; generate a full 3-video/3-wiki/4-tip
  set for each eligible user with a paid request in the last 24 hours and at least
  one viewed inspiration. The number viewed gates eligibility; it does not reduce
  generation below three requested videos. E2E users have a skip guard.
- The first paid-request path can immediately generate the same mixed set when
  the first-run flag is absent. The flag has a seven-day TTL and is refreshed by
  daily generation; this is not an irrevocable once-per-account lifetime bound.
- Generated cards are copied into the shared pool (best effort, video deduplication,
  nominal 500-entry cap), then delivered/cached for that user. This is shared
  reuse of personally initiated generation, not a separately scheduled fresh
  generation batch per language.
- **06:15 UTC:** pool/default audit uses deterministic keyword, age and media
  checks. **06:30 UTC:** shared-default selection scores pool entries by
  interactions and recency, tries to avoid yesterday's IDs, and selects a mixed
  3/3/4 set for each of the 20 supported languages. No model call is made by this
  historical selection task. English entries can fill gaps outside en/de; this
  does not translate them or make them native-language examples.

Twenty locale defaults therefore target **200 displayed slots**, with reuse and
possible shortfalls, and **zero new inference calls solely for their selection**.
Generating one fresh personal refresh in each locale is a different workload:
20 refreshes, 60 video + 60 wiki cards + 80 static tips, normally 160 logical
Mistral calls and 60 Brave searches. Actual volume depends on eligible users and
first-run events, not the size of the language list. No eligible-user count,
request logs, invoice or monthly production-spend total was established here.

## Cost baseline: known tariffs, unknown original spend

At the baseline revision, `backend/providers/mistral.yml` records supplier rates
of **$0.15/M uncached input**, **$0.015/M cached input**, and **$0.60/M output**
tokens. These are supplier catalog rates, not customer credit charges. Catalog
`per_credit_unit` includes a different commercial pricing layer; do not use it
as provider spend. These checked-in rates are the historical/as-of-repository
basis, not a fresh verification of today's external price sheet or alias target.

For aggregate metered token counts across all original logical roles and every
actual retry/fallback transport, the Mistral estimate is:

`C_M = (0.15 * I_uncached + 0.015 * I_cached + 0.60 * O) / 1,000,000`

Use actual fallback-provider tariffs where they differ. For perspective, exactly
1,000 uncached input + 200 output tokens cost **$0.00027** at these rates; this is
unit arithmetic, **not an assumed size or measured price of a historical call**.
Without the classifiers', writers' and validators' real token counts there is
no defensible exact dollar amount per original refresh.

The same historical `backend/providers/brave.yml` records the Search plan at
**$5/1,000 successful requests**, including video search, with **$5 monthly
credits** shared at account level. Thus 3 successful searches per personal refresh
have a **$0.015 gross catalog value before credits**, and 20 fresh refreshes have
a **$0.30 gross search value**. Net payment can differ with free credits, account
plan, failed requests, retries and other workloads consuming the same credits.
This discovery component was excluded from the frozen-source writer comparisons.
YouTube enrichment and Wikimedia requests lack monetary billing receipts here;
quota/API traffic and infrastructure cost must not silently be treated as a
measured zero-dollar total.

For N full successful original refreshes, before credits and other services:

`C_total_estimate = sum(C_M_refresh) + $0.015 * N + unmeasured_services`

Per admitted generated card is `C_total / admitted_video_and_wiki_cards`;
per displayed slot can be separately stated as `C_total / delivered_total_slots`.
For a single complete set those denominators are 6 and 10 respectively. At
20-locale scale, sum token counts per locale instead of assuming English token
length, equal cache hits or equal rejection rates.

## What earlier native receipts do and do not measure

Before the linked native follow-up, no inspected receipt exercised the **complete
original pre-Jev pipeline**, with its original three roles around video generation
and original wiki ordering. The new replay now exercises those historical paths
but yields incomplete sets. Original production spend and the cost/latency of a
successful original refresh remain **unmeasured**, not inferred from a later
writer-control arm.

The retained `logs/daily-inspiration-jev/d115-inspiration-holdout/receipt.json`
contains eight real direct Mistral writer responses, returned model
`mistral-small-latest`: **15,534 prompt tokens, 1,445 completion tokens**, with
estimated writer supplier cost **$0.00296382**. Its additional recorded Jev estimate
is **$0.00081795**, giving **$0.00378177** combined. The writer component averages
$0.0003704775 per one-card attempt in **that** fixture holdout. It is useful
observed Mistral usage but is **not the original architecture**: Jev source/copy
review remains, candidates are frozen, and original classifiers/validators/wiki
ordering are absent. The native alias response also does not prove immutable
Small 4 weights. The earlier 24-attempt paired summary's raw responses were lost;
its recorded $0.00757281 Mistral+Jev total is not recoverable original-native proof.

Likewise `d115-inspiration-real-facade.json` explicitly records
`daily-editorial-v4`: three videos, three wiki cards and static tips with Mistral
writing **after Jev introduction**. Yesterday's Gemini-only+Jev multilingual
control is another post-change control. Neither should be labeled the original
pre-Jev baseline or used to claim original production savings.

## Defensible paired historical benchmark without private writes

1. Load the exact historical generator, processor, validator, wiki generator,
   coherence and config modules at the baseline ref into an isolated benchmark
   namespace/environment. Hash every loaded file. Invoke generation functions
   directly, **never** the delivery helper, Celery task, pool/default services or
   real user history. Use an isolated public benchmark identifier and public
   topic lists; no account defaults or routing overrides are necessary.
2. Freeze a fresh public discovery corpus **before either arm writes**: Brave
   results, actual YouTube metadata/JPEGs, canonical Wikipedia lookup responses,
   local summaries and entity identities. Keep the original candidate lists and
   rejected items, not only Jev-approved winners. Patch retrieval I/O only. The
   historical classifier, selection prompt, lexical check, validator, fail-open
   outcomes, facade retries and writer-before-Wikipedia order remain intact.
3. Run identical locale/topic/count batches (3 + 2 for five cards per type and
   locale) for historical Mistral and the final Mercury/Jev pipeline. For one
   20-locale historical arm targeting 100 videos + 100 wiki cards, the normal
   successful-path count is **280 logical Mistral calls**: 100 classifiers,
   40 video-writer batches, 100 video validators and 40 wiki-writer batches.
   This is a workload expansion beyond the current paired writer-only experiment.
4. A faithful historical wiki writer chooses its own titles before retrieval.
   Freeze a canonical lookup catalogue and classify requests outside it as
   discovery misses; do not fabricate articles, silently remap identities or
   inject new source-grounding instructions. This yields a paired **topic/input
   workload**, not guaranteed identical final source IDs. Report source-match
   strata and discovery shortfalls separately. If identical article evidence is
   mandatory, add a separately labeled source-conditioned Mistral experiment;
   changing the old prompt/order makes it a counterfactual, not exact history.
5. Capture each native request/response, actual route/model, attempted/admitted
   counts, input/cached/output tokens, cost completeness and latency, including
   failures and retries. Record Brave cost separately, and distinguish current
   tariff repricing from any historical invoice. Review admitted output arm-blind
   against actual sources using the same multilingual policy/coherence/follow-up
   rubric, while retaining the historical gate's own decisions unchanged.
6. Report historical versus final total dollars per requested/admitted card and
   per complete 3/3/4 refresh, quality and abstention rates, source repetitions and
   20-locale aggregates. Separate discovery, classifier/decision, writing, review,
   image review and static-card costs. Keep any independent judging calls out of
   the product-arm bill. Native-speaker review remains a separate qualification.

This benchmark has not been executed. Existing receipts establish later writer
experiments; they do not supply the missing original baseline measurement.

## Opt-in full-refresh measurement harness

`backend/scripts/benchmark_daily_inspiration_costs.py` implements a bounded cost
replay, not yet executed against providers. Default `--mode both` launches fresh
original/current processes, each requesting one English and one Japanese full
refresh. Live discovery is independent in each setup; this measures full-refresh
cost rather than identical-source quality. Historical generation logic uses exact
old modules; wrappers and effective tariffs use the current runtime and are
hashed in receipts. Mistral is only the historical comparison.

Stage the following twelve files from `c94ebe85a14f87aa3223eacfe129aa85ec93d939`,
preserving repository-relative paths beneath `--historical-source-dir`:

```
backend/apps/ai/daily_inspiration/__init__.py
backend/apps/ai/daily_inspiration/category_age_policy.py
backend/apps/ai/daily_inspiration/content_filter.py
backend/apps/ai/daily_inspiration/feature_suggestions.py
backend/apps/ai/daily_inspiration/generator.py
backend/apps/ai/daily_inspiration/media_coherence.py
backend/apps/ai/daily_inspiration/schemas.py
backend/apps/ai/daily_inspiration/validator.py
backend/apps/ai/daily_inspiration/video_processor.py
backend/apps/ai/daily_inspiration/wiki_generator.py
backend/apps/ai/daily_inspiration/wiki_suggestions.py
backend/shared/config/blocked_content_keywords.yml
```

The harness embeds each file's SHA256 and rejects changes before native calls.
The host can enumerate `HISTORICAL_HASHES` from the script and stage each file
using `git show <BASELINE_REF>:<relative-path>`; the container needs no `.git`.
Use a directory mounted into the API container. Within an authorized native-test
lease/coordinator context, run:

```bash
python -m backend.scripts.benchmark_daily_inspiration_costs \
  --historical-source-dir /app/test-results/staged-original \
  --output-dir /app/test-results/d115-original-vs-current-costs
```

This is a dependency-free dry-run. Add `--execute` for provider calls. Optional
`--mode original|current`, `--languages en ja`, and `--max-seconds 600` bound the
work. The per-refresh deadline accepts 30–900 seconds; each setup process also
has a thirty-minute maximum. The harness does not acquire or alter runtime leases.
It hashes the current decisions, writer, generator, wiki generator, video processor,
validator, thumbnail reviewer, writer config and `llm_utils` before initialization.
Optional `--reviewed-source-manifest <json>` compares a `source_sha256` (or
`current_source_sha256`) mapping against recognized filenames before any native
calls. A mismatch aborts; receipts list matched and unreviewed files explicitly,
so a partial manifest does not masquerade as full source review.
Resume skips completed refreshes and archives incomplete receipts before retrying.
Historical imports fail if any daily module is already loaded, preventing old/new
module mixing. A network guard blocks product/account/pool reads and all writes
except inference and Google OAuth; public sources and Vault reads are allowed.
No delivery helper or task runs, and no account routing preference changes.

`<mode>/<locale>.json` retains public native requests/responses, observed models,
logical calls, source identities, transport failures, per-attempt facade tariff
telemetry, actual Jev source/copy/image accounting and wall-clock duration. Auth
headers, query credentials and Vault payloads are excluded; thumbnail payloads
become hashes/byte lengths. Four static tips remain when generated cards fall
short; receipts explicitly identify incomplete 3/3/4 sets. Cost separates known
inference, gross Brave discovery, per-admitted-generated-card and per-delivered-
slot amounts. Current source-selection Jev costs are included, unlike the earlier
frozen-source writer comparison. Native payload usage is not added a second time
to facade/Jev accounting. All-transport spend remains incomplete because canceled
or internally retried requests can lack billed usage. Include `history/` when
totaling experimental spend after interrupted retries. `summary.json` contains
the latest refresh outcomes and costs.

Nine offline tooling tests verify native-write protection, historical identity,
loaded-package rejection, process mode isolation, no-call dry-run and deduplicated
cost arithmetic, plus reviewed-current-source mismatch rejection. They do not
certify live provider availability or model weights.

### Background public-default review is an additional current cost

The primary full-refresh receipts measure **personal generation only**. Current
`default_inspiration_tasks._review_pool_entries` additionally submits external pool
cards (including copy/follow-ups and actual video thumbnail review) to Jev before
shared-default selection. It fetches up to 50 pool records per available language,
reviews English once and reuses its result for English selection, and reviews
other available language pools. Static feature tips bypass that paid gate.
Candidate counts, packed text batches, surviving video images, failures and
effective tariffs determine the bill. Twenty display slots/locale do not imply
twenty fixed-size review calls, and 200 displayed defaults do not establish the
number of candidates reviewed. This background selection had **zero inference
cost in the historical setup**. The complete scheduler/pool-volume cost remains
unmeasured; the harness separately measures a bounded public-record sample.

By default, after each current personal refresh receipt is saved, the harness
revalidates only its newly generated public video/wiki cards (at most six) through
the exact current `_review_pool_entries` function. It AST-extracts that function
without executing the task module, initializing Celery, reading a database or
performing any selection/persistence. The namespace supplies only its actual
`json`, `review_candidates`, `editorial_review_digest` and `canonical_wiki_review_source` dependencies. Receipt
provenance includes the full source-file hash, function-source hash and normalized
function-AST hash. Pool conversion follows the public fields used by `add_to_pool`,
preserves source edition, passages, metadata and thumbnail identity, and discards
unknown/private fields. IDs are synthetic benchmark identifiers.

Separate `current-pool-review/<locale>.json` receipts have their own active native
accounting context and contain input/output counts, public records, actual Jev
text/image request/response/usage, wall-clock duration and known cost per input
entry and per retained entry. No pool-review amount enters the personal-refresh
ledger. There is no new Brave/Wikipedia discovery in this stage; actual thumbnail
pixels are fetched/reviewed through the current gate. The default stage deadline
is 180 seconds, configurable with `--pool-review-max-seconds` (30–300). Disable
this stage with `--no-measure-pool-review`. The existing thirty-minute maximum per
setup still applies. Completed pool samples resume independently; incomplete
receipts are archived before retry. Offline tests cover exact-function isolation
and privacy-preserving public row conversion in addition to the native-write guard.

For an honest total daily before/after comparison use:

`original_daily = sum(original_personal_refresh_costs) + original_other_service_costs`

`current_daily = sum(current_personal_refresh_costs) + current_defaults_Jev_text_and_image_cost + current_other_service_costs`

Each personal-refresh term already includes its own discovery and gates. The
additional defaults term requires actual pool-volume telemetry or a separate
full-volume source-only replay; this small fresh-card sample supplies a measured
revalidation unit cost, not an assumed per-user default cost. Do not invoke
pool-write tasks to obtain it. Report the remaining volume uncertainty, account
credits, actual refresh counts and remaining service costs before describing a
saving as total public daily production spend.
