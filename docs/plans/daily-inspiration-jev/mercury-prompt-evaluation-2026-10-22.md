# Mercury writer prompt evaluation — 2026-10-22

## Question and prior evidence

The user asked us to give Mercury 3 clearer instructions and source input, then
evaluate whether it can replace Gemini 3.8 Flash as the sole Daily Inspirations
writer. Jev 1.14 remains the decision model, including actual thumbnail review.

The previous three-source comparison did not demonstrate Mercury incapability.
Every Mercury response had valid structure; independent automated source review
found apparent false holds in all five rejected drafts across both writers.
Published general-purpose benchmarks also support trying Mercury, but do not
replace a workload-specific check. See [Inception's Mercury 3 announcement](https://www.inceptionlabs.ai/blog/introducing-mercury-3).

## Implementation

The existing video schema still assigned selection to the writer, requested a
rich three-to-five-sentence introduction and surprising details, and supplied
unrelated examples. Those conflicted with the exact-three-sentence,
source-grounded system brief. The Wikipedia schema also requested three to five
sentences. Jev already fixes source selection before writing.

The new `writer_prompt.py` builds a short role/style instruction followed by a
JSON evidence packet, an explicitly separate format example, and a final task
and grounding checklist. It follows [Inception's prompt guide](https://docs.inceptionlabs.ai/resources/prompt-guide).
Only source IDs, titles, descriptions/extracts and approved categories enter the
packet; private topics, popularity, scores and unrelated metadata are excluded.
Source values remain untrusted data. The tool retains its required fields,
types, enums and output identity; conflicting prose descriptions are replaced.
No source passage is rewritten or supplemented by another model.

The brief consistently requests two short banner sentences, a short title,
exactly three introduction sentences and three distinct short follow-ups tied
to explicit source concepts. Safety, promotion, clickbait and source-grounding
constraints remain explicit. A question may explore a source concept without
requiring the source to answer it, but cannot presume an absent fact.

## Evaluation design and verification

One cohort plans twelve source slots: video and Wikipedia for three concepts in
English and German. Source eligibility and thumbnail pixels are checked once;
all arms receive the same frozen evidence and images. Terminal discovery
shortages remain visible and are not replaced after outputs are seen.

The arms are current Gemini, original-request Mercury and clearer-request
Mercury. Both Mercury arms use LOW reasoning, temperature 0.5 and a 4,096-token
cap, isolating prompt/input changes. Each arm makes one attempt per source with
no fallback or separate LLM reviewer. Every actual draft receives unchanged
production assembly and native Jev admission checks. Raw writer quality is
reviewed separately against exact evidence, blinded to model and admission.
This review is automated, not human/native-speaker gold.

- **75 focused tests passed locally and in [isolated CI run 39744938433](https://github.com/glowingkitty/OpenMates/actions/runs/39744938433)**;
  scoped Ruff passed. Coverage includes public-evidence whitelisting, exact
  identities/categories, adversarial input serialization, no mutation, actual
  video/wiki schemas, diagnostic isolation and existing retry behavior.
- CI source: `e2b166d0641fd6604bd8a2b44eeb60bb8a2129a5`. Its receipt was
  retrieved and the evidence command completed with no unit recording inventory.
- Diagnostic candidate deployed to dev:
  `0b8885c012fbf3de81e8888210b330a15ff5527f`. Runtime operation
  `docker-9a0c3ccc` completed with all seventeen consumers healthy. Fourteen
  runtime module hashes are required before paid calls.

## Result and decision

**Use Mercury 3 with the clearer source-bound request.** The writer is capable
of this task when instructions are consistent. The original request produced
several unsupported premises; the clearer request's ten returned drafts all
passed the model/admission-blind source-only review, including format checks.
One of its eleven requests timed out, rather than returning invalid copy.

Twelve planned slots yielded eleven eligible sources; one English recycling
video slot had a terminal discovery shortfall. Every arm received the same
source/JPEG hashes, and all fourteen runtime module hashes matched before calls.

| Writer/request | Returned drafts | Source-only audit | v8 Jev admission | Median writer latency | Captured writer + production Jev estimate |
| --- | ---: | --- | ---: | ---: | ---: |
| Gemini, original request | 11/11 | 8 pass, 2 minor, 1 material | 5/11 | 12.74 s | $0.075037362 |
| Mercury, original request | 11/11 | 6 pass, 4 material, 1 uncertain | 0/11 | 2.29 s | $0.008111076 |
| Mercury, clearer request | 10/11; one 30 s timeout | **10 pass, no material or formatting issues** | 3/11 | **1.35 s** | **$0.004382172 plus unknown timeout spend** |

The five material flags and one uncertainty were all withheld by Jev. Material
flags include changing “mostly near the poles” into “only,” changing a recycling
quantity relationship, and attributing auroras to cultural meaning. These labels
were fixed before unblinding. Some source-coverage extrapolations may be true
outside the supplied passages; the audit is not evidence they are all unsafe or
factually false. See the [fixed audit](mercury-prompt-blind-audit-2026-10-22.json).

Every clearer-Mercury copy rejection was a favorable Jev language/grounding answer
below the existing confidence threshold. This is a distinct gate-yield issue,
not a Mercury writing error. Inspection found an erroneous blanket warning
against English sentences even for English targets. The v9 question names the
target language explicitly and permits normal headings/fragments and necessary
names/terms. Choices, uncertainty handling, finite-confidence threshold, source
policy, grounding, follow-up relevance and actual pixel checks stay unchanged.
The v9 release diagnostic then exposed a real qualifier error in an original-
Mercury negative: “mostly near the poles” became “only near the poles.” It was
admitted, so that gate diagnostic failed and is preserved as failed evidence.
The bounded v10 repair makes every existing grounding question explicitly check
scope, qualifiers, quantifiers and causal roles, including premises hidden in
questions. Usually/mostly cannot entail always/only/all. No confidence threshold
or verdict choice was changed. Old proofs and defaults caches are invalidated
(`daily-editorial-v10`, `v19`).

Both runtime generators now use the clearer packet and cleaned schema. The sole
writer is `inception/mercury-3`, LOW reasoning, temperature 0.5, a 4,096-token cap
and a 30-second attempt limit. Provider/schema failures may retry Mercury once;
editorial rejections are terminal. There is no Gemini writing/review stage or
cross-model fallback. Activity gates and localized recovery remain in place.

## Cost interpretation

The [native accounting aggregate](mercury-prompt-costs-2026-10-22.json) counts each
actual native response once, including reasoning inside output usage. The table
compares captured first-attempt costs for the same eleven eligible source slots;
it is not a completed-refresh price or a complete bill. Google's cache counters
were absent in eleven responses, so its value assumes uncached input. Mercury's
cancelled request had no captured usage and remains unpriced. The ten successful
clear-Mercury responses had median writer latency 1.26 seconds; the all-attempt
median above also includes the timeout.

At regular Mercury prices, doubling only its launch-rate writer charge gives
$0.007238442 including the same Jev work, plus unknown cancelled spend. Shared
source collection ($0.002371866) and locale assessment ($0.000198198) are separate.
Search/API/infra charges are unmetered; credits are not subtracted. The original
pre-Jev architecture's historical full-refresh replay is a different workload
and cannot establish a savings percentage for this cohort.

The separate [four-card runtime check](mercury-release-check-2026-10-22.json)
recorded **$0.001233830 writer + $0.000802914 production Jev = $0.002036744**,
or $0.000509186 per card for writing/admission. All four calls returned valid
cards and were admitted, including the previously cancelled source. Source
revalidation cost $0.000423444 separately. No cancellation or unpriced native
response occurred in this check; the earlier cancellation still remains unknown.
At regular Mercury rates its writing/admission total is $0.003270574. The gate
diagnostic's separate control/locale costs are not production card prices.

## Current rollout verification

- **297 focused tests passed locally and in [CI run 39750076090](https://github.com/glowingkitty/OpenMates/actions/runs/39750076090)**.
  The preceding Mercury integration passed 292 checks in CI run 39747886416;
  counts overlap and are not added. Scoped Ruff and independent integration
  review passed.
- Implementation deployed to dev as
  `32d62b7f4adf328ce5530d6f71ef670eaffc35d1`. All 25 scoped files matched tested
  candidate `38c5bbec12b2ad31aef6dce150f17a2c5447ffad`; three unrelated local
  dispatcher-adoption files were excluded. CI receipt/evidence retrieval
  completed with no unit recording inventory.
- Runtime reload `docker-88327cf3` completed with all seventeen consumers
  healthy; exact-source readiness passed for the Mercury integration commit.
  The v9 native check made four production Mercury calls, all valid/admitted,
  with zero provider, schema or formatting failures. Its nineteen separate Jev
  controls were all available: six of ten positives admitted, four of five
  material negatives withheld, and all four wrong-language/off-topic negatives
  withheld. The qualifier false admission means the gate check failed.
- The v10 repair is deployed as
  `161e2df3f927cf615d70c3fec8575c9086bc189c`. All fifteen scoped paths matched CI
  candidate `614628cfee1e969bbca63712b3684320122e6bb7`; receipt/evidence retrieval
  completed with empty unit recording inventory. Runtime operation
  `docker-e7ca37eb` completed with all seventeen consumers healthy; fourteen
  exact module hashes matched before native calls. Exact-source frontend
  readiness passed for this commit.
- The [final v10 native check](mercury-v10-gates-2026-10-22.json) passed:
  all twenty-four decisions were available, **all ten negatives were withheld**,
  and **eleven of fourteen positives were admitted**, including all four actual
  Mercury runtime drafts. Both the known German qualifier error and the added
  English exclusivity mutation were withheld. Saved public evidence/drafts and
  actual thumbnail pixels received fresh native decisions; no new writer calls
  or reruns were made. Twenty-eight Jev responses cost $0.004169046, with no
  unknown usage or provider errors. The failed v9 result is retained.

The remaining three valid-draft holds make conservative Jev yield a
**medium-priority improvement**, rather than a blocker for this English/German
dev rollout. Thresholds remain unchanged. Localized public recovery and retention
of the previous personal set cover incomplete personal results; no further paid
sweeps are required for this delivery.

The comparison is small and focused on English/German, not twenty-language
quality certification. No production-server deployment was performed.
