# Granular inspiration review and historical cost comparison

The approved follow-up implements per-field Jev grounding/language decisions,
source-specific follow-up decisions and repair of only unresolved source IDs.
The original pre-Jev/pre-Mercury workflow, not the later Gemini-only plus Jev
control, is the cost baseline. Native qualification and final cost results are
recorded below when complete; no production promotion is inferred from unit tests.

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

Pending native results and isolated CI completion. Focused local checks currently
cover granular fail-closed decisions, source-bound repair union/order, malformed
neighbors, cancellation/deadlines, source/pixel proofs, localized static delivery,
fresh-source exclusions and protected historical replay.
