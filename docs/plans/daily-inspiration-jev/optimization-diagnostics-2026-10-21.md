# Editorial optimization diagnostics — 2026-10-21

The Jev-only candidates were not adopted. The later Gemini 3.8 profile was selected for EN/DE verification after the fourteen-control result below; this report is not deployment evidence. The Jev confidence threshold (`>= 0.5`) remains unchanged. Initial diagnostics use the same 29 curated controls: 14 expected allows and 15 expected rejects. They do not establish population accuracy, native-language quality, image suitability or full pipeline qualification.

The [compact aggregate](optimization-diagnostics-2026-10-21.json) records immutable runtime directories, manifest hashes, receipt-set hashes, case admissions and native accounting. No paid calls were made to prepare this report; original receipts remain unchanged.

| Jev 1.14 variant | Positive controls admitted | Negative controls falsely admitted | Native requests | Input tokens | Supplier cost estimate |
| --- | ---: | ---: | ---: | ---: | ---: |
| Indexed paths | 9/14 | 2/15 | 29 | 103,314 | $0.004339188 |
| Scalar language + grounding | 12/14 | 3/15 | 348 | 210,058 | $0.008822436 |
| Independent semantic dimensions | 0/14 | 0/15 | 29 | 336,230 | $0.014121660 |

Every native response reports `jev-1.14.0`; all requests were available. Each native HTTP response's `usage.input_tokens` is counted once at $0.042 per million input tokens, with output free. Facade accounting and typed responses are not added again. Recorded totals match each run's summary. These are supplier tariff estimates before credits, not invoices. The three Jev runs together cost $0.027283284.

Indexed paths uses the actual v6 one-case batch, replaces absent aliases with actual backticked JSON paths and explicitly names the requested language. It retains policy, coherence, grounding, language and follow-up relevance checks. Scalar copy sends six separate field-language requests and six separate field-grounding requests per case. It isolates text checks rather than reproducing all policy/coherence decisions. Dimensions puts literal field text and source evidence into each independent question, with only the unchanged grounding rubric and untrusted-content flag shared. Its 39 questions per case were packed into one actual request per case by the production budget-aware batcher. It checks topic/entities, role direction, qualifiers/scope, temporal status, unsupported additions, language and separate follow-up relevance. Assessment date is fixed at 2026-10-21. Question independence does not itself establish a question-count interference explanation.

Both paths and scalar copy falsely admit the Turkish producer/product role reversal (`card-4d557a74cab1`) and German component/whole change (`card-6bc707660ed2`). Scalar copy additionally admits the Arabic vaccine claim that drops the infectious-disease restriction (`card-d399e32936fc`). Its two false withholds are the valid Arabic Mira title, labeled language `wrong` at confidence 0.40, and the original Japanese metaphor title, labeled grounding `supported` at confidence 0.35. Both fail the unchanged threshold; no retrospective threshold adjustment was made.

Dimensions withholds every positive and negative card. That is not evidence of a causal-role fix: all twelve checks on the faulty Turkish phrase and intro pass, including role direction at 0.52 and 0.83. The negative is blocked by other checks on its follow-ups. The matched valid Turkish control is also withheld, including low-confidence checks on its valid follow-ups (and title scope). Thus zero card false admissions conceals a surviving field-level semantic miss and universal withholding.

## Completed opaque-ID LLM semantic diagnostic

The replacement runs use only `source_000` as the provider identity. All 29 cases complete in each profile; fixture IDs are absent from their retained immutable requests. Both manifests pin probe SHA `a69624279e0052456adb7d1acbbaceb25a597c122eebbb4c48ed1b8b880c4635`, the original case/source hashes, low reasoning effort and requested temperature zero. Google thinking-model calls actually use temperature 1.0 because of the adapter clamp; earlier zero-valued metadata must not be read as effective temperature. The aggregate retains those source hashes and manifest/receipt-set hashes. These results are separate from the invalid runs below.

| Opaque profile | Positive controls admitted | Negative controls rejected | Negative controls falsely admitted | Unavailable/withheld | Native requests | Supplier cost estimate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Mercury chain | 14/14 | 12/15 | 3/15 | 0 | 29 Mercury | $0.011294030 launch / $0.022588060 regular |
| Gemini only | 14/14 | 0/15 | 14/15 | 1 | 29 Gemini | $0.025361300 uncached upper bound |

Mercury matches 26/29 fixture outcomes but falsely allows all three real regression negatives: Turkish role reversal, German component/whole and Arabic restriction omission. It rejects the twelve synthetic negative controls. Gemini matches 14/29 outcomes, falsely allows fourteen negatives and withholds the remaining negative (`v6-ar-01-reject`) because its accepted/rejected partition disagrees with its field reviews. That schema inconsistency is not a correct semantic rejection. The schema-failed response remains included in native cost. These observations are bounded to these controls; they do not establish general model quality or justify adoption.

Both profiles make exactly one attempt per case: no retries, canceled calls or fallback calls occur. The Mercury-chain profile observes `mercury-3` in all 29 responses and never reaches Gemini. Its native usage is 35,255 prompt tokens, including 19,838 cached tokens, plus 27,297 completion tokens. Gemini observes `gemini-3.5-flash-lite` in all 29 responses: 27,721 prompt and 6,818 output tokens. Its cache counters are absent in all responses, so its estimate remains an uncached upper bound. All actual responses are counted once; no facade or reasoning double counting is applied.

Recorded per-attempt latency is median 1.729 seconds / maximum 4.938 seconds for Mercury and median 1.296 seconds / maximum 1.943 seconds for Gemini. Summed attempt durations are 57.016 and 40.156 seconds respectively; concurrency is three, so these sums are not end-to-end wall-clock durations.

Evidence roots are `d115-v7-blind-semantic-{mercury-chain,gemini-only}-20261021` under the same runtime test-results directory. Further evidence-backed and higher-reasoning diagnostics are being evaluated before any adoption. No application behavior changed and no additional paid calls were made for this report.

## Concurrent medium-reasoning and evidence profiles: availability confound

Three additional opaque-ID profiles completed all 29 case files, but ran simultaneously with three concurrent calls per process. Mercury returned repeated HTTP 429 errors for output-token/request limits. These are availability failures, not semantic verdicts. Their aggregate chain outcomes cannot qualify Mercury or isolate a prompting/reasoning improvement. All three pin probe SHA `c5a0f394dc8e92fb17219c230dc7e758296a3ed2039c6bdc40b509a6aad13f2d`, an 8,192-token output cap and requested temperature zero; their manifests record effective Mercury temperature 0.5. Their Gemini effective-temperature entry of zero is incorrect: the adapter clamps Google thinking models to 1.0. Immutable manifests have not been rewritten.

| Profile | Mercury HTTP 200 / 429 | Mercury usable verdicts: allow / reject | Gemini usable verdicts: allow / reject | Final available cases | Total attempts / cases retried |
| --- | ---: | ---: | ---: | ---: | ---: |
| Verdict, medium reasoning | 23 / 13 | 11 / 11 | 7 / 0 | 29/29 | 43 / 7 |
| Evidence, low reasoning | 18 / 26 | 8 / 8 | 8 / 0 | 24/29 | 57 / 15 |
| Evidence, medium reasoning | 12 / 37 | 5 / 4 | 13 / 0 | 22/29 | 69 / 20 |

For verdict-medium, Mercury's 22 usable verdicts cover eleven positive allows and eleven negative rejections. All four chain false admissions come from Gemini fallback. In particular, each of the three real Turkish/German/Arabic regression negatives receives two Mercury HTTP 429 responses followed by a Gemini allow. Those outcomes are **not Mercury semantic failures**. One additional Mercury HTTP 200 response ends at `length` and fails tool parsing; its paid usage is included.

For evidence-low, Mercury's sixteen usable verdicts cover eight positive allows and eight negative rejections. Gemini supplies four positive allows and four negative false allows; five further cases remain unavailable after Gemini schema failures (three `evidence_quote_not_in_source`, two `source_partition`). The three real regression negatives all encounter Mercury 429 twice, then Gemini schema failure; no Mercury semantic verdict exists for them. Two paid Mercury HTTP 200 responses fail: one `length`/parse failure and one `schema:status_codes` failure.

For evidence-medium, Mercury produces four positive allows, four negative rejections and one actual false allow on the synthetic Arabic wrong-language control (`v6-ar-02-reject`). Gemini supplies eight positive allows and five negative false allows; seven further cases remain unavailable after Gemini schema failures (four `source_partition`, two `evidence_quote_not_in_source`, one `evidence_quote_shape`). Again the real regression negatives receive only Mercury 429 responses: Gemini allows the German negative, while the Arabic and Turkish cases fail Gemini evidence validation. Three paid Mercury HTTP 200 responses fail: two `length`/parse failures and one `schema:status_codes` failure. Availability, output truncation and schema rejection are reported separately from usable native model verdicts.

| Profile | Mercury paid-200 estimate, launch / regular | Gemini uncached upper bound | Known launch estimate + Google upper bound |
| --- | ---: | ---: | ---: |
| Verdict-medium | $0.015837670 / $0.031675340 | $0.006406600 | $0.022244270 |
| Evidence-low | $0.017286560 / $0.034573120 | $0.035430600 | $0.052717160 |
| Evidence-medium | $0.016634040 / $0.033268080 | $0.052872800 | $0.069506840 |

Every captured Mercury HTTP 200 response is priced once from raw usage, including length, parse and schema failures. Google costs include every native response, including schema failures, and remain upper bounds because cache counters are absent. HTTP 429 responses contain no captured inference usage; no token charge or zero-spend guarantee is invented. The old capture omitted response headers, so retry timing cannot be reconstructed from headers. Receipt-level tokens, errors, model attribution and costs are retained in the companion JSON.

Evidence roots are `d115-v7-{verdict-medium,evidence-low,evidence-medium}-20261021`. The next isolation design is one paced process, concurrency one, at least three seconds between calls and no Gemini reviewer fallback, so a final result can be attributed to Mercury. This report does not execute that design, adopt any candidate or change the application.

## Paced Mercury-only native profiles

The follow-up profiles isolate Mercury: one process, concurrency one, at least three seconds between attempt starts, medium reasoning, 8,192 maximum output tokens and reviewer exhaustion withheld without Gemini fallback. Both pin probe SHA `0be6b61610ce2df3d27ebe3cccaa3cac4b88a02453cce5368cc6f2e13127ff27`; the aggregate retains the original source hashes. Every captured response is HTTP 200 and reports `mercury-3`; there are **no HTTP 429s or Gemini calls**. Minimum recorded attempt-start gaps are 3.001 seconds for verdict-core and 4.359 seconds for evidence-hard. These runs therefore remove the earlier cross-process quota/fallback attribution confound, without resolving the remaining semantic errors.

| Paced profile | Positive allows | Negative rejects / uncertain withheld / false allows | Native responses | Paid length failures | Launch / regular estimate |
| --- | ---: | ---: | ---: | ---: | ---: |
| Verdict-medium core | 14/14 | 13 / 1 / 1 of 15 | 29 | 0 | $0.019347360 / $0.038694720 |
| Evidence-medium hard | 3/4 | 1 / 0 / 2 of 3 | 9 | 2 | $0.015980770 / $0.031961540 |

Verdict-core completes all 29 cases with no retries or parse/schema failures. Fourteen negative cards are withheld: thirteen explicit rejects and one uncertain decision on the Arabic control with an English intro (`v6-ar-02-reject`). The Turkish causal-role negative (`card-4d557a74cab1`) is falsely allowed by Mercury itself. That is a native semantic miss, unlike the Gemini-produced real-regression outcomes after 429s in the earlier concurrent verdict-medium profile. Its 34,895 prompt tokens include 21,781 cached tokens; completion usage is 50,909 tokens.

Evidence-hard completes all seven cases (four expected allows, three expected rejects). Two cases require one retry each after a length-truncated tool response, giving nine paid HTTP 200 responses. The Japanese paraphrase and matched Turkish/Arabic positives are allowed; the German component/whole negative is rejected. The Turkish causal-role and Arabic infectious-disease restriction negatives are falsely allowed. The valid German gear-transmission positive (`v7-de-gear-transmission-followup-allow`) is falsely rejected: its comparison treats omission of the nonrestrictive adjective “evenly” and the entailed two-wheel case of “two or more” as disqualifying changes. This is overstrict validation of the positive control, not successful detection of the component/whole negative.

The evidence profile's own English normalizations expose the unresolved contrasts but its verdicts still allow them. For Turkish, `source_meaning` says organisms produce hard colonies, while `copy_meaning` asks how reefs form hard colonies and attributes colony formation to reefs. For Arabic, `source_meaning` retains “prevent infectious diseases” but `copy_meaning` broadens this to “prevent diseases.” The comparison nevertheless calls the Arabic claims directly supported. Normalization and quoted evidence alone therefore do not establish correct semantic adjudication. A Jev diagnostic comparing these English meanings is planned separately; this report makes no result or adoption claim for it.

Evidence-hard uses 16,571 prompt tokens, including 11,092 cached, and 43,777 completion tokens. Its total includes both paid `length`/parse failures as well as the seven completed verdicts. Costs in both rows use raw native cached/uncached usage once; retries, completion reasoning and facade telemetry are not double counted. All attempts have recorded native usage, so these tariff estimates have no canceled/uncached-counter gap. Per-attempt median/maximum durations are 2.170/11.981 seconds for verdict-core and 6.433/18.322 seconds for evidence-hard. These small curated diagnostics remain insufficient for qualification, and no profile is adopted.

Evidence roots are `d115-v7-paced-verdict-medium-core-20261021` and `d115-v7-paced-evidence-medium-hard-20261021`. No new paid calls, application changes or Plan edits were made in preparing this report.

## Selected EN/DE Gemini 3.8 fourteen-control profile

The final opaque-ID EN/DE profile matches all fourteen control outcomes: seven positive allows and seven negative rejects, with no false admission, false rejection or final withholding. It uses `google/gemini-3.8-flash`, low reasoning, a 4,096-token output cap, concurrency one, three-second pacing and at most two bounded attempts. Requested temperature is zero; actual effective Google thinking-model temperature is **1.0**, as correctly recorded by this final manifest. The earlier Google temperature descriptions above are corrected at report level only; original manifests and receipts remain immutable.

There are fifteen attempts and fourteen captured native SDK responses, all reporting `gemini-3.8-flash`. The German component/whole negative (`card-6bc707660ed2`) first times out after 30.032 seconds without a captured SDK response, then succeeds on retry. The first attempt has **unknown cost**, not zero. This fourteen-control result supports selecting the EN/DE profile for further application verification; it does not qualify the other eighteen languages, images, policy, the full pipeline or population performance. No new experiment or deployment was performed for this report.

Captured usage totals 12,922 input tokens, 3,327 candidate output tokens and **9,845 thinking tokens**. Pricing all input as uncached at $0.75/M and all 13,172 output-plus-thinking tokens at $3.75/M gives **$0.059086500 for captured responses**. All fourteen cache counters are absent, so this is an uncached upper bound for those responses only. Additional spend from the timed-out attempt is unpriced: $0.059086500 is neither an exact bill nor an upper bound on all fifteen attempted calls. No facade usage or thinking tokens are counted a second time.

Evidence root: `d115-v7-final-gemini-ende-20261021`. Probe SHA is `e94761dd4d691a5832cb606604dea81bf8bdff00d5e38d3c138d87b69e34fdbb`; frozen fixture SHA is `7da9bd2c6c2966517c8afa5ec1e636c86a68e11cf4797f1f586f4141406008e6`. The companion JSON pins the manifest, source hashes and all fourteen case receipts, retaining the unpriced canceled attempt separately. A future deployed EN/DE refresh cost sample will be separate evidence; it has not been started or monitored for this report.

## Invalid initial LLM semantic diagnostic

Both initial semantic runs are **invalid for quality assessment**: provider `source_id` contained fixture IDs with `allow`/`reject` labels. Their `INVALID-BENCHMARK.json` files explicitly preserve this finding. No accuracy, false-admission or model-quality comparison is derived from those outputs. The receipts remain evidence of incurred native usage, including responses that failed schema validation.

| Invalid profile | Native observed usage | Known cost estimate | Uncertainty |
| --- | --- | ---: | --- |
| Mercury chain | 27 `mercury-3` HTTP 200 responses; 30,719 prompt tokens, including 18,205 cached; 27,603 completion tokens | $0.011094500 launch / $0.022189000 regular | One interrupted Mercury attempt has no native response/usage and remains unpriced. No Gemini fallback ran. |
| Gemini only | 29 `gemini-3.5-flash-lite` SDK responses; 26,776 prompt and 7,726 output tokens | $0.027347800 uncached upper bound | Cached-input counters are absent in all 29 responses. Five responses fail `schema:partition_disagrees_with_fields`; their usage is included. |

Mercury has 28 retained case files: 27 complete and one interrupted; its final planned case did not start. Requested models are 28 `inception/mercury-3` attempts versus 29 `google/gemini-3.5-flash-lite` attempts. A chain profile name does not imply that retries or fallbacks actually occurred. None did in the retained Mercury run.

Mercury launch pricing uses the receipt's tariff snapshot: $0.10/M uncached input, $0.01/M cached input and $0.35/M completion. Regular sensitivity uses $0.20/$0.02/$0.70 respectively. Completion tokens already include reasoning tokens; reasoning is not billed a second time. Google uses the receipt's $0.30/M input and $2.50/M output tariff. Missing cache counters prevent an exact Google cost; pricing every prompt token as uncached gives the stated upper bound. The canceled Mercury attempt could have incurred additional spend. Neither missing telemetry nor invalid quality results justify treating paid work as free.

The evidence roots are `d115-v7-{indexed,atomic-copy,dimensions}-20261021` and `d115-v7-semantic-{mercury-chain,gemini-only}-20261021` under `/home/superdev/projects/.openmates-runtime/product-stack/test-results/`. This report covers only those diagnostic calls; it excludes source acquisition, refresh generation, public-pool selection and production traffic. No production-spend or savings claim follows.
