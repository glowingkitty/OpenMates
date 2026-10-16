# Fastino decision models compared with OpenMates Jev

Measured on the dev server on 2 October 2026, using synthetic inputs and the current production request builders. Keep Jev for the existing preprocessing and decision paths. GLiDE matched the hand-labeled expectations in this sample but increased latency and cost; the cheaper hosted GLiNER model did not preserve the required decisions or full request contract.

## Verified prices and published claims

| Model | Input per million tokens | Output per million tokens | Relative input rate |
| --- | ---: | ---: | ---: |
| Jev 1.13 through OpenRouter | $0.042 | $0 | 1.00× |
| Fastino GLiDE | $0.30 | $0 | 7.14× |
| Fastino GLiNER-2.5-Decide | $0.03 | $0 | 0.71× |

Prices were verified against the live Fastino `/v1/base-models` catalog and OpenRouter model endpoint metadata. Fastino’s pricing page also lists Decide at $0.03, while its static model-catalog documentation lists $0.15; the live catalog is the basis of the estimates below. Estimates use returned input-token usage and published rates, exclude fallback calls and account funding fees, and have not been reconciled against an invoice.

GLiDE reports Decision Index 0.2.1 skill 64.81 versus Jev’s published 57.91, with leads on 31 of 38 benchmarks. These are Fastino’s reported results, and its announcement says GLiDE is not yet on the public leaderboard. The cheaper GLiNER-Decide reports 60.1% versus 57.5% for **JevK5**, an open reproduction, on its own 17-dataset Fast Decisions suite. That comparison does not establish a win over TypeSafe Jev 1.13.

## Full request workloads: Jev and adapted GLiDE

All 56 application workloads met the 105 hand-labeled assertions for both models. That is selective ground truth, not a claim that every returned field was correct: tool, focus, memory and app recommendation selections were generated but not exhaustively graded. The 12 compact routing controls add 49 assertions; both models also met all of those.

| Area | Cases | Jev p50 / p95 | GLiDE p50 / p95 | Jev cost / 1,000 calls | GLiDE cost / 1,000 calls |
| --- | ---: | ---: | ---: | ---: | ---: |
| Full preprocessing | 12 | 0.418s / 0.664s | 3.771s / 4.144s | $0.7230 | $7.0280 |
| Request safety | 6 | 0.298s / 0.571s | 6.920s / 19.782s | $0.0562 | $0.6501 |
| Prompt injection | 6 | 0.251s / 0.310s | 1.191s / 1.678s | $0.0168 | $0.0481 |
| Postprocessing | 4 | 0.245s / 0.256s | 2.039s / 2.160s | $0.0897 | $1.4950 |
| Workflow Check | 6 | 0.263s / 0.324s | 1.496s / 3.063s | $0.0244 | $0.1321 |
| Workflow authoring validation | 4 | 0.262s / 0.290s | 1.167s / 1.583s | $0.0176 | $0.0465 |
| Workflow skill preselection | 2 | 0.366s / 0.368s | 2.578s / 2.702s | $0.4822 | $4.3716 |
| Search ranking: 13 profiles, 2 candidates | 13 | 0.261s / 0.452s | 1.482s / 24.574s | $0.0348 | $0.4448 |
| Search ranking: 20/40 candidates | 3 | 0.312s / 0.372s | 3.310s / 3.833s | $0.2900 | $19.4120 |

Full preprocessing used 104–105 questions with the available skill/focus catalog and two synthetic memory categories. Jev took a median 0.418s; GLiDE took 3.771s, about 9.0× longer. Their estimated per-request costs differed by 9.72× because GLiDE also reported more billable input tokens. Ten of twelve GLiDE responses exceeded the current 3-second Jev client timeout. These were successful responses under a 300-second research timeout; they would not all complete under the current runtime limit.

Request-safety GLiDE responses ranged up to 19.8s. Search-ranking responses ranged up to 24.6s. Primary-call eligibility also depends on confidence and exact evidence validation: Jev cleared those checks in 5/6 safety cases and GLiDE in 4/6, despite both choosing the correct allow/block label. The existing fallback is still needed. No fallback model was invoked in this benchmark.

The original Jev request fails at GLiDE with HTTP 422 when `instructions` is an object. The benchmark converts these objects to JSON strings without losing their contents. GLiDE also returns an integer winning `score`; the benchmark uses `expected_level` to preserve Jev’s continuous score semantics. The product provider configuration was not switched.

## Cheaper hosted GLiNER-Decide

GLiNER-Decide uses `/v1/chat/completions` classification schemas rather than `/v1/systemone`. The full 105-question preprocessing, 43-question postprocessing and 36-question workflow preselection schemas returned HTTP 400 because the schema exceeds the hosted context limit. Its live catalog lists 8,192 tokens and the model card describes an English checkpoint. A shared API envelope does not imply identical decision capabilities.

To give the hosted classifier a smaller documented workload, the final comparison used short semantic task names, descriptive plain-string labels, and readable conversation text for routing. Each compact request contained only the hand-labeled heads. Local model-card features were probed separately: the hosted API explicitly rejected both per-task `prompt` fields and dictionary label descriptions. A separate earlier adapter retaining full instructions in task names was also tried; neither adapter established a general replacement for Jev.

| Compact routing controls | Jev | GLiDE | GLiNER-Decide |
| --- | ---: | ---: | ---: |
| Correct hand-labeled fields | 49/49 | 49/49 | 37/49 |
| Cases with all fields correct | 12/12 | 12/12 | 5/12 |
| Median HTTP latency | 0.245s | 1.441s | 0.751s |
| Estimated cost / 1,000 calls | $0.0367 | $0.2002 | $0.0007 |

The encoder misclassified several safe coding/defensive requests as harmful, treated using an assistant as discussing language models, and selected German for an English instruction containing quoted German. On the other small adapted tasks it passed 6/6 prompt-injection examples, 2/4 workflow authoring labels, 1/12 Workflow Check fields, 0/6 request-safety labels, and 1/13 ranking comparisons. These results evaluate the tested hosted adapters, not the locally deployable checkpoint with its richer schema support or a fine-tuned classifier.

Classification confidence is a winning-label score rather than the complete calibrated Noul/Choice/Score response expected by current callers. Matching a label alone does not prove it can use the existing probability thresholds. The six prompt-injection controls are too small to justify changing safety routing.

## Method and limits

- Final matched passes: 21 full/schema-size workloads for Jev and GLiDE, then 47 smaller workloads for all three. The smaller set contains 12 compact routing controls. The final comparison is one matched pass per workload; an earlier two-pass attempt was stopped after repeated schema rejections. Its receipts are retained separately and excluded from the headline tables.
- Sequential HTTP requests from the same dev host, shared warm HTTP client, rotated model order, no transport retries. Timings include network and provider execution, but exclude credential retrieval and deterministic request construction. Requests used a 300-second research timeout; the 3-second runtime budget was measured separately.
- All cases are synthetic. Search rubrics come from all 13 production profiles. The 20/40-candidate scaling controls alternate explicit direct-fit/conflicting projections with unique fixture IDs; they are schema/load probes, not real retrieval-quality evaluations.
- Ground truth covers language, task area, selected risk/model/topic flags, allow/block, injection labels, broad safety score bands, workflow controls and simple ranking comparisons. It does not measure nuanced dialogue quality, every selection head, calibrated probabilities, title generation, real search recall, concurrency, long-chat performance, or production fallback costs.
- The displayed p95 values use nearest-rank quantiles of very small samples and are illustrative; the 2–6-case groups mostly show the largest observation. They are not production tail-latency estimates.
- Production request-builder SHA-256 digests and per-request payload digests are saved in the JSON receipts and matched the reviewed source. No private chats, user identifiers, credentials or provider authorization headers were recorded.

## Recommendation

Retain Jev for current preprocessing, safety, search ranking and workflows. GLiDE’s higher published benchmark score did not produce a measured quality gain on these labeled controls, while it exceeded the latency budget and increased costs. Hosted GLiNER-Decide is a real cheaper option for narrow English classification, but this comparison does not support replacing the existing arbitrary-context decisions. A future experiment could evaluate a bespoke small classifier or local/fine-tuned Decide separately; it would need its own held-out corpus and compatibility design.

## Archived experiment

The temporary Fastino benchmark harness, fixtures and tests were removed after the decision to retain Jev. This report and the synthetic raw receipts on dev at `test-results/decision-benchmark-2894/` preserve the measured results. Event specialist routing and additional workflow planning paths were identified but not benchmarked before the experiment was stopped.

Sources: [Fastino live model catalog](https://api.fastino.ai/v1/base-models), [Fastino pricing](https://docs.fastino.ai/pricing), [Fastino static catalog](https://docs.fastino.ai/concepts/models), [OpenRouter Jev](https://openrouter.ai/typesafe/jev-1.13), [GLiDE announcement](https://fastino.ai/blog/introducing-glide-the-first-thinking-decision-model), [GLiNER-Decide announcement](https://fastino.ai/blog/gliner-2-5-decide-open-weight-decision-model), [GLiDE migration contract](https://docs.fastino.ai/inference/systemone), [hosted GLiNER contract](https://docs.fastino.ai/inference/chat-completions), [GLiNER-Decide model card](https://huggingface.co/fastino/GLiNER2.5-Decide).
