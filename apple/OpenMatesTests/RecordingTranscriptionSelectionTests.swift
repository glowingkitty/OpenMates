import Combine
import CryptoKit
import XCTest
@testable import OpenMates

@MainActor
final class RecordingTranscriptionSelectionTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle,message-input.privacy-context
    func testNoStoredChoicePreservesLegacyOnlineAndInstalledWhisperBehavior() async throws {
        let directory = root()
        defer { try? FileManager.default.removeItem(at: directory) }
        let bytes = Data("local fixture".utf8)
        let model = LocalModelManifest(id: .whisper, revision: "fixture", estimatedSizeBytes: Int64(bytes.count), files: [
            LocalModelFile(path: "model.bin", url: URL(string: "https://huggingface.co/fixture/whisper/resolve/" + String(repeating: "a", count: 40) + "/model.bin")!,
                sha256: SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined(), sizeBytes: Int64(bytes.count))])
        let downloader = RecordingModelFixtureDownloader(bytes: bytes)
        let store = LocalModelStore(catalog: try JSONEncoder().encode(LocalModelCatalog(models: [model])), root: directory,
            storageReserveBytes: 0, downloader: downloader, verifyExisting: false,
            bundledWhistle: .init(modelURL: nil))
        XCTAssertEqual(store.recordingTranscriptionPreference, .automatic)
        XCTAssertEqual(store.recordingTranscriptionRoute, .online)
        await store.download(.whisper)
        #if arch(arm64) && !os(watchOS)
        XCTAssertEqual(store.recordingTranscriptionRoute, .whisper)
        #else
        XCTAssertEqual(store.recordingTranscriptionRoute, .online)
        #endif
        XCTAssertEqual(store.state(for: .whisper), .ready)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.privacy-context,apple-local-model-lab.optional-downloads
    func testExplicitLocalChoicePersistsAndMissingAssetsNeverGrantOnlineRoute() async throws {
        let suite = "recording-selection-" + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let store = emptyStore(defaults: defaults, included: nil)
        await store.setRecordingTranscriptionPreference(.whistle)
        XCTAssertEqual(store.recordingTranscriptionRoute, .unavailable(.whistle))
        let selected = store.recordingTranscriptionSelection()
        XCTAssertNotNil(selected.runtime)
        do { _ = try await selected.runtime?.transcribe([0.1]); XCTFail("Missing bundled assets must fail locally") }
        catch let error as LocalSpeechRuntimeError { if case .unavailableRuntime = error {} else { XCTFail("Expected local unavailable") } }
        await selected.runtime?.unload()
        let reopened = emptyStore(defaults: defaults, included: nil)
        XCTAssertEqual(reopened.recordingTranscriptionPreference, .whistle)
        XCTAssertEqual(reopened.recordingTranscriptionRoute, .unavailable(.whistle))
        await reopened.setRecordingTranscriptionPreference(.whisper)
        XCTAssertEqual(reopened.recordingTranscriptionRoute, .unavailable(.whisper))
        XCTAssertFalse(LocalModelID.allCases.contains { $0.rawValue == "whistle" }, "Bundled assets never join downloadable/deletable models")
        XCTAssertFalse(reopened.bundledWhistle.canDownload)
        XCTAssertFalse(reopened.bundledWhistle.canDelete)
        XCTAssertEqual(reopened.bundledWhistle.documentsSizeBytes, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle,message-input.privacy-context
    func testOffClosesAdmissionAndWaitsForRegisteredRuntimeDrainWithoutDeletingBundle() async throws {
        let included = URL(fileURLWithPath: "/fixture/Whistle/whistle.cact")
        let store = emptyStore(included: included)
        let probe = RecordingDrainProbe()
        await store.setRecordingTranscriptionPreference(.whistle)
        let selection = store.recordingTranscriptionSelection(factory: .init(whisper: { _ in probe }, whistle: { _ in probe }))
        let change = Task { await store.setRecordingTranscriptionPreference(.off) }
        await probe.waitForUnload()
        XCTAssertTrue(store.changingRecordingTranscriptionPreference)
        XCTAssertEqual(store.recordingTranscriptionRoute, .disabled)
        XCTAssertNotEqual(store.recordingTranscriptionGeneration, selection.preferenceGeneration)
        XCTAssertNil(store.recordingTranscriptionSelection().runtime)
        do { _ = try await selection.runtime?.transcribe([0.1]); XCTFail("Stopped registration must reject new inference") }
        catch is CancellationError { }
        let calls = await probe.calls
        XCTAssertEqual(calls, 0)
        await probe.releaseUnload()
        await change.value
        XCTAssertFalse(store.changingRecordingTranscriptionPreference)
        XCTAssertEqual(store.bundledWhistle.modelURL, included)
        XCTAssertEqual(store.bundledWhistle.includedSizeBytes, 16_919_407)
        XCTAssertFalse(store.bundledWhistle.reclaimsModelOnSessionEnd)
        await selection.runtime?.unload()
        let ended = await probe.ended
        XCTAssertEqual(ended, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle
    func testLastExplicitChoiceWinsWhileTheSameDrainIsStillPending() async throws {
        let suite = "recording-last-choice-" + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let store = emptyStore(defaults: defaults, included: URL(fileURLWithPath: "/fixture/whistle.cact"))
        let probe = RecordingDrainProbe()
        await store.setRecordingTranscriptionPreference(.whistle)
        let selected = store.recordingTranscriptionSelection(factory: .init(whisper: { _ in probe }, whistle: { _ in probe }))
        let off = Task { await store.setRecordingTranscriptionPreference(.off) }
        await probe.waitForUnload()
        // The second request must update intent before joining the first drain.
        let changed = expectation(description: "Last choice becomes current while cleanup is pending")
        let observation = store.$recordingTranscriptionPreference.dropFirst().filter { $0 == .whisper }.first().sink { _ in changed.fulfill() }
        let last = Task { await store.setRecordingTranscriptionPreference(.whisper) }
        await fulfillment(of: [changed], timeout: 1)
        XCTAssertTrue(store.changingRecordingTranscriptionPreference)
        XCTAssertEqual(store.recordingTranscriptionRoute, .unavailable(.whisper))
        await probe.releaseUnload()
        await off.value; await last.value
        withExtendedLifetime(observation) {}
        XCTAssertEqual(store.recordingTranscriptionPreference, .whisper)
        XCTAssertEqual(store.recordingTranscriptionRoute, .unavailable(.whisper))
        XCTAssertEqual(emptyStore(defaults: defaults).recordingTranscriptionPreference, .whisper)
        await selected.runtime?.unload()
        let ended = await probe.ended
        XCTAssertEqual(ended, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle,message-input.privacy-context
    func testOffAlsoDrainsPreviouslySelectedOnlineCaptureAndRejectsLateOwners() async {
        let store = emptyStore()
        let generation = store.recordingTranscriptionGeneration
        let probe = RecordingDrainProbe()
        let owner = UUID()
        XCTAssertTrue(store.registerRecordingTranscriptionOwner(owner, generation: generation) { await probe.unload() })
        let stop = Task { await store.setRecordingTranscriptionPreference(.off) }
        await probe.waitForUnload()
        XCTAssertFalse(store.registerRecordingTranscriptionOwner(UUID(), generation: generation, drain: {}))
        XCTAssertEqual(store.recordingTranscriptionRoute, .disabled)
        await probe.releaseUnload()
        await stop.value
        store.unregisterRecordingTranscriptionOwner(owner)
        let ended = await probe.ended
        XCTAssertEqual(ended, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle,message-input.privacy-context
    func testWhistleRecordingPublishesWhistleIdentityWithOriginalTextAndNoCloudTransport() async throws {
        let done = expectation(description: "Selected local transcription completed")
        let events = RecordingSelectionEvents()
        let runtime = RecordingImmediateProbe()
        let client = AudioRealtimeTranscriptionClient(authenticationProvider: { _ in
            XCTFail("Explicit local Whistle must never authenticate cloud STT")
            throw AudioRealtimeTranscriptionError.authenticationUnavailable
        }, localRuntime: runtime, localModelIdentifier: "whistle-local", transportFactory: {
            XCTFail("Explicit local Whistle must never create audio transport")
            return RecordingForbiddenTransport()
        }, eventHandler: { event in
            await events.append(event)
            if event == .status(.completed) { done.fulfill() }
        })
        try await client.start(chatID: "fixture")
        try await client.append(samples: [0.1, 0.2], sourceSampleRate: 16_000)
        await client.finish()
        await fulfillment(of: [done], timeout: 2)
        let recorded = await events.values
        let corrections = recorded.compactMap { event -> AudioRealtimeTranscriptionClient.CorrectionResult? in
            if case .correctionDone(let result) = event { return result }; return nil
        }
        let result = try XCTUnwrap(corrections.first)
        XCTAssertEqual(result.model, "whistle-local")
        XCTAssertEqual(result.transcript, "Whistle local fixture")
        XCTAssertEqual(result.transcriptOriginal, "Whistle local fixture")
        XCTAssertNil(result.transcriptCorrected)
        XCTAssertFalse(result.useCorrected)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle,message-input.privacy-context
    func testOffClientNeverAuthenticatesBuildsTransportOrInvokesDecoder() async throws {
        let events = RecordingSelectionEvents()
        let runtime = RecordingImmediateProbe()
        let client = AudioRealtimeTranscriptionClient(authenticationProvider: { _ in
            XCTFail("Off must not authenticate")
            throw AudioRealtimeTranscriptionError.authenticationUnavailable
        }, localRuntime: runtime, transcriptionDisabled: true, transportFactory: {
            XCTFail("Off must not create transport"); return RecordingForbiddenTransport()
        }, eventHandler: { await events.append($0) })
        try await client.start()
        try await client.append(samples: [0.1, 0.2], sourceSampleRate: 44_100)
        await client.finish(); await client.cancel()
        let calls = await runtime.calls
        XCTAssertEqual(calls, 0)
        let recorded = await events.values
        XCTAssertEqual(recorded, [.status(.completed)])
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle,message-input.privacy-context
    func testConfirmedRemoteAllocationMarkerCompletesBeforeAuthenticationOrQueuedAudio() async throws {
        let marker = RecordingDrainProbe()
        let authenticated = expectation(description: "Authentication occurs after confirmed allocation marker")
        let settled = expectation(description: "Synthetic transport failure settles forwarder")
        var markerDone = false
        var authentications = 0
        let client = AudioRealtimeTranscriptionClient(authenticationProvider: { _ in
            authentications += 1
            XCTAssertTrue(markerDone)
            authenticated.fulfill()
            return .init(apiBaseURL: URL(string: "https://example.invalid")!, webOrigin: "https://example.invalid",
                         sessionID: "fixture", webSocketToken: "fixture")
        }, transportFactory: { RecordingForbiddenTransport() }, eventHandler: { _ in })
        let forwarder = OrderedRealtimePCMForwarder(client: client, chatID: "explicit-confirmed-draft",
            beforeRemoteStart: { await marker.unload(); markerDone = true }, onFailure: {
                await client.cancel(); settled.fulfill()
            })
        await marker.waitForUnload()
        forwarder.append(samples: [0.1], sampleRate: 16_000)
        XCTAssertEqual(authentications, 0)
        await marker.releaseUnload()
        await fulfillment(of: [authenticated, settled], timeout: 2)
        XCTAssertEqual(authentications, 1)
        forwarder.cancel(); await client.cancel()
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle,message-input.privacy-context
    func testFailedRemoteAllocationMarkerPreventsAuthenticationAndAudioTransport() async {
        let settled = expectation(description: "Failed marker blocks remote start")
        let client = AudioRealtimeTranscriptionClient(authenticationProvider: { _ in
            XCTFail("A failed confirmed-allocation marker must block cloud authentication")
            throw AudioRealtimeTranscriptionError.authenticationUnavailable
        }, transportFactory: {
            XCTFail("A failed marker must block socket construction"); return RecordingForbiddenTransport()
        }, eventHandler: { _ in })
        let forwarder = OrderedRealtimePCMForwarder(client: client, chatID: "explicit-confirmed-draft",
            beforeRemoteStart: { throw AudioRealtimeTranscriptionError.invalidState }, onFailure: {
                await client.cancel(); settled.fulfill()
            })
        forwarder.append(samples: [0.1], sampleRate: 16_000)
        await fulfillment(of: [settled], timeout: 2)
        forwarder.cancel(); await client.cancel()
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle,message-input.privacy-context,message-input.embeds.gated-send
    func testOffAttachmentPreservesUploadAndWaveformWithoutBatchInferenceOrFailureMetadata() async throws {
        let upload = UploadFileResponse(embedId: "off-recording", filename: "recording.m4a", contentType: "audio/mp4",
            contentHash: "fixture-hash", files: ["original": UploadedFileVariant(s3Key: "fixture/recording.m4a",
                sizeBytes: 512, width: nil, height: nil, format: "m4a")], s3BaseUrl: "https://example.invalid/audio",
            aesKey: "fixture-key", aesNonce: "fixture-nonce", vaultWrappedAesKey: "fixture-wrapped-key",
            pageCount: nil, deduplicated: false)
        let waveform = try XCTUnwrap(AudioRecordingWaveform(normalizedLevels: [0.1, 0.3, 0.2], duration: 1))
        for localFlag in [false, true] {
            let result = await AudioRecordingUploadPipeline.run(waveform: waveform,
                realtimeResult: { .transcriptionDisabled }, localTranscription: localFlag,
                upload: { upload }, batchTranscription: { _ in
                    XCTFail("Explicit Off must never invoke automatic batch transcription")
                    return nil
                })
            let prepared = try XCTUnwrap(result)
            XCTAssertEqual(prepared.upload.embedId, upload.embedId)
            XCTAssertEqual(prepared.transcription.waveform, waveform)
            XCTAssertNil(prepared.transcription.transcript)
            XCTAssertNil(prepared.transcription.model)
            XCTAssertEqual(prepared.transcription.transcriptionSource, "disabled")
            XCTAssertEqual(prepared.transcription.transcriptionStatus, "disabled")
        }
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle,message-input.privacy-context
    func testTurningOffAfterAnAlreadyFailedSessionSuppressesAttachmentBatchFallback() async throws {
        var off = false
        let speech = AssistantSpeechAppRuntime()
        let session = AudioRecordingRealtimeSession(speechRuntime: speech, isTranscriptionOff: { off })
        session.beginLocalRecordingForTesting()
        await session.receiveForTesting(.status(.failed(.localTranscriptionFailed)))
        off = true
        session.finish()
        let resolved = await session.awaitResult()
        let result = try XCTUnwrap(resolved)
        XCTAssertEqual(result.disposition, .disabled)
        XCTAssertFalse(speech.hasRecordingReservationForTesting)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle
    func testRecorderAdmissionRejectsGuestCaptureBeforePermissionOrAudioEngine() async {
        let recorder = VoiceRecorder(recordingAdmission: { false })
        let granted = await recorder.requestPermission()
        XCTAssertFalse(granted)
        XCTAssertTrue(recorder.recordingAdmissionRejected)
        recorder.startRecording()
        XCTAssertFalse(recorder.isRecording)
        XCTAssertEqual(recorder.error, AppStrings.recordingBlockedByCall)
        XCTAssertEqual(recorder.duration, 0)
        XCTAssertNil(recorder.stopRecording())
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle
    func testRecordingSessionCannotAcquireReservationDuringLiveCall() async throws {
        let speech = AssistantSpeechAppRuntime()
        let lease = try await speech.reserveLiveCall(onInvalidated: {})
        defer { speech.releaseLiveCall(lease) }
        let session = AudioRecordingRealtimeSession(speechRuntime: speech)
        session.beginLocalRecordingForTesting()
        XCTAssertFalse(speech.hasRecordingReservationForTesting)
        await session.cancel()
        XCTAssertTrue(speech.isLiveCallReservationCurrent(lease))
    }

    private func root() -> URL { FileManager.default.temporaryDirectory.appendingPathComponent("recording-selection-" + UUID().uuidString) }
    private func emptyStore(defaults: UserDefaults? = nil, included: URL? = nil) -> LocalModelStore {
        LocalModelStore(catalog: Data("{\"models\":[]}".utf8), root: root(), verifyExisting: false,
            preferences: defaults, bundledWhistle: .init(modelURL: included))
    }
}

private actor RecordingModelFixtureDownloader: LocalModelFileDownloading {
    let bytes: Data
    init(bytes: Data) { self.bytes = bytes }
    func download(_ file: LocalModelFile, to destination: URL,
                  progress: @escaping @Sendable (Int64) -> Void) async throws {
        try bytes.write(to: destination); progress(Int64(bytes.count))
    }
}

private actor RecordingDrainProbe: LocalPCMTranscribing {
    private var continuation: CheckedContinuation<Void, Never>?
    private var observers: [CheckedContinuation<Void, Never>] = []
    private var started = false
    var calls = 0
    var ended = 0
    func transcribe(_ samples: [Float]) -> String { calls += 1; return "unused" }
    func unload() async {
        ended += 1
        await withCheckedContinuation { continuation in
            self.continuation = continuation; started = true
            let waiters = observers; observers.removeAll(); waiters.forEach { $0.resume() }
        }
    }
    func waitForUnload() async { if !started { await withCheckedContinuation { observers.append($0) } } }
    func releaseUnload() { continuation?.resume(); continuation = nil }
}

private actor RecordingImmediateProbe: LocalPCMTranscribing {
    var calls = 0
    func transcribe(_ samples: [Float]) -> String { calls += 1; return "Whistle local fixture" }
    func unload() {}
}
private actor RecordingSelectionEvents {
    var values: [AudioRealtimeTranscriptionClient.Event] = []
    func append(_ event: AudioRealtimeTranscriptionClient.Event) { values.append(event) }
}
private actor RecordingForbiddenTransport: AudioRealtimeSocketTransport {
    func connect(_ request: URLRequest) throws { throw AudioRealtimeTranscriptionError.invalidState }
    func send(_ text: String) throws { throw AudioRealtimeTranscriptionError.invalidState }
    func receive() throws -> String { throw AudioRealtimeTranscriptionError.invalidState }
    func close(code: Int, reason: Data?) {}
}
