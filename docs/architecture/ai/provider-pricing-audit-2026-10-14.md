# Provider model pricing audit — October 14, 2026

Scope: the 50 existing `ai.ask` catalog entries and Gemini 4 Argon. Prices below
are USD per million tokens for standard synchronous inference, unless stated
otherwise. Provider costs and OpenMates customer credits are separate tariffs.
The catalog changes below implement the approved `feature.billing@10` pricing
scope. Runtime and end-to-end verification are recorded separately.

## Required changes

| Model / supplier | Stored input / cached / output | Verified current input / cached / output | Duration |
| --- | --- | --- | --- |
| Gemini 4 Argon / Google AI Studio | Not present | 2 / 0.10 / 10 | Through November 30, 2026; 4 / 0.20 / 20 starting December 1 |
| Gemini 3.7 and 3.8 Flash / Google AI Studio | 0.75 / 0.075 / 3.75 stored as base | Same current rates | Through December 31, 2026; 1.50 / 0.15 / 7.50 starting January 1, 2027 |
| Mistral Large 4 / Mistral | 1.36 / 0.14 / 4.18 | 0.68 / 0.07 / 2.09 | Sale; no published end date. Explicit regular rates match stored values |
| DeepSeek V4 Pro 0813 / Together | 2.10 / 0.20 / 4.40 | 1.32 / 0.13 / 3.96 | No temporary period identified |
| DeepSeek V4 Flash / AtlasCloud through OpenRouter | 0.14 / absent / 0.28 | 0.14 / 0.028 / 0.28 | Endpoint reports no discount |
| Kimi K2.6 / Together | 1.20 / absent / 4.50 | 1.20 / 0.20 / 4.50 | Model page now labels deployment Dedicated |
| Kimi K2.7 Code / Together | 0.95 / absent / 4.00 | 0.95 / 0.19 / 4.00 | Model page now labels deployment Dedicated |

Google sources: [current Gemini rate card](https://ai.google.dev/gemini-api/docs/pricing),
[Argon migration and introductory rates](https://ai.google.dev/gemini-api/docs/latest-model?hl=en),
[3.7 launch](https://blog.google/innovation-and-ai/models-and-research/gemini-models/introducing-gemini-3-7-flash/),
and [Vertex pricing](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing).
Vertex Flash's advertised discount is supplied through credits back: preserve
gross supplier costs until invoice credits are confirmed. Argon supports implicit
caching only, ignores sampling parameters, and defaults to medium thinking.
Use the existing bounded streaming path; background long decode is separate scope.

Other sources: [Mistral Large 4 sale](https://docs.mistral.ai/models/mistral-large),
[Together DeepSeek](https://www.together.ai/models/deepseek-v4-pro-0813),
[Together Kimi K2.6](https://www.together.ai/models/kimi-k26),
[Together Kimi K2.7 Code](https://www.together.ai/models/kimi-k27-code),
and [OpenRouter Flash supplier metadata](https://openrouter.ai/api/v1/models/deepseek/deepseek-v4-flash/endpoints).
Adding a supplier cache cost does not independently authorize customer cache billing.

## Matching published rates

[OpenAI official model documentation](https://developers.openai.com/api/docs/pricing)
matches the configured direct rates for GPT-6 Astra, GPT-6.1 Sol, GPT-6 Luna,
GPT-5.6 Terra, GPT-6 Sol, GPT-5.6 Sol, GPT-5.6 Luna, GPT-5.5 and Pro, GPT-5.4 and
Pro/Mini/Nano, GPT-5.2 and Pro, and GPT-5.1. Existing configured long-context
multipliers match their published bands. GPT-5.6 Sol's current 4 / 0.40 / 20
rate, with a 5.00 cache-write rate, is promotional **at least through November
21, 2026**. This is a minimum duration, not a firm end date; do not invent a
November 22 replacement tariff. [Model source](https://developers.openai.com/api/docs/models/gpt-5.6-sol).

[Anthropic's direct rate card](https://platform.claude.com/docs/en/about-claude/pricing)
matches all 13 configured Claude entries: Fable 5.1 and 5; Opus 5.5, 5, 4.8, 4.7,
4.6 and 4.5; Sonnet 5.5, 5 and 4.6; Haiku 5.5 and 4.5. Cache read/write and
Haiku 5.5's over-100k band match. No temporary Claude token discount was found.

[Mistral pricing](https://docs.mistral.ai/inference/pricing) matches Small 4
(0.15 / 0.015 / 0.60), Medium 3.5 (1.50 / 0.15 / 7.50), and
[GLM 5.3](https://docs.mistral.ai/models/zai-glm-5-3) (1.40 / 0.14 / 4.40).

Google's Flash-Lite rate matches 0.30 input / 0.03 cached / 2.50 output.
Legacy Flash's documented rates remain 0.50 input / 3.00 output, and 3.5 Flash
remains 1.50 input / 9.00 output in Google's migration documentation.
Gemini 3.1 Pro's base 2.00 / 12.00 rates match; its over-200k 4.00 / 18.00 tier
now has explicit customer and supplier context-band coverage.
[Google migration source](https://ai.google.dev/gemini-api/docs/generate-content/whats-new-gemini-3.6).

[Together pricing](https://www.together.ai/pricing) matches Kimi K3
(3.00 / 0.30 / 15.00). [Cerebras pricing](https://www.cerebras.ai/pricing)
matches Qwen 3.8 27B (0.99 input / 1.49 output) and the GPT OSS 120B Cerebras
supplier profile (0.35 input / 0.75 output).

## Verification gaps — retain values rather than guess

- Gemma 4 31B, Qwen3 235B A22B 2507, and GLM 4.7 no longer have public shared
  Cerebras prices. Dedicated inference requires a quote; the stored values
  cannot be claimed as currently verified. [Catalog](https://inference-docs.cerebras.ai/models/overview),
  [dedicated inference](https://inference-docs.cerebras.ai/dedicated/overview).
- GLM 5.2's unconstrained OpenRouter route has no single supplier price. No
  current endpoint matched its stored 1.20 / 0.20 / 4.10 triplet. Endpoint sales
  exist without published expiries; an aggregator's minimum cannot stand in for
  the actual host. [Endpoint catalog](https://openrouter.ai/api/v1/models/z-ai/glm-5.2/endpoints).
- GPT OSS 120B's Bedrock Frankfurt tariff and Claude Bedrock regional profiles
  were not independently confirmed by region. Mistral Small/Medium OpenRouter
  fallback costs also remain unverified. Preserve these host-specific values
  pending authoritative evidence; direct-provider prices do not verify them.
- Cerebras's $5 introductory account credit expires 30 days after activation.
  It is an account credit, not a discounted per-token tariff.

Implementation must preserve these distinctions, apply known discounts
prospectively, and freeze each actual provider attempt's resolved prices before
dispatch. Refresh local checks and isolated E2E coverage after approval of the
billing specification; this audit alone is not implementation evidence.

## Implemented catalog decisions

- Gemini 4 Argon is available for exact selection through Google AI Studio only;
  automatic defaults remain unchanged. Regular customer units are 80 input,
  1,600 cache-read, and 15 output tokens per credit; introductory units are
  160 / 3,200 / 30 through November 30 inclusive. The synchronous output cap
  is 65,536, with medium thinking. Published cache prices are recorded, while
  customer cache billing remains pending actual provider usage evidence.
  [Official model capabilities](https://ai.google.dev/gemini-api/docs/models/gemini-4-argon).
- Gemini 3.7 and 3.8 keep 450 / 4,500 / 90 customer units during their offers;
  regular units become 225 / 2,250 / 45. Their supplier base is
  1.50 / 0.15 / 7.50, and the promotion supplies 0.75 / 0.075 / 3.75.
  Vertex gross supplier multiplier is 1 against the regular base and 2 against
  the introductory base; retrospective credits never reduce dispatch cost.
  Existing cache-policy review expiry remains a separate December 31 field.
- Gemini 3.1 Pro adds its over-200k customer band at 200,001 input tokens:
  85 input / 20 output units, against regular 170 / 30. Both Google hosts
  use supplier multipliers 2x input, 2x cache-read, and 1.5x output; the verified
  base supplier cache price is 0.20. Customer cache billing remains pending.
- Mistral Large 4 retains published regular supplier and customer rates and
  adds the verified undated sale: supplier 0.68 / 0.07 / 2.09, customer
  490 / 4,760 / 158. October 14 is the first reviewed applicability date for
  this catalog entry, rather than an invented historical sale start.
- GPT-5.6 Sol records its August 21 promotion separately, guaranteed through
  November 21 with no firm expiry. The official change describes a 20% input
  reduction and a 33% output reduction, supporting historical regular
  5.00 input / 30.00 output; regular cache costs follow the documented
  0.1x read and 1.25x write conventions (0.50 / 6.25). These historical rates
  do not promise a future replacement tariff. Current customer units and
  context bands remain 80 / 800 / 64 / 15 and 40 / 400 / 32 / 10;
  historical regular units are 65 / 650 / 52 / 10 and 32 / 325 / 26 / 7.
  Its pending cache policy is unchanged.
  [Official August 21 changelog](https://developers.openai.com/api/docs/changelog),
  [model pricing and cache-write convention](https://developers.openai.com/api/docs/models/gpt-5.6-sol).
- Together DeepSeek V4 Pro becomes 1.32 / 0.13 / 3.96 supplier costs and
  250 input / 84 output customer units under the existing approximately 3x
  markup. Kimi K2.6 and K2.7 Code gain supplier cache costs 0.20 and 0.19;
  DeepSeek V4 Flash gains its verified AtlasCloud cache cost 0.028. These
  additions activate no customer cache policy.

All five modified provider YAML files parse successfully; temporary entries
carry complete customer and supplier token categories. Unverified legacy and
fallback rates remain unchanged. Promotions target standard processing and
explicit eligible hosts; no batch price or account credit enters the tariffs.
