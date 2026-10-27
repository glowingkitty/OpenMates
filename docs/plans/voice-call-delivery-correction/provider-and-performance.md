# Realtime speech and shared processing findings

Checked on 2026-10-25 for TASK-6049. The call UI and voice instruction repairs preserve the complete shared pre/main/post pipeline and normal model/thinking selection.

## Mistral realtime TTS remains unresolved

The [TTS overview](https://docs.mistral.ai/studio/audio/text-to-speech/overview) lists `voxtral-mini-tts-realtime-3-0`, separately from complete-text `voxtral-mini-tts-3-0`. However, the [speech streaming guide](https://docs.mistral.ai/studio/audio/text-to-speech/stream-speech) documents a complete `input` string and SSE audio output; its streaming-text section has no standalone connection contract. The [official public OpenAPI](https://github.com/mistralai/platform-docs-public/blob/main/openapi-public-doc.yaml) and SDK expose `POST /v1/audio/speech` with that complete-text request. An unrestricted model string in a schema does not establish realtime model availability or a streaming-input protocol.

A single authenticated, read-only `GET /v1/models` using the configured account returned only these TTS identifiers: `voxtral-mini-tts-2603`, `voxtral-mini-tts-3`, `voxtral-mini-tts-3-0`, and `voxtral-mini-tts-latest`. It did not list the dedicated realtime identifier. The reproducible probe is `backend/scripts/test_mistral_realtime_tts_availability.py`; it makes no paid generation request and prints no credentials or private content.

Mistral's [managed voice-agent configuration](https://docs.mistral.ai/studio/audio/voice-agents/configuration) owns the model pipeline, while its public session controls do not expose an external streamed-text TTS input. Moving reasoning into it would change the requested shared OpenMates architecture. No unsupported endpoint, fallback provider or model-ID substitution is implemented. Standalone connection/session, text append/completion/cancellation, output format and account access remain necessary provider facts. The user confirmed that no separate preview documentation or access is available. No provider contact was made.

## Previous complete-text call path

The previous call path consumed Mistral SSE audio deltas and fed progressive browser playback. It did not wait for synthesis completion or persist call audio. The separate unsupported capability is continuously appending text to an open synthesis session. That synthesis accepted each completed speech clause before streaming its audio. A dedicated realtime model name alone does not establish that request contract. A minimal REST request using the realtime identifier returned HTTP 400; that response did not establish why it was rejected.

## Selected call provider: Eleven v4 Turbo

The user's intended alternative is **Eleven v4 Turbo** (`eleven_v4_turbo`). Its [official realtime dialogue guide](https://elevenlabs.io/docs/eleven-api/guides/how-to/websockets/realtime-tdd) documents incremental text input and streamed audio through `wss://api.elevenlabs.io/v1/text-to-dialogue/stream-input`. The [protocol comparison](https://elevenlabs.io/docs/eleven-api/guides/how-to/websockets/tts-vs-ttd-websockets) confirms v4 uses this dialogue endpoint. The configured account's read-only model catalogue lists v4 Turbo with TTS enabled and no alpha-access requirement; no paid generation was requested for that check.

The user explicitly selected v4 Turbo for call output. The implementation changes only the call speech provider, preserving Voxtral transcription, automatic reasoning, the common pipeline and approved prose projection. Maintain one ordered stream per assistant turn; send released prose promptly, flush short useful openings, and feed arriving MP3 bytes directly to the existing call-owned player. Retain text/rich messages only. Manual Speak can keep its independent Mistral generation/cache policy. The v4 dialogue protocol requires one registered voice for Turbo and keep-alives before its 20-second idle limit. On interruption, fence the old stream and close its transport; `close_socket` deliberately flushes pending audio and must not be treated as an abort. Verify real cancellation, alignment/heard boundaries, first audible speech and costs before rollout. Required release checks cover the real incremental provider boundary, native browser playback, interruption, transient call audio and independent message Speak. Provider inference timing is not end-to-end call response latency.

## Shared speed opportunities, without omitting decisions

These are source-backed investigation priorities, not measured improvements or implemented shortcuts:

- `JevDecisionClient.evaluate` creates and closes an HTTP client for each decision unless a caller supplies one. `evaluate_jev_decisions` currently supplies none. Reusing a bounded client within one owning async request can avoid repeated connection setup for batches without removing questions, changing fallback or caching decisions. Do not retain async clients globally across Celery event loops.
- Verify queue wait separately from request work before changing worker allocation or handoffs. Earlier traces included several hundred milliseconds around routing/main admission; those timings do not establish the same delay in today's deployment. Preserve durable admission, cancellation and encrypted persistence.
- Credits/Project checks and several routing reads already run concurrently. Parallelize only remaining independent reads whose results are all still awaited; do not treat missing or incomplete Task/Project inventories as permission to omit related context.
- Preserve the stable prompt prefix and verify actual provider-reported cached token counts and first-token timing. Token throughput alone does not establish startup latency, and prior tiny cache counts are not thousands of cached tokens.
- Cache versioned public configuration and parsed instruction sources where repeated loading is demonstrated. Keep private authorization and current request context fresh. Voice delivery instructions change presentation, not routing or required information.

No voice-only preprocessing bypass, lower-information context, forced model/provider, or speculative paid execution is introduced by this correction. Future optimization should compare text and voice timings and preserve decision/context outputs, with first token and first useful spoken clause measured separately.

## Verified provider boundary and current limits

A bounded real-provider check on 2026-10-25 sent two synthetic text inputs totalling 84 characters. Actual audio arrived before the second input was supplied, in 159 ms from connection setup; 19 audio chunks drained with a real final marker, and the entire probe completed in 884 ms. This proves incremental provider input/output and termination, not full OpenMates call latency or browser playback. No audio file was written. The parser accepts the provider's empty audio envelope as a bounded no-op; it still requires real nonempty output and explicit final completion.

Provider alignment timestamps restart within returned chunks. The integration deliberately makes no global timing inference from them. Partial playback therefore supplies explicit conservative empty heard coverage until verified timing is available; clean provider completion, successful semantic membership seal and actual native playback end are all required for full heard completion. A continuous MP3 track is separate from immutable semantic clauses.

The asynchronous speech owner runs alongside the common AI request and its final bounded drain occurs after ordinary canonical persistence and postprocessing. The AI worker slot remains occupied during that final drain, bounded by the turn lifetime. This is a measurable future worker-capacity optimization, not an excuse to bypass preprocessing or claim that provider output blocks the first response. Metadata handoff timing retains its existing policy.


## Isolated voice regression configuration

The complete voice suite needs the same canonical saved-chat recovery protocol as dev. A read-only authoritative dev check confirmed epoch 1, with sends enabled and no legacy turns in flight. Fresh isolated databases begin at epoch 0; completed-reply discovery correctly refuses that disabled state, so testing voice turns there stops before inference or speech generation.

The voice suite therefore uses a dedicated, narrowly guarded activation fixture after disposable account provisioning and before browser execution. It verifies the exact private voice/storage profile, runs the normal pause/activate/resume transaction, and records the durable and cached acknowledgements. Other fixture gates retain their existing restrictions. Product discovery, privacy and admission checks remain intact; disabled or failed discovery is never accepted as empty history.


## Concurrent call completion persistence

The full authenticated call regression found that immediate hangup can append its lifecycle entry between assistant completion writes. A local optimistic revision and the later lifecycle append can cause two consecutive legitimate compare-and-swap conflicts. The existing browser recovery handler now allows at most four writes, refreshing the authoritative revision after each conflict without changing the encrypted payload, completion identity or lease. Session, socket and foreground authority remain required across each await; invalid refreshes, other errors and exhausted retries fail closed. No inference is replayed and the backend compare-and-swap remains strict. This narrowly repairs the existing browser transport during the shared Rust transition; it adds no reusable TypeScript recovery policy module.
