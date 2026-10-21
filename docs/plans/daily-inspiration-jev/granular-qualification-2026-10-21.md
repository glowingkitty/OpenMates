# Granular inspiration review and historical cost comparison

The approved follow-up implements per-field Jev grounding/language decisions,
source-specific follow-up decisions and repair of only unresolved source IDs.
The original pre-Jev/pre-Mercury workflow, not the later Gemini-only plus Jev
control, is the cost baseline. Native qualification and final cost results are
recorded below; no production promotion is inferred from unit tests.

**Decision:** retain the requested Mercury retry chain as the dev candidate.
Its 34 admitted fresh cards had no material findings in the blinded automated
review; Gemini-only had five material findings among 39. Production qualification
remains open: Jev still withholds many faithful translations and admits a known
Turkish causal-role regression. The end-to-end cost replay establishes no saving
over the original architecture and neither setup completed a personal refresh.

## Implemented workflow

1. Recent-topic or generic seeds drive Brave video discovery and localized
   Wikipedia discovery. Deterministic identity, age, audience and content checks
   run before paid writing. Wikipedia summaries and canonical identities are
   fetched before copy is generated.
2. Pinned Jev 1.14 evaluates source policy, educational fit and category. Videos
   also require an actual bounded JPEG-pixel decision. A failure or uncertainty
   withholds the source; a text-only result cannot approve an image.
3. Mercury 3 LOW writes titles, phrases, introductions and three follow-ups for
   the approved sources, using public source passages rather than private history.
4. Jev gives every generated field its own grounding decision and requested-
   language decision. Each follow-up also gets its own source-relevance decision.
   Policy and subject coherence remain independent checks. Translations, faithful
   paraphrases, metaphors and open questions about explicit source concepts are
   allowed. New specific facts, absent scenarios and changed qualifiers, entities,
   causal roles or temporal status are off-source even if plausible.
5. Approved card objects are retained by canonical source ID. The second Mercury
   request asks only for unresolved source IDs and receives bounded machine
   rejection codes. Gemini 3.5 Flash-Lite handles the final unresolved request.
   Every repaired draft is reviewed again; approved cards cannot be overwritten.
   Maximum three logical writing attempts, thirty seconds each, no nested retries.
6. Four localized static feature tips require no inference. Complete personalized
   3-video/3-wiki/4-tip sets replace personal delivery; otherwise existing recovery
   remains. Public pool/default selection performs background Jev review, and
   anonymous requests use cached results or localized static recovery without
   triggering provider calls. Twenty feed languages do not imply twenty new
   generation jobs per day.

Source IDs, rejection codes and partial repair metadata remain internal. Video
assembly binds a repair to its approved ID rather than its compacted row position.
Review proof is `daily-editorial-v6`; public cache version is `v15`, so an older
video or Wikipedia approval cannot satisfy the stronger gate. Dynamic wiki proof binds the actual article identity, source edition and fetched passage as well as all generated copy. Missing source evidence is withheld; localized static recovery remains available. Existing encryption and ordinary
account/chat routing are unchanged.

## Review standard and qualification

The prior rubric alignment is documented in
[rubric adjudication](rubric-adjudication-2026-10-21.md). Of 23 selected historical
cards, 18 remain material rejects, four have minor wording advisories and one
Vietnamese causal-agent interpretation remains unresolved. One formerly material
Swedish terminology finding was explicitly downgraded. These labels do not turn
an unsupported fact into a factual falsehood or constitute native-speaker sign-off.

The fresh text controls contain 120 cases: sixty matched allow/reject pairs across
twenty languages, using three disclosed semantic templates. The image controls
contain 100 translated panels from five disclosed templates, including matched
honest/deceptive imagery with identical neutral metadata and honest expressive
style controls. These are controlled translated panels, not one hundred independent
real-world thumbnails. Their renderer records fixture/case/image/font hashes,
actual glyph coverage, RAQM shaping and full text bounds; representative Arabic,
Hindi, Thai, Japanese and Korean panels were visually inspected. Native execution
requires the exact verified JPEGs and refuses unreadable or altered panels before
paid requests.

The paired writing comparison uses five fresh topics (aurora, paper recycling,
seed dispersal, architectural arches and circadian rhythm), excludes all 147 prior
source identities, and randomizes provider order deterministically. Sources are
approved once and frozen across arms; every new draft still gets fresh final Jev
review. Source shortages, unavailable providers, false admissions and conservative
false rejections are reported separately. Known regression controls are separate
from fresh writing. Labels and blinded reviews remain automated; native-speaker
approval is not fabricated.

Generation-admission yield is an efficiency measure. The earlier 95% first-draft
and 99% final-yield targets remain visible in historical results but are not
standalone safety gates. Publication qualification depends on source-faithful,
correct-language, policy-safe accepted cards and complete localized fallback
behavior. A finite green sample does not prove a zero population error rate.

## Historical baseline and rate basis

The exact original implementation is
`c94ebe85a14f87aa3223eacfe129aa85ec93d939`. Its normal successful fresh set used
three Mistral channel classifiers, one video writer, three per-video validators
and one Wikipedia writer: eight logical Mistral calls, three Brave searches, six
generated cards and four static tips. The video validator failed open on errors;
wiki copy preceded summary retrieval; thumbnails and all follow-ups lacked the
new review. Original shared public default selection used zero inference.

The opt-in full-refresh replay stages twelve byte-verified original files and
runs original/current setups in separate processes. It records real logical and
native calls, actual models, token/cache/reasoning usage, source shortages,
latency and current tariff snapshots. English and Japanese discovery is live and
independent, so this is not a same-source quality experiment or a reconstruction
of a historical invoice. Current provider wrappers and alias targets are explicit
replay inputs. Current pool revalidation is metered in a separate receipt using
only newly generated public cards; it is not charged a second time to the personal
refresh ledger and does not read or modify a real pool.

Official rate pages were checked on 2026-10-21:

| Supplier | USD per million input / output tokens | Basis |
| --- | --- | --- |
| Original Mistral Small 4 | $0.15 / $0.60; cached input $0.015 | [Mistral pricing](https://docs.mistral.ai/inference/pricing) |
| Mercury 3 launch offer | $0.10 / $0.35; cached input $0.01 | [Inception launch terms](https://www.inceptionlabs.ai/blog/introducing-mercury-3) |
| Mercury 3 regular | $0.20 / $0.70; cached input $0.02 | [Inception launch terms](https://www.inceptionlabs.ai/blog/introducing-mercury-3) |
| Gemini 3.5 Flash-Lite | $0.30 / $2.50 | [Google pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| Jev 1.14 | $0.042 input; output free | [TypeSafe models](https://docs.typesafe.ai/models) |

[Brave Search](https://brave.com/search/api/) costs $5 per thousand requests before
its shared monthly credits: three successful searches have a gross catalog value
of $0.015 per fresh personal set. This is separate from inference. Supplier
estimates precede credits and exclude unmeasured infrastructure, YouTube/Wikimedia
charges and unknown usage on failed transports. Mercury launch and regular-price
sensitivity must be stated separately. Original production spend, actual eligible
user volume and account-level invoices are unavailable; no monthly saving is
invented from the number of languages.

## Verification and measured results

The final application is `76419cba88796db635c80e0c5218ece0783a581c`, deployed to
dev with all seventeen affected backend consumers healthy (`docker-78d5bd31`)
and both Vercel projects successful. The final focused local suite passed **163
tests**; scoped lint passed. Isolated CI passed the Jev boundary
([39573343486](https://github.com/glowingkitty/OpenMates/actions/runs/39573343486)),
public-feed browser flows
([39574090167](https://github.com/glowingkitty/OpenMates/actions/runs/39574090167)),
corrected writer/Google conversion
([39579556331](https://github.com/glowingkitty/OpenMates/actions/runs/39579556331))
and source-bound generator integration
([39582942072](https://github.com/glowingkitty/OpenMates/actions/runs/39582942072)).
The earlier boundary/browser candidates contain the same relevant source; the
later writer fix changes request construction only. Evidence commands were run
and browser recordings uploaded. Focused checks cover granular fail-closed decisions, source-bound repair union/order, malformed
neighbors, cancellation/deadlines, source/pixel proofs, localized static delivery,
fresh-source exclusions and protected historical replay.


### Controlled native results and language precision

| Control cohort | Native result | Limit |
| --- | --- | --- |
| Historical regressions plus original Japanese paraphrase | 19/23 scored labels matched; one automated-label negative admitted, three positives withheld, one unscored uncertain case | 24 total; known regressions, not fresh holdout |
| Twenty-language matched text controls | All 60 negatives withheld; 10/60 positives admitted | Three disclosed semantic templates; translated copy over English evidence |
| Twenty-language thumbnail controls | 100/100 matched: 60 honest accepted, 40 deceptive rejected | Five rendered-panel templates, not 100 natural thumbnails |

The original valid Japanese paraphrase was accepted. An independent source-only
review retained the Turkish reef/colony role reversal as material; Swedish
technical wording was allowed and two Arabic/Thai wording cases remained
uncertain. No labels were silently changed after observing decisions. A bounded
audit of fifteen multilingual positives found eleven withholds with title-language
blockers despite recognizable translated headings. Native-speaker sign-off remains
unavailable. This is a substantial precision limitation even though all sixty
controlled negatives were withheld.

Two exploratory 24-case language pilots (explicit language anchoring, and separate
generated-only language evidence) each accepted eight of twelve positives rather
than two, but each admitted a known English-introduction negative. Neither pilot
was adopted. Their requests/results remain separate from the deployed setup and
final paired comparison; confidence thresholds were not lowered.

### Retry integration correction and frozen sources

The first paired run exposed a request-format bug in the new repair instruction:
Google extracts the initial system message and interpreted a trailing system
message as a model turn, returning HTTP 400. The corrected writer places the
trusted repair instruction in the initial system prompt, retains original user
source passages, and never ends a repair request with a system/model turn. The
32-case writer suite includes Google's actual message conversion, mutation
isolation and all retry/fallback paths.

The interrupted run and every paid receipt were retained. Source collection had
completed all 200 slots: 168 eligible and 32 eligibility shortfalls. Only the
source snapshots and frozen JPEGs are reused in a new output directory, with
byte-verified provenance; old writer rows/drafts are not copied. Both writer arms
produce new drafts and undergo fresh final review. Source shortfalls stay frozen.

Initial exact-timing historical replay had eight cancellations near the original
five-second cap and no complete sets. Initial current costs include the now-fixed
Google repair failures and are not the final cost basis. Native Jev spend must be
counted once per actual response: shared accounting-list slices overlapped during
concurrent images and raw summaries omitted supplier charges. Corrected companion
analysis preserves every raw receipt and separates unknown failed usage. A
supplementary original-only replay with a declared thirty-second caller cap keeps
the historical modules, roles, prompts and model; it is a timing sensitivity, not
the original production timing or invoice.

### Completed fresh paired comparison and blinded review

Both arms completed all **78 nonempty writer batches** across twenty locales.
The planned 400 slots contained 336 eligible locale/source slots (168 per arm)
and 64 paired eligibility shortfalls (32 per arm). The shared cohort represents
128 distinct source identities, so translated or repeated sources are not
independent real-world discoveries. Provider order was randomized before writing;
all 147 source identities from the previous day's run were excluded.

| Result | Mercury twice, Gemini fallback | Gemini-only, up to three attempts |
| --- | ---: | ---: |
| First-draft admissions / eligible | 15 / 168 (8.9%) | 21 / 168 (12.5%) |
| Final admissions / eligible | 34 / 168 (20.2%) | 39 / 168 (23.2%) |
| Complete writer batches | 9 / 78 | 10 / 78 |
| Median / p95 batch latency | 12.60s / 20.67s | 6.11s / 9.67s |
| Admitted cards with material findings | 0 / 34 | 5 / 39 |
| Additional minor / uncertain admitted cards | 0 / 0 | 3 / 1 |
| Strictly clean under automated review | 34 | 30 |

All 73 admitted cards and two sampled withheld drafts per locale (40 total) were
mixed into three randomized packets hiding provider and admission status. Every
case received a source-only review. All 21 non-allow flags received a second
source-only adjudication; labels were frozen before the origin key was read.
All initial labels were retained. The audit records packet/review hashes,
field-level reasons and unblinding provenance in
[blinded review](blinded-review-2026-10-21.json).

Gemini's five admitted material findings change an arch modifier into a dam
subtype (Arabic), reverse clock/rhythm control (German), add school newness
(Vietnamese), replace a driving role with monitoring (Russian), or present a
2022 sighting as recent (Dutch). Its uncertain Turkish case concerns branded
source eligibility, not a demonstrated copy-language error. These are automated
interpretations of the supplied source, not native-speaker certification or
claims that every unsupported detail is factually false in the real world.

Of the sampled withholds, 28 were allowed by independent review, four had minor
advisories, six were material and two were uncertain. This is a deliberately small
sample of rejected drafts, not a population false-rejection estimate. Together
with the matched positive controls, it confirms a precision problem. Title-
language checks failed or abstained on 285/431 Mercury reviewed drafts and
293/449 Gemini reviewed drafts; repeated repairs are included in those counts.
The exact internal cause of this field-binding/language failure is not proven.

Both arms had zero source-identity or required-field structure errors. Word- and
sentence-quota diagnostics flagged eleven Mercury and nineteen Gemini admitted cards;
these are separate from material grounding/language findings. Independent Jev
locale assessment passed all 34 Mercury cards and 38/39 Gemini cards, further
showing that one automated pass is not an independent quality guarantee.

The paired costs below include every writing attempt and unique production Jev
review. Eleven unusable Mercury HTTP-200 responses lacked facade telemetry but
had native usage: recovering that usage adds $0.01930285 at launch rates, counted
once. One canceled Mercury request remains unpriced. Google input uses uncached
upper estimates where cache telemetry is missing. Shared source acquisition and
the separate locale assessment are excluded from these writer-arm figures.

| Paired writing/review cost | Mercury chain, launch | Mercury chain, regular reprice | Gemini-only |
| --- | ---: | ---: | ---: |
| Estimated total | $0.345598104 | $0.503063644 | $0.437491362 |
| Per admitted card | $0.01016465 | $0.01479599 | $0.01121773 |
| Per strictly clean reviewed card | $0.01016465 | $0.01479599 | $0.01458305 |

Mercury used 153 primary/retry requests and 71 Gemini fallbacks; Gemini-only used
220 Gemini requests. Eleven Mercury responses were unusable by the writer and
one timed out; Gemini had no recorded writer errors. The recovery chain retains
valid source-bound cards while processing the remaining identities. Actual
responses confirmed Mercury 3, Gemini 3.5 Flash-Lite and Jev 1.14.0. Full usage,
native-response recovery and immutable receipt hashes are in
[paired aggregate](granular-paired-aggregate-2026-10-21.json).

Mercury's launch-price advantage is temporary: its regular-price workload and
clean-card estimates are higher than Gemini's, and its median batch is
roughly twice as slow. Gemini's five material admissions rule out selecting it
on speed or admission count alone. Neither paired writer estimate includes the
whole daily workflow or proves a saving against the original architecture.


### Final historical-versus-current cost replay

The corrected writer ran all four Gemini fallback calls successfully (zero Google
ClientErrors), with observed models `mercury-3`, `gemini-3.5-flash-lite` and
`jev-1.14.0`. Current generation made twelve writing calls and sixty-three native
Jev requests across two refresh attempts. Details and immutable receipt hashes:
[full-refresh cost aggregate](full-refresh-costs-2026-10-21.json).

| Observed attempt | Video / wiki / static output | Inference estimate | Gross search | Total estimate |
| --- | --- | ---: | ---: | ---: |
| Original architecture, declared 30s cap, EN | 1 / 2 / 4 | $0.00390693 | $0.015 | $0.01890693 |
| Original architecture, declared 30s cap, JA | 0 / 2 / 4 | $0.00463938 | $0.015 | $0.01963938 |
| Current Mercury chain, launch pricing, EN | 1 / 0 / 4 | $0.01353472 | $0.015 | $0.02853472 |
| Current Mercury chain, launch pricing, JA | 0 / 0 / 4 | $0.015628986 | $0.015 | $0.030628986 |

Neither setup assembled a complete 3-video/3-wiki/4-tip refresh. These are candidate
outputs; partial sets are not proof of successful personal replacement. The old
architecture averaged **$0.019273155 per attempt** in the declared 30-second
sensitivity. Current averaged **$0.029581853 at Mercury launch rates**, or
**$0.034852118 repricing the same tokens at regular Mercury rates**. This is not a
like-quality saving or a historical invoice. Exact historical five-second timing
remains separately reported above; it incurred unknown canceled-request spend.

| Component across two attempts | Original architecture / 30s | Current launch | Current regular reprice |
| --- | ---: | ---: | ---: |
| Mistral writing/classification/validation | $0.00854631 | — | — |
| Mercury writing/recovery | — | $0.01054053 | $0.02108106 |
| Gemini fallback writing estimate | — | $0.00789100 | $0.00789100 |
| Jev source, copy and actual-image gates | — | $0.010732176 | $0.010732176 |
| Six gross Brave requests | $0.03000000 | $0.03000000 | $0.03000000 |
| Generation attempts | **$0.03854631** | **$0.059163706** | **$0.069704236** |

The old replay admitted five generated cards, current one. Including both
successful and unsuccessful attempts, gross cost per admitted generated card was
$0.007709262 old versus $0.059163706 current at launch rates. Admission is not
independent factual quality, so these denominators cannot establish an equal-
quality value comparison. Static tips require no marginal inference.

The additional shared-pool sample reviewed one current card for **$0.00014595**
and retained none. The other locale had no external cards and made no review
calls. This does not estimate a complete daily scan or a per-user pool charge.
Cached page reads make no paid model calls in either architecture.

Google supplied tokens but omitted cache-read telemetry in four records; the
uncached tariff amounts are finite supplier upper estimates, not precise net
spend. Jev is counted once per real native send, even where concurrent raw
accounting slices overlap. Credits, invoices, invisible SDK retries, actual user
volume and infrastructure/YouTube/Wikimedia charges remain unmeasured.

### Qualification decision and next bounded check

The requested implementation, measurements and scoped dev deployment are
delivered. The Plan remains active for production qualification: passing unit,
CI and static-recovery checks cannot override the failed positive controls,
known causal-role miss or incomplete personal-refresh samples. No quality
criterion was waived and no production deployment was performed.

The next useful experiment is a scalar, one-field-at-a-time Jev language check
against the pinned positive/negative controls, isolating generated text from
English source metadata and other questions. This tests a specific binding/task-
interference hypothesis; it is not a proven fix. Preserve the wrong-English-intro
negative and the causal-role controls, and do not lower confidence thresholds.
Only after those pass should a fresh multilingual writing cohort, natural-
thumbnail holdout and complete personal refresh be repeated. Obtain targeted
native-speaker review for ambiguous wording and confirm clean-card/full-set
costs before any production decision. The two failed exploratory pilots are
evidence against adopting a broad language-prompt relaxation.
