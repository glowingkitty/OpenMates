# TypeSafe Jev decision API

OpenMates uses Jev 1.14 directly through TypeSafe AI as the primary provider for internal, bounded decisions, with OpenRouter as a text-only availability fallback. Public `ai.decide` also supports experimental inline image decisions through direct TypeSafe. The internal catalogue and billing ID remains `typesafe/jev-1.14`. Jev evaluates text or structured `state` against named questions and returns typed `choice`, `noul` (yes/no probability), or `score` answers. It does not generate titles, suggestions, summaries, translations, arbitrary JSON, or answer prose.

## Current transport

- Primary: `POST https://api.typesafe.ai/v1/systemone`, pinned model `jev-1.14.0`. Authentication: Vault `kv/data/providers/typesafe` / `api_key`, then environment `SECRET__TYPESAFE__API_KEY`.
- Availability fallback: `POST https://openrouter.ai/api/alpha/decisions`, model `typesafe/jev-1.14`. Authentication: Vault `kv/data/providers/openrouter` / `api_key`, then environment `SECRET__OPENROUTER__API_KEY`.
- Both transports use Bearer authentication and never reuse another provider's key. TypeSafe receives no OpenRouter attribution headers. Pinning the version preserves the current decision thresholds rather than following `jev-latest`.
- Request data: a bounded recent-message projection, an optional fresh chat summary carried as a separate `conversation_summary` state object labeled conversation data (never instructions), and only the minimized candidate catalogues required by the named decisions. Optional search ranking sends the user-stated relevance criteria, ranking-relevant search parameters, and minimized public result fields without account identifiers, chat identifiers, credentials, private-repository data, or private catalog data.
- Modalities: text or JSON-compatible structured state. Public `ai.decide` additionally accepts bounded PNG/JPEG image assets; audio, video, PDF, remote image URLs, and stored-upload references are not accepted through this inline interface.
- Text decisions retain the client's conservative 30,000 estimated-input-token working budget, including state, question IDs, instructions, criteria and framing, plus the existing 80,000 state-character, 120,000 request-character and 160-question limits. TikToken estimates are proxies rather than the provider's native token count. Provider context errors are typed as oversized input and never retried. OpenRouter's Jev 1.14 catalogue context ceiling is 262,144 tokens; this larger ceiling informs conservative accounting, not a larger public input allowance.
- TypeSafe lists `jev-1.14.0` at $0.042 per million input tokens with no output-token charge, a default 64k per-request context, and 32k per-question context. OpenMates pins the version rather than following a moving alias; it does not enable TypeSafe's separate experimental long-context mode. See [TypeSafe models](https://docs.typesafe.ai/models) (checked 2026-10-19).

The provider client lives in `backend/shared/providers/typesafe/`. AI-pipeline code calls the decision helper in `backend/apps/ai/processing/jev_decisions.py`, while app skills use the shared bounded search-ranking helper in `backend/shared/python_utils/search_relevance.py`; neither path uses the normal chat-completions client. The transport switch preserves the public API/client contracts and decision shapes.

The public `ai.decide` skill accepts at most 16 questions and 16,384 UTF-8 bytes
of normalized state and questions, independently of image data. Routing is
server-selected, with no retries: text permits at most one TypeSafe attempt plus
one OpenRouter fallback; image requests permit one direct TypeSafe attempt only.
The server reserves the reviewed native context ceilings against the anonymous
free budget before dispatch and settles server-reported input usage, including
image tokens. A failed public decision returns a typed provider failure instead
of substituting an unrelated model. See [REST access and inline decisions](../architecture/apps/rest-api.md#inline-decisions).

## Experimental inline images

`ai.decide` accepts an optional `assets` map. Each entry has `type: "image"`,
`format: "png"`, `"jpg"`, or `"jpeg"`, and `data_base64` containing standard
base64 file bytes. Use a canonical lowercase UUID as the entry key and put that
reference in a string value in `state`, question instructions, or criteria.
Every asset must be referenced; object keys are not image references. OpenMates
sets `TypeSafe-Danger-Zone-Images: true` on the direct provider call, so callers
need no provider key or header. The provider describes this feature as suitable
for prototypes and subject to change. See [TypeSafe images](https://docs.typesafe.ai/images).

OpenMates applies its own smaller public limits: four still images, 1 MiB of
decoded bytes per image, 4 MiB decoded in total, and 6 MiB for the complete JSON
body. Both image dimensions must be 280–1568 pixels. Validation checks the actual
PNG/JPEG content, not just the extension or supplied format. The 16 KiB state and
questions limit remains separate. Prepare images locally; the service neither
fetches remote image URLs nor creates a stored upload. Existing account-required
upload flows are unchanged. Supported public question types remain `noul`,
`choice`, and `score`; provider support for Box is not an OpenMates API promise.

Image requests never fall back to OpenRouter. Missing direct credentials or
provider failure returns a safe failure, and the reservation accounts for
potentially incurred provider usage. Transient OpenMates processing does not
imply zero retention by TypeSafe.
For text-only requests, missing or rejected credentials (401/403), transport timeouts, and exhausted transient failures (408/425/429/500/502/503/504/529) try OpenRouter after TypeSafe. Each provider retains bounded retries with exponential backoff capped at 0.5 seconds and bounded `Retry-After`; HTTP requests honor the configured timeout even with an injected client. Request-size errors, other rejected requests, invalid schemas, and missing answers do not resend to OpenRouter: callers keep their independent non-Jev fallback. Existing aggregate batch/caller deadlines remain in force. Logs retain counts and provider names, never private input or provider error bodies. Explicit provider probes disable failover so a missing TypeSafe key cannot produce a false direct-provider pass.

## Configure the API key

Run on the target server; the first command prompts without displaying the key:

```bash
openmates server env set SECRET__TYPESAFE__API_KEY --path /home/superdev/projects/OpenMates
openmates server start --services vault-setup --path /home/superdev/projects/OpenMates
```

For another installation, replace `--path` with its canonical installation directory. Vault setup imports the value into `kv/data/providers/typesafe` as `api_key` and replaces the inline `.env` value with its existing import marker. API/worker secret loading reads that Vault path; OpenRouter remains usable until the TypeSafe key is supplied. Do not pass the key as a command-line argument.

## Direct-provider contract

Request: `{"model":"jev-1.14.0","state":"A harmless greeting","questions":{"safe":{"type":"noul","instructions":"Is this harmless?"}}}`.

A compatible response is `{"model":"jev-1.14.0","answers":{"safe":{"type":"noul","noul":0.95}},"usage":{"input_tokens":40,"output_tokens":8}}`, parsed into `DecisionResponse` with `NoulAnswer` and nonnegative usage counts. Choice and Score retain their existing typed schemas. Incomplete or malformed answers are rejected. The public skill wraps these answers in `data.answers`; its optional `assets` field carries inline images.

## Privacy

TypeSafe AI, Inc. hosts its services in the US and states it does not train or fine-tune models on submitted input. Zero data retention is a separate enterprise offering, not an assumption for this integration. The [TypeSafe privacy policy](https://typesafe.ai/legal/privacy-policy) was verified on 2026-10-06. OpenMates discloses direct TypeSafe processing and conditional text-only OpenRouter fallback. Public `ai.decide` sends caller-supplied state, questions, and any inline images to TypeSafe; the caller should minimize these inputs. Images do not use OpenRouter fallback. Inline image bytes are not covered by typed-message placeholder substitution. OpenMates does not create saved chats, embeds, or stored uploads for these decisions; that does not promise zero provider retention.

## Production uses and fallbacks

| Use | Jev result | Independent fallback |
| --- | --- | --- |
| Foreground preprocessing | tier, task area, topic, language, temperature band, skill/focus/memory/preview selections, icon, and safety scores | existing Gemini preprocessing model and its configured provider fallbacks |
| Request safety confirmation | allow/block/uncertain, category, action, and an exact evidence candidate selected from deterministic user-text spans | existing Mistral structured safety confirmation |
| External-content prompt injection | yes/no probability; safe content passes and high-confidence attacks block | GPT-OSS Safeguard for ambiguous decisions, exact-span redaction, and Jev outages |
| Postprocessing | assistant-response safety score and bounded app ranking | existing Gemini postprocessor fields |
| Optional search relevance | one score per bounded, deduplicated candidate using a skill-specific evidence rubric | unchanged pre-ranking provider order, followed by the requested public result limit |

Internal Jev calls are optional at the caller boundary; public `ai.decide` returns a typed failure instead of using the independent generative fallbacks below. Transport errors, timeouts, malformed responses, missing answers, request-size limits, and task-specific confidence failures invoke a non-Jev path. The GPT-OSS sanitizer remains necessary because Jev cannot generate or quote arbitrary redaction spans.

Search relevance ranking runs only when a nonblank `relevance_criteria` value is present. Web uses at most two twenty-result Brave pages; news, events, video search, fitness location/class search, public code-repository search, and public 3D-model search rank up to 40 candidates. Maps, product search, and stay search rank up to 20 candidates so relevance ranking does not add a billable provider page; housing uses its bounded merged provider pool. Hard filters and stable deduplication run before the decision. Each skill uses a separate rubric that only scores explicit result evidence appropriate to that domain. Repository ranking prioritizes explicit use-case, technology, license, and date fit over popularity and does not infer security, repository health, documentation quality, maintenance quality, or API compatibility. 3D-model ranking prioritizes explicit function, feature, license, file-format, and price fit over engagement and does not infer geometry quality, printability, or device compatibility. Candidate text is labeled untrusted, the decision can only reorder existing candidates, and every skill slices back to its requested `count`, `max_results`, `pageSize`, or `limit` before output safety, response serialization, or embed creation. Health appointment search is intentionally excluded because appointment availability is already a hard, time-sensitive ranking constraint rather than a broad discovery pool.

Jev's limit is local to decision processing. OpenMates does not compress the answer model's conversation to that limit. The Jev adapter keeps at most eight recent user/assistant messages and an optional 4,000-character summary. Older messages have bounded projections and yield before the complete latest user request. If essential state alone cannot fit, the caller uses its independent fallback.

The shared batcher partitions independent questions or candidate rows into at most eight requests, with at most three concurrent calls and a finite aggregate deadline. All batches are validated before inference; stable IDs must have complete, nonoverlapping responses. Search scores use the same absolute rubric and are sorted globally after merging. Workflow questions retain the entire selected graph: splitting its essential state would change the decision and is not permitted. Usage is summed across physical requests, with sizing logs containing counts rather than input text.

External-output safety shares one logical scan across at most eight physical batches. Every passage retains its source ID and neighboring context. Each batch uses one Jev gate and, when necessary, at most one GPT exact-span review, without retries and within the existing per-skill deadline. Replacements are applied only after complete coverage succeeds. Any failure preserves the existing ASCII-cleaned/unscanned policy; terminal output continues to withhold model text when unscanned. Inputs exceeding the bounded partition are never silently truncated.

## Title timing

Jev selects the initial icon but cannot generate title text. On the healthy path, preprocessing returns without a title and main answer inference starts immediately. The existing postprocessor generates the initial title after the first response and sends it in the existing `post_processing_completed.updated_chat_title` field. If Jev is unavailable, the generative preprocessing fallback may still generate the title before main inference as a degraded but reliable path.

## Verification

- Unit transport and schema tests: `backend/tests/test_typesafe_decisions.py`
- Public decision boundaries and accounting: `backend/tests/test_ai_decide.py`
- Preprocessing mapping tests: `backend/tests/test_preprocessor_jev.py`
- Safety and outage tests: `backend/tests/test_chat_request_safety.py`
- Prompt-injection confidence-band tests: `backend/tests/test_content_sanitization.py`
- Search relevance ranking and fallback tests: `backend/tests/test_search_relevance.py`
- Manual real-provider test entry point: `scripts/api_tests/test_typesafe_jev_api.py`
- Manual real search-ranking comparison: `backend/scripts/test_search_relevance_ranking.py` (run inside the API container)

Primary references: [TypeSafe API reference](https://docs.typesafe.ai/api), [TypeSafe models](https://docs.typesafe.ai/models), [TypeSafe images](https://docs.typesafe.ai/images), [TypeSafe legal and privacy documents](https://docs.typesafe.ai/legal), and [OpenRouter Jev model page](https://openrouter.ai/typesafe/jev-1.14).
