// Deterministic supporting evidence; no physical audio/network/provider claim.
// Specification: specifications/features/video-call/specification.yml
import Foundation
import XCTest
@testable import OpenMates

@MainActor
final class NativeVoiceCallAdmissionTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=video-call.privacy.first-call-warning,video-call.audio.single-owner,video-call.chat.fixed-binding
    func testConsentedCapturePrecedesCanonicalPreparationAndProviderConnection() async throws {
        let log = NativeVoiceCallAdmissionLog()
        let transport = NativeVoiceCallAdmissionTransport(log: log)
        let controller = NativeVoiceCallController(environment: .init(isCurrent: { _ in true },
            ensureConsent: { _ in await log.append("saved_consent") },
            authentication: { _ in
                await log.append("authentication")
                return .init(apiBaseURL: URL(string: "https://api.example.invalid")!, webOrigin: "https://example.invalid",
                    sessionID: "fixture", webSocketToken: "fixture", nativeHeaders: [:])
            }, context: { _ in
                await log.append("canonical_context")
                return try .init(messages: [], mateCategory: "general_knowledge", canonicalRangeComplete: true)
            }, prepare: { _ in await log.append("canonical_chat_confirmed") }),
            audio: NativeVoiceCallAdmissionAudio(log: log), persistence: NativeVoiceCallAdmissionPersistence(),
            transportFactory: { transport }, eventHandler: { _ in })
        try await controller.start(scope: .init(accountID: "fixture", profileID: "development", workspaceGeneration: UUID(),
            chatID: "00000000-0000-4000-8000-000000000001", mateCategory: "general_knowledge"))
        let values = await log.values
        XCTAssertEqual(values, ["saved_consent", "exclusive_reservation", "genuine_capture", "canonical_chat_confirmed",
            "canonical_context", "authentication", "provider_socket", "start"])
        await controller.hangup()
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.audio.automatic-idle,video-call.audio.background-detection
    func testEnergyGateRequiresFiveSecondsAndReplaysOnlyBoundedRealPrespeechPCM() throws {
        var gate = NativeVoiceCallEnergyGate()
        for _ in 0..<4 {
            if case .upload = try gate.process(Data(repeating: 0, count: 32_000)) { }
            else { XCTFail("Initial four seconds stay in continuous streaming") }
        }
        if case .enteredIdle = try gate.process(Data(repeating: 0, count: 32_000)) { }
        else { XCTFail("Fifth quiet second must emit the ordered end boundary") }
        XCTAssertTrue(gate.idle)
        _ = try gate.process(Data(repeating: 0, count: 32_000))
        let speech = NativeVoiceCallPCM.encode(Array(repeating: Float(0.1), count: 1_024))
        if case .resumed(let data) = try gate.process(speech) {
            XCTAssertLessThanOrEqual(data.count, 6_400)
            XCTAssertEqual(data.suffix(speech.count), speech)
        } else { XCTFail("Actual PCM energy resumes input with bounded pre-speech") }
        XCTAssertFalse(gate.idle)
    }
}

private actor NativeVoiceCallAdmissionLog {
    private(set) var values: [String] = []
    func append(_ value: String) { values.append(value) }
}
private actor NativeVoiceCallAdmissionTransport: NativeVoiceCallTransport {
    let log: NativeVoiceCallAdmissionLog
    private var waiter: CheckedContinuation<String, any Error>?
    private var closed = false
    init(log: NativeVoiceCallAdmissionLog) { self.log = log }
    func connect(_ request: URLRequest) async { await log.append("provider_socket") }
    func send(_ text: String) async throws { await log.append(try NativeVoiceCallWire.decode(text)["type"]?.string ?? "unknown") }
    func receive() async throws -> String {
        guard !closed else { throw NativeVoiceCallError.connectionLost }
        return try await withCheckedThrowingContinuation { waiter = $0 }
    }
    func close() { closed = true; waiter?.resume(throwing: NativeVoiceCallError.connectionLost); waiter = nil }
}
private actor NativeVoiceCallAdmissionAudio: NativeVoiceCallAudio {
    let log: NativeVoiceCallAdmissionLog
    init(log: NativeVoiceCallAdmissionLog) { self.log = log }
    func reserve(scope: NativeVoiceCallScope) async { await log.append("exclusive_reservation") }
    func start(input: @escaping @Sendable (Data) async -> Void,
               failure: @escaping @Sendable (NativeVoiceCallError) async -> Void) async { await log.append("genuine_capture") }
    func setMicrophoneEnabled(_ enabled: Bool) {}
    func play(_ pcm16: Data, sampleRate: Int) {}
    func interruptPlayback() {}
    func stop() {}
}
private actor NativeVoiceCallAdmissionPersistence: NativeVoiceCallPersistence {
    func stageTyped(scope: NativeVoiceCallScope, callID: String, messageID: String, text: String, createdAt: Int) {}
    func transcript(scope: NativeVoiceCallScope, value: NativeVoiceCallTranscript) {}
    func lifecycle(scope: NativeVoiceCallScope, callID: String, started: Bool, createdAt: Int, activeSeconds: TimeInterval) {}
    func compression(scope: NativeVoiceCallScope, callID: String, frame: NativeVoiceCallFrame) throws -> NativeVoiceCallFrame {
        throw NativeVoiceCallError.persistenceFailed
    }
}
