# Multilingual inspiration and thumbnail qualification

The approved follow-up replaces lexical media overlap with Jev semantic checks,
requires source-specific follow-ups, localizes static recovery in all twenty feed
languages, screens actual video thumbnail pixels, and compares the requested
Mercury/retry/Gemini chain against Gemini-only before the deployment decision.

## Implementation and verification

Dev candidate: `1c753c461f9b97e1bc1e4c61c1d06b431e19bae1`.
The setup-gated runtime operation `docker-2074e2a0` applied additive review fields
before recreating the API and seventeen affected backend consumers; all were healthy.
The candidate frontend deployment completed successfully. The scoped deadline and
search-country correction is `785f15a0a9237a96640927d1b5f6cf1e2d6c4005`; runtime
operation `docker-434fef82` completed with all seventeen consumers healthy, and
that frontend deployment also completed successfully.

- 148 focused inspiration cases passed after the deadline/search corrections; 19 frontend unit cases passed.
- The expanded writer/adapter CI run passed 54 cases, including every new timeout
  case. Two pre-existing Google usage-normalization assertions failed: one expects
  inferred reasoning tokens without a reasoning-billing tariff, the other expects
  missing output to remain null where existing normalization emits estimated zero.
  The timeout patch does not participate in these mismatches. Observed Gemini
  responses in this run report no reasoning tokens; cache input is retained for
  the price comparison, and all supplier amounts remain estimates.
  [Adapter CI receipt](https://github.com/glowingkitty/OpenMates/actions/runs/39483991623).
- [All fourteen native search-locale enum cases](https://github.com/glowingkitty/OpenMates/actions/runs/39483183607) passed in isolated CI.
- [Isolated native decision boundary](https://github.com/glowingkitty/OpenMates/actions/runs/39471945379) passed.
- [Component navigation](https://github.com/glowingkitty/OpenMates/actions/runs/39471951724) passed both cases, including Japanese card/source-edition identity.
- [Public feed](https://github.com/glowingkitty/OpenMates/actions/runs/39474468256) passed German and Japanese navigation/reload and withheld-inventory recovery; all twenty endpoint locales returned ten correctly labeled cards.
- CI source: `0bc10e895f172067491e06ecf6128d9ec697d4fa`; harness: `d2733343be7dbfa5cfcd2d8849f8742956f8b6aa`. Its task application files match the published candidate; later harness/report changes do not alter application behavior.

The shared YAML catalog now supplies all fifteen backend static cards across the
21 UI registry locales (including Hebrew), with a backend-only compiled JSON
artifact. The feed's twenty supported languages no longer borrow relabeled
English pool copy. Static Wikipedia cards retain their verified English article
identities and declare the source edition separately from translated card text.

Jev separately reviews policy, factual support, subject coherence, every follow-up's
explicit source concepts and the requested copy language. Japanese and other
unspaced scripts have no lexical overlap gate. Public video defaults carry a
versioned content hash bound to the reviewed copy, language, metadata and thumbnail
identity; anonymous page loads make no paid model calls. Semantic uncertainty
withholds publication without deleting historical pool content.

Actual bounded JPEG pixels go to pinned Jev 1.14 through direct TypeSafe. Missing,
failed or uncertain visual review withholds the video; no text-only fallback can
approve it. Expressive faces/arrows/legible titles alone do not imply deception.
Image support is [experimental](https://docs.typesafe.ai/images); this reviews a
thumbnail snapshot and source metadata, not watched video content or later edits.

## Predeclared comparison

Both writer arms use the same frozen real public source passages and thumbnail
snapshots: five new topic/source pairs per locale, video and Wikipedia, twenty
locales, targeting 200 cards per arm (400 total). Production three-card and two-card
batches exercise the actual assembly, bounded recovery and final Jev admission paths.
Initial source eligibility/ranking and thumbnail approval are obtained live once
and held fixed across arms. Final draft policy, grounding, coherence, follow-ups
and language are reviewed live for every attempt; final video admission can also
re-review the same frozen JPEG pixels. This isolates writing from source-review variation
and is not a benchmark of complete production discovery or candidate ranking.
The Mercury arm is Mercury 3 LOW, one Mercury retry, then Gemini 3.5 Flash-Lite;
the control allows up to three Gemini 3.5 Flash-Lite attempts. Account/chat defaults
are unchanged. Random topic ordering is seeded identically across paired arms.
Arm order is fixed (Mercury then Gemini), not a randomized crossover. A Mercury
fallback can warm a subsequent Gemini request; observed cache use and an uncached
price sensitivity are reported rather than claiming an unbiased production bill.

Retrieval/source eligibility is evaluated before selecting snapshots and retained
separately from writer cost. Wikipedia fallback queries stay on the target edition;
video retrieval locale is recorded without claiming verified spoken language.
Thirty-four holdout admission controls include Japanese semantic paraphrase and
mismatch, a German bridge/wind follow-up drift, policy/grounding/injection cases,
and five image controls. Matched astronomy and clinical-image pairs have identical
neutral metadata; only pixels distinguish educational titles from conspiracy or
miracle-cure claims. The ordinary image is an actual public YouTube thumbnail.

The proposed decision gates remain: no known admitted material unsupported claim,
policy violation or invented source; at least 95% acceptable first drafts and 99%
acceptable completed chains. Source shortages and outages remain separate from
writer failures. Finite format diagnostics do not substitute whitespace counts
for Japanese/Chinese/Thai segmentation. All-field language assessments and an
independent arm-blinded content review are automated, not native-speaker approval.

The independent review anonymizes every admitted card and its exact source
passage, hiding provider identity, admission scores and metrics. Codex reviewers
check meaning, factual premises, source scope and language; the parent adjudicates
material flags against the full card context before reading the provider key.
Context-resolvable ellipsis and open questions about explicit source concepts are
not automatically hallucinations. Minor grammar, retained source-title wording and
finite format differences are reported separately. This is automated review, not
human or native-speaker sign-off.

Native requests, observed model identities, every draft and Jev decision, actual
usage, hashes and latencies are retained in the persistent test-results mount.
Resuming archives incomplete receipts instead of overwriting billed attempts.
Supplier prices are estimates from observed usage and the repository tariff;
missing telemetry is flagged rather than represented as an exact bill. Estimates
exclude provider credits and do not represent out-of-pocket spending. Source
retrieval/approval, exploratory runs and independent review are outside the paired
writer-and-final-admission totals.

## Live controls and discovery

The holdout admission controls scored **33/34**, including **5/5 visual controls**.
The image pairs correctly allowed the educational versions and rejected the
flat-earth/NASA-deception and miracle-cancer-cure versions with identical neutral
metadata. This establishes that actual pixels influenced admission, rather than
only titles or descriptions.

The sole incorrect control was a valid Japanese paraphrase conservatively withheld:
semantic coherence was `coherent` at confidence 0.97 and follow-ups `relevant` at
0.91, while grounding confidence was only 0.31. The Japanese lexical-overlap bug is
fixed; this remains a distinct grounding false negative. Thresholds were unchanged.
No unsafe holdout was admitted.

The first end-to-end pilot exposed source-review variation: a previously approved
video received low policy confidence on re-review, so one writer was never called.
The paired comparison therefore freezes the initial live source approval, rather
than counting that variation as a writer failure. A subsequent two-slot pilot gave
Mercury-chain 1/2 final admissions and Gemini 2/2; these pilots are exploratory and
excluded from the qualification sample.

Live Brave requests exposed unsupported language codes (`zh`, `pt`, `id`, `no`)
and countries (`vn`, `th`, `cz`). The implementation maps language codes to Brave's
supported values and uses `all` for unsupported countries, retaining the language
filter. Fourteen focused enum regressions cover these cases and optional locales.

The initial source corpus obtained **183/200** requested source contexts. Fifteen
video shortages are filled using already approved public metadata and verified
JPEG snapshots from the same predeclared query-slot index in another locale; no writer outputs were
consulted when selecting donors. Two Wikipedia shortages use authoritative
Wikidata sitelinks plus matching real Japanese/Chinese page summaries and fresh
native Jev source gates (`ja:受粉`, `zh:传粉`, both Q134624). These seventeen
backup slots are explicit in provenance. This is query-slot matching, not human
semantic validation: polysemous queries produced some different educational topics
(for example Vulkan graphics and fear-of-success content in a gear query slot).
Initial source admission was first-eligible rather than full production top-candidate
selection. These limitations affect retrieval/topic conclusions, while each paired
writer still receives identical actual evidence. Video spoken language remains
unverified.

The initial five-second writer run was stopped after 63 paired batches per arm:
153 slots per arm, Mercury-chain 32 first-draft / 126 final admissions and Gemini
107 first-draft / 132 final admissions. These are exploratory results, not the final
provider comparison. Raw errors revealed that the shared preprocessing adapter
canceled many Mercury requests after five seconds despite the writer's outer
thirty-second allowance. Canceled requests often have no billable usage receipt;
known supplier estimates can materially undercount that exploratory spend.

The correction adds an explicit, finite single-attempt allowance of at most thirty
seconds, usable only when facade retries are disabled. It bounds provider setup and
the request; ordinary preprocessing retains its existing five-second request and
twelve-second total limits. The requested Mercury/Mercury/Gemini chain remains at
most three writing attempts. This changes a demonstrated timeout defect rather than
loosening any editorial decision.

The final controlled comparison uses all **200 source contexts (147 distinct IDs:
47 videos and 100 Wikipedia articles)** and completed **400 fresh copy slots**. It
reuses source passages and JPEGs but no writing results from the five-second run.
Exploratory runs, earlier partial batches and their costs remain separate from the
final comparison. An initial blinded review of 153 exploratory admitted cards found
six material source/meaning errors after adjudication; those observations are not
counted as final-copy review results.

Two supplemented Wikipedia snapshots initially omitted the cached `approved` row.
Both Chinese writer arms stopped before their first call; the missing field was
restored solely from the stored successful native candidate evidence and fit/category
decisions, retaining byte-exact originals and repair hashes. All 200 snapshots then
passed structural validation. The skipped Chinese batch was replayed with both writers. Both completed; its
zero-call harness errors are archived and excluded from writer-failure rates.

## Paired result and deployment decision

**Neither setup qualifies for production.** Retain the requested Mercury 3 LOW →
Mercury retry → Gemini 3.5 Flash-Lite chain on dev while preserving the stricter
Jev gates and localized static recovery. The implementation and the comparison
are complete; the quality qualification remains failed. Do not promote a provider
on cost or inventory admission alone.

| Observed result | Mercury/Mercury/Gemini + Jev | Gemini writing only + Jev |
| --- | ---: | ---: |
| Requested slots / completed batches | 200 / 80 | 200 / 80 |
| First-draft Jev admissions | 110/200 (55%) | 112/200 (56%) |
| Final Jev admissions | 165/200 (82.5%) | 150/200 (75%) |
| Full batches | 49/80 | 42/80 |
| Material errors among final admitted cards, blinded adjudication | 12/165 (7.3%) | 7/150 (4.7%) |
| Additional uncertain cards | 1 | 3 |
| Batch latency, median / p95 | 16.0 / 24.8 seconds | 6.6 / 10.3 seconds |
| Known writer + final Jev supplier estimate, before credits | $0.2412 | $0.3733 |
| Same usage with observed cache reads priced as ordinary input | $0.2523 | $0.3777 |

These are admission rates, **not independently proven correctness rates**. All
315 final admitted cards were reviewed anonymously, with material findings
adjudicated before unblinding. Nineteen cards retained material findings; four
additional cards remain uncertain and need native adjudication. Errors include
broadened entity qualifiers, changed biological roles or causal order, absent
follow-up scenarios, untranslated English copy and one future sequence described
as already finished. Some facts may be true outside the supplied passage; the
qualification rule requires actual supplied evidence. Neither arm met the zero
known material admissions, 95% first-draft or 99% final targets. No invented source
identity or structural failure was observed in either arm.

The Mercury chain's 165 final cards were written by Mercury in 117 cases and its
Gemini fallback in 48. Its twelve material cards include seven Mercury outputs
and five fallback Gemini outputs. This is a chain comparison, not twelve errors
attributable solely to Mercury. Eighteen of 136 Mercury calls returned provider
errors, including eight first attempts; no Gemini transport errors were recorded.
The writer made 183 total attempts in the Mercury chain and 190 in the control.
The thirty-second allowance fixed premature cancellation, but did not eliminate
provider failures or editorial rejection.

Japanese final admissions were 10/10 for the Mercury chain and 8/10 for the Gemini
control, with no material Japanese finding in the blinded sample. This supports
removal of the lexical gate; it does not erase the separate valid-paraphrase
false rejection in the grounding control or constitute native-language sign-off.
The additional all-field language probe flagged one Mercury-chain card and four
Gemini cards. Format diagnostics flagged 54 and 60 final cards respectively;
these include brevity/sentence-format differences and are separate from material
source/language adjudication, not silently counted as correctness passes.

Mercury admitted fifteen more cards at roughly 35% lower observed supplier cost;
Gemini was faster and had fewer material findings in this sample. The corpus has
reused sources across languages, only ten slots per locale and fixed arm order.
It does not establish a definitive quality winner. Cache sensitivity preserves
the observed price ordering, but neither amount is a verified invoice. Writer
usage was present in every attempt receipt, yet incomplete in 65/183 Mercury-chain
and 182/190 control attempts; failed native requests can omit billable tokens.
Observed Mercury output includes reasoning tokens, while the Google responses
contain no reported reasoning tokens. Missing accounting fields and the two
pre-existing accounting test failures limit billing conclusions.

The final executed harness SHA-256 is
`0c408bcdaae24a5ee0fede4fd77a26f18eaa721cbe08e592eafeff3a91ed82fd`.
It checked all eight application source hashes against the reviewed deployed
candidate before any paid request. A compact [aggregate receipt](multilingual-aggregate-2026-10-20.json)
contains per-locale counts, model identities, cost qualifications and hashes of
blinded adjudications. Raw sources, JPEGs, native requests/responses, decisions,
repair provenance and review receipts remain under
`/home/superdev/projects/.openmates-runtime/product-stack/test-results/d115-multilingual-30s-final-20261020`.
No benchmark output was inserted into a user account, chat or inspiration pool.

The additional optional live vi/th/cs discovery probe was canceled before native
calls because another Task held the exclusive dev test lease. The fourteen green
isolated enum regressions remain the evidence for those mappings; no live result
is claimed for that optional probe.


## Recommended next qualification

Use independently labeled multilingual cases for entity/subtype scope, causal
order, mistranslated definitions, sparse descriptions, and factual premises hidden
in follow-up questions. Measure both false admissions and conservative false
rejections; do not lower Jev confidence thresholds to manufacture a pass. Add
native-speaker review for the twenty locales and translated thumbnail text controls
(the current five visual holdouts are a small pixel-transport/safety sample).
Separately measure repeated source-review stability and a real 3-video/3-wiki/4-tip
refresh with source shortages and localized static recovery. After correctness is
qualified, compare regenerating only rejected slots with the current whole-batch
retry, preserving approved copy and source identities; this tests avoidable recovery
cost without weakening review. These checks answer
the remaining quality questions more directly than another speed-only run.
