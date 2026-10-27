# Expanded native workflow evaluation — 20 October 2026

Mercury 3 INSTANT is faster on this bank, but the expanded evaluation does **not**
support enabling it as the automatic workflow author. It returned six incomplete
results out of 48, including repeated retention of a withdrawn Monday reminder.
Gemini 3.8 Flash LOW also failed important contracts. Its failures do not excuse
Mercury regressions. Keep the proposed workflow default unpublished.

## Frozen method and provenance

The [pre-inference protocol](expanded-evaluation-protocol.md) fixed the rubric.
Eight original English cases plus sixteen new independent cases (eight English,
eight German), two repeats, two native arms: **96 rows**. These are synthetic
requests; no workflow, schedule, chat, account or wallet was written or executed.
The corpus and oracle were not changed after observing these outputs.

- Exact published benchmark/case revision: `3c1106d837a982e8bd740f72266a9552b87db849`.
- Corpus: `workflow-native-quality-24-v1`, explicitly `--suite expanded --profile native`.
- Arms: native Google `gemini-3.8-flash`, LOW; direct Inception `mercury-3`, INSTANT,
  temperature 0.5, 8192 completion-token budget. No gateway or provider fallback.
- Production author prompt, equivalent native logical JSON schema, incremental
  parser, compiler, graph validation and existing correction allowance. No extra
  guidance or evaluator feedback was appended to either model's native prompt.
- Real Jev selection was measured once per case, then frozen and reused across
  both arms/repeats. Paired order rotated. All expected capabilities were present
  except the two schedule-only edits, whose existing weather action needed no new
  capability selection. Both authors preserved those graphs correctly.
- A shared read lease protected the actual API runtime. Only a disposable child
  loaded the two exact published benchmark/case modules; shared runtime bytes
  were not changed. All **18** checked product/config dependency hashes matched
  publication. Runtime revision: `b2a15b4d7055c18b22026e6e086fa5919e3337c2`;
  image: `sha256:1eb8eb5a49e21acc8f8d38663742a1a65d9fa539540e456da4e6e4253eae84d6`.
- Provider response identities matched the expected native model in all 96 rows.
  This is endpoint/model verification; native responses do not independently
  attest a separate provider-name field. Every recorded transport attempt was
  HTTP 200: 54 Google and 63 Inception attempts. No HTTP 429, no availability stop,
  no skipped rows, `partial=false`. Incomplete rows remain in quality denominators.
- Provider calls finished, both artifacts were copied with mode 0600, then the
  shared read lease was released. No further inference was run for this review.

Private evidence (complete prompts, compiled plans, correction diagnostics,
per-attempt native stream events/usage and selection diagnostics):

| Artifact | SHA-256 |
| --- | --- |
| `/tmp/mercury-acad-expanded-workflow.json` | `5e0698ea166204a6886448e602cebdd022f97957358aebf6fd61da3b4787ce0e` |
| `/tmp/mercury-acad-expanded-workflow-runtime.json` | `0b04c479a18c50a326062b45ab3cf29b0a147ca8ad85f7afaf629c3dde0132c7` |

These local private artifacts are evidence retained on this host, not durable
public downloads. The source manifest and exact requests are inside the report.

## Quality, strict and manual

Every one of the 96 result plans was inspected, including trigger configuration,
app inputs, Check predicates/branches, typed references, delivery and preserved
update state. No result was executed, so this is authoring-intent review rather
than proof of downstream skill output quality.

| Measure | Gemini LOW | Mercury INSTANT |
| --- | ---: | ---: |
| Complete valid result | 46/48 | 42/48 |
| Frozen strict intent oracle | 33/48 | 40/48 |
| Original eight cases, strict | 12/16 | 15/16 |
| New sixteen cases, strict | 21/32 | 25/32 |
| English, strict | 25/32 | 29/32 |
| German, strict | 8/16 | 11/16 |
| Manual: no identified critical defect or unresolved gap | 34/48 | 40/48 |
| Manual: critical contract/incomplete-result defect | 13/48 | 6/48 |
| Manual: unresolved shared per-item relevance gap | 1/48 | 2/48 |

Manual acceptable counts include disclosed cosmetic differences and finite-oracle
false positives below; they are not replacements for the preserved strict scores.
Of 48 matched case/repeat pairs, strict outcomes were: both pass 29; only Mercury
passes 11; only Gemini passes 4; neither passes 4. The bank has 16 German rows
per arm and 32 English rows, not equal language sample sizes overall.

### Critical Mercury findings

1. `events_free_text`, repeat 1: only the events-search prefix survived; Ask AI
   and delivery were missing. Two HTTP-200 attempts ended with selected-schema
   `additionalProperties` at `$.steps[1]`. The first Ask-AI record incorrectly
   carried `capability`; the repair added `selected_inputs` to an Ask-AI step.
2. `de_two_city_weather`, both repeats: Vienna/Graz forecasts survived, but the
   comparison and answer delivery did not. Both attempts in each row failed
   selected-schema `additionalProperties` at `$.steps[2]`. Ask-AI records again
   used unsupported `capability` or `selected_inputs` properties after flat
   normalization. The same failure repeated after a correction opportunity.
3. `en_mixed_edit_glutenfree`, repeat 0: the Paris clock edit survived, but the
   requested new recipe workflow was not returned. Final validation failed
   `anyOf` at `$.steps[1].message`; the repair combined `text` and `ref` in one
   message part. This is a model/schema failure, not an upstream outage.
4. `de_negated_reminder_schedule`, both repeats: generated **two** reminders,
   including the explicitly withdrawn Monday 07:00 schedule, alongside the
   requested Wednesday/Friday 18:35 schedule. Jev correctly selected one workflow.
   Both attempts completed with valid usage/stop data, but the planner rejected
   `workflow_count_mismatch` and returned partial operations. The invalid Monday
   operation must not be silently treated as a valid requested workflow.

All six are non-availability failures. A timeout/outage-only Gemini fallback
would not repair these defects; the existing validation/correction allowance was
already exercised. The partial results must not be presented as complete success.

### Critical Gemini findings

- Ten rows authored an unrequested historical `starts_at`: events repeat 1;
  nutrition repeat 1; mixed headphones repeat 1; backpack repeat 1; German
  three-branch AI Check both repeats; German two-zone workflows both repeats;
  quoted-instruction news both repeats. These dates came from provider output,
  not a compiler-generated default. Historical bounds may not change the next
  recurrence in every runtime situation; they still violate the frozen
  no-invented-date contract. This test did not execute schedules to measure harm.
- The two German two-zone rows used **Europe/Berlin** for the Lisbon recipe
  workflow. The mixed gluten-free repeat 1 used **Europe/Berlin** instead of UTC
  for its new workflow. The existing Paris updates remained correct.
- `subjective_news` repeat 1 returned only a trigger after selected-schema
  `additionalProperties` at `$.steps[0]` in two HTTP-200 attempts.
- `de_backpack_self_correction` repeat 0 retained shopping but lost chat delivery
  after three HTTP-200 attempts; final failure code `node_json`. Raw first output
  appended `Tools` inside `message_json`. This was not an availability failure.

Ten date-bearing rows, one further wrong-zone row and two incomplete rows give
13 unique critical rows; overlapping date/zone defects are not double-counted.

### Strict false positives, cosmetic findings and unresolved semantics

The frozen oracle remains unchanged. Manual distinctions are explicit:

- Gemini `de_two_city_weather` repeat 1 says “keine Vorhersagedaten vorliegen”
  and explicitly asks to mention that absence. It meets missing-data intent but
  misses the finite `fehl|missing|unavailable|no data` regex.
- Gemini `de_weather_news_typed_inputs` repeat 1 says “Fasse ... zusammen” and
  “kurzes, deutsches Update”, with both correct typed inputs. This meets summary
  intent but misses `zusammenfass|summar`.
- Mercury `en_mixed_edit_glutenfree` repeat 1 uses the explicit query
  `gluten-free dinner recipes`, retains the real result reference and chooses
  exactly two with explanation. The strict fixture demands `health:[gluten-free]`;
  the registry explicitly supports free-text queries such as `gluten-free pancakes`
  and describes health labels as optional. Treat the strict “missing reference”
  flag as cascading role matching, not an absent actual reference. Structured
  health filtering would be more robust; downstream dietary correctness was not
  measured. This is accepted for authoring intent, not proof of allergen safety.
- Mercury `de_two_zones_recipe_reminder` repeat 0 replaces the literal TRINKWASSER
  reminder with “Denk daran, Wasser zu trinken!”. The schedule and water-reminder
  meaning are retained; the requested literal text is not. It remains a strict
  failure, manually classified as a cosmetic paraphrase, not exact compliance.
- Mercury `en_two_product_budgets`, both repeats, emits the same combined results
  twice under USB-C-dock and HDMI-cable labels. The one shopping action has the
  two correct DE requests and separate ceilings, and one message contains both
  groups. This is redundant/misleading presentation, not two extra actions; it
  is a cosmetic concern in the manual acceptable count.
- All three complete `subjective_news` rows (two Mercury, one Gemini) use an
  aggregate relevance Check and then send the **whole** search result list.
  Relevance ranking is requested in the search, but no per-item selection proves
  that only relevant items reach chat. Preserve these as unresolved intent gaps
  rather than claim flawless semantic passes. The incomplete fourth row is
  already counted as critical. The bank does not execute a mixed-relevance result
  fixture to settle the runtime effect.

No wrong owned-workflow target or lost unrelated graph state was found. The
schedule-only edits retained the Paris timezone, ID, metadata and nontrigger
nodes/edges. Both authors preserved the quoted untrusted phrase as query data;
Gemini's date additions in that case are separate failures.

## Latency and stream accounting

Milliseconds; medians include validation/correction attempts and failures, not
only successful rows. First header/node means the first **accepted** production
callback; a schedule-only update can correctly have no newly emitted node.

| Group / arm | Rows | Complete wall median | First header median | First node median |
| --- | ---: | ---: | ---: | ---: |
| All / Gemini | 48 | 3961.45 | 2653.75 | 3182.10 (43 observed) |
| All / Mercury | 48 | 1613.65 | 1184.25 | 1272.70 (47 observed) |
| Original eight / Gemini | 16 | 3964.85 | 2507.35 | 3120.30 |
| Original eight / Mercury | 16 | 1659.05 | 1215.50 | 1384.60 |
| New sixteen / Gemini | 32 | 3927.55 | 2673.75 | 3257.85 |
| New sixteen / Mercury | 32 | 1524.75 | 1145.50 | 1245.50 |
| English / Gemini | 32 | 3909.15 | 2507.35 | 2940.20 |
| English / Mercury | 32 | 1483.95 | 1180.45 | 1255.20 |
| German / Gemini | 16 | 4494.35 | 2959.25 | 3317.25 |
| German / Mercury | 16 | 1715.00 | 1184.25 | 1272.70 |

Mercury's median row wall time was 59.3% lower on this bank. One Mercury row
exceeded five seconds (6679.9 ms maximum); ten Gemini rows did (16371.3 ms maximum).
No Mercury accepted header exceeded five seconds; one Gemini header did. These
are observations under this harness, not an end-to-end product SLA or a simulated
fallback result. The proposed production total/idle/first-useful deadlines were
not enforced by this comparative injected author.

Fourteen Mercury rows and five Gemini rows needed correction. Google exposed
46 STOP records, with eight attempts closed before a finish record. Mercury
exposed 48 stop records and 47 DONE records across 63 attempts; early validation
closure explains why a row can have a result prefix without terminal usage. Do
not infer an upstream disconnect from a missing terminal record after rejection.

Wall time excludes the separately paired Jev selection and excludes workflow
persistence/UI/runtime execution. It includes the injected author request and
validation work, potentially credential resolution. First text per-attempt is
also retained separately; it is not interchangeable with first accepted node.

## Supplier cost and completeness

These are uncached supplier estimates, **not customer billing** and not actual
provider charges. Sum all author attempts; do not price only the last attempt.
Google output is candidates plus thought tokens; Inception completion includes
reasoning once. Cache tokens are subsets of input, not additional input.

| Measure | Gemini LOW | Mercury INSTANT |
| --- | ---: | ---: |
| Raw attempts | 54 | 63 |
| Attempts with usable observed usage | 54 | 47 |
| Observed input / output tokens | 251062 / 13949 | 293016 / 20221 |
| Known cached input subset | 59722, in 18 attempts | 88818, in 47 attempts |
| Known reasoning subset | not separately reported | 417, in 47 attempts |
| Known uncached author subtotal, USD | 0.24060525 | 0.03637895 promotional |
| Same Mercury subtotal at regular tariff, USD | — | 0.07275790 |
| Rows marked complete for all costs | 43/48 | 36/48 |
| Median complete-row author estimate, USD | 0.00435300 | 0.00075885 promotional |

Tariffs per million input/output tokens: Google 0.75/3.75; Mercury launch
0.10/0.35, regular 0.20/0.70, as frozen in this harness. Even the requested INSTANT
profile reported 417 reasoning tokens in three metered attempts; use actual usage
rather than assume zero. Missing Google thoughts metadata is unknown, not a
verified zero breakdown. Counts above include potentially interim Google usage
on rejected streams; complete billing is not established for those rows.

Sixteen Mercury attempts lack usable final usage. Some Google attempts expose
only counters observed before early validation closure. Consequently the known
subtotals **are incomplete and cannot establish a full-run cost-saving ratio**.
Never convert missing usage to zero. No native `usage.cost` was reported; actual
provider-reported USD charges remain unknown. Cached-input discounts are excluded
from these estimates; differing cache warmth also limits cold-latency comparisons.

Jev actually ran 24 calls, one per case, with a separate estimated total
**USD 0.01292881**. This common cost was incurred once, not once per arm/repeat.
The planner row `estimated_cost_usd` includes the reused Jev estimate; summing it
across 96 rows would count that common work four times. Top-level row input/output
metrics describe Jev, `generation` is only the last attempt, and `gemini_calls`
is a legacy author-call counter even for Mercury. Use `provider_attempts` plus
`generation_attempts` and `cost_estimate_complete` for interpretation.

## Per-row manual review ledger

Each cell contains repeat 0 / repeat 1. `P` = no material concern found; `C` =
critical defect; `U` = unresolved whole-list relevance; `F` = strict false positive
with accepted equivalent intent; `T` = preserved reminder meaning but literal text
paraphrased; `D` = duplicated combined results presentation. `F/T/D` count as
manually acceptable with the disclosed qualifications. Parentheses preserve the
strict oracle (`+` pass, `-` fail). Every row was reviewed; no arbitrary case-ID
fallthrough or post-observation rescoring changed the finite oracle.

| Case | Gemini r0 / r1 | Mercury r0 / r1 |
| --- | --- | --- |
| `headphones_filter` | P (+) / P (+) | P (+) / P (+) |
| `corrected_rain` | P (+) / P (+) | P (+) / P (+) |
| `three_city_forecast` | P (+) / P (+) | P (+) / P (+) |
| `events_free_text` | P (+) / C (-) | P (+) / C (-) |
| `nutrition_free_text` | P (+) / C (-) | P (+) / P (+) |
| `subjective_news` | U (+) / C (-) | U (+) / U (+) |
| `two_creates` | P (+) / P (+) | P (+) / P (+) |
| `mixed_create_update` | P (+) / C (-) | P (+) / P (+) |
| `en_manual_lunch_choices` | P (+) / P (+) | P (+) / P (+) |
| `de_two_city_weather` | P (+) / F (-) | C (-) / C (-) |
| `en_edit_weekly_keep_paris` | P (+) / P (+) | P (+) / P (+) |
| `de_edit_clock_keep_identity` | P (+) / P (+) | P (+) / P (+) |
| `en_battery_news_no_ai` | P (+) / P (+) | P (+) / P (+) |
| `de_backpack_self_correction` | C (-) / C (-) | P (+) / P (+) |
| `en_exact_false_rain` | P (+) / P (+) | P (+) / P (+) |
| `de_ai_check_three_paths` | C (-) / C (-) | P (+) / P (+) |
| `en_exact_shared_continuation` | P (+) / P (+) | P (+) / P (+) |
| `de_two_zones_recipe_reminder` | C (-) / C (-) | T (-) / P (+) |
| `en_mixed_edit_glutenfree` | P (+) / C (-) | C (-) / F (-) |
| `de_weather_news_typed_inputs` | P (+) / F (-) | P (+) / P (+) |
| `en_query_instructions_are_data` | C (-) / C (-) | P (+) / P (+) |
| `de_exact_news_threshold` | P (+) / P (+) | P (+) / P (+) |
| `en_two_product_budgets` | P (+) / P (+) | D (+) / D (+) |
| `de_negated_reminder_schedule` | P (+) / P (+) | C (-) / C (-) |

## Decision and limits

Hold the automatic Mercury workflow rollout. The repeated self-correction and
Ask-AI/schema failures violate the fixed no-unexplained-critical-regression gate,
even though aggregate strict scores and latency favor Mercury here. An
outage-only fallback does not cover these successful-HTTP semantic/schema errors.
Do not silently broaden fallback semantics or weaken validation to make the
benchmark pass. Any narrower eligibility or repair change needs a separate
supported decision and focused verification before another default evaluation.

This is 24 synthetic cases with two repeats, not a population error-rate estimate,
statistical guarantee or evidence of production workflow execution. There was no
load/concurrency stress, all calls were sequential, and prior workloads/caching
can affect speed. New manual findings were recorded separately without changing
the frozen corpus. Existing unpublished defaults and unapproved Specification
fingerprints remain unchanged by this report.

## Later diagnostic: Mercury LOW, same frozen selections

After the primary 96-row comparison, an explicitly authorized diagnostic ran
**48 additional rows**, Mercury LOW only. The primary raw report, case bank,
prompts, oracle and preceding results are unchanged. It used the same publication,
18 matching dependencies, runtime/image and native transport. Both host and child
verified the original selection-report SHA-256 before inference. The diagnostic
`selections` payload is exactly equal to the original 24 frozen selections; no
new Jev, Gemini or INSTANT calls ran. All 51 author attempts were HTTP 200, model
identity matched `mercury-3`, no 429 or skipped rows occurred, and both private
artifacts were copied before the shared read lease was released.

| Private diagnostic artifact | SHA-256 |
| --- | --- |
| `/tmp/mercury-acad-expanded-workflow-low.json` | `d8d74ccc429dd39b39dba2175b919854fe9153c64f18be67f91cb938328f1413` |
| `/tmp/mercury-acad-expanded-workflow-low-runtime.json` | `2e053b0a2248f0706cdb92073080c859f08e899cedf4c5cbcc1bf31c8222d239` |

Every diagnostic compiled graph was manually inspected against the same fixed
contracts. LOW achieved **47/48 complete valid**, **45/48 strict** (English 31/32,
German 14/16; original eight 15/16; new sixteen 30/32). Manual assessment gives
46/48 with no identified critical defect or unresolved relevance gap, one critical
incomplete row and one unresolved whole-list relevance row. This is a later
profile diagnosis, not a replacement paired primary comparison.

- LOW completed both previously failing German two-city comparisons, both mixed
  gluten-free workflows, both events summaries and both corrected reminder
  requests. Jev's frozen count for the reminder is **one**, correctly reflecting
  the user's final corrected request. INSTANT authored two reminders including
  the withdrawn Monday; LOW and Gemini each authored only Wednesday/Friday.
  The INSTANT failure is not a wrong Jev count obeyed by one author.
- LOW `subjective_news` repeat 0 still returned an incomplete prefix: search and
  AI Check, but no requested branch messages. Two HTTP-200 attempts, final
  `node_selected_schema` failure. It is not an outage. LOW repeat 1 retains the
  same unresolved aggregate-Check/whole-list-delivery gap discussed above.
- LOW `de_two_city_weather` repeat 1 says “Falls ... keine Daten vorliegen”, an
  equivalent missing-data instruction outside the finite regex. Strict failure
  remains recorded; manual authoring intent passes.
- LOW `de_two_zones_recipe_reminder` repeat 1 has the correct two schedules,
  literal TRINKWASSER reminder and real recipe-result delivery. Its explicit
  `vegetarian dinner recipes` query lacks optional structured `health` labels.
  As with the primary query-only gluten-free row, this is a strict role-matching
  miss, not a missing actual reference. Manual authoring intent passes, with
  weaker structured dietary filtering and no downstream dietary guarantee.
- LOW backpack repeat 0 additionally authored `only_new_results:true` on its
  result block. This is an unrequested field to disclose. The current adapter
  normalizes list blocks to new-result handling regardless of that optional
  flag; this authoring-only run does not establish a distinct provider-caused
  delivery regression. No extra action, wrong schedule or lost graph state was
  otherwise found in complete diagnostic graphs. LOW avoided the INSTANT
  duplicate combined-shopping presentation in both product-budget repeats.

The wrong-zone Gemini rows also are not a frozen Jev forcing artifact: its
`workflow_count=2` explicitly makes the production prompt/compiler honor each
workflow's requested zone. The schedule-only edit missing-capability diagnostics
are expected because their existing weather steps are preserved, not regenerated.
Unsupported Ask-AI fields, invalid message JSON and authored starts_at values are
author/compiler-interface failures rather than missing selected capabilities.
The unresolved relevance case is explicitly a shared prompt/runtime contract gap.

| Diagnostic LOW timing | Median ms | Observations |
| --- | ---: | --- |
| Wall including corrections | 3051.90 | 48 rows, maximum 8480.8 |
| First accepted header | 2783.90 | 48 rows, maximum 4903.6 |
| First accepted node | 2938.60 | 44 rows; four schedule-only updates emitted none |
| Original eight wall | 3051.90 | 16 rows |
| New sixteen wall | 2965.70 | 32 rows |
| English wall | 2771.45 | 32 rows |
| German wall | 3779.70 | 16 rows |

Three LOW rows exceeded five seconds wall time; no header exceeded five seconds.
Three rows required correction. These timings occurred later with warmed caches
and no interleaved Gemini arm. They cannot establish a controlled LOW-vs-INSTANT
or LOW-vs-Gemini speed ratio, nor directly simulate a chained recovery request.

Usage was observed for 47/51 attempts: 298319 input, 54962 completion tokens,
including 39996 reasoning tokens and 267460 cached-input tokens. Completion
already includes reasoning. Known uncached author subtotal: **USD 0.04906860**
launch or **USD 0.09813720** regular, incomplete for four attempts. Forty-five rows
have complete cost estimates; their median author cost is USD 0.00103120 launch.
No actual provider USD charge was supplied. The reused Jev estimate is not a new
incurred Jev bill for this diagnostic. There were 47 stop/DONE records and four
early-closed attempts; missing terminal usage is not priced as zero.

### Diagnostic per-row ledger

Same `P/C/U/F` codes and preserved strict `+/-` as above; both repeats of every
case were reviewed, including all strict passes.

| Case | LOW r0 / r1 |
| --- | --- |
| `headphones_filter` | P (+) / P (+) |
| `corrected_rain` | P (+) / P (+) |
| `three_city_forecast` | P (+) / P (+) |
| `events_free_text` | P (+) / P (+) |
| `nutrition_free_text` | P (+) / P (+) |
| `subjective_news` | C (-) / U (+) |
| `two_creates` | P (+) / P (+) |
| `mixed_create_update` | P (+) / P (+) |
| `en_manual_lunch_choices` | P (+) / P (+) |
| `de_two_city_weather` | P (+) / F (-) |
| `en_edit_weekly_keep_paris` | P (+) / P (+) |
| `de_edit_clock_keep_identity` | P (+) / P (+) |
| `en_battery_news_no_ai` | P (+) / P (+) |
| `de_backpack_self_correction` | P (+) / P (+) |
| `en_exact_false_rain` | P (+) / P (+) |
| `de_ai_check_three_paths` | P (+) / P (+) |
| `en_exact_shared_continuation` | P (+) / P (+) |
| `de_two_zones_recipe_reminder` | P (+) / F (-) |
| `en_mixed_edit_glutenfree` | P (+) / P (+) |
| `de_weather_news_typed_inputs` | P (+) / P (+) |
| `en_query_instructions_are_data` | P (+) / P (+) |
| `de_exact_news_threshold` | P (+) / P (+) |
| `en_two_product_budgets` | P (+) / P (+) |
| `de_negated_reminder_schedule` | P (+) / P (+) |

LOW improves the observed failure pattern but is not flawless. This evidence
supports investigating LOW as a recovery profile; the remaining incomplete row
still fails the original no-critical-defect automatic-default gate. A subsequent
explicit user decision authorizes a separate rollout policy of Mercury INSTANT,
then Mercury LOW correction, then Gemini LOW correction with a safe partial
prefix. That recovery chain has not been live-tested by these independent-arm
benchmarks. Its implementation and approval must be recorded separately; this
diagnostic does not retroactively score a failed row as recovered.
