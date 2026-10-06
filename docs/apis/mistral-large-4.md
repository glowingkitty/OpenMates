# Mistral Large 4

Verified 2026-10-06 against the [release announcement](https://mistral.ai/news/mistral-large-4/),
[model card](https://docs.mistral.ai/models/mistral-large-4-0), and
[native reasoning contract](https://docs.mistral.ai/studio/conversations/reasoning).

The public-preview model is available as `mistral/mistral-large-4` through the
existing direct Mistral API integration. It supports text and image input, text
output, function calling, streaming, and a 1M-token context. Its weights have not
yet been released; Mistral plans to release them later in October.

The selector assigns **Max**, provisionally, as the strongest curated Mistral
option. Mistral reports strong coding,
agentic, legal, financial, and visual-grounding results. Many comparisons concern
other open-weight models, and some Artificial Analysis coding scores were
evaluated privately ahead of public harness release. These results do not establish
broad quality parity with OpenMates' Max models (GPT-6 Astra and Claude Fable 5.1).
Price, parameter count, and context size alone do not determine capability.

The current selector has four bars: Low 1/4, Medium 2/4, High 3/4, and Max 4/4.
The curated Mistral choices are Large 4 (Max), Medium 3.5 (Medium), and Small 4
(Low). Small 3.2 and Devstral 2 have been deleted from the provider catalog because
Mistral marks them deprecated. Ministral 3 8B is still GA upstream but has also
been deleted by product choice. Internal Small 3.2 calls now use Small 4, with
the matching OpenRouter Small 4 fallback. Its current rates are $0.15 input and
$0.60 output per million tokens, with a 262,144-token context and a March 16,
2026 release date. [Small 4](https://docs.mistral.ai/models/mistral-small-4-0-26-03),
[Small 3.2 lifecycle](https://docs.mistral.ai/models/mistral-small-3-2-25-06),
[Devstral 2 lifecycle](https://docs.mistral.ai/models/devstral-2-25-12).

## Pricing

USD per million tokens, direct API, excluding tools and regional surcharges:

| Model | Input | Output | 1M input + 250K output |
| --- | ---: | ---: | ---: |
| Mistral Large 4, current Standard rate | $0.68 | $2.09 | $1.20 |
| Mistral Large 4, crossed-out original price | $1.36 | $4.18 | $2.41 |
| Mistral Medium 3.5 | $1.50 | $7.50 | $3.38 |
| Gemini 3.8 Flash, through 2026-12-31 | $0.75 | $3.75 | $1.69 |
| GPT-6.1 Sol | $2.00 | $10.00 | $4.50 |
| Claude Opus 5.5 | $4.00 | $20.00 | $9.00 |
| GPT-6 Astra / Claude Fable 5.1 | $10.00 | $50.00 | $22.50 |

Peer sources: [Mistral pricing](https://docs.mistral.ai/inference/pricing),
[Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing),
[GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol),
[GPT-6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra),
[Claude Opus 5.5](https://platform.claude.com/docs/en/models/opus-5-5/overview), and
[Claude models](https://platform.claude.com/docs/en/models/overview).

The model card shows $0.07/M cached input, with $0.14/M crossed out. The release
page still shows original prices. The pricing page lists the lower rates under
Standard, rather than Batch. No reason or expiry is published for the reduction.
The provider catalog uses the current Standard rates; recheck them when the
preview changes. Budget longer-term comparisons at original rates as well.
OpenMates charges approximately its existing 3x token markup: one credit per
490 input tokens and 155 output tokens. Reasoning increases completion usage.

[Prompt caching](https://docs.mistral.ai/studio/conversations/advanced/prompt-caching)
reuses unchanged prompt prefixes. A stable opaque `prompt_cache_key` improves
cache-hit chances; hits are not guaranteed. Cached tokens are reported in
`usage.prompt_tokens_details.cached_tokens` and included in total prompt tokens.
The current OpenMates client does not send this key or account for cache hits
separately, so the comparisons above use uncached prices.

## Native reasoning and speed

The model catalog sets Mistral's `reasoning_effort` to `high`; this is independent
of the selector's Max capability label. The client handles thinking-only and
mixed thinking/text stream deltas, sends thinking through the existing thinking
channel, and keeps the final answer separate. Native thinking from tool turns is
replayed in the next inference iteration using private tool transport state.
Small 4 explicitly uses `none` to preserve fast utility calls. Other Mistral
models retain their existing unspecified reasoning setting.

Neither the announcement nor the model card publishes quantified throughput,
time to first token, or end-to-end latency. Large 3 measurements and third-party
Large 4 pages are insufficient evidence for Large 4 speed. Do not promise a speed
rank from those sources alone.

A small direct Mistral API sample on 2026-10-06 used the same approximately
60-word explanation prompt, streaming, temperature 0.7, and a 1,536-token limit.
These are individual requests, not statistically representative benchmarks:

| Model/settings | First content (s) | First answer (s) | Total (s) | Completion tokens |
| --- | ---: | ---: | ---: | ---: |
| Large 4, high reasoning, sample 1 | 0.582 | 13.926 | 19.001 | 812 |
| Large 4, high reasoning, sample 2 | 0.491 | 15.505 | 16.236 | 1,228 |
| Medium latest, default reasoning | 0.217 | 0.217 | 0.802 | 78 |

Large 4 streamed thinking quickly but delayed the visible answer while reasoning.
Different reasoning settings prevent a like-for-like underlying speed ranking.
All three calls finished normally and reported zero cached tokens. These timings
exclude the OpenMates pipeline. Reproduce with
`backend/scripts/test_mistral_large4_latency.py` inside the API container.

To validate the provisional Max rating, compare it against Astra and Fable on the same OpenMates
tasks: multi-step tool use, code correctness, image/document understanding,
multilingual answers, and long-context synthesis. Record task success, first
visible answer latency, total duration, and total billed tokens (including
thinking). Require comparable quality across workloads rather than a single
specialist benchmark win.
