# Seamless offline speech and enhanced anonymization

Planning snapshot: 8 October 2026, TASK-8137. This extends the [existing Apple stability Plan](plan.yml), using its existing speech, PII, notifications, settings and local-model contracts. It records proposed follow-up work; it does not claim that the following production integration ships in build96 or approve a future changed contract fingerprint.

## What is available today

| Capability | Production behavior | Local model and remaining integration |
| --- | --- | --- |
| Speech to text | Microphone transcription uses server Voxtral Realtime. Recordings also take the batch/upload path; successful realtime transcription does not establish that audio stays on the device. | Whisper large-v3 is a downloaded laboratory model: **629,481,698 bytes** (629.5 MB). The laboratory loads a model, transcribes a file and unloads it; bundled incremental composer transcription is pending. |
| Text to speech | Responses use provider-generated audio, with encrypted stored assets. | Supertonic3 is a downloaded laboratory model: **401,291,751 bytes** (401.3 MB). Local-first production playback, idle preparation and bounded chunk streaming are already authorized follow-ups and remain pending. |
| Enhanced PII anonymization | Optional local ExecuTorch/XNNPACK inference is integrated with foreground model retention, 500 ms edit debounce and exact outgoing-revision validation at Send. Local regex detection remains available. | The verified package is **1,269,572,251 bytes** (about 1.27 GB). Its XNNPACK artifact runs on CPU; a dedicated equivalent Core ML export would require qualification. |
| Watch transcription | Production transcription currently uses the server route. | The separate foreground tiny Whisper laboratory uses **79,398,546 bytes** (79.4 MB). Physical Watch speed, sustained battery, memory and transcript quality remain unqualified. |

Package sizes come from the pinned [local-model catalog](../../../apple/OpenMates/Resources/LocalModels/catalog.json) and [Watch tiny-model manifest](../../../apple/OpenMatesWatch/Resources/watch-whisper-tiny.json). They describe downloads, not installed disk use or working memory. Current phone/Mac laboratory support is arm64; Intel support needs its own decision and qualification.

Source references: [realtime client](../../../apple/OpenMates/Sources/Core/Networking/AudioRealtimeTranscriptionClient.swift), [recording submission](../../../apple/OpenMates/Sources/Features/Chat/ViewModels/ChatViewModel.swift), [Whisper laboratory](../../../apple/OpenMates/Sources/Core/LocalModels/LocalSpeechRuntimes.swift), [production speech runtime](../../../apple/OpenMates/Sources/Shared/Composer/AssistantSpeechAppRuntime.swift), [local TTS laboratory](../../../apple/OpenMates/Sources/Core/LocalModels/LocalNeuralTTSRuntime.swift), and [production PII runtime](../../../apple/OpenMates/Sources/Core/LocalModels/ProductionPIIRuntime.swift).

## What the measurements permit

The retained M1 enhanced-PII benchmark measured a **3.94 s cold load**, isolated warm scans of **2.65, 2.14 and 2.02 s**, and sampled peak process RSS of about **1.24 GiB**. Process RSS remained allocated after unload; the receipt does not establish memory release. These scans do not measure residual Send delay, p95 performance, concurrent speech memory or physical iPhone/iPad behavior. They do not qualify the current CPU path for an activation recommendation promising no noticeable Send delay.

Until a device/model/language/text-length envelope passes that qualification, show only a one-time information banner pointing to Privacy settings. Installed, opted-in models must still validate the exact outgoing revision; hiding latency must never bypass privacy correctness. The existing recommendation's 30-day dismissal is separate from the proposed flow below.

Proposed usability targets are p95 residual Send delay of **at most 100 ms for an already prepared draft** and **at most 200 ms for representative last-second edits**. These are proposed budgets, not measured promises or approved product-contract requirements.

## Integration sequence

1. **Bundle and qualify offline transcription on iOS, iPadOS and macOS.** Select verified multilingual Whisper/Core ML assets and tokenizer, using a smaller baseline where necessary. Connect microphone PCM to incremental decoding with voice-activity detection, editable partial/final transcripts, cancellation and stale-generation fencing. Retain warm resources while an eligible composer is active, within measured memory limits. A transcript-only local route must open no realtime socket, upload no recording and attach no audio. Recording sharing or server fallback requires a separate explicit choice. Qualify Intel separately or disclose its support limit.

2. **Integrate Supertonic3 into response playback.** Preserve explicit verified downloads and selected voice/language mapping. Prepare an installed selected engine after the chat has fully opened and becomes idle. Use a single owner off the main actor, bounded semantic chunks, safe cancellation on account/chat/voice changes and memory-pressure eviction. Measure first audible audio and continuous playback. Keep provider fallback explicit and separate from a local-only mode. Kitten, Pocket, Kokoro and rejected Apple system-voice testing remain removed.

3. **Qualify enhanced anonymization before recommending activation.** Reuse complete results bound to the exact draft revision, model, options and account context. Coalesce obsolete edits and evaluate safe overlap-aware reuse without losing entities across token/window boundaries. Measure the existing CPU path first; separately evaluate a dedicated equivalent Core ML export and actual compute placement. Send must await any incomplete exact outgoing-revision check. An asynchronous scan while typing does not grant execution after iOS suspends the app.

4. **Add the conditional consent flow.** Only qualified devices receive an activation recommendation; other devices receive the one-time Privacy settings information. Verify storage, memory and sustained performance independently. Use the state machine below, with no download before consent.

5. **Qualify Watch independently.** Measure the tiny model on supported physical Watches for sustained realtime factor, update cadence, multilingual accuracy, memory, heat and battery. If standalone inference fails, evaluate an explicit paired-iPhone local route. Its audio crosses devices, which the privacy copy must disclose. Do not promise the large phone/Mac model or near-realtime Watch transcription based on framework support or Siri.

## Consent and capacity

The proposed storage policy preserves **8 GiB free on iOS/iPadOS** and **12 GiB on macOS**, in addition to package-specific staging, installation/compilation/cache, replacement and safety headroom. Recheck before transfer and installation. These are proposed disk-reserve floors, not app-memory guarantees. Show the verified manifest download size—currently about **1.27 GB** for Privacy Filter.

| State or action | Proposed visible behavior |
| --- | --- |
| First eligible composer activation on a qualified device | Offer **Maybe later** and **Activate**. Begin no transfer until Activate. |
| Maybe later | Snooze for at least 24 hours. A later composer activation may then offer **Ignore** and **Activate**. A timer alone must not open a prompt. |
| Ignore | Permanently suppress activation prompts until the user explicitly changes the preference. Show one information banner explaining activation in Privacy settings. |
| Activate | Enter the existing pinned download/progress/cancel/retry flow. Enable only after verification and readiness. |
| Device does not meet latency or resource qualification | Show only the one-time Privacy settings information; do not recommend activation. |

Persist this choice per user and device. Relaunches, duplicate focus events, Team switches and model updates must not reset Ignore. Test clock boundaries, account isolation, free-space changes, interrupted transfers and readiness failures.

On first eligible message-field activation, the existing notification banner may explain offline transcription and no audio transmission **only after the verified local-only route is selected and ready**. The current server-backed production route cannot carry that promise.

## Alternatives and evidence needed

WhisperKit remains the first offline candidate. Its [official package](https://github.com/argmaxinc/argmax-oss-swift) supports Apple targets, but target support does not qualify a particular model on Watch. Apple's [SpeechAnalyzer announcement](https://developer.apple.com/videos/play/wwdc2025/277/) and runtime availability checks may inform a separate on-device STT alternative; Siri does not establish public Watch Speech API support.

Voxtral Realtime has [Apache-2.0 open weights](https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602). The publisher's [experimental 4-bit M-series Metal checkpoint](https://huggingface.co/mistral-experimental/Voxtral-Mini-4B-Realtime-2602-ExecuTorch) is about **4.42 GB**, plus tokenizer/preprocessor, and is a separate Mac-first experiment. It is not a small drop-in Whisper replacement or qualified iPhone/iPad/Watch option. [XNNPACK](https://docs.pytorch.org/executorch/stable/backends/xnnpack/xnnpack-arch-internals.html) is CPU; adding [Core ML](https://docs.pytorch.org/executorch/stable/backends/coreml/coreml-overview.html) does not automatically accelerate the existing artifact or guarantee Neural Engine execution.

Verification must cover airplane-mode first launch, no outbound audio traffic, multilingual and long-recording quality, editable transcript convergence, cancellation, cold/warm preparation, p50/p95 residual Send delay, chunk-boundary PII correctness, repeated chat switching, and concurrent speech/PII memory. Record exact OS/device/model revision, compute placement, thermal/power conditions and network traces. Synthetic native/E2E fixtures prove control flow; physical-device benchmarks and listening establish speed and quality. Keep raw audio, transcripts, entity spans, keys and personal identifiers out of diagnostics.

## Release boundary

The core source is published at `987ec61db56da8a74c83d87a1c9c1dae7cb1839d`, with Vercel ready. Build96 retains its frozen 1,725-file content identity `ed222235d3297a9939971d02709a47c2a6b7c4289a7c1dcb5d3f9ef5e7901656`; its task provenance HEAD is separately `234ff583686c7a832845a8a65ba82c1217a2e7f4`.

The latest user order is iOS/iPadOS with embedded Watch first, followed by macOS. This supersedes the historical requirement to prove Mac notification delivery before iOS upload. Signed capabilities and actual background/closed-app notification delivery still need honest evidence; no physical delivery or TestFlight availability is asserted here. This documentation follow-up must not change the frozen release source. Production offline-AI implementation starts as subsequent work after the build96 release sequence, using the existing contracts and the qualification decisions above.
