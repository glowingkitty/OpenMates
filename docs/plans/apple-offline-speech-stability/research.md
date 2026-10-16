# Offline speech and PII investigation

Updated October 4, 2026. The user rejected Pocket TTS's heard quality and requested
complete removal. Its runtime, developer lab, catalog and build dependency are
removed. Apple system voice testing and Kokoro remain removed. Supertonic3 and exact KittenTTS Mini0.8 were subsequently selected for developer testing; the release92 removal remains historical, and no production speech replacement is selected. Implementation/native verification is pending. Existing chat speech uses its separate
server-produced/encrypted-media and public-example pipeline; Pocket was never its
provider. Whisper, enhanced PII and their download/privacy safeguards remain.

## Current offline neural TTS candidates

These are source/compatibility findings, **not listening results**. No samples,
models or inference were run for this research. Published realism and speed claims
do not establish human quality, memory use or reliability on iPhone 13 Pro.

| Candidate | Runtime and size evidence | License and Apple compatibility evidence |
| --- | --- | --- |
| **Supertonic 3** (April 29 release) | 99M parameters; ONNX Runtime; English/German plus 29 other languages. Four current ONNX assets total **398,075,273 bytes** before configs/voice styles/runtime. | Sample code MIT; weights OpenRAIL-M. Official examples specify iOS 15+ and Swift/macOS 13+. The official repository was archived September 9, 2026 and support ended; this is an evaluation candidate requiring owned maintenance, not a maintained integration recommendation. [Archive/status](https://github.com/supertone-oss-archive/supertonic), [model](https://huggingface.co/supertone-oss-archive/supertonic-3), [file sizes](https://huggingface.co/api/models/supertone-oss-archive/supertonic-3/tree/main?recursive=true&limit=1000), [iOS example](https://raw.githubusercontent.com/supertone-oss-archive/supertonic/main/ios/README.md), [Swift example](https://raw.githubusercontent.com/supertone-oss-archive/supertonic/main/swift/README.md). |
| **KittenTTS 2**, current flagship main/weights | 1.7B speech language model; Python/PyTorch or publisher C++ llama.cpp fork. Publisher describes 947 MiB lossless and 506 MiB embedding-quantized packages, ~6 GB RAM for CPU, and multilingual/expressive fixed voices. These sizes are not the much smaller legacy ONNX model. | Code Apache-2.0; weights **Stellon Labs Community License**, with its own commercial/attribution conditions. Current official Swift SDK supports legacy 0.8, not this architecture; the official website says TTS 2 device SDKs are forthcoming. Mac listening/resource feasibility can be investigated, but no iPhone/iPad native compatibility is established here. [Current source](https://github.com/KittenML/KittenTTS), [weights/license](https://huggingface.co/KittenML/kitten-tts-2), [SDK status](https://kittenml.com/). |
| **Kitten legacy 0.8**, latest tagged package **0.8.1** | English ONNX: Mini 80M (~80 MB), Micro 40M (~41 MB), Nano 15M (~56 MB), Nano int8 (~25 MB). Mini's model plus voice file are **81,546,918 bytes**, before phonemizer/runtime assets. Smallest download does not imply best voice quality. | Mini weights and Swift code Apache-2.0. Publisher Swift SDK uses ONNX Runtime on iOS 16+/macOS 14+. Its default C++ phonemizer downloads GPLv3 data files; resolve packaging/terms and pin all files before distribution. Stock first-use downloads must be replaced by explicit verified installation in any future app integration. [Tagged releases](https://github.com/KittenML/KittenTTS/releases), [Mini weights](https://huggingface.co/KittenML/kitten-tts-mini-0.8), [file sizes](https://huggingface.co/api/models/KittenML/kitten-tts-mini-0.8/tree/main?recursive=true&limit=1000), [official Swift SDK](https://github.com/KittenML/KittenTTS-swift), [package dependency](https://github.com/KittenML/KittenTTS-swift/blob/main/Package.swift). |
| **NeuTTS Nano / NeuTTS-2E** | Nano: ~120M active parameters, separate English/German/French/Spanish variants; 2E: ~125M active, English emotional/fixed-speaker model. GGUF llama.cpp backbone plus separate NeuCodec decoder: Q4 files **195 MB Nano / 301 MB 2E**, plus **312 MB** ONNX int8 decoder and tokenizer/reference assets. | Nano/2E weights use **NeuTTS Open License 1.0**; Air is a different, larger Apache-2.0 model. Decoder card identifies Apache-2.0. Weight access is publisher gated. Upstream Python/GGUF/ONNX support and Android/iMac backbone benchmarks exist; no official complete Swift/iPhone pipeline or end-to-end iPhone measurement was established. [Runtime/model matrix](https://github.com/neuphonic/neutts), [Nano file listing](https://huggingface.co/neuphonic/neutts-nano-q4-gguf/tree/main), [2E file listing](https://huggingface.co/neuphonic/neutts-2e-q4-gguf/tree/main), [decoder listing](https://huggingface.co/neuphonic/neucodec-onnx-decoder-int8/tree/main). |

File sizes above came from the publisher's current metadata/listings, without
fetching weights; they are not installation memory estimates. Pin revisions and
check the complete tokenizer, decoder, phonemizer and licensed preset-voice asset
set before any separately approved experiment. Use presets; no private voice
cloning input is needed.

## Recommended next bounded experiment (proposal only)

Prioritize **blind listening**, then decide whether a mobile prototype is worth
building. Compare Supertonic 3 and Kitten Mini 0.8 as the two existing Apple-path
candidates; add current KittenTTS 2 as a Mac quality comparator only if its memory
budget fits the available host. NeuTTS-2E can be a later fixed-voice comparator
once publisher access/terms and its full decoder pipeline are resolved. None is
selected as the replacement and no quality winner is claimed.

Use six fixed public sentences (prose, dates/numbers, names, a question, technical
terms and a short paragraph), two licensed preset voices, and loudness-matched,
anonymous samples. Let the user judge naturalness, pronunciation and artifacts.
Include German samples for multilingual candidates, without pretending English-only
Kitten Mini provides German. Stop after this small listening set if all fail the
user's quality requirement; do not ship another rejected laboratory adapter.

For a preferred voice only, separately authorize an isolated offline iPhone 13 Pro,
iPad and Mac probe. Measure cold load, warm first audible PCM, synthesis real-time
factor, peak/end resident memory, cancellation drain, underruns and a ten-minute
thermal run while the UI remains responsive. Verify no inference network traffic,
explicit asset installation and no fallback. Desktop timings, LM token throughput
and an iOS example's existence do not prove full audio-generation phone performance.

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

Historical Pocket measurements below predate the user quality rejection and removal;
they are retained as evidence, not a current recommendation.

The removed Pocket English/Alba CPU bridge generated a real, non-silent 24 kHz
mono PCM16 WAV: 3.12 seconds of audio in 2.413 seconds total, with a 0.341-second
model load. These are actual Mac runtime results, not iPhone performance or a
subjective voice-quality verdict. The user subsequently rejected its listening quality; it will not receive further adapter integration.
An isolated repeat measured 2.201 seconds total, a 0.427-second load and
617,431,040 bytes maximum resident memory, with no swaps recorded by `time -l`.
Inference was measured without another model or native build running.

Local receipts: `.runtime/followups98/pii-benchmark174-receipt.json` and
`.runtime/followups98/pocket-smoke173-receipt.json`; fixed public synthetic inputs
only. No authenticated app installation was replaced for these checks.
The repeated Pocket memory measurement is in `.runtime/followups98/pocket-memory175.log`.


## Selected developer tests (later October4 approval)

Supertonic source is pinned to the archived publisher repository; its current HF revision is `aafc6e32416a594460b32413efc49d7fe4ce6d46`. Complete four-model/config/indexer/ten-stock-style/license installation totals **401,291,751 bytes**. Source MIT; weights/styles OpenRAIL-M. The official Swift example is an executable, so the lab adapts the attributed helper with CPU thread bounds and cancellation checks. No maintained-support or heard-quality promise is made. [Pinned assets](https://huggingface.co/supertone-oss-archive/supertonic-3/tree/aafc6e32416a594460b32413efc49d7fe4ce6d46), [publisher source](https://github.com/supertone-oss-archive/supertonic).

Exact Kitten Mini0.8 revision `c02725660cea441db4c383af69f1f26f5cd00947` has **81,547,388 bytes** including ONNX, voice embeddings and config. The user-approved compatibility path uses the publisher's pure Swift `BuiltinPhonemizer`: roughly300-word dictionary and simplified rules. It excludes all CE/eSpeak code, GPL data and network download implementations. The pronunciation frontend differs from the stock SDK; this is explicitly labeled and no quality equivalence is claimed. The pinned SDK README declares Apache2.0 but its LICENSE link is missing; include standard Apache text and preserve headers. [Exact weights](https://huggingface.co/KittenML/kitten-tts-mini-0.8/tree/c02725660cea441db4c383af69f1f26f5cd00947), [SDK](https://github.com/KittenML/KittenTTS-swift/tree/20cd4d8784c1bad348326955709892c8dfe7226b), [pure Swift frontend](https://github.com/KittenML/KittenTTS-swift/blob/20cd4d8784c1bad348326955709892c8dfe7226b/Sources/KittenTTS/Phonemizer/BuiltinPhonemizer.swift).

The default C++ SDK headers declare original Apache code rather than linked GPL eSpeak code, but mapping/reference comments do not independently prove provenance. English rules/list files are definitively GPL3-or-later. OpenMates' App Store exception cannot grant exceptions for third-party GPL copyrights. The selected pure Swift path removes this dependency question rather than treating download delivery as a license exemption. [C++ declaration](https://github.com/KittenML/KittenTTS-swift/blob/20cd4d8784c1bad348326955709892c8dfe7226b/Sources/CEPhonemizer/phonemizer.cpp), [data license header](https://raw.githubusercontent.com/espeak-ng/espeak-ng/59eb19938f12e30881c81d86ce4a7de25414c9f4/dictsource/en_rules).

Both use Microsoft ONNX Runtime1.20.0 (`12ce7374c86944e1f68f3a866d10105d8357f074`), MIT. Its official package supports iOS13+/macOS11+ and pins binary zip checksum `50891a8aadd17d4811acb05ed151ba6c394129bb3ab14e843b0fc83a48d450ff`. Kitten SDK raises its own platform minima to iOS16/macOS14. No ORT package was found in assigned/canonical repository runtime caches; global caches were not mutated or resolved. Native package compatibility remains a parent-lane check. [Microsoft package](https://github.com/microsoft/onnxruntime-swift-package-manager/blob/12ce7374c86944e1f68f3a866d10105d8357f074/Package.swift).

Next verification: source-frozen native compile and synthetic unit/UI tests first. Then explicit asset downloads and an offline fixed-text listening comparison with measured cold/repeat timings, first-audio time, numeric baseline/peak/end memory, cancellation/page/account cleanup and removal. Physical iPhone13Pro/iPad evidence is separate from Mac results. No weights/native engines, synthesis or audio playback were performed during this draft phase.


## Native ONNX compatibility verification (October4, build92 candidate)

The source-frozen iOS Simulator test build and 542 focused native tests passed.
An explicitly opted-in smoke test revalidated all 20 pinned downloaded assets,
then ran both production CPU adapters with the public phrase “Hello world.
This is a local speech test.” No remote inference or audio playback occurred.

| Exact model | Output | Cold adapter execution | Signal |
| --- | --- | --- | --- |
| Supertonic3, F1/en, 8 steps | 3.3101s, mono 44,100Hz | 1.9071s | peak 0.2722, RMS 0.04264 |
| Kitten Mini0.8, Bella/en | 5.3667s, mono 24,000Hz | 4.3073s | peak 0.6368, RMS 0.08902 |

These timings include the adapter's model load, synthesis, WAV writing and
unload on the Mac-hosted arm64 Simulator. They exclude prior asset verification
and do not establish physical iPhone performance or pronunciation quality.
Both generated files were removed after validation; installed assets remained
read-only. The bounded Supertonic chunker additionally preserves unspaced CJK,
combining/ZWJ graphemes and comma separators.

Source content SHA256: `d60d8415c91bda3cefbbe35864649d845ac1c077f6679899d6b68b0aadd2de55`.
Test-input SHA256: `cf9098c23d6f13e4ad6fc9a32178598b2dd02268f7d06dd0ce9b984e914c0405`.
Private receipts: `native-focused491-receipt.json`,
`native-tts-smoke488-receipt.json`, and the two numeric JSON attachments in
`tts-smoke488-attachments/`. Developer UI, release builds and listening evidence
are reported separately.
