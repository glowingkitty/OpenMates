# Offline speech and PII investigation

Research date: October 3, 2026. The user rejected Apple system voice quality after
TestFlight testing and authorized removing that laboratory and testing Pocket TTS.
Kokoro remains removed. Production assistant speech routing is unchanged.

## Pocket TTS experiment

Pocket TTS is the first listening experiment, not a proven iPhone quality or latency
recommendation. Kyutai's current multilingual release includes English and German,
but the pinned Rust/Candle Apple loader uses the compatible January English model.
This initial lab therefore offers **English, Alba only**. It must not advertise
German until the multilingual weights/tokenizer/runtime combination is verified.

The released UnaMentis binary has iOS device/simulator slices, without macOS.
The implementation uses pinned source through a small CPU bridge for supported
Apple targets. Model, tokenizer and voice assets are independently verified;
approximately 236 MB is downloaded only after the user requests it. No weights
are bundled. The model license is CC BY 4.0; the selected voice's attribution
must accompany its assets. Upstream token diagnostics are suppressed in the pinned
source preparation so private input cannot appear in logs.

Primary references: [Kyutai overview](https://kyutai.org/tts/),
[quality report](https://kyutai.org/pocket-tts-technical-report/),
[multilingual release](https://kyutai.org/blog/2026-05-04-pocket-tts-multilingual/),
[upstream model](https://huggingface.co/kyutai/pocket-tts),
[voice licenses](https://huggingface.co/kyutai/tts-voices),
[Apple Rust loader](https://github.com/UnaMentis/pocket-tts-ios).

For quality evaluation, compare loudness-matched, anonymously labeled samples
against existing server voices. Use prose, names, dates and numbers; measure cold
load, warm first audible PCM, synthesis real-time factor, sampled memory,
cancellation, underruns and ten-minute thermal behavior on iPhone 13 Pro, iPad
and Mac. Desktop or Simulator timings do not establish physical-phone performance.

Supertonic 3 is a possible multilingual comparison, but its upstream repository
is archived and support ended. Kitten is a smaller English-only comparison.
Neither is included in the current implementation.
[Supertonic](https://github.com/supertone-oss-archive/supertonic),
[Kitten Swift](https://github.com/KittenML/KittenTTS-swift).

## Same-model Core ML feasibility

The existing OpenAI Privacy Filter has 33 BIOES token labels and calibrated Viterbi
span decoding. A Core ML conversion must preserve tokenization, offsets, window
seams and span semantics, not only approximate logits.
[OpenAI model card](https://huggingface.co/openai/privacy-filter).

A community Neural Engine prototype reports macOS results, but its published
repository lacks referenced conversion/driver files and uses shorter sequences.
No validated iPhone/iPad drop-in with equivalent spans was found. Retain the
existing pinned ExecuTorch/XNNPACK model as the user explicitly allowed.
[Prototype report](https://github.com/videlalvaro/ane-book/blob/main/models/privacy-filter/README.md),
[prototype validation](https://github.com/videlalvaro/ane-book/blob/main/models/privacy-filter/build_scripts/eval_pf_full_chain.py),
[ExecuTorch Core ML support](https://docs.pytorch.org/executorch/stable/backends/coreml/coreml-overview.html).

Core ML compute-unit configuration permits device selection; it does not prove
Neural Engine placement. A future conversion requires compute-plan inspection,
span fixtures and physical-device memory/latency measurements.
[Apple execution](https://apple.github.io/coremltools/docs-guides/source/typed-execution.html).

## Responsive composer PII

The prior developer test created and unloaded the model on every run; its reported
inference time included tokenizer/configuration/model activation. Measure those
phases independently before attributing the reported four seconds to warm inference.

The approved production design keeps one module warm while an eligible composer
is active, publishes regex matches immediately, and debounces contextual scanning
by 500 ms. One native scan owns resources at a time; only the newest pending text
is retained. Exact text, settings, route and account-generation checks reject
obsolete highlights. Send verifies the immutable current document and preserves
exclusions and encrypted mappings. Missing or unavailable assets retain existing
regex processing. No input is logged, persisted as diagnostics or submitted to a
network inference service.

A background task here means work away from the main UI thread while the app is
active. It does not promise inference after iOS suspends the app. Memory warnings,
page/account changes, removal and disabled privacy settings release ownership.

## Current reported failures

- Audio source comparison found a dev upload host mismatch and missing `/v1` on
  batch transcription. These explain plausible transport failures; the screenshot
  alone does not establish the physical-device HTTP status.
- Tasks deployed legacy inventories lack the newer pagination completeness receipt.
  Compatibility must never cache a capped response as a complete offline snapshot.
- Download Live Activities must use ActivityKit authorization independently of
  push/notification authorization. Successful download notifications remain separate.
- Navigation performance needs local-first coherent publication and measured work
  on the main actor, rather than guesses based on reconnecting banners.

Native tests, actual model execution and physical-device observations are recorded
separately. Dev-host CI/deployment remains deferred until the user's Monday SSH window.

## Measured Mac runtime checks (2026-10-03)

On the M1 MacBookPro17,1 with 8 GB memory, the installed TestFlight 90 PII lab
completed a fixed synthetic three-entity sample in 6.62 seconds, including cold
loading. The exact new production engine in an isolated release CLI measured
3.94 seconds to warm, then 2.65, 2.14 and 2.02 seconds per warm scan. All three
values were covered. Raw BPE ranges included leading whitespace for email and
phone; the production adapter now trims whitespace-only boundaries before
merging. Sampled resident memory peaked at 1,332,985,856 bytes and remained there
immediately after unload, so warming does not establish a memory reduction.

The pinned Pocket English/Alba CPU bridge generated a real, non-silent 24 kHz
mono PCM16 WAV: 3.12 seconds of audio in 2.413 seconds total, with a 0.341-second
model load. These are actual Mac runtime results, not iPhone performance or a
subjective voice-quality verdict. Device listening and thermal tests remain.
An isolated repeat measured 2.201 seconds total, a 0.427-second load and
617,431,040 bytes maximum resident memory, with no swaps recorded by `time -l`.
Inference was measured without another model or native build running.

Local receipts: `.runtime/followups98/pii-benchmark174-receipt.json` and
`.runtime/followups98/pocket-smoke173-receipt.json`; fixed public synthetic inputs
only. No authenticated app installation was replaced for these checks.
The repeated Pocket memory measurement is in `.runtime/followups98/pocket-memory175.log`.
