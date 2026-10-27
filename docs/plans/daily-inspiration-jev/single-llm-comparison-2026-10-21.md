# Single-writer EN/DE smoke comparison — 2026-10-21

Three shared sources were eligible out of four planned slots. The English video query returned ineligible city/school matches for “Aurora”; that slot produced no writer call. Both arms used the same three source-snapshot hashes and thumbnail hashes under `daily-editorial-v8`. All thirteen application hashes matched before the run at runtime revision `1c60de459e0a4e828f6c886e8e8cf68bc23fa710`.

| Isolated writer arm | Native writer calls | Admitted / eligible drafts | Writer estimate | Production Jev | Arm estimate | Median writer / writer-plus-Jev latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Gemini 3.8 Flash | 3 | 1/3 | $0.017394750 | $0.000465276 | **$0.017860026** | 12.441s / 12.748s |
| Mercury 3 | 3 | 0/3 | $0.001875320 | $0.000469182 | **$0.002344502** | 2.725s / 3.025s |

Each eligible source receives **one writer attempt per arm**, with a 4,096-token output cap and identical production Jev gates. Gemini uses default thinking and temperature 1.0; the isolated Mercury control uses LOW reasoning and temperature 0.5. All three responses per arm report the intended native model, `gemini-3.8-flash` or `mercury-3`. There are no retries, fallbacks, LLM review calls, observed transport failures, rate limits or cancellations. Production remains Gemini-only; the Mercury override exists only inside the diagnostic call wrapper.

All six writer responses parse into the expected tool collection, each containing one complete draft and three follow-ups. There are **zero tool-parse or malformed-draft failures**. A separate deterministic formatting check flags the Mercury German wiki intro's sentence count; this heuristic warning is not a provider parse failure or an independently established material error.

The sole admitted card is Gemini's German `Polarlicht` wiki card. The withheld outputs receive these production gate codes:

| Shared source | Gemini outcome | Mercury outcome |
| --- | --- | --- |
| English Aurora wiki | Withheld: follow-up 1 language uncertain | Withheld: follow-up 2 language uncertain |
| German video `khXcp_S3qT0` | Withheld: title grounding uncertain; follow-up 1 language uncertain | Withheld: title grounding unsupported |
| German Polarlicht wiki | Admitted | Withheld: intro grounding uncertain; follow-up 1 language uncertain |

“Unsupported” and “uncertain” here describe Jev's decisions, not independent gold labels. Independent automated source-only review found **apparent false withholding in all five rejected drafts**, with no obvious material source/language/follow-up blocker in any of the six raw drafts. Several choices were favorable but below the unchanged confidence threshold: Gemini English wiki correct-language 0.43; Gemini German video supported-title 0.45 and correct-language 0.31; Mercury English wiki correct-language 0.48; Mercury German wiki supported-intro 0.49 and correct-language 0.46. Mercury's German video title was labeled unsupported despite its wording appearing verbatim in the source description and chapter list. This is automated review, not native-speaker or human sign-off. **The 1/3 versus 0/3 admission counts do not establish a quality winner.**

The strict confidence/safety gates remain unchanged. Conservative Jev yield is a medium-priority follow-up; no additional paid sweep is implied. This three-source smoke test does not establish general model quality, a successful full-refresh price, savings against the original architecture or twenty-locale costs.

## Native accounting and separate collection

Each native response is priced once; facade telemetry and duplicate transport views are not added again. Gemini records 5,108 input and 3,617 output tokens, including **3,077 thinking tokens**. Cache counters are absent in all three responses, so its price is an uncached captured-response upper estimate at $0.75/M input and $3.75/M output through December 31, 2026. Mercury records 5,628 input tokens, including 27 cached, and 3,757 completion tokens; its 3,024 reasoning tokens are already included in completion and are not added again. Launch rates are $0.10/$0.01/$0.35 per million uncached/cached/output tokens. Repricing only Mercury at regular $0.20/$0.02/$0.70 gives **$0.004219822** including the same Jev work; this is sensitivity arithmetic, not another run.

Each arm has three production Jev requests, with 11,078 Gemini-arm and 11,171 Mercury-arm input tokens, priced at $0.042/M with output free. Source collection is separate: **10 native Jev requests, 14,244 input tokens, $0.000598248**, including actual thumbnail eligibility review. One additional admitted-card locale-assessment request costs **$0.000026250** and is excluded from product-arm costs. Total metered AI captured-response pricing across the smoke test is **$0.020829026**. There are no observed usage-missing calls, but Google's exact cache-adjusted bill remains unknown. Public search/YouTube/Wikimedia charges and infrastructure are not metered here and are not assumed free. Prices are before credits, not invoices.

The [compact receipt aggregate](single-llm-comparison-2026-10-21.json) contains source/benchmark/catalog fingerprints, per-row profiles, native token ledgers, rejection codes, format warnings and exact cost arithmetic. Raw evidence remains unchanged at `/home/superdev/projects/.openmates-runtime/product-stack/test-results/d115-v8-single-writer-pair-20261021`. No additional calls, benchmarks, application changes or Plan edits were made for this report.
