# Inception Mercury 3

Verified against official documentation on 2026-10-20. Mercury 3 was announced
on October 19. Provider ID: `inception`; model ID: `mercury-3`.

## API

Use `https://api.inceptionlabs.ai/v1/chat/completions` with bearer authentication.
The chat interface is OpenAI-compatible, including SSE streaming, function tools,
and JSON-schema structured output. Mercury 3 accepts text only; voice processing
requires separate transcription and speech synthesis. The documented context
window is 1,000,000 tokens and maximum output is 131,072 tokens. Reasoning efforts
are `instant`, `low`, `medium`, and `high`; supported temperature is 0.5–1.0.
Streaming usage requires `stream_options.include_usage: true`. Cached prompt and
reasoning token detail counts are subsets of prompt and completion totals,
respectively; do not double count them.

Direct API tests intermittently received free-tier HTTP 429 on 2026-10-20;
later paired native suites completed 54 fast-task responses and 48 workflow
results without rate limits. These include Gemini comparison arms and establish
usable direct capacity during those runs. Synthetic OpenRouter benchmarks are
authorized only to inform the decision about upgrading the direct Inception
account. Product requests remain direct; gateway results do not establish
direct-API latency or capacity.

Rechecking produced successful direct and gateway completions, followed by
renewed gateway HTTP 429 during its paired run. This is intermittent
request rejection, not proof that the service is broadly overloaded. The
[official error documentation](https://docs.inceptionlabs.ai/resources/error-codes)
distinguishes 429 (rate limit reached) from 503 (engine overloaded). No current
incident announcement was found in the accessible official blog/LinkedIn posts.
Both benchmark harnesses now stop on their first HTTP 429 and save a partial
report, without scoring skipped requests as quality failures. See the
[completed task-specific evaluation](../plans/mercury-fast-inference/evaluation-2026-10-20.md).

## Manual selection

Mercury 3 is available in the composer: **model selector → More providers →
Inception → Mercury 3**. Manual selection uses direct Inception. The catalog's
historical `allow_auto_select: false` configuration restricted automatic routing
without removing the manual entry. The low-complexity default is deployed to dev
in `7ff9714f24c62a0b8bc5d07e164b7b719be055b7`, with `allow_auto_select: true`.
Normal user-disabled-model/server and provider-health filtering
still apply. The dev health endpoint reported Inception healthy on 2026-10-20.

Credentials belong in Vault at `kv/data/providers/inception_labs`, key `api_key`.
The environment convention is `SECRET__INCEPTION_LABS__API_KEY`. Do not commit
credentials or print them in diagnostics. Vault access was verified during integration. The local `.env` value is the
normal `IMPORTED_TO_VAULT` sentinel, not a stale credential; the key is stored
only in Vault. Never assume environment values are literal provider keys.

## Pricing

Regular provider rates per million tokens: $0.20 input, $0.02 cached input,
$0.70 output. Launch rates are $0.10, $0.01, and $0.35 respectively. No launch
end date was established. The dated `temporary_prices` entry applies the launch
savings to both provider accounting and customer tariffs without inventing an
expiry. Customer token allowances are 3,300 input and 950 output tokens per
credit during the launch, compared with regular allowances of 1,650 input and
475 output. Retiring the promotional entry restores the regular rates. Dollar
rates above are provider prices; customer charges use the token allowances.

## Automatic prefix caching

Checked against the direct Inception [FAQ](https://docs.inceptionlabs.ai/resources/faq)
and [model price table](https://docs.inceptionlabs.ai/get-started/models) on
2026-10-20. Prefix caching is automatic: no activation request parameter is
required. The reviewed official documentation does not state a minimum eligible
prefix length or cache TTL, and documents no API to pin, invalidate or inspect
entries. Do not assume another provider's minimum or retention behavior.

`usage.prompt_tokens_details.cached_tokens` reports cached input as a subset of
inclusive `prompt_tokens`. Streaming requests set
`stream_options.include_usage: true`; cached tokens must not be added to the
prompt total again. Supplier cache reads cost **$0.01/M during launch**, versus
ordinary input **$0.10/M** (regular **$0.02/M** versus **$0.20/M**). This is a 90%
supplier discount on reported cache hits, not a guarantee that any request hits.

The pure client retains prompt-token details; the OpenMates adapter maps the
reported count to `cache_read_input_tokens`. Normalized usage preserves that
counter, and the shared supplier-cost estimator subtracts reported cache reads
from ordinary input before pricing them at the configured cached-input rate.
Missing cache counters remain unknown rather than proving zero hits. Native
benchmark receipts reported actual cached input; their uncached cost estimates
were deliberately conservative and do not represent supplier invoices.

**Customer cache savings are deployed to dev.** Native
Inception chat and workflow settlement use the shared category-credit calculator
with `write_billing: included_in_input`. Ordinary fills incur no extra cache-write
fee. Reported cached input uses **33,000 tokens/credit during launch**, versus
ordinary input **3,300**; regular allowances are **16,500 cached / 1,650 ordinary**.
Output remains **950 tokens/credit promotional / 475 regular**. This passes the
90% cached-input discount to customers in addition to the 50% launch promotion,
only for the provider-reported cached subset. Missing cache counters charge
inclusive input at the ordinary allowance; invalid subsets fail closed.

The native-Inception-only cache policy's `expires_on: 2026-11-20` is an **internal
evidence-review deadline**, not an Inception cache TTL or promotion end date.
Minimum-credit rules and final rounding mean cached-input savings do not imply
90% off the entire charge. Workflow `estimated_cost_usd` remains a conservative
supplier estimate pricing all input at the ordinary supplier rate; cache-aware
customer settlement does not make that estimate a cache-adjusted invoice.

Existing native postprocessing receipts already demonstrate cache hits without
additional calls: the twenty Mercury requests reported **80,018 of 94,356 input
tokens cached (84.8%)**, all twenty with positive hits and eighteen above 1,000
cached tokens. This is observed reuse, not a minimum-prefix or TTL experiment.
The [postprocessing comparison](../plans/mercury-fast-inference/postprocessing-2026-10-20.md)
retains Gemini 3.5 Flash-Lite for that specific task: Mercury LOW's median was
1.590 s versus Lite's 1.603 s, with additional language and task-contract defects.


## Use and privacy

Mercury can process selected-model text requests. Ordinary audio correction sends
only raw transcript text and a language hint for correction/title generation,
not audio. Raw transcripts are outside typed-message placeholder protection.
The account owner confirmed the training opt-out on 2026-10-20. Correction uses
Mercury **low** when `INCEPTION_TRANSCRIPT_CORRECTION_ENABLED=true`, with a
five-second total deadline including credential lookup, no correction retries
and native Gemini 3.8 Flash LOW fallback. This is deployed to dev in `7ff9714`.
Native completed tool calls can report `stop` or `tool_calls`; truncated,
blocked, missing-finish and malformed responses are rejected.
The flag is enabled on dev after live direct-facade verification on 2026-10-20:
the refined helper passed twelve repeated synthetic cases and the final shared
runtime passed six more without fallback (median 0.795 seconds). The new deployed
facade passed all six original synthetic cases again, including German and mixed
language, without fallback: median 1.135 seconds, range 0.541–2.693 seconds.
The rollout
included a generic self-correction instruction refinement after one earlier
cleanup miss. Production configuration was not changed.
The authorized implementation is deployed to dev with isolated browser/database
coverage and verified runtime source identity. Workflow generation uses a request-wide maximum of three actual
author calls: **Mercury INSTANT → Mercury LOW repair → Gemini 3.8 Flash LOW repair**.
Outage recovery can skip an unavailable Mercury route and allow one Gemini repair
when budget remains; it never exceeds three calls or advances on Stop. Accepted
prefixes and actual-attempt billing survive recovery. A semantically wrong
accepted prefix may require a disabled partial and manual editing; the chain
does not guarantee recovery of every defect.
Mercury **LOW** is the approved eligible low-complexity text default, with native
Gemini 3.8 Flash **LOW** fallback after five seconds without substantive output.
Unsupported vision and other ineligible Mercury
requests use Gemini; global account settings and exact model preferences stay
unchanged. Jev remains the primary preprocessing/routing decision provider.
Only where generative recovery is already allowed, the approved recovery order
is Mercury 3 first, then Gemini 3.5 Flash-Lite; preserve Jev's Unsure/decision
contracts. This Lite secondary recovery is distinct from the Gemini 3.8 Flash
LOW fallbacks for correction, workflows and low-complexity chat. Healthy Jev
should not trigger generative recovery. Medium-complexity defaults remain Gemini: bounded writing exposed
unsupported claims, and no matched public general-quality benchmark established
Mercury parity. See the [rollout addendum](../plans/mercury-fast-inference/rollout-addendum.md)
for verification, source identities and receipts.

The [expanded correction evaluation](../plans/mercury-fast-inference/expanded-correction-2026-10-20.md)
and [expanded workflow evaluation with LOW diagnosis](../plans/mercury-fast-inference/expanded-workflow-2026-10-20.md#later-diagnostic-mercury-low-same-frozen-selections)
are complete and retain critical defects. Successful chained repairs and safe
exhaustion passed deterministic unit, real-database and browser checks. A later
native controlled-error test did not fully recover: Mercury LOW repeated a
forbidden Ask AI field, then Gemini produced the comparison but omitted the final
Send. The three-attempt chain retained the validated disabled partial and notice;
its strict complete-workflow oracle remains failed. This is a disclosed quality
limit, not evidence of universal recovery. User/model/server/key restrictions are
enforced, including a bounded per-turn transport of disabled-model/server settings.
The disabled-model browser case recorded zero Mercury provider attempts.
Preserve Gemini 3.5 Flash-Lite generative postprocessing. Synthetic
benchmark results do not establish quality for private user transcripts.

Inception's public terms permit training on submitted content with an API Platform
account opt-out. The account owner confirmed on 2026-10-20 that
“Improve the model for everyone” is OFF for the OpenMates API account. This
account-specific opt-out is not an unconditional provider policy; training may
apply if the setting is reenabled. The public privacy policy states purpose- and law-based retention without
a fixed maximum. The API FAQ describes custom zero-retention arrangements as
case-specific; none is established for this account. Deleting OpenMates content
does not promise deletion of provider-side records.

## Official sources

- [Mercury 3 announcement](https://www.inceptionlabs.ai/blog/introducing-mercury-3)
- [Models and pricing](https://docs.inceptionlabs.ai/get-started/models)
- [Chat completion API](https://docs.inceptionlabs.ai/api-reference/chat/create-a-chat-completion)
- [Reasoning efforts](https://docs.inceptionlabs.ai/capabilities/reasoning-efforts)
- [API FAQ: token accounting, text input, caching, retention](https://docs.inceptionlabs.ai/resources/faq)
- [Privacy Policy](https://www.inceptionlabs.ai/docs/privacy-policy), verified HTTP 200 and page title on 2026-10-20
- [Terms of Use: Licenses and account training opt-out](https://www.inceptionlabs.ai/docs/terms-of-use)
