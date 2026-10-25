# Provider cache audit — 2026-10-25

This audit separates request support, reported usage, and customer tariff
eligibility. Only reviewed host/model tariffs receive customer cache discounts;
unknown counters never imply a cache hit. Provider caches are opportunistic.

| Adapter/host | Request path and usage | Outcome |
| --- | --- | --- |
| Baseten | Automatic prefix cache; opaque root affinity; final usage requested | New direct transport; read/write/reasoning counters retained; pinned V4.1 tariff |
| OpenRouter | Automatic or upstream-specific cache support; opaque session affinity; final usage requested | Fixed usage-only chunks and preserved counters; V4.1 fallback pinned to Baseten |
| Together | Automatic cache; optional opaque root `prompt_cache_key` | Fixed streaming/non-stream usage; nested and top-level `cached_tokens` supported |
| Cerebras | Automatic for all customers/models; optional opaque root `prompt_cache_key` | Fixed null/terminal usage; counters retained; current supplier cache price equals ordinary input |
| Groq | Automatic on supported models | Fixed SDK usage and `x_groq` final metadata before empty-choice handling |
| Google MaaS | Model-specific implicit caching | Fixed terminal usage; compatible nested counter and Google alias retained |
| Local compatible | Depends on configured local server | Request final stream usage and preserve SDK counters if returned; no unsupported caching claim or inferred hit |
| Mistral | Automatic prefix caching; opaque root hint already supported | Merge cumulative partial usage instead of discarding earlier cache counters |
| OpenAI | Chat Completions and native Responses; configured cache options where supported | Existing read/write extraction and usage-only handling checked by focused regressions |
| Anthropic | Explicit stable system/history checkpoints, capped at four | Existing read/write and TTL counters retained, start/delta merge tested |
| AWS Bedrock | Explicit Converse cache points, controlled five-minute writes | Existing read/write extraction and TTL normalization checked |
| Google native | Implicit caching on supported models | Existing cached-content count normalization checked |
| Inception | Automatic prefix cache; final usage requested | Existing cached-input and reasoning counters retained |

Corrections are covered by transport-shaped fixtures rather than calls to paid
models. Nested tariff tests cover depth 0/1/2, continuations, cumulative replacement,
per-attempt settlement and root reservation attribution. The isolated product
proof checks encrypted ledger receipts, authenticated retrieval and replay without
a second debit. Cache savings apply to children using the same tariff rules as
normal authenticated chats; root budget and idempotency logic are preserved.

Provider documentation:

- [Baseten API and costs](https://docs.baseten.co/inference/model-apis/pricing-and-limits)
- [OpenRouter caching](https://openrouter.ai/docs/guides/best-practices/prompt-caching)
- [Together caching and both counter shapes](https://docs.together.ai/docs/inference/chat/prompt-caching)
- [Cerebras caching, hints and equal input price](https://inference-docs.cerebras.ai/capabilities/prompt-caching)
- [Groq caching](https://console.groq.com/docs/prompt-caching)
- [Google implicit caching](https://ai.google.dev/gemini-api/docs/caching)
- [Mistral caching](https://docs.mistral.ai/capabilities/completion/prompt_caching)
- [OpenAI caching](https://developers.openai.com/api/docs/guides/prompt-caching)
- [Anthropic caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [Bedrock caching](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html)
- [Inception cache FAQ](https://docs.inceptionlabs.ai/resources/faq)

The current Cerebras documentation supersedes earlier enterprise-only descriptions:
caching is automatic for all customers and provides a latency benefit, without a
supplier input-price discount. Do not activate discounted customer tariffs based
on another host's rates. Hosts without verified model-specific tariff evidence
retain ordinary pricing while preserving any provider-reported counters.
