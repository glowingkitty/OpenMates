# TypeSafe Jev decision API

OpenMates uses `typesafe/jev-1.13` through OpenRouter for internal, bounded decisions. Jev is not a chat-completions model: it evaluates a supplied text or structured `state` against named questions and returns typed `choice`, `noul` (yes/no probability), or `score` answers. It does not generate titles, suggestions, summaries, translations, arbitrary JSON, or answer prose.

## Current transport

- Endpoint: `POST https://openrouter.ai/api/alpha/decisions`
- Model: `typesafe/jev-1.13`
- Authentication: existing OpenRouter key at `kv/data/providers/openrouter` / `api_key`, with `SECRET__OPENROUTER__API_KEY` as the self-hosted environment fallback
- Request data: a bounded recent-message projection, an optional fresh chat summary carried as a separate `conversation_summary` state object labeled conversation data (never instructions), and only the minimized candidate catalogues required by the named decisions. Optional search ranking sends the user-stated relevance criteria, ranking-relevant search parameters, and minimized public result fields without account identifiers, chat identifiers, credentials, private-repository data, or private catalog data.
- Modalities: text or JSON-compatible structured state; no image, audio, video, or PDF input
- OpenRouter advertises a 32,000-token context limit. The client enforces a 30,000 estimated-input-token working budget, including state, question IDs, instructions, criteria and framing, plus the existing 80,000 state-character, 120,000 request-character and 160-question limits. TikToken's `cl100k_base` and `o200k_base` are proxies: the larger estimate and 2,000-token headroom (6.25 percent) reduce risk but cannot guarantee the undocumented native tokenizer's count. Encoding operations use bounded text fragments to avoid long repeated-string stalls. Provider context errors are typed as oversized input and never retried.
- Price observed for OpenRouter: $0.042 per million input tokens and no output-token charge

The provider client lives in `backend/shared/providers/typesafe/`. AI-pipeline code calls the decision helper in `backend/apps/ai/processing/jev_decisions.py`, while app skills use the shared bounded search-ranking helper in `backend/shared/python_utils/search_relevance.py`; neither path uses the normal chat-completions client. This boundary is intentional so a direct TypeSafe transport (`POST https://api.typesafe.ai/v1/systemone`, model alias `jev-latest`) can be added later without changing preprocessing, search ranking, or safety policy.

## Production uses and fallbacks

| Use | Jev result | Independent fallback |
| --- | --- | --- |
| Foreground preprocessing | tier, task area, topic, language, temperature band, skill/focus/memory/preview selections, icon, and safety scores | existing Gemini preprocessing model and its configured provider fallbacks |
| Request safety confirmation | allow/block/uncertain, category, action, and an exact evidence candidate selected from deterministic user-text spans | existing Mistral structured safety confirmation |
| External-content prompt injection | yes/no probability; safe content passes and high-confidence attacks block | GPT-OSS Safeguard for ambiguous decisions, exact-span redaction, and Jev outages |
| Postprocessing | assistant-response safety score and bounded app ranking | existing Gemini postprocessor fields |
| Optional search relevance | one score per bounded, deduplicated candidate using a skill-specific evidence rubric | unchanged pre-ranking provider order, followed by the requested public result limit |

Every Jev call is optional at the caller boundary. Transport errors, timeouts, malformed responses, missing answers, request-size limits, and task-specific confidence failures invoke a non-Jev path. The GPT-OSS sanitizer remains necessary because Jev cannot generate or quote arbitrary redaction spans.

Search relevance ranking runs only when a nonblank `relevance_criteria` value is present. Web uses at most two twenty-result Brave pages; news, events, video search, fitness location/class search, public code-repository search, and public 3D-model search rank up to 40 candidates. Maps, product search, and stay search rank up to 20 candidates so relevance ranking does not add a billable Google Places or SerpAPI page; housing uses its bounded merged provider pool. Hard filters and stable deduplication run before the decision. Each skill uses a separate rubric that only scores explicit result evidence appropriate to that domain. Repository ranking prioritizes explicit use-case, technology, license, and date fit over popularity and does not infer security, repository health, documentation quality, maintenance quality, or API compatibility. 3D-model ranking prioritizes explicit function, feature, license, file-format, and price fit over engagement and does not infer geometry quality, printability, or device compatibility. Candidate text is labeled untrusted, the decision can only reorder existing candidates, and every skill slices back to its requested `count`, `max_results`, `pageSize`, or `limit` before output safety, response serialization, or embed creation. Health appointment search is intentionally excluded because appointment availability is already a hard, time-sensitive ranking constraint rather than a broad discovery pool.

Jev's limit is local to decision processing. OpenMates does not compress the answer model's conversation to that limit. The Jev adapter keeps at most eight recent user/assistant messages and an optional 4,000-character summary. Older messages have bounded projections and yield before the complete latest user request. If essential state alone cannot fit, the caller uses its independent fallback.

The shared batcher partitions independent questions or candidate rows into at most eight requests, with at most three concurrent calls and a finite aggregate deadline. All batches are validated before inference; stable IDs must have complete, nonoverlapping responses. Search scores use the same absolute rubric and are sorted globally after merging. Workflow questions retain the entire selected graph: splitting its essential state would change the decision and is not permitted. Usage is summed across physical requests, with sizing logs containing counts rather than input text.

External-output safety shares one logical scan across at most eight physical batches. Every passage retains its source ID and neighboring context. Each batch uses one Jev gate and, when necessary, at most one GPT exact-span review, without retries and within the existing per-skill deadline. Replacements are applied only after complete coverage succeeds. Any failure preserves the existing ASCII-cleaned/unscanned policy; terminal output continues to withhold model text when unscanned. Inputs exceeding the bounded partition are never silently truncated.

## Title timing

Jev selects the initial icon but cannot generate title text. On the healthy path, preprocessing returns without a title and main answer inference starts immediately. The existing postprocessor generates the initial title after the first response and sends it in the existing `post_processing_completed.updated_chat_title` field. If Jev is unavailable, the generative preprocessing fallback may still generate the title before main inference as a degraded but reliable path.

## Verification

- Unit transport and schema tests: `backend/tests/test_typesafe_decisions.py`
- Preprocessing mapping tests: `backend/tests/test_preprocessor_jev.py`
- Safety and outage tests: `backend/tests/test_chat_request_safety.py`
- Prompt-injection confidence-band tests: `backend/tests/test_content_sanitization.py`
- Search relevance ranking and fallback tests: `backend/tests/test_search_relevance.py`
- Manual real-provider test entry point: `scripts/api_tests/test_typesafe_jev_api.py`
- Manual real search-ranking comparison: `backend/scripts/test_search_relevance_ranking.py` (run inside the API container)

Primary references: [TypeSafe API reference](https://docs.typesafe.ai/api), [TypeSafe models](https://docs.typesafe.ai/models), [TypeSafe legal and privacy documents](https://docs.typesafe.ai/legal), and [OpenRouter Jev model page](https://openrouter.ai/typesafe/jev-1.13).
