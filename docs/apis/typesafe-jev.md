# TypeSafe Jev decision API

OpenMates uses `typesafe/jev-1.13` through OpenRouter for internal, bounded decisions. Jev is not a chat-completions model: it evaluates a supplied text or structured `state` against named questions and returns typed `choice`, `noul` (yes/no probability), or `score` answers. It does not generate titles, suggestions, summaries, translations, arbitrary JSON, or answer prose.

## Current transport

- Endpoint: `POST https://openrouter.ai/api/alpha/decisions`
- Model: `typesafe/jev-1.13`
- Authentication: existing OpenRouter key at `kv/data/providers/openrouter` / `api_key`, with `SECRET__OPENROUTER__API_KEY` as the self-hosted environment fallback
- Request data: a bounded recent-message projection plus only the candidate catalogues required by the named decisions
- Modalities: text or JSON-compatible structured state; no image, audio, video, or PDF input
- OpenRouter context limit: 32,768 tokens. The client also enforces conservative serialized state and total-request bounds so an oversized call falls back before depending on provider rejection.
- Price observed for OpenRouter: $0.042 per million input tokens and no output-token charge

The provider client lives in `backend/shared/providers/typesafe/`. Application code calls the provider-neutral decision helper in `backend/apps/ai/processing/jev_decisions.py`; callers do not use the normal chat-completions client. This boundary is intentional so a direct TypeSafe transport (`POST https://api.typesafe.ai/v1/systemone`, model alias `jev-latest`) can be added later without changing preprocessing or safety policy.

## Production uses and fallbacks

| Use | Jev result | Independent fallback |
| --- | --- | --- |
| Foreground preprocessing | tier, task area, topic, language, temperature band, skill/focus/memory/preview selections, icon, and safety scores | existing Gemini preprocessing model and its configured provider fallbacks |
| Request safety confirmation | allow/block/uncertain, category, action, and an exact evidence candidate selected from deterministic user-text spans | existing Mistral structured safety confirmation |
| External-content prompt injection | yes/no probability; safe content passes and high-confidence attacks block | GPT-OSS Safeguard for ambiguous decisions, exact-span redaction, and Jev outages |
| Postprocessing | assistant-response safety score and bounded app ranking | existing Gemini postprocessor fields |

Every Jev call is optional at the caller boundary. Transport errors, timeouts, malformed responses, missing answers, request-size limits, and task-specific confidence failures invoke a non-Jev path. The GPT-OSS sanitizer remains necessary because Jev cannot generate or quote arbitrary redaction spans.

## Title timing

Jev selects the initial icon but cannot generate title text. On the healthy path, preprocessing returns without a title and main answer inference starts immediately. The existing postprocessor generates the initial title after the first response and sends it in the existing `post_processing_completed.updated_chat_title` field. If Jev is unavailable, the generative preprocessing fallback may still generate the title before main inference as a degraded but reliable path.

## Verification

- Unit transport and schema tests: `backend/tests/test_typesafe_decisions.py`
- Preprocessing mapping tests: `backend/tests/test_preprocessor_jev.py`
- Safety and outage tests: `backend/tests/test_chat_request_safety.py`
- Prompt-injection confidence-band tests: `backend/tests/test_content_sanitization.py`
- Manual real-provider test entry point: `scripts/api_tests/test_typesafe_jev_api.py`

Primary references: [TypeSafe API reference](https://docs.typesafe.ai/api), [TypeSafe models](https://docs.typesafe.ai/models), [TypeSafe legal and privacy documents](https://docs.typesafe.ai/legal), and [OpenRouter Jev model page](https://openrouter.ai/typesafe/jev-1.13).
