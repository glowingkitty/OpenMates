# Whisper on Apple Watch

Research date: **2026-10-03**. The original research did not build, run or download Watch models.
The subsequently authorized experiment is now implemented in source; native
verification is owned by the root agent. Physical Watch performance is unverified.

## Answer

**WhisperKit has explicit watchOS support and an upstream Watch example. The
current OpenMates large-v3 model has not been shown to work well on Watch, and
OpenMates excludes the existing large-v3 model from Watch inference.
A separate explicitly enabled multilingual tiny experiment is now authored.** Phone/iPad success establishes
neither Watch model compatibility nor acceptable latency, memory or battery use.

The pinned package declares watchOS 10+, alongside iOS 16+ and macOS 13+.
Its Watch example restricts its normal UI to the `Watch7` device family, describes
that gate as Series 9/Ultra 2, and offers `tiny`, `tiny.en`, `base` and `base.en`
initially. That example gate is not a universal statement about every Watch
generation. [Pinned package manifest](https://github.com/argmaxinc/argmax-oss-swift/blob/1e2a163736dfa5a198e637ae44c114e1c6d5cc2d/Package.swift),
[pinned Watch example](https://github.com/argmaxinc/argmax-oss-swift/blob/1e2a163736dfa5a198e637ae44c114e1c6d5cc2d/Examples/WhisperAX/WhisperAXWatchApp/WhisperAXExampleView.swift).

## Exact current OpenMates selection

| Item | Current workspace evidence |
| --- | --- |
| Runtime | `WhisperKit` product from `argmaxinc/argmax-oss-swift`, revision `1e2a163736dfa5a198e637ae44c114e1c6d5cc2d`, corresponding to upstream **v1.1.0**. |
| Model | `openai_whisper-large-v3-v20240930_626MB`, Argmax Core ML conversion, revision `0f63a7800b00dd0226abd051b906c246e1907482`. |
| Download total | **629,481,698 bytes** across 19 catalog assets, including tokenizer files: 629.5 decimal MB, approximately 600.3 MiB. This is asset size, not an inference RAM measurement. |
| Tokenizer | OpenAI `whisper-large-v3`, revision `06f233fe06e710322aca913c1bc4249a0d71fce1`, supplied locally. |
| Watch integration | The local runtime import, tokenizer implementation and inference branch use `arch(arm64) && !os(watchOS)`. Its other branch throws `unavailableRuntime`. The newly authored separate Watch tiny adapter uses the same pinned WhisperKit product, and does not expose large-v3. |

Local evidence: [catalog](../../../apple/OpenMates/Resources/LocalModels/catalog.json),
[resolved packages](../../../apple/OpenMates.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved),
[runtime](../../../apple/OpenMates/Sources/Core/LocalModels/LocalSpeechRuntimes.swift),
[target configuration](../../../apple/OpenMates.xcodeproj/project.pbxproj).
Upstream associates the same runtime revision with
[v1.1.0](https://github.com/argmaxinc/argmax-oss-swift/releases/tag/v1.1.0).

## What the available evidence proves

- Apple documents `MLModel` on watchOS. Framework availability makes a Core ML
  experiment possible; it does not certify this compiled model bundle, operator
  placement, or workload. [Apple MLModel](https://developer.apple.com/documentation/coreml/mlmodel).
- A first-person upstream discussion reports completing **tiny.en** inference on
  one Watch. Its fixture is five seconds of silence, its runtime is described only
  as 0.9.x, and its memory measurement is before/after resident size. This supports
  feasibility for that small English model; it is not a speech-accuracy benchmark,
  a measured peak, or evidence for our pinned large-v3 bundle. The hardware/OS
  descriptions and full harness would need confirmation before treating its
  timing numbers as reproducible. [Community feasibility report](https://github.com/argmaxinc/argmax-oss-swift/discussions/437).
- Apple warns that Watch apps normally suspend after wrist lowering; sustained CPU
  use can invalidate extended runtime sessions. Those sessions have specific
  permitted purposes, not a general transcription background entitlement.
  [Apple runtime guidance](https://developer.apple.com/documentation/watchkit/using-extended-runtime-sessions).
- Switching to whisper.cpp does not establish support for this integration. Its
  current Apple XCFramework build script includes iOS, macOS, visionOS and tvOS
  slices, with no Watch build step. It also requires its own runtime/model
  integration. [Current upstream build script](https://github.com/ggml-org/whisper.cpp/blob/master/build-xcframework.sh).

## Recommendation and next test

Keep the existing large-v3 selection confined to its current supported app
targets. A separate **foreground Watch feasibility experiment with multilingual
`tiny`** is a reasonable next step if English and German are required; `tiny.en`
would test English only. This is a proposed experiment, not a shipping
recommendation or a claim that small models already meet the required accuracy.
[OpenAI model/language variants](https://github.com/openai/whisper#available-models-and-languages).

First verify a watchOS build of the pinned runtime and an explicitly pinned small
model/tokenizer on the actual intended Watch. Then use identical short spoken
English/German fixtures with network disabled. Measure cold loading separately
from warm transcription, transcript accuracy, current/peak process memory,
jetsam, CPU/energy, cancellation, repeated runs and wrist-lowering behavior.
Evaluate the current large-v3 bundle only after that baseline establishes a safe
device-specific test path; do not predict RAM or speed from its download size.

Apple's Core ML performance report covers load/prediction time and compute-unit
placement, **not memory or power**. Those need separate profiling and device
logs. [Core ML measurement guidance](https://developer.apple.com/documentation/coreml/analyzing-a-core-ml-model-s-performance-in-xcode),
[jetsam guidance](https://developer.apple.com/documentation/xcode/identifying-high-memory-use-with-jetsam-event-reports).

## Authorized tiny experiment implementation

The Watch developer lab selects **`openai_whisper-tiny`**, not `tiny.en`, from the
same Argmax immutable revision `0f63a7800b00dd0226abd051b906c246e1907482`.
Its local tokenizer is OpenAI `whisper-tiny` at revision
`169d4a4341b33bc18d8881c4b69c2e104e1cc0af`. The complete catalog contains
**21 files and 79,398,546 bytes**. LFS metadata supplies SHA-256 for large files;
small text files were fetched from immutable URLs to compute their SHA-256.
No weights were downloaded while writing this change.
[Argmax pinned tiny tree](https://huggingface.co/argmaxinc/whisperkit-coreml/tree/0f63a7800b00dd0226abd051b906c246e1907482/openai_whisper-tiny),
[OpenAI pinned tiny tokenizer](https://huggingface.co/openai/whisper-tiny/tree/169d4a4341b33bc18d8881c4b69c2e104e1cc0af).

Catalog: `apple/OpenMatesWatch/Resources/watch-whisper-tiny.json`.
The Watch-specific adapter follows the existing store's bounded checksum and
atomic installation pattern, but owns a distinct root and catalog to avoid
linking the privacy-filter/iOS Live Activity stack or selecting large-v3.
The runtime cold-creates a local tokenizer and WhisperKit instance with
`download: false`, performs local transcription, and unloads before the
controller becomes idle. No fallback selects a cloud endpoint.

The experiment is reached through Watch Settings, Developers. It is explicitly
enabled and runs in the foreground. A microphone recording is limited to thirty
seconds. The Watch has no document picker; the ephemeral import API supports
unit and DEBUG UI fixtures. Paired-phone document transfer is outside this
requested experiment. Cancellation, page exit and backgrounding clear private
results and wait for the native operation/unload before releasing audio files.
The UI exposes load/transcribe/unload duration and start, sampled peak and end
resident memory, with unavailable measurements labeled accordingly.

`WatchWhisperLabTests` proves catalog, hash/revision, interrupted-transfer,
local-reopen, lifetime and cancellation outcomes using tiny disposable fixtures.
`WatchWhisperLabUITests` proves visible controls/results through a runtime stub;
its positive transcript is fixture output and does **not** establish real Whisper
accuracy. Root owns all Xcode/simulator runs. Physical Watch latency, accuracy,
peak memory, jetsam and battery behavior remain unverified.
