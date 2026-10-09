# Seamless offline speech and enhanced anonymization

Planning snapshot: 8 October 2026, TASK-8137. This extends the [existing Apple stability Plan](plan.yml), using its existing speech, PII, notifications, settings and local-model contracts. The user’s subsequent clarification authorizes the optional download pack and production integration through these existing contracts. **Weights must never be bundled.** This work does not change the frozen build96 release source or establish physical-device performance.

## What is available today

| Capability | Production behavior | Local model and remaining integration |
| --- | --- | --- |
| Speech to text | Production adapter work selects verified installed Whisper on supported arm64 targets. With no ready model, existing server STT remains the default; Intel and Watch remain server STT. A selected local route fails explicitly without automatic server fallback. | Whisper large-v3: **629,481,698 bytes** (629.5 MB), downloaded explicitly. Native route execution and device performance remain qualification gates. Ordinary audio attachments and cross-device playback remain: audio uploads over TLS and the server encrypts it for storage. This is not client encryption before upload; local inference does not mean recordings stay on the device. |
| Text to speech | Production adapter work selects verified installed Supertonic3 on supported arm64 targets. Missing assets retain provider TTS; local failures or unsupported languages require local retry or an explicit Use online speech choice. | Supertonic3: **401,291,751 bytes** (401.3 MB), downloaded explicitly. Idle preparation, cancellation, native playback and device voice/performance evidence remain separate qualification gates. |
| Enhanced PII anonymization | Optional local ExecuTorch/XNNPACK inference is integrated with foreground model retention, 500 ms edit debounce and exact outgoing-revision validation at Send. Local regex detection remains available. | The verified package is **1,269,572,251 bytes** (about 1.27 GB). Its XNNPACK artifact runs on CPU; a dedicated equivalent Core ML export would require qualification. |
| Watch transcription | Production transcription currently uses the server route. | The separate foreground tiny Whisper laboratory uses **79,398,546 bytes** (79.4 MB). Physical Watch speed, sustained battery, memory and transcript quality remain unqualified. |

Package sizes come from the pinned [local-model catalog](../../../apple/OpenMates/Resources/LocalModels/catalog.json) and [Watch tiny-model manifest](../../../apple/OpenMatesWatch/Resources/watch-whisper-tiny.json). They describe downloads, not installed disk use or working memory. Current phone/Mac laboratory support is arm64; Intel support needs its own decision and qualification.

Source references: [realtime client](../../../apple/OpenMates/Sources/Core/Networking/AudioRealtimeTranscriptionClient.swift), [recording submission](../../../apple/OpenMates/Sources/Features/Chat/ViewModels/ChatViewModel.swift), [Whisper laboratory](../../../apple/OpenMates/Sources/Core/LocalModels/LocalSpeechRuntimes.swift), [production speech runtime](../../../apple/OpenMates/Sources/Shared/Composer/AssistantSpeechAppRuntime.swift), [local TTS laboratory](../../../apple/OpenMates/Sources/Core/LocalModels/LocalNeuralTTSRuntime.swift), and [production PII runtime](../../../apple/OpenMates/Sources/Core/LocalModels/ProductionPIIRuntime.swift).

## What the measurements permit

The retained M1 enhanced-PII benchmark measured a **3.94 s cold load**, isolated warm scans of **2.65, 2.14 and 2.02 s**, and sampled peak process RSS of about **1.24 GiB**. Process RSS remained allocated after unload; the receipt does not establish memory release. These scans do not measure residual Send delay, p95 performance, concurrent speech memory or physical iPhone/iPad behavior. They do not qualify the current CPU path for an activation recommendation promising no noticeable Send delay.

Until a device/model/language/text-length envelope passes that qualification, show only a one-time information banner pointing to Privacy settings. Installed, opted-in models must still validate the exact outgoing revision; hiding latency must never bypass privacy correctness. The existing recommendation's 30-day dismissal is separate from the proposed flow below.

Proposed usability targets are p95 residual Send delay of **at most 100 ms for an already prepared draft** and **at most 200 ms for representative last-second edits**. These are proposed budgets, not measured promises or approved product-contract requirements.

## Optional pack and integration sequence

The latest requested composer banner is **“Want to download offline AI models (2.3GB) for reducing your costs & even better privacy protection?”**, with **Later** and **Download**. Its benefit copy is qualified only after verified installed local production routes actually handle speech. Installation alone cannot establish lower inference costs or local production audio processing.

The pinned pack totals **2,300,345,700 bytes** (2.3 GB decimal), downloaded strictly in this order: **Whisper STT → Supertonic3 TTS → enhanced PII**. The app bundle contains catalog metadata, never weights. Watch production transcription stays on the server; offline Voxtral is outside this scope. The existing tiny Whisper Watch developer experiment remains separate.

`OfflineAIModelPack` is a small observable coordinator around the existing `LocalModelStore`. It owns consent and the sequential queue. The store remains the sole transfer/install owner, including durable iOS background URLSession, pinned operation recovery, size/SHA checks, atomic replacement, Live Activity events and completion notifications. The coordinator joins an existing store operation rather than starting a second transfer. Fully verified installations are skipped. The same OS Activity spans model transitions, and background completion waits for the next real URLSession enqueue. Observing pack status alone starts no multi-GB hashing; eligible activation, explicit Download or a persisted consented transfer begins validation. Pack completion does not activate Enhanced PII or change provider preferences; production speech adapters independently select verified installed assets under the speech contract.

| State or action | Behavior |
| --- | --- |
| Eligible composer activation | Offer Later and Download; begin no transfer before Download. |
| Later | Persist a 24-hour deferral. Only a later composer activation can show the offer again. |
| Download | Persist consent before starting STT, then TTS, then PII. |
| Interrupted downloading | Reattach pinned store work and continue the previously consented sequence after relaunch. |
| Pause | Preserve installed models and verified staged files. Explicit resume rechecks staged hashes; an active partial file may restart. |
| Cancel | Stop queued work, drain cancellation, discard partial staging, preserve installed models. |
| Failure | Stop the queue and show the model failure; retry requires an explicit action. |
| Complete | All assets passed verification and installation. This does not select an inference route. |

Only device-local public asset metadata, byte counts, queue state and consent are persisted; no chat content, recordings, transcripts or account identifiers enter the pack journal. UI progress exposes the current model, transferred/verified bytes and transfer, waiting, retry and verification phases. OS Live Activity availability remains subject to device authorization.

The implemented storage policy preserves **8 GiB free on iOS/iPadOS** and **12 GiB on macOS**, plus remaining pack bytes, the largest temporary transfer copy and **150 MB** safety headroom. It checks the entire remaining pack before starting, rechecks before each transfer and before atomic installation, and excludes the asset root and staging from backup. This is disk policy; it does not qualify app memory, sustained inference or performance.

1. **Use downloaded local transcription on iOS, iPadOS and macOS.** Reuse verified Whisper/Core ML assets and tokenizer with runtime downloading disabled. Connect microphone PCM to local decoding, editable partial/final transcripts, cancellation and stale-generation fencing. The selected local STT route opens no realtime STT socket and never invokes server/external transcription. Per the latest user instruction, preserve the ordinary audio attachment and cross-device playback: audio uploads over TLS, then the server encrypts stored recording assets. Persist `transcription_source` and `transcription_status` for local complete and failed recordings; delayed, manual or mixed-recording resolution must never implicitly transcribe them on the server. Online STT requires a separate explicit choice. This does not claim client encryption before upload or no audio transmission. Qualify unsupported platforms truthfully.

2. **Integrate Supertonic3 into response playback.** Preserve explicit verified downloads and approved voice/language mapping. Prepare an installed selected engine off the main actor after a chat opens and becomes idle. Retain one bounded owner, synthesize semantic chunks, cancel on account/chat/voice changes and evict under memory pressure. Provider fallback remains separately explicit. Kitten, Pocket, Kokoro and rejected Apple system voices stay removed.

3. **Preserve enhanced anonymization correctness and separate opt-in.** Reuse complete results bound to exact draft revision, model, options and account context. Coalesce obsolete edits without losing entities at token/window boundaries. Send awaits any incomplete exact outgoing-revision check. Current XNNPACK CPU measurements do not qualify a no-noticeable-delay recommendation; a dedicated equivalent Core ML export requires its own evidence.

## Verification and limits

Focused native coverage in `LocalModelStoreTests` exercises initial consent, Later/relaunch clock boundaries, STT→TTS→PII order, installed-model skip, stopped queue on failure, persisted pause suppression, retained verified staging on resume and reserve arithmetic. Swift 6 static typechecking of the store/coordinator and test source passed with narrow diagnostics/string/activity stubs. Native test execution, rendered composer behavior and actual Live Activity delivery remain separate root-owned verification gates.

Before claiming production local speech, verify local decoding after explicit installation, no server/external STT requests for local complete or failed recordings, persisted source/status across delayed and mixed recording resolution, ordinary audio attachments and cross-device playback, multilingual and long-recording quality, transcript convergence, cancellation, cold/warm preparation, p50/p95 residual Send delay, chunk-boundary PII correctness, repeated chat switching and concurrent speech/PII memory. Record OS/device/model revision, compute placement, thermal/power conditions and network traces. Synthetic fixtures prove control flow; physical-device benchmarks and listening establish speed and quality. Keep raw audio, transcripts, entity spans, keys and personal identifiers out of diagnostics.

## Future client encryption and Neural Engine research

A future encrypt-before-upload recording path needs an opaque-ciphertext endpoint, client-wrapped keys and a separate explicit online-STT consent. That work is outside this slice; the current TLS upload followed by server encryption must not be described as end-to-end encryption before upload.

The retained 8 October research found no inspected official ready-to-use Privacy Filter ANE artifact or iPhone13 Pro/A15 benchmark against the current XNNPACK path. [Software Mansion’s model documentation](https://docs.swmansion.com/react-native-executorch/docs/extensions/privacy-filter) covers the current XNNPACK/MLX choices. A separate [ExecuTorch Core ML export](https://docs.pytorch.org/executorch/stable/backends/coreml/coreml-overview.html) and actual placement inspection through [Apple MLComputePlan](https://developer.apple.com/documentation/coreml/mlcomputeplan) remain a qualification project. Community M4 Max claims compare PyTorch CPU and cannot establish an iPhone multiplier or our Send latency. No model download, inference or native build formed part of that research.

A bounded post-release comparison may preserve the exact tokenizer, windows, constrained/Viterbi spans and privacy quality while measuring physical iPhone13 Pro and one newer device: cold/warm p50/p95 scan and residual Send delay, CPU/GPU/ANE placement, peak memory and sustained thermal/battery behavior. Promote a port only with equivalent privacy behavior and measured benefit; no numeric iPhone speedup is promised.

## Release boundary

The core source is published at `987ec61db56da8a74c83d87a1c9c1dae7cb1839d`, with Vercel ready. Build96 retains its frozen 1,725-file content identity `ed222235d3297a9939971d02709a47c2a6b7c4289a7c1dcb5d3f9ef5e7901656`; its task provenance HEAD is separately `234ff583686c7a832845a8a65ba82c1217a2e7f4`.

The latest user order is iOS/iPadOS with embedded Watch first, followed by macOS. This supersedes the historical requirement to prove Mac notification delivery before iOS upload. Signed capabilities and actual background/closed-app notification delivery still need honest evidence; no physical delivery or TestFlight availability is asserted here. The current optional-pack and production-routing source work uses the existing contracts and qualification limits above; the frozen build96 archive identity remains separate.
