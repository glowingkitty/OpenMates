# TypeSafe Jev decision API

OpenMates uses Jev 1.13 directly through TypeSafe AI as the primary provider for internal, bounded decisions, with OpenRouter as an availability fallback. The internal catalogue and billing ID remains `typesafe/jev-1.13`. Jev evaluates text or structured `state` against named questions and returns typed `choice`, `noul` (yes/no probability), or `score` answers. It does not generate titles, suggestions, summaries, translations, arbitrary JSON, or answer prose.

## Current transport

- Primary: `POST https://api.typesafe.ai/v1/systemone`, pinned model `jev-1.13.0`. Authentication: Vault `kv/data/providers/typesafe` / `api_key`, then environment `SECRET__TYPESAFE__API_KEY`.
- Availability fallback: `POST https://openrouter.ai/api/alpha/decisions`, model `typesafe/jev-1.13`. Authentication: Vault `kv/data/providers/openrouter` / `api_key`, then environment `SECRET__OPENROUTER__API_KEY`.
- Both transports use Bearer authentication and never reuse another provider's key. TypeSafe receives no OpenRouter attribution headers. Pinning the version preserves the current decision thresholds rather than following `jev-latest`.
- Request data: a bounded recent-message projection, an optional fresh chat summary carried as a separate `conversation_summary` state object labeled conversation data (never instructions), and only the minimized candidate catalogues required by the named decisions. Optional search ranking sends the user-stated relevance criteria, ranking-relevant search parameters, and minimized public result fields without account identifiers, chat identifiers, credentials, private-repository data, or private catalog data.
- Modalities: text or JSON-compatible structured state; no image, audio, video, or PDF input
- OpenRouter advertises a 32,000-token context limit. The client enforces a 30,000 estimated-input-token working budget, including state, question IDs, instructions, criteria and framing, plus the existing 80,000 state-character, 120,000 request-character and 160-question limits. TikToken's `cl100k_base` and `o200k_base` are proxies: the larger estimate and 2,000-token headroom (6.25 percent) reduce risk but cannot guarantee the undocumented native tokenizer's count. Encoding operations use bounded text fragments to avoid long repeated-string stalls. Provider context errors are typed as oversized input and never retried.
- Published TypeSafe Jev 1.13 price: $0.042 per million input tokens and no output-token charge (verified 2026-10-06), matching the existing OpenRouter rate. TypeSafe documents 100,000 tokens/second and 80 requests/second, subject to change. Its context limits are 64,000 tokens overall and 32,000 for state plus the longest question; the common conservative budget remains unchanged for fallback compatibility.

The provider client lives in `backend/shared/providers/typesafe/`. AI-pipeline code calls the decision helper in `backend/apps/ai/processing/jev_decisions.py`, while app skills use the shared bounded search-ranking helper in `backend/shared/python_utils/search_relevance.py`; neither path uses the normal chat-completions client. The transport switch preserves the public API/client contracts and decision shapes.

Missing or rejected credentials (401/403), transport timeouts, and exhausted transient failures (408/425/429/500/502/503/504/529) try OpenRouter after TypeSafe. Each provider retains bounded retries with exponential backoff capped at 0.5 seconds and bounded `Retry-After`; HTTP requests honor the configured timeout even with an injected client. Request-size errors, other rejected requests, invalid schemas, and missing answers do not resend to OpenRouter: callers keep their independent non-Jev fallback. Existing aggregate batch/caller deadlines remain in force. Logs retain counts and provider names, never private input or provider error bodies. Explicit provider probes disable failover so a missing TypeSafe key cannot produce a false direct-provider pass.

## Configure the API key

Run on the target server; the first command prompts without displaying the key:

```bash
openmates server env set SECRET__TYPESAFE__API_KEY --path /home/superdev/projects/OpenMates
openmates server start --services vault-setup --path /home/superdev/projects/OpenMates
```

For another installation, replace `--path` with its canonical installation directory. Vault setup imports the value into `kv/data/providers/typesafe` as `api_key` and replaces the inline `.env` value with its existing import marker. API/worker secret loading reads that Vault path; OpenRouter remains usable until the TypeSafe key is supplied. Do not pass the key as a command-line argument.

## Direct-provider contract

Request: `{"model":"jev-1.13.0","state":"A harmless greeting","questions":{"safe":{"type":"noul","instructions":"Is this harmless?"}}}`.

A compatible response is `{"model":"jev-1.13.0","answers":{"safe":{"type":"noul","noul":0.95}},"usage":{"input_tokens":40,"output_tokens":8}}`, parsed into `DecisionResponse` with `NoulAnswer` and nonnegative usage counts. Choice and Score retain their existing typed schemas. Incomplete or malformed answers are rejected. No additional skill/client fields are introduced.

## Privacy

TypeSafe AI, Inc. hosts its services in the US and states it does not train or fine-tune models on submitted input. Zero data retention is a separate enterprise offering, not an assumption for this integration. The [TypeSafe privacy policy](https://typesafe.ai/legal/privacy-policy) was verified on 2026-10-06. OpenMates discloses direct TypeSafe processing and conditional OpenRouter fallback with the same minimized data categories.

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
