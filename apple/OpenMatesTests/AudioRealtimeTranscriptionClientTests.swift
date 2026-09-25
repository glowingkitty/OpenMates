import Foundation
import XCTest
@testable import OpenMates

@MainActor
final class AudioRealtimeTranscriptionClientTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle
    func testShortLivedHMACTokenRefreshBoundary() {
        let now = Date(timeIntervalSince1970: 1_000)
        XCTAssertFalse(AudioRealtimeTranscriptionClient.tokenNeedsRefresh(token(expiry: 1_031), now: now))
        XCTAssertTrue(AudioRealtimeTranscriptionClient.tokenNeedsRefresh(token(expiry: 1_030), now: now))
        XCTAssertFalse(AudioRealtimeTranscriptionClient.tokenNeedsRefresh("development-token", now: now))
        XCTAssertTrue(AudioRealtimeTranscriptionClient.tokenNeedsRefresh("", now: now))
        XCTAssertTrue(AudioRealtimeTranscriptionClient.tokenNeedsRefresh(nil, now: now))
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle
    func testRequestUsesDedicatedEndpointNativeSessionOriginAndToken() throws {
        let authentication = AudioRealtimeTranscriptionClient.Authentication(
            apiBaseURL: URL(string: "https://api.example.test")!,
            webOrigin: "https://example.test",
            sessionID: "native-session",
            webSocketToken: token(expiry: Int(Date().timeIntervalSince1970) + 300)
        )
        let request = try AudioRealtimeTranscriptionClient.makeRequest(authentication: authentication)
        let components = try XCTUnwrap(URLComponents(url: XCTUnwrap(request.url), resolvingAgainstBaseURL: false))
        XCTAssertEqual(components.scheme, "wss")
        XCTAssertEqual(components.path, "/v1/apps/audio/realtime-transcription")
        XCTAssertEqual(components.queryItems?.first(where: { $0.name == "sessionId" })?.value, "native-session")
        let requestTokenMatches = components.queryItems?.first(where: { $0.name == "token" })?.value
            == authentication.webSocketToken
        XCTAssertTrue(requestTokenMatches, "WebSocket request must carry the supplied short-lived token")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Origin"), "https://example.test")
        XCTAssertNotNil(request.value(forHTTPHeaderField: "X-OpenMates-Client"))
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle
    func testPCMConversionIsMono16kSignedLittleEndian() throws {
        let encoded = try AudioRealtimeTranscriptionClient.pcm16Base64(
            samples: [-1, 0, 1],
            sourceSampleRate: 16_000
        )
        XCTAssertEqual(Data(base64Encoded: encoded), Data([0x00, 0x80, 0x00, 0x00, 0xff, 0x7f]))

        let downsampled = try AudioRealtimeTranscriptionClient.pcm16Base64(
            samples: [1, 1, -1, -1],
            sourceSampleRate: 32_000
        )
        XCTAssertEqual(Data(base64Encoded: downsampled), Data([0xff, 0x7f, 0x00, 0x80]))

        let nonfinite = try AudioRealtimeTranscriptionClient.pcm16Base64(
            samples: [.nan, .infinity, -.infinity],
            sourceSampleRate: 16_000
        )
        XCTAssertEqual(Data(base64Encoded: nonfinite), Data(repeating: 0, count: 6))
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle
    func testFinishBeforeReadyFlushesBoundedAudioMetadataThenOneEnd() async throws {
        let transport = FakeAudioRealtimeTransport()
        let recorder = AudioRealtimeEventRecorder()
        let client = makeClient(transport: transport, recorder: recorder)
        try await client.start(chatID: "chat-1")
        try await client.append(samples: [0.25], sourceSampleRate: 16_000)
        try await client.append(samples: [-0.25], sourceSampleRate: 16_000)
        await client.finish()
        let sentBeforeReady = await transport.sentMessages()
        XCTAssertTrue(sentBeforeReady.isEmpty)

        await transport.push(#"{"type":"session.ready"}"#)
        await transport.waitForSentMessageCount(4)
        let types = await transport.sentMessages().compactMap(messageType)
        XCTAssertEqual(types, ["input_audio.append", "input_audio.append", "session.metadata", "input_audio.end"])

        await client.finish()
        let sentAfterSecondFinish = await transport.sentMessages()
        XCTAssertEqual(sentAfterSecondFinish.compactMap(messageType).filter { $0 == "input_audio.end" }.count, 1)
        await client.cancel()
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send
    func testTranscriptAndCorrectionFinalizeExactlyOnce() async throws {
        let transport = FakeAudioRealtimeTransport()
        let recorder = AudioRealtimeEventRecorder()
        let client = makeClient(transport: transport, recorder: recorder)
        try await client.start()
        await transport.push(#"{"type":"session.ready"}"#)
        await transport.push(#"{"type":"transcription.text.delta","text":"Hello "}"#)
        await transport.push(#"{"type":"transcription.text.delta","text":"world"}"#)
        await transport.push(#"{"type":"transcription.done","transcript":"Hello world","language":"en","model":"voxtral-mini-transcribe-realtime-2602"}"#)
        await transport.push(#"{"type":"transcription.done","transcript":"duplicate"}"#)
        await transport.push(#"{"type":"correction.started","model":"gemini"}"#)
        await transport.push(#"{"type":"correction.done","title":"Greeting","transcript":"Hello, world.","correction_model":"gemini"}"#)
        await transport.push(#"{"type":"correction.done","title":"Duplicate","transcript":"Duplicate"}"#)
        await recorder.waitForCompleted()

        let events = await recorder.events()
        XCTAssertEqual(events.compactMap { event -> AudioRealtimeTranscriptionClient.TranscriptionResult? in
            if case .transcriptionDone(let result) = event { return result }
            return nil
        }, [.init(transcript: "Hello world", language: "en", model: AudioRealtimeTranscriptionClient.model)])
        XCTAssertEqual(events.compactMap { event -> AudioRealtimeTranscriptionClient.CorrectionResult? in
            if case .correctionDone(let result) = event { return result }
            return nil
        }.count, 1)
        XCTAssertEqual(events.filter { $0 == .status(.completed) }.count, 1)
        let closeCalls = await transport.closeCalls()
        XCTAssertEqual(closeCalls, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle
    func testQueueOverflowFailsOnceAndClosesWithoutPlaintextFinalization() async throws {
        let transport = FakeAudioRealtimeTransport()
        let recorder = AudioRealtimeEventRecorder()
        let client = makeClient(transport: transport, recorder: recorder)
        try await client.start()
        for _ in 0..<AudioRealtimeTranscriptionClient.maximumQueuedChunks {
            try await client.append(samples: [0], sourceSampleRate: 16_000)
        }
        do {
            try await client.append(samples: [0], sourceSampleRate: 16_000)
            XCTFail("Expected a bounded-queue failure")
        } catch {
            XCTAssertEqual(error as? AudioRealtimeTranscriptionError, .audioQueueFull)
        }
        await recorder.waitForFailure()
        let events = await recorder.events()
        XCTAssertEqual(events.filter { $0 == .status(.failed(.audioQueueFull)) }.count, 1)
        XCTAssertFalse(events.contains { if case .transcriptionDone = $0 { true } else { false } })
        let closeCalls = await transport.closeCalls()
        XCTAssertEqual(closeCalls, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle
    func testCancellationSendsCancelAndSuppressesLaterServerFinalization() async throws {
        let transport = FakeAudioRealtimeTransport()
        let recorder = AudioRealtimeEventRecorder()
        let client = makeClient(transport: transport, recorder: recorder)
        try await client.start()
        await transport.push(#"{"type":"session.ready"}"#)
        await recorder.waitForListening()
        await client.cancel()
        await transport.push(#"{"type":"transcription.done","transcript":"must not escape"}"#)

        let sentMessages = await transport.sentMessages()
        XCTAssertEqual(sentMessages.compactMap(messageType), ["session.cancel"])
        let events = await recorder.events()
        XCTAssertEqual(events.filter { $0 == .status(.cancelled) }.count, 1)
        XCTAssertFalse(events.contains { if case .transcriptionDone = $0 { true } else { false } })
        let closeCalls = await transport.closeCalls()
        XCTAssertEqual(closeCalls, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle
    func testReadinessDeadlineFailsConnectingSocketOnceForBatchFallback() async throws {
        let transport = FakeAudioRealtimeTransport()
        let recorder = AudioRealtimeEventRecorder()
        let client = makeClient(transport: transport, recorder: recorder)
        try await client.start()

        await client.deadlineElapsed(.readiness)
        await recorder.waitForFailure()
        await client.deadlineElapsed(.readiness)

        let events = await recorder.events()
        XCTAssertEqual(events.filter { $0 == .status(.failed(.connectionTimedOut)) }.count, 1)
        let closeCalls = await transport.closeCalls()
        XCTAssertEqual(closeCalls, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send
    func testCompletionDeadlineFailsAfterRawTranscriptWithoutDuplicateTerminalEvent() async throws {
        let transport = FakeAudioRealtimeTransport()
        let recorder = AudioRealtimeEventRecorder()
        let client = makeClient(transport: transport, recorder: recorder)
        try await client.start()
        await transport.push(#"{"type":"session.ready"}"#)
        await recorder.waitForListening()
        await client.finish()
        await transport.push(#"{"type":"transcription.done","transcript":"Raw text","model":"voxtral-mini-transcribe-realtime-2602"}"#)
        await recorder.waitForTranscription()

        await client.deadlineElapsed(.completion)
        await recorder.waitForFailure()
        await transport.push(#"{"type":"correction.done","transcript":"Late correction"}"#)

        let events = await recorder.events()
        XCTAssertEqual(events.filter { $0 == .status(.failed(.connectionTimedOut)) }.count, 1)
        XCTAssertEqual(events.filter { if case .correctionDone = $0 { true } else { false } }.count, 0)
        let closeCalls = await transport.closeCalls()
        XCTAssertEqual(closeCalls, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle
    func testRejectedInitialHandshakeRefreshesAuthenticationOnceAndRetainsQueuedAudio() async throws {
        let firstTransport = FakeAudioRealtimeTransport()
        let retryTransport = FakeAudioRealtimeTransport()
        let transports = AudioRealtimeTransportSequence([firstTransport, retryTransport])
        let recorder = AudioRealtimeEventRecorder()
        let authenticationCalls = AudioRealtimeAuthenticationRecorder()
        let authentication = AudioRealtimeTranscriptionClient.Authentication(
            apiBaseURL: URL(string: "https://api.example.test")!,
            webOrigin: "https://example.test",
            sessionID: "native-session",
            webSocketToken: token(expiry: Int(Date().timeIntervalSince1970) + 300)
        )
        let client = AudioRealtimeTranscriptionClient(
            authenticationProvider: { forceRefresh in
                await authenticationCalls.record(forceRefresh: forceRefresh)
                return authentication
            },
            transportFactory: { transports.next() },
            eventHandler: { event in await recorder.record(event) }
        )

        try await client.start(chatID: "chat-1")
        try await client.append(samples: [0.25], sourceSampleRate: 16_000)
        await firstTransport.pushFailure(AudioRealtimeTranscriptionError.connectionEndedEarly)
        await authenticationCalls.waitForCount(2)
        await retryTransport.push(#"{"type":"session.ready"}"#)
        await retryTransport.waitForSentMessageCount(2)

        let refreshValues = await authenticationCalls.values()
        let firstCloseCalls = await firstTransport.closeCalls()
        let retryMessageTypes = await retryTransport.sentMessages().compactMap(messageType)
        XCTAssertEqual(refreshValues, [false, true])
        XCTAssertEqual(firstCloseCalls, 1)
        XCTAssertEqual(retryMessageTypes, ["input_audio.append", "session.metadata"])
        await client.cancel()
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle
    func testSecondPreReadyFailureStopsAfterSingleAuthenticationRetry() async throws {
        let firstTransport = FakeAudioRealtimeTransport()
        let retryTransport = FakeAudioRealtimeTransport()
        let transports = AudioRealtimeTransportSequence([firstTransport, retryTransport])
        let recorder = AudioRealtimeEventRecorder()
        let authenticationCalls = AudioRealtimeAuthenticationRecorder()
        let authentication = AudioRealtimeTranscriptionClient.Authentication(
            apiBaseURL: URL(string: "https://api.example.test")!,
            webOrigin: "https://example.test",
            sessionID: "native-session",
            webSocketToken: token(expiry: Int(Date().timeIntervalSince1970) + 300)
        )
        let client = AudioRealtimeTranscriptionClient(
            authenticationProvider: { forceRefresh in
                await authenticationCalls.record(forceRefresh: forceRefresh)
                return authentication
            },
            transportFactory: { transports.next() },
            eventHandler: { event in await recorder.record(event) }
        )

        try await client.start()
        await firstTransport.pushFailure(AudioRealtimeTranscriptionError.connectionEndedEarly)
        await authenticationCalls.waitForCount(2)
        await retryTransport.pushFailure(AudioRealtimeTranscriptionError.connectionEndedEarly)
        await recorder.waitForFailure()

        let refreshValues = await authenticationCalls.values()
        let events = await recorder.events()
        XCTAssertEqual(refreshValues, [false, true])
        XCTAssertEqual(events.filter { $0 == .status(.failed(.connectionEndedEarly)) }.count, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle
    func testCancellationDuringAuthenticationRefreshDoesNotOpenReplacementSocket() async throws {
        let firstTransport = FakeAudioRealtimeTransport()
        let retryTransport = FakeAudioRealtimeTransport()
        let transports = AudioRealtimeTransportSequence([firstTransport, retryTransport])
        let recorder = AudioRealtimeEventRecorder()
        let authenticationCalls = AudioRealtimeAuthenticationRecorder()
        let refreshCancellation = AudioRealtimeCounter()
        let authentication = AudioRealtimeTranscriptionClient.Authentication(
            apiBaseURL: URL(string: "https://api.example.test")!,
            webOrigin: "https://example.test",
            sessionID: "native-session",
            webSocketToken: token(expiry: Int(Date().timeIntervalSince1970) + 300)
        )
        let client = AudioRealtimeTranscriptionClient(
            authenticationProvider: { forceRefresh in
                await authenticationCalls.record(forceRefresh: forceRefresh)
                if forceRefresh {
                    do {
                        try await Task.sleep(for: .seconds(30))
                    } catch {
                        await refreshCancellation.increment()
                        throw error
                    }
                }
                return authentication
            },
            transportFactory: { transports.next() },
            eventHandler: { event in await recorder.record(event) }
        )

        try await client.start()
        await firstTransport.pushFailure(AudioRealtimeTranscriptionError.connectionEndedEarly)
        await authenticationCalls.waitForCount(2)
        await client.cancel()
        await refreshCancellation.waitForCount(1)

        let refreshValues = await authenticationCalls.values()
        let transportFactoryCalls = transports.callCount()
        let retryCloseCalls = await retryTransport.closeCalls()
        let events = await recorder.events()
        XCTAssertEqual(refreshValues, [false, true])
        XCTAssertEqual(transportFactoryCalls, 1)
        XCTAssertEqual(retryCloseCalls, 0)
        XCTAssertEqual(events.filter { $0 == .status(.cancelled) }.count, 1)
        XCTAssertFalse(events.contains { if case .status(.failed) = $0 { true } else { false } })
    }

    private func makeClient(
        transport: FakeAudioRealtimeTransport,
        recorder: AudioRealtimeEventRecorder
    ) -> AudioRealtimeTranscriptionClient {
        let authentication = AudioRealtimeTranscriptionClient.Authentication(
            apiBaseURL: URL(string: "https://api.example.test")!,
            webOrigin: "https://example.test",
            sessionID: "native-session",
            webSocketToken: token(expiry: Int(Date().timeIntervalSince1970) + 300)
        )
        return AudioRealtimeTranscriptionClient(
            authenticationProvider: { _ in authentication },
            transportFactory: { transport },
            eventHandler: { event in await recorder.record(event) }
        )
    }

    private func token(expiry: Int) -> String {
        "\(String(repeating: "a", count: 64)):\(expiry):\(String(repeating: "b", count: 64))"
    }

    private func messageType(_ text: String) -> String? {
        guard let data = text.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        return object["type"] as? String
    }
}

private actor FakeAudioRealtimeTransport: AudioRealtimeSocketTransport {
    private var request: URLRequest?
    private var sent: [String] = []
    private var incoming: [String] = []
    private var incomingFailures: [AudioRealtimeTranscriptionError] = []
    private var receivers: [CheckedContinuation<String, any Error>] = []
    private var sendWaiters: [(Int, CheckedContinuation<Void, Never>)] = []
    private var closes = 0

    func connect(_ request: URLRequest) {
        self.request = request
    }

    func send(_ text: String) {
        sent.append(text)
        let ready = sendWaiters.filter { sent.count >= $0.0 }
        sendWaiters.removeAll { sent.count >= $0.0 }
        ready.forEach { $0.1.resume() }
    }

    func receive() async throws -> String {
        if !incomingFailures.isEmpty { throw incomingFailures.removeFirst() }
        if !incoming.isEmpty { return incoming.removeFirst() }
        return try await withCheckedThrowingContinuation { continuation in
            receivers.append(continuation)
        }
    }

    func close(code: Int, reason: Data?) {
        closes += 1
        let pending = receivers
        receivers.removeAll()
        pending.forEach { $0.resume(throwing: CancellationError()) }
    }

    func push(_ text: String) {
        if !receivers.isEmpty {
            receivers.removeFirst().resume(returning: text)
        } else {
            incoming.append(text)
        }
    }

    func pushFailure(_ error: AudioRealtimeTranscriptionError) {
        if !receivers.isEmpty {
            receivers.removeFirst().resume(throwing: error)
        } else {
            incomingFailures.append(error)
        }
    }

    func sentMessages() -> [String] { sent }
    func closeCalls() -> Int { closes }

    func waitForSentMessageCount(_ count: Int) async {
        if sent.count >= count { return }
        await withCheckedContinuation { continuation in
            sendWaiters.append((count, continuation))
        }
    }
}

private final class AudioRealtimeTransportSequence: @unchecked Sendable {
    private let lock = NSLock()
    private var transports: [FakeAudioRealtimeTransport]
    private var calls = 0

    init(_ transports: [FakeAudioRealtimeTransport]) {
        self.transports = transports
    }

    func next() -> any AudioRealtimeSocketTransport {
        lock.lock()
        defer { lock.unlock() }
        precondition(!transports.isEmpty, "Test requested more transports than expected")
        calls += 1
        return transports.removeFirst()
    }

    func callCount() -> Int {
        lock.lock()
        defer { lock.unlock() }
        return calls
    }
}

private actor AudioRealtimeCounter {
    private var count = 0
    private var waiters: [(Int, CheckedContinuation<Void, Never>)] = []

    func increment() {
        count += 1
        let ready = waiters.filter { count >= $0.0 }
        waiters.removeAll { count >= $0.0 }
        ready.forEach { $0.1.resume() }
    }

    func waitForCount(_ expected: Int) async {
        if count >= expected { return }
        await withCheckedContinuation { waiters.append((expected, $0)) }
    }
}

private actor AudioRealtimeAuthenticationRecorder {
    private var recorded: [Bool] = []
    private var waiters: [(Int, CheckedContinuation<Void, Never>)] = []

    func record(forceRefresh: Bool) {
        recorded.append(forceRefresh)
        let ready = waiters.filter { recorded.count >= $0.0 }
        waiters.removeAll { recorded.count >= $0.0 }
        ready.forEach { $0.1.resume() }
    }

    func values() -> [Bool] { recorded }

    func waitForCount(_ count: Int) async {
        if recorded.count >= count { return }
        await withCheckedContinuation { waiters.append((count, $0)) }
    }
}

private actor AudioRealtimeEventRecorder {
    private var recorded: [AudioRealtimeTranscriptionClient.Event] = []
    private var completedWaiters: [CheckedContinuation<Void, Never>] = []
    private var listeningWaiters: [CheckedContinuation<Void, Never>] = []
    private var failureWaiters: [CheckedContinuation<Void, Never>] = []
    private var transcriptionWaiters: [CheckedContinuation<Void, Never>] = []

    func record(_ event: AudioRealtimeTranscriptionClient.Event) {
        recorded.append(event)
        switch event {
        case .status(.completed):
            completedWaiters.forEach { $0.resume() }
            completedWaiters.removeAll()
        case .status(.listening):
            listeningWaiters.forEach { $0.resume() }
            listeningWaiters.removeAll()
        case .status(.failed):
            failureWaiters.forEach { $0.resume() }
            failureWaiters.removeAll()
        case .transcriptionDone:
            transcriptionWaiters.forEach { $0.resume() }
            transcriptionWaiters.removeAll()
        default:
            break
        }
    }

    func events() -> [AudioRealtimeTranscriptionClient.Event] { recorded }

    func waitForCompleted() async {
        if recorded.contains(.status(.completed)) { return }
        await withCheckedContinuation { completedWaiters.append($0) }
    }

    func waitForListening() async {
        if recorded.contains(.status(.listening)) { return }
        await withCheckedContinuation { listeningWaiters.append($0) }
    }

    func waitForFailure() async {
        if recorded.contains(where: { if case .status(.failed) = $0 { true } else { false } }) { return }
        await withCheckedContinuation { failureWaiters.append($0) }
    }

    func waitForTranscription() async {
        if recorded.contains(where: { if case .transcriptionDone = $0 { true } else { false } }) { return }
        await withCheckedContinuation { transcriptionWaiters.append($0) }
    }
}
