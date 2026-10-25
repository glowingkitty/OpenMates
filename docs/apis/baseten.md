# Baseten Model APIs and DeepSeek V4.1 Flash

Reviewed 2026-10-25. Baseten is an inference host; the logical model belongs to
`deepseek/deepseek-v4.1-flash`. Direct requests use the pinned
`deepseek-ai/DeepSeek-V4.1-Flash-1017` snapshot. OpenRouter fallback uses
`deepseek/deepseek-v4.1-flash-20261017` and permits only its `baseten` endpoint.
This restriction keeps the host-specific cache tariff valid after fallback.

## API and credentials

The documented [Chat Completions API](https://docs.baseten.co/reference/inference-api/chat-completions)
is `POST https://inference.baseten.co/v1/chat/completions`, authenticated with a
Bearer API key. The shared transport owns HTTP, validation, bounded 429 retries,
SSE parsing and sanitized failures; the AI adapter owns tools and usage mapping.
There is no silent retry after a stream starts. Existing model routing tries
OpenRouter when direct Baseten is unavailable, including when its key is absent.

Set Vault `kv/data/providers/baseten`, field `api_key`, or
`SECRET__BASETEN__API_KEY`. Vault takes precedence; `IMPORTED_TO_VAULT` is never
accepted as a credential. Do not log keys, requests, tool arguments or responses.
The optional key is discoverable from both the Baseten host and DeepSeek catalog.

`GET /v1/models` checks credentials and catalog readiness without inference cost.
Background health uses that endpoint. Manual readiness check inside the API
container: `python scripts/api_tests/test_baseten_api.py --test models`.
The helper defaults to this non-billable check; `--list` describes available checks.
OpenMates chat tests continue to use automatic model routing.

## Caching and pricing

[Baseten pricing](https://docs.baseten.co/inference/model-apis/pricing-and-limits)
lists $0.30/M ordinary input, $0.007/M cached input and $1.20/M output for this
snapshot. The matching OpenRouter endpoint was checked through its documented
model endpoints catalog. Customer allowances follow the existing markup and
rounding convention: 1,100 ordinary-input, 47,500 cached-input and 275 output
tokens per credit. Cache fills are included in input; there is no invented write
charge. The tariff has an internal evidence-review deadline of 2026-11-25.

Prefix caching is automatic and opportunistic. `x-session-affinity` carries an
opaque HMAC over owner, team and root chat identity; descendants share their
root's hint. OpenRouter receives the same opaque value as `session_id`. Neither
hint guarantees a hit. Usage-only terminal SSE events are retained, including
`usage.prompt_tokens_details.cached_tokens`. Missing counters remain unknown;
reported zero means zero. Read tokens are a subset of prompt tokens, and
reasoning tokens are a subset of completion tokens: neither is added again.

Cache-aware customer settlement applies to authenticated orchestrated roots,
children and grandchildren when their actual host has a verified tariff. Every
attempt retains its own usage and frozen tariff. Existing reservation limits,
root attribution, encrypted receipts and idempotent charging still apply.
Native transcript replay, summary billing and workflow/external/anonymous rollout
boundaries are separate from this customer-tariff eligibility change.

## Data handling and permission

[Baseten's terms](https://www.baseten.co/terms-and-conditions/) authorize the
provided Model API service and prohibit training on customer content. The
[privacy policy](https://www.baseten.co/privacy-policy/) and
[Model APIs documentation](https://docs.baseten.co/inference/model-apis/overview)
describe synchronous request handling and transient automatic KV caches. This is
not a promise of fixed residency: the shared route is marked `global`. The
privacy policy and training-policy inventory include Baseten before routing.
No scraping, undocumented endpoints or intermediary credentials are used.

## Verification and limits

Transport tests cover streaming/non-streaming, tools, reasoning, usage-only
terminal chunks, unknown/zero/hit counters, bounded rate-limit retries, cancellation
and privacy-preserving errors. The isolated product test uses synthetic counters
through real reservations, settlement, encrypted persistence and the authenticated
usage API for parent, child and grandchild; it makes no paid inference calls.
A successful synthetic test does not establish a live provider cache hit. Report
live readiness and hit evidence separately when credentials are available.

As of the 2026-10-25 live Together validation, DeepSeek V4.1 Flash prefers
Together directly, with OpenRouter as its first fallback. Direct Baseten remains
an optional supported route; a Baseten key is not required for the primary route.
See the cache Plan for the actual live counters and host-specific supplier rates.
