# Live cache verification — 2026-10-25

Provider/cache implementation `9cc730d1f5`, orchestration fixes `0e9e2a78fc`,
Together-primary update `dd9e7cf183`. Real cache hits were observed across 11 cloud
hosts and 12 model paths. Root/child/grandchild execution, fresh saved-descendant
turns, the maximum depth and the 14-receipt wallet reconciliation passed.

Direct provider adapter probes used synthetic reference text, real credentials and real network requests, with replay/mock mode off. No OpenMates chat model/provider overrides or account model-default changes were used. Each tested provider received a non-streaming request followed by a streaming request with the same prefix. Only numeric usage and sanitized error classifications were retained.

| Provider path | Model | Repeated input | Cache read | Read share |
| --- | --- | ---: | ---: | ---: |
| anthropic | anthropic/claude-haiku-5-5 | 15,087 | 15,071 | 99.9% |
| aws_bedrock | anthropic/claude-sonnet-4-6 | 11,876 | 11,866 | 99.9% |
| cerebras | openai/gpt-oss-120b | 10,741 | 10,624 | 98.9% |
| google | google/gemini-3.8-flash | 12,977 | 8,168 | 62.9% |
| google_ai_studio | google/gemini-3.8-flash | 12,979 | 10,929 | 84.2% |
| groq | openai/gpt-oss-safeguard-20b | 10,741 | 10,496 | 97.7% |
| inception | inception/mercury-3 | 10,712 | 10,394 | 97.0% |
| mistral | mistral/mistral-small-latest | 12,994 | 12,976 | 99.9% |
| openai | openai/gpt-6-luna | 10,677 | 10,674 | 100.0% |
| openrouter | deepseek/deepseek-v4.1-flash | 11,099 | 11,008 | 99.2% |
| together | moonshot/kimi-k3 | 10,763 | 10,624 | 98.7% |
| together | deepseek/deepseek-v4.1-flash (1017) | 11,098 | 11,008 | 99.2% |

All **11 tested cloud hosts** reported a live hit across **12 model paths**. There were 31 bounded direct-provider requests, including failed legacy/preview routes and the later Together tool round trip. The ratios above describe these controlled repeated-prefix probes, not a guaranteed application-wide hit rate.

OpenAI, Anthropic and Bedrock also reported a positive cache-write count on the initial request and a cache read on the repeated request. Missing implicit cache counters remained unknown instead of being replaced with zero.

Cerebras initially rejected the retired Qwen 235B route with HTTP 404; its current GPT-OSS 120B route passed. Together rejected the old Kimi K2.7 Code route with HTTP 400 and the tested Qwen preview with HTTP 403; the current Kimi K3 catalog route passed. These route availability findings were not counted as cache passes or repaired as unrelated catalog work.

Direct Baseten remains untested at the user’s request until its key is configured. Google MaaS has no registered model route in this environment. Local compatible endpoints were outside these live cloud probes; neither is established by the results above.

## Live OpenMates billing and orchestration

The application run used a fresh disposable account, client encryption and TOTP, an isolated CLI state directory, a new test Project and automatic routing. Its bounded 1,000-credit development fixture grant went through the internal billing ledger; encrypted balances were not patched. No real user account or Project was used for inference.

The first four normal chat turns consumed 66 credits. Saved usage summed to 66, every receipt matched an independent rational calculation from its frozen category rates, and held credits returned to zero. Automatic routing selected Mercury 3 and Gemini 3.8 Flash; cache reads were observed in application receipts. Missing Gemini cache counters correctly selected ordinary-input billing.

The approved fixes expose one remaining delegation level to an initial child,
while grandchildren, resumed orchestrations and fresh user turns in saved
descendants cannot spawn further children. Worker admission re-reads owned,
immutable database ancestry, including for reconstructed queues and async/focus
resumes. An edited client parent/depth field cannot reset the physical depth.
The authoritative transaction rejects depth-three preparation and re-rooting an
existing child, even if an older root record declares a larger maximum depth.

A real root → child → grandchild QA run completed the grandchild report, child
synthesis and root synthesis. That orchestration spent 417 credits with zero
reserved credits and exactly two descendants. The earlier one-child orchestration
spent 215 with zero reserved. A new user message in a completed saved child
completed and charged 64 credits at depth one under the original root, without
reopening its old delegated job. A new user message in the grandchild requested
another child: it answered that the tool was unavailable, spawned none, and
charged 51 credits at depth two. Database traversal confirms no depth-three node.
Fresh user turns use ordinary wallet admission, retaining root attribution;
they do not reuse a historical autonomous turn's reservation or dispatch token.

**Final owner-visible verification:** 14 unique receipts were independently
repriced with rational arithmetic from their frozen rates. They sum to **813
credits**, exactly matching the disposable wallet's **1,000 → 187** change.
Held credits and both orchestrations' reserved credits are zero. Real descendant
Gemini calls did not report cache counters and correctly used ordinary-input
billing; do not describe those calls as demonstrated discounted cache hits.
The isolated product proof separately verifies discounted root/child/grandchild
receipts with controlled provider counters, replay idempotency and owner access.

The globally installed CLI release `6ee143c7` predates existing encrypted-wrapper
race repair `51d45817f3`. It rejected recovery acknowledgement after all three
backend stages had already finished. A private current-source CLI build recovered
the same saved outputs without new inference: all 15 existing typed outputs were
ACKNOWLEDGED and none remained pending. The root's final synthesis was readable.
No new client product fix or unsafe key-mismatch bypass was needed.

## Together V4.1 Flash primary validation

The user requested this host change only after a brief real test. Six Together
requests used the documented October 17 snapshot and the real existing key,
with mock/replay off: four text/stream requests and a two-request function-call
round trip. Initial cold/warm cached counts were 0 and 11,008/11,098; the updated
adapter's repeated request returned the same hit count in 0.320 seconds. A real
function call, synthetic tool result and final answer also completed, reporting
6,272/6,364 cached input tokens on the follow-up. These short requests are not
proof of sustained 280 tokens/second throughput.

Together is primary, OpenRouter is the first fallback on the previously reviewed
Baseten snapshot, and optional direct Baseten remains supported afterward. The
adapter accepts Together V4.1's documented integer reasoning effort 1–100,
preserves returned reasoning chunks for tool loops, and classifies connection
failures for fallback. Supplier cached-input costs are host-specific: Together
USD 0.006/M; Baseten and the pinned gateway USD 0.007/M. The shared customer
cache tariff remains unchanged and conservative for both hosts.

Sources: [Together model and tariff](https://www.together.ai/models/deepseek-v4-1-flash-1017),
[Together cache semantics](https://docs.together.ai/docs/inference/chat/prompt-caching).

## Verification scope

Focused orchestration checks: 216 Python tests and 22 transaction tests passed.
The subsequent Together-focused suite passed 101 tests, including both direct
hosts' missing-key/403/429/connection fallbacks, numeric wire controls, reasoning
chunks, usage-only cache events and supplier rates. The isolated nested ledger
case passed on source `8ad06807a1a995565125a033b3a25e5e46898213`
([run 40186494953](https://github.com/glowingkitty/OpenMates/actions/runs/40186494953));
the final three-host variant passed on source `4cc87f9cc16b2e05fb2e4857021240c6f9127230`
([run 40188591963](https://github.com/glowingkitty/OpenMates/actions/runs/40188591963)).
Both published frontend builds passed, and the loaded API primary/fallback/cache
host configuration plus adapter file hash matched the deployed source. Baseten live inference,
unregistered MaaS and local endpoints retain the explicit limits above.

| Accepted outcome | Evidence | Result |
| --- | --- | --- |
| Direct Together Flash 1017, cache counters and fallback | Six live component requests; 101 focused tests; deployed configuration | Passed |
| Child delegation and hard grandchild ceiling | Real three-level execution; grandchild user turn with no spawn; transaction negatives | Passed |
| Fresh saved-child admission and encrypted completion | Live child follow-up; current CLI acknowledged all retained outputs without new inference | Passed |
| Correct cache tariffs and nested ledger | 14 independently repriced live receipts; final isolated three-host ledger proof | Passed |
| Privacy, metadata and documentation | Scoped lint, metadata generators, Plan validation and complete-phase verification | Passed |

Direct Baseten's live key test is deferred by explicit user instruction. The
installed global CLI remains older than an existing recovery repair; the verified
current source build was used for recovery and the final grandchild/receipt views.
