# Gemini voice and H3 Turbo experiment

The first implementation evaluates whether native Gemini conversation and short
generated video clips make a useful explanation experience. It lives at
`/experiment/videocall`, separate from ordinary chats. It does not save recordings,
transcripts, messages or app-skill results.

The permanent experimental contract is
[`feature.video-call-experiment`](../../specifications/features/video-call-experiment/specification.yml).
The separate [full-mode draft](../../specifications/features/video-call/specification.yml)
describes future chat binding, skills and recordings. The executable scope is in
the [experiment Plan](../plans/video-call-experiment/plan.yml).

## Connection and media

The browser uses the private `/v1/experiment/videocall` WebSocket with the existing
session ID and a short-lived, user-bound WebSocket token. Origin, authentication,
credit admission and a Redis per-user call lock precede any provider connection.
Provider keys come from the existing Vault entries for Google AI Studio and fal.

Microphone audio is PCM16 at 16 kHz. Gemini supplies native PCM speech at 24 kHz,
user/model transcription and one non-blocking `generate_visual_clip` function.
There is no separate speech synthesis service or ordinary app-skill dispatcher.
Audio sources are scheduled continuously and flushed on interruption. Video
ambience is quieter and ducks further while either participant speaks.

H3 Max Turbo returns completed MP4 clips. Five-second 480p requests use disabled
prompt expansion. The first request can start from text; following requests use
the previous clip's final frame. The browser separately samples the actually
displayed video for Gemini at up to one frame per second. These feedback frames
do not refresh the visual-instruction timer.

Only one generation request can be outstanding. New Gemini visual instructions
steer the next request; they cannot rewrite frames already generated. Ten seconds
without a new instruction closes the visual segment and leaves voice running.
User Close video, hangup, expiry and disconnect fence late results and stop new
paid requests. The experiment ends after two minutes and does not reconnect
automatically. Wide screens show transcript and video together; narrow screens
retain call controls and transcript access over the video experience.

MP4 files and browser Blob URLs are transient. Server downloads accept bounded
media only from the fal CDN, and authenticated queue requests use validated fal
URLs. Neither provider credentials nor arbitrary client URLs reach this path.
Provider-side media retention remains subject to fal's account settings; the
experiment does not promise deletion of provider-hosted outputs.

## Costs researched on 6 October 2026

Accounting uses USD 0.001 per credit and a 1.2 multiplier. EUR examples use the
existing EUR 20 / 21,000-credit pack, so one credit corresponds to EUR 0.00095238
of that purchased pack. They are user-credit equivalents, not currency conversion
or a new tax-inclusive retail quote.

| Usage | Provider price | Credits at 1.2 | Pack-equivalent EUR |
| --- | --- | --- | --- |
| H3 Turbo 480p generated second, promotion | USD 0.015 | 18 | 0.0171 |
| Five generated seconds, promotion | USD 0.075 | 90 | 0.0857 |
| Sixty generated seconds, promotion | USD 0.90 | 1,080 | 1.0286 |
| H3 Turbo 480p generated second after promotion | USD 0.025 | 30 | 0.0286 |
| Five generated seconds after promotion | USD 0.125 | 150 | 0.1429 |
| Sixty generated seconds after promotion | USD 1.50 | 1,800 | 1.7143 |
| Gemini fresh audio input minute plus audio output minute | USD 0.023 | 27.6 | 0.0263 |
| Gemini fresh visual input minute, indicative | USD 0.002 | 2.4 | 0.0023 |

The [Turbo-specific price notice](https://fal.ai/models/minimax/h3-max-turbo/image-to-video)
says its promotion ends October 15; the implementation changes rates on October
16 UTC. The actual generated output can be longer than requested. Published
prices and provider billable duration must be checked against the first real
provider usage receipt; requested duration is not proof of final billing.

[Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) is per modality
token: input text/audio/visual USD 0.75/3/1 per million; output text/audio USD
4.5/12 per million. Per-minute examples exclude transcript text and repeated
conversation context. The server meters reported usage, retains fractional
credits and settles through the existing idempotent credit ledger. The visible
audio rate is an estimate; ongoing credited spend is authoritative. A frozen
frame or replayed clip is not new generation.

The UI shows rounded whole credits per minute: approximately 28 for the base
voice estimate and 1,108 for voice plus 480p generated video at the promotional
rate. Display rounding does not alter proportional per-second usage billing.
Positive billable usage has a one-credit minimum; failed admission or microphone
permission does not create a charge.

## Evaluation and future recording

Mocked backend, controller and browser checks prove lifecycle, controls and
metering behavior. They cannot prove provider latency, seamless continuity,
instruction adherence or scientific accuracy. A scoped dev evaluation must
measure time to first audio/video, clip gaps, redirection delay, voice intelligibility,
frame feedback and actual billed costs before deciding whether to expand.

Future full mode saves exactly one encrypted recording at call end: audio for
an entirely audio-only call, or video for the entire call if any interval had
video. Audio-only gaps in that video show a circular mate portrait and a gently
animated AI icon. Both participant voices and audible video ambience belong in
the recording. Encryption precedes S3 upload. Composition technology, including
Remotion, remains deferred until this experiment is evaluated.

Provider references: [Gemini Live capabilities](https://ai.google.dev/gemini-api/docs/live-api/capabilities),
[non-blocking functions](https://ai.google.dev/gemini-api/docs/live-api/tools),
[H3 Turbo schema](https://fal.ai/models/minimax/h3-max-turbo/image-to-video/api),
and [fal queue cancellation](https://fal.ai/docs/documentation/model-apis/inference/queue).
