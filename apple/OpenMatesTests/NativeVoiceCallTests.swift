// Specification: specifications/features/video-call/specification.yml
// Deterministic protocol evidence only: these tests do not prove microphone,
// speaker, physical Watch networking, provider inference or foreground eligibility.
import Foundation
import CryptoKit
import XCTest
@testable import OpenMates

@MainActor
final class NativeVoiceCallTests: XCTestCase {
    private let scope = NativeVoiceCallScope(accountID: "fixture-owner", profileID: "development",
        workspaceGeneration: UUID(), chatID: "00000000-0000-4000-8000-000000000001", mateCategory: "general")

    // contract-test: supporting surface=gui.apple assertions=video-call.privacy.first-call-warning,video-call.audio.single-owner
    func testDeclinedConsentNeverReservesAudioOrOpensSocket() async throws {
        let transport = VoiceCallTransportFixture()
        let audio = VoiceCallAudioFixture()
        let controller = makeController(transport: transport, audio: audio, consent: {
            throw NativeVoiceCallError.consentRequired
        })
        do { try await controller.start(scope: scope); XCTFail("Consent must abort startup") }
        catch { XCTAssertEqual(error as? NativeVoiceCallError, .consentRequired) }
        let opened = await transport.connections
        let reserved = await audio.reservations
        let state = await controller.snapshot()
        XCTAssertEqual(opened, 0)
        XCTAssertEqual(reserved, 0)
        XCTAssertEqual(state.status, .failed)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.audio.startup-buffer,video-call.audio.automatic-idle
    func testStartupAudioAndMuteEndMarkerRemainOrderedWithoutRenewingAllowance() async throws {
        let transport = VoiceCallTransportFixture(), audio = VoiceCallAudioFixture()
        let live = expectation(description: "Ready admits audio")
        let controller = makeController(transport: transport, audio: audio, event: { event in
            if case .state(let state) = event, state.status == .live { live.fulfill() }
        })
        try await controller.start(scope: scope)
        await audio.emit(Data([1, 0, 2, 0]))
        await controller.setMuted(true)
        let before = try await transport.frames()
        XCTAssertEqual(before.map { $0["type"]?.string }, ["start"])
        try await transport.push(ready())
        await fulfillment(of: [live], timeout: 2)
        let frames = try await transport.frames()
        XCTAssertEqual(frames.map { $0["type"]?.string }, ["start", "mic_audio", "audio_stream_end"])
        await controller.hangup()
        let stops = await audio.stops
        XCTAssertEqual(stops, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.audio.startup-buffer,video-call.audio.single-owner
    func testMuteDoesNotRenewTenSecondStartupAllowance() async throws {
        let transport = VoiceCallTransportFixture(), audio = VoiceCallAudioFixture()
        let controller = makeController(transport: transport, audio: audio)
        try await controller.start(scope: scope)
        for _ in 0..<10 { await audio.emit(Data(repeating: 0, count: 32_000)) }
        await controller.setMuted(true)
        await controller.setMuted(false)
        await audio.emit(Data([1, 0]))
        let state = await controller.snapshot()
        XCTAssertEqual(state.status, .failed)
        XCTAssertEqual(state.error, .audioQueueFull)
        let frames = try await transport.frames()
        XCTAssertEqual(frames.count, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.audio.startup-buffer,video-call.lifecycle.recovery-and-billing
    func testStartupDeadlineTerminatesWithoutReadyAndWithoutPaidReconnect() async throws {
        let transport = VoiceCallTransportFixture(), audio = VoiceCallAudioFixture()
        let deadline = VoiceCallDeadlineFixture()
        let ended = expectation(description: "Startup timeout")
        let controller = makeController(transport: transport, audio: audio, sleep: { duration in
            if duration == .seconds(10) { await deadline.wait() }
            else { try await Task.sleep(for: duration) }
        }, event: { event in
            if case .state(let state) = event, state.error == .startupTimedOut { ended.fulfill() }
        })
        try await controller.start(scope: scope)
        await deadline.release()
        await fulfillment(of: [ended], timeout: 2)
        let opened = await transport.connections
        XCTAssertEqual(opened, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.typed-input,video-call.chat.transcripts
    func testTypedInputIsEncryptedBeforeSocketAndUsesUUIDv7WithoutOrdinaryInference() async throws {
        let transport = VoiceCallTransportFixture(), audio = VoiceCallAudioFixture()
        let persistence = VoiceCallPersistenceFixture()
        let live = expectation(description: "Live")
        let controller = makeController(transport: transport, audio: audio, persistence: persistence, event: { event in
            if case .state(let state) = event, state.status == .live { live.fulfill() }
        })
        try await controller.start(scope: scope)
        try await transport.push(ready())
        await fulfillment(of: [live], timeout: 2)
        let id = try await controller.sendText("Fixture text")
        XCTAssertEqual(id.split(separator: "-")[2].first, "7")
        let staged = await persistence.typedIDs
        let frames = try await transport.frames()
        XCTAssertEqual(staged, [id])
        XCTAssertEqual(frames.last?["type"]?.string, "text_input")
        XCTAssertEqual(frames.last?["message_id"]?.string, id)
        XCTAssertEqual(frames.last?["created_at"]?.number, 100)
        await controller.hangup()
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.lifecycle.recovery-and-billing,video-call.chat.fixed-binding
    func testTerminalSocketLossStopsAudioAndNeverReconnects() async throws {
        let transport = VoiceCallTransportFixture(), audio = VoiceCallAudioFixture()
        let ended = expectation(description: "Disconnect is terminal")
        let controller = makeController(transport: transport, audio: audio, event: { event in
            if case .state(let state) = event, state.status == .failed { ended.fulfill() }
        })
        try await controller.start(scope: scope)
        await transport.fail()
        await fulfillment(of: [ended], timeout: 2)
        let opened = await transport.connections, stopped = await audio.stops
        XCTAssertEqual(opened, 1)
        XCTAssertEqual(stopped, 1)
        await audio.emit(Data([9, 0])) // retained hardware callback is fenced
        let frames = try await transport.frames()
        XCTAssertEqual(frames.map { $0["type"]?.string }, ["start"])
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.transcripts,video-call.privacy,video-call.chat.typed-input
    func testOutboxKeepsExactCiphertextAcrossRetriesAndRequiresRevisionBoundACK() async throws {
        let key = SymmetricKey(size: .bits256)
        let storage = VoiceCallOutboxStorageFixture()
        let crypto = NativeVoiceCallChatCryptography(key: { _ in key }, isCurrent: { _ in true })
        let outbox = NativeVoiceCallOutbox(crypto: crypto, storage: storage, isCurrent: { _ in true },
            checkpoint: { _, _, _ in throw NativeVoiceCallError.persistenceFailed })
        let value = transcript(text: "Private fixture", final: true)
        try await outbox.transcript(scope: scope, value: value)
        let first = try await outbox.pendingFrames(scope: scope)
        let retry = try await outbox.pendingFrames(scope: scope)
        XCTAssertEqual(first, retry)
        XCTAssertEqual(first.first?["user_message_id"]?.string, value.userMessageID)
        let encrypted = try XCTUnwrap(first.first?["encrypted_content"]?.string)
        XCTAssertNotEqual(encrypted, value.text)
        let decrypted = try await crypto.decrypt(encrypted, scope: scope)
        XCTAssertEqual(decrypted, value.text)
        let raw = try JSONEncoder().encode(await storage.rows)
        XCTAssertFalse(String(decoding: raw, as: UTF8.self).contains(value.text))
        let request = try XCTUnwrap(first.first?["request_id"]?.string)
        let wrong = try await outbox.acknowledge(scope: scope, frame: ["type": .string("call_message_confirmed"),
            "request_id": .string(request), "revision": .number(2), "outcome": .string("created")])
        XCTAssertFalse(wrong)
        let right = try await outbox.acknowledge(scope: scope, frame: ["type": .string("call_message_confirmed"),
            "request_id": .string(request), "revision": .number(1), "outcome": .string("created")])
        XCTAssertTrue(right)
        let remaining = try await outbox.pendingFrames(scope: scope)
        XCTAssertTrue(remaining.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.typed-input,video-call.chat.transcripts
    func testTypedFinalEchoKeepsSelfUserParentAndClearsOnlyAcceptancePending() async throws {
        let key = SymmetricKey(size: .bits256), storage = VoiceCallOutboxStorageFixture()
        let outbox = NativeVoiceCallOutbox(crypto: NativeVoiceCallChatCryptography(key: { _ in key }, isCurrent: { _ in true }),
            storage: storage, isCurrent: { _ in true }, checkpoint: { _, _, _ in throw NativeVoiceCallError.persistenceFailed })
        let id = NativeVoiceCallMessageID.make(now: Date(timeIntervalSince1970: 100))
        try await outbox.stageTyped(scope: scope, callID: "fixture-call", messageID: id, text: "Typed fixture", createdAt: 100)
        let before = try await outbox.pendingFrames(scope: scope)
        XCTAssertTrue(before.isEmpty)
        try await outbox.transcript(scope: scope, value: .init(callID: "fixture-call", messageID: id,
            role: .user, text: "Typed fixture", final: true, interrupted: false, userMessageID: id,
            createdAt: 100, modelName: nil, mateCategory: nil, mateName: nil))
        let rows = await storage.rows
        XCTAssertEqual(rows.first?.typedPending, false)
        XCTAssertEqual(rows.first?.userMessageID, id)
        let after = try await outbox.pendingFrames(scope: scope)
        XCTAssertEqual(after.count, 1)
        // call_message_completed_handler rejects user_message_id on user rows;
        // the broker-shaped echo above still retains its self ID in local storage.
        XCTAssertNil(after.first?["user_message_id"])
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.transcripts,video-call.chat.compressed-context
    func testFinalCorrectionIncrementsRevisionAndLateInterimCannotDowngradeIt() async throws {
        let key = SymmetricKey(size: .bits256), storage = VoiceCallOutboxStorageFixture()
        let outbox = NativeVoiceCallOutbox(crypto: NativeVoiceCallChatCryptography(key: { _ in key }, isCurrent: { _ in true }),
            storage: storage, isCurrent: { _ in true }, checkpoint: { _, _, _ in throw NativeVoiceCallError.persistenceFailed })
        try await outbox.transcript(scope: scope, value: transcript(text: "First", final: true))
        try await outbox.transcript(scope: scope, value: transcript(text: "Correction", final: true))
        try await outbox.transcript(scope: scope, value: transcript(text: "Old interim", final: false))
        let frames = try await outbox.pendingFrames(scope: scope)
        XCTAssertEqual(frames.map { $0["revision"]?.number }, [1, 2])
        let rows = await storage.rows
        XCTAssertEqual(rows.first?.revision, 2)
        XCTAssertEqual(rows.first?.final, true)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.compressed-context,video-call.audio.background-detection,video-call.audio.automatic-idle
    func testOversizedContextIsRefusedAndUnverifiedDetectorNeverClaimsIdle() throws {
        XCTAssertThrowsError(try NativeVoiceCallContext(messages: [], summary: String(repeating: "a", count: 48_001),
            mateCategory: "general", canonicalRangeComplete: true))
        XCTAssertThrowsError(try NativeVoiceCallContext(messages: [], mateCategory: "general", canonicalRangeComplete: false))
        var gate = NativeVoiceCallInputGate()
        XCTAssertFalse(gate.observe(speech: false, at: 0))
        XCTAssertFalse(gate.observe(speech: false, at: 8))
        gate.setDetector(.ready)
        XCTAssertFalse(gate.observe(speech: false, at: 10))
        XCTAssertTrue(gate.observe(speech: false, at: 15))
        gate.setDetector(.failed)
        XCTAssertFalse(gate.idle)
        XCTAssertFalse(gate.observe(speech: false, at: 30))
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.audio.startup-buffer,video-call.provider.boundary
    func testPCMIsLittleEndianAndRoundTripsAtDeclaredWireRates() throws {
        let data = NativeVoiceCallPCM.encode([-1, 0, 0.5, 1, .nan])
        XCTAssertEqual(Array(data), [0, 128, 0, 0, 0, 64, 255, 127, 0, 0])
        let samples = try NativeVoiceCallPCM.decode(data)
        XCTAssertEqual(samples[2], 0.5)
        XCTAssertEqual(NativeVoiceCallWire.inputSampleRate, 16_000)
        XCTAssertEqual(NativeVoiceCallWire.outputSampleRate, 24_000)
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.audio.single-owner,video-call.lifecycle.recovery-and-billing
    func testSharedSpeechLeaseRejectsRecordingAndResetRevokesOnlyThatLease() async throws {
        let runtime = AssistantSpeechAppRuntime()
        let recording = runtime.beginRecording()
        do {
            _ = try await runtime.reserveLiveCall(onInvalidated: {})
            XCTFail("A recorder must retain exclusive ownership through final decode")
        } catch { XCTAssertEqual(error as? NativeVoiceCallError, .audioUnavailable) }
        runtime.endRecording(recording)
        let invalidated = expectation(description: "Account reset invalidates call")
        let call = try await runtime.reserveLiveCall { invalidated.fulfill() }
        XCTAssertNil(runtime.tryBeginRecording())
        XCTAssertTrue(runtime.isLiveCallReservationCurrent(call))
        runtime.reset()
        await fulfillment(of: [invalidated], timeout: 2)
        XCTAssertFalse(runtime.isLiveCallReservationCurrent(call))
        runtime.releaseLiveCall(call) // an old release cannot affect a future lease
    }

    private func ready() -> NativeVoiceCallFrame {
        ["type": .string("ready"), "call_id": .string("fixture-call"),
         "model": .string("fixture-model"), "mate_category": .string("general"),
         "mate_name": .string("Fixture"), "input_sample_rate": .number(16_000),
         "output_sample_rate": .number(24_000), "billing_basis": .string("provider_tokens")]
    }
    private func transcript(text: String, final: Bool) -> NativeVoiceCallTranscript {
        .init(callID: "fixture-call", messageID: "fixture-message", role: .assistant, text: text,
            final: final, interrupted: false, userMessageID: "fixture-user", createdAt: 100,
            modelName: "fixture-model", mateCategory: "general", mateName: "Fixture")
    }
    private func makeController(transport: VoiceCallTransportFixture, audio: VoiceCallAudioFixture,
        persistence: VoiceCallPersistenceFixture = .init(),
        consent: @escaping @Sendable () async throws -> Void = {},
        sleep: @escaping @Sendable (Duration) async throws -> Void = { try await Task.sleep(for: $0) },
        event: @escaping NativeVoiceCallController.Handler = { _ in }
    ) -> NativeVoiceCallController {
        NativeVoiceCallController(environment: .init(isCurrent: { _ in true }, ensureConsent: { _ in try await consent() },
            authentication: { _ in .init(apiBaseURL: URL(string: "https://api.example.invalid")!,
                webOrigin: "https://example.invalid", sessionID: "fixture-session", webSocketToken: "fixture-token", nativeHeaders: [:]) },
            context: { _ in try .init(messages: [], mateCategory: "general", canonicalRangeComplete: true) },
            now: { Date(timeIntervalSince1970: 100) }, sleep: sleep),
            audio: audio, persistence: persistence, transportFactory: { transport }, eventHandler: event)
    }
}

private actor VoiceCallTransportFixture: NativeVoiceCallTransport {
    private var pending: [String] = []
    private var waiter: CheckedContinuation<String, any Error>?
    private var closed = false
    private var sent: [String] = []
    private(set) var connections = 0
    func connect(_ request: URLRequest) { connections += 1 }
    func send(_ text: String) { sent.append(text) }
    func receive() async throws -> String {
        if !pending.isEmpty { return pending.removeFirst() }
        guard !closed else { throw NativeVoiceCallError.connectionLost }
        return try await withCheckedThrowingContinuation { waiter = $0 }
    }
    func close() {
        closed = true
        let waiter = waiter; self.waiter = nil
        waiter?.resume(throwing: NativeVoiceCallError.connectionLost)
    }
    func push(_ frame: NativeVoiceCallFrame) throws {
        let text = try NativeVoiceCallWire.encode(frame)
        if let waiter { self.waiter = nil; waiter.resume(returning: text) }
        else { pending.append(text) }
    }
    func fail() { close() }
    func frames() throws -> [NativeVoiceCallFrame] { try sent.map(NativeVoiceCallWire.decode) }
}

private actor VoiceCallAudioFixture: NativeVoiceCallAudio {
    private var input: (@Sendable (Data) async -> Void)?
    private(set) var reservations = 0
    private(set) var stops = 0
    func reserve(scope: NativeVoiceCallScope) { reservations += 1 }
    func start(input: @escaping @Sendable (Data) async -> Void,
               failure: @escaping @Sendable (NativeVoiceCallError) async -> Void) { self.input = input }
    func setMicrophoneEnabled(_ enabled: Bool) {}
    func play(_ pcm16: Data, sampleRate: Int) {}
    func interruptPlayback() {}
    func stop() { stops += 1 }
    func emit(_ data: Data) async { await input?(data) }
}

private actor VoiceCallPersistenceFixture: NativeVoiceCallPersistence {
    private(set) var typedIDs: [String] = []
    func stageTyped(scope: NativeVoiceCallScope, callID: String, messageID: String, text: String, createdAt: Int) { typedIDs.append(messageID) }
    func transcript(scope: NativeVoiceCallScope, value: NativeVoiceCallTranscript) {}
    func lifecycle(scope: NativeVoiceCallScope, callID: String, started: Bool, createdAt: Int, activeSeconds: TimeInterval) {}
    func compression(scope: NativeVoiceCallScope, callID: String, frame: NativeVoiceCallFrame) throws -> NativeVoiceCallFrame {
        throw NativeVoiceCallError.persistenceFailed
    }
}

private actor VoiceCallOutboxStorageFixture: NativeVoiceCallOutboxStorage {
    private(set) var rows: [NativeVoiceCallStoredRow] = []
    func load(scope: NativeVoiceCallScope) -> [NativeVoiceCallStoredRow] { rows }
    func save(_ rows: [NativeVoiceCallStoredRow], scope: NativeVoiceCallScope) { self.rows = rows }
}

private actor VoiceCallDeadlineFixture {
    private var waiter: CheckedContinuation<Void, Never>?
    private var released = false
    func wait() async {
        if released { return }
        await withCheckedContinuation { waiter = $0 }
    }
    func release() { released = true; waiter?.resume(); waiter = nil }
}
