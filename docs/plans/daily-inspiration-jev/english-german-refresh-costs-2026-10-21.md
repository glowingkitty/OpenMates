# English/German refresh costs — 2026-10-21

The corrected live generation probe delivered a complete English refresh and an incomplete German refresh. It exercised the actual generation functions with public benchmark inputs and no account/pool writes. All twelve application source hashes matched the reviewed runtime manifest. The [native-response ledger](english-german-refresh-costs-2026-10-21.json) pins the receipts and separates writer, Jev, semantic-review and search costs.

| Workload | Video / wiki / static tips | Duration | Captured-response inference estimate | Gross search | Recorded-response estimate + search |
| --- | ---: | ---: | ---: | ---: | ---: |
| Original pre-Jev/pre-Mercury, EN, declared 30s cap | 1 / 2 / 4 | 32.255s | $0.003906930 | $0.015 | $0.018906930 |
| Original pre-Jev/pre-Mercury, JA, declared 30s cap | 0 / 2 / 4 | 37.545s | $0.004639380 | $0.015 | $0.019639380 |
| Corrected current, EN | **3 / 3 / 4** | 202.658s | $0.044215606 | $0.015 | **$0.059215606 + unpriced cancellations** |
| Corrected current, DE | **1 / 3 / 4** | 60.942s | $0.027219968 | $0.015 | **$0.042219968** |

Google cache counters are absent in all thirteen captured current SDK responses. Their component prices therefore use an uncached upper estimate. English additionally has **three semantic-review cancellations**, each near thirty seconds, without a native response or usage. Their spend is unknown, not zero. The English number is an upper estimate for captured responses only, **not an upper bound on all attempted spend**. German has no observed canceled call. These are supplier tariff estimates before credits, not invoices or complete operating costs.

## Current components and paid failures

| Component | EN | DE |
| --- | ---: | ---: |
| Mercury writer, launch rates | $0.003225980 | $0.004768820 |
| Gemini 3.5 Flash Lite writer, uncached estimate | $0.001529000 | $0.002621100 |
| Jev 1.14 source/copy/image decisions | $0.002682876 | $0.003528798 |
| Gemini 3.8 Flash semantic review, captured responses | $0.036777750 | $0.016301250 |
| Brave discovery, gross catalog | $0.015000000 | $0.015000000 |

English makes five writer attempts (four Mercury, one Gemini 3.5), ten semantic attempts (seven responses, three cancellations) and twenty-eight Jev requests. German makes four writer attempts (three Mercury, one Gemini 3.5), four semantic attempts and twenty-three Jev requests. Semantic calls are not writer attempts. Observed models are `mercury-3`, `gemini-3.5-flash-lite`, `jev-1.14.0` and `gemini-3.8-flash`.

Both German Mercury video drafts end at `length` and fail tool parsing. Their HTTP 200 native responses still record paid usage: **$0.001810290 + $0.001842690 = $0.003652980** at launch rates. Facade usage drops these counters; this report recovers them from the raw responses. Every native response is priced once. Shared Jev accounting slices are never summed, and SDK/HTTP/facade views are not added together. Mercury completion tokens already include reasoning. Gemini semantic review includes 6,616 EN and 2,437 DE thinking tokens in addition to candidate output.

The German two-video shortfall is not a terminal writer failure: the final fallback supplies all three video-copy rows. Parent source review identifies two videos from 2017/2019 excluded by the existing five-year science age cap after writing. Earlier age checks or discovery of recent replacements are the relevant improvement; these costs do not justify relaxing the age policy.

The two corrected samples together admit ten generated cards and eight static tips. Their captured-response-plus-search estimate is **$0.101435574**, plus unknown English cancellation spend. At regular Mercury rates, holding the same tokens/cache hits and all Google/Jev/search rates fixed, the estimates become **$0.062441586 EN** and **$0.046988788 DE**; the English unknown remains. This is a tariff sensitivity, not another run or a spend forecast. Gemini 3.8 uses introductory rates through December 31, 2026: $0.75/M input, $0.075/M cached input and $3.75/M output including thinking. Other rates are retained in the JSON and receipt tariff snapshots; [official Google pricing](https://ai.google.dev/gemini-api/docs/pricing) supports the introductory rate basis.

Allocating all captured work and gross search across admitted generated cards gives $0.009869268 EN and $0.010554992 DE per admission; English cancellation spend is additional. These are allocation units for these attempts, not prices for independent successful card requests. The original English replay's equivalent allocation is $0.006302310 across only three generated admissions. None of these figures proves a saving or a like-for-like quality comparison.

## What the historical baseline supports

The actual original architecture is revision `c94ebe85a14f87aa3223eacfe129aa85ec93d939`, before Jev and Mercury introduction. All classification/writing/adversarial-validator roles request `mistral/mistral-small-latest`; normal complete generation has eight logical Mistral roles, three searches, six generated cards and four static tips. It is **not** the later Gemini-only plus Jev control. See the [baseline reconstruction](pre-jev-baseline-2026-10-21.md) and [retained original native aggregate](full-refresh-costs-2026-10-21.json).

The table uses a declared thirty-second historical deadline sensitivity, preserving original content/model roles. Exact original five-second timing had eight cancellations. Neither historical sample produced a complete ten-card refresh, and no historical German replay exists. Current EN versus historical EN has different fresh sources and admission counts; current EN/DE versus historical EN/JA is not a paired locale comparison. The historical replay uses measured native tokens and retained tariffs, not an original production invoice or proof of immutable historical alias weights. A successful original ten-card price, monthly savings and full twenty-language costs cannot be inferred.

## Failed first integration probe, kept separately

`d115-v7-final-refresh-20261021` is an **invalid working-after/qualification sample**. An unsupported `observability_purpose` caused all twenty-six semantic seam calls to raise `ValueError` before provider dispatch. Neither locale admitted generated cards; each delivered four static tips. No Gemini 3.8 provider call was recorded. Its actual other paid work must still be retained:

| Failed integration sample | Mercury launch | Gemini 3.5 uncached estimate | Jev | Gross Brave | Recorded-response total |
| --- | ---: | ---: | ---: | ---: | ---: |
| EN | $0.004618910 | $0.003725600 | $0.003271128 | $0.015 | $0.026615638 |
| DE | $0.005461010 | $0.004219700 | $0.003941574 | $0.015 | $0.028622284 |

Combined failed integration work is **$0.055237922** at launch rates, using uncached Google estimates; exact Google cache cost remains unknown. Two paid Mercury responses missing facade usage are included. This cost is not merged into the corrected workflow's per-refresh price. It is also distinct from the earlier invalid fixture-label semantic diagnostic documented in [optimization diagnostics](optimization-diagnostics-2026-10-21.md).

Static feature templates and reading an already shared/cached card have zero marginal inference calls. This probe disables separate public-pool revalidation; shared discovery, background pool review/default selection and actual eligible-user volume are separate costs. It does not measure public daily spend per user. Gross Brave pricing is $5/1,000 successful requests before shared account credits. YouTube/Wikimedia monetary bills, storage, serving and infrastructure costs are unmeasured. Production admission gates do not replace independent review of these fresh cards. No additional calls, benchmarks, deployment or Plan changes were performed for this analysis.

Corrected evidence root: `/home/superdev/projects/.openmates-runtime/product-stack/test-results/d115-v7-corrected-refresh-20261021`. The JSON includes exact source/receipt hashes, all native billable-response ledger entries and unpriced cancellations.
