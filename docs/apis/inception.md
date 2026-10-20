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
`allow_auto_select: false` restricts automatic routing; it does not remove the
manual entry. Normal user-disabled-model/server and provider-health filtering
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

## Use and privacy

Mercury can process selected-model text requests. The proposed audio use sends
only raw transcript text and a language hint for correction/title generation,
not audio. Raw transcripts are outside typed-message placeholder protection.
The account owner confirmed the training opt-out on 2026-10-20. Correction uses
Mercury **low** when `INCEPTION_TRANSCRIPT_CORRECTION_ENABLED=true`, with a
five-second total deadline, no correction retries and the established Gemini
fallback. Native completed tool calls can report `stop` or `tool_calls`; truncated,
blocked, missing-finish and malformed responses are rejected. Workflow generation
remains on Gemini; Mercury instant's completed benchmark supports a scoped pilot.
The flag is enabled on dev after live direct-facade verification on 2026-10-20:
the refined helper passed twelve repeated synthetic cases and the final shared
runtime passed six more without fallback (median 0.795 seconds). The rollout
included a generic self-correction instruction refinement after one earlier
cleanup miss. Production configuration was not changed.
Synthetic benchmark results do not establish quality for private user transcripts.

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
