// Dedicated, short-lived realtime audio transcription transport.
// Mirrors the authenticated browser protocol without sharing the long-lived chat socket.
// Specification: specifications/features/message-input/specification.yml
// Assertions: message-input.recording.lifecycle, message-input.embeds.gated-send

import Foundation

protocol AudioRealtimeSocketTransport: Sendable {
    func connect(_ request: URLRequest) async throws
    func send(_ text: String) async throws
    func receive() async throws -> String
    func close(code: Int, reason: Data?) async
}

actor URLSessionAudioRealtimeSocketTransport: AudioRealtimeSocketTransport {
    private let session: URLSession
    private var task: URLSessionWebSocketTask?

    init() {
        let configuration = URLSessionConfiguration.default
        configuration.httpCookieAcceptPolicy = .always
        configuration.httpShouldSetCookies = true
        configuration.httpCookieStorage = OpenMatesSharedEnvironment.cookieStorage
        session = URLSession(configuration: configuration)
    }

    func connect(_ request: URLRequest) throws {
        guard task == nil else { throw AudioRealtimeTranscriptionError.invalidState }
        let socket = session.webSocketTask(with: request)
        task = socket
        socket.resume()
    }

    func send(_ text: String) async throws {
        guard let task else { throw AudioRealtimeTranscriptionError.notConnected }
        try await task.send(.string(text))
    }

    func receive() async throws -> String {
        guard let task else { throw AudioRealtimeTranscriptionError.notConnected }
        switch try await task.receive() {
        case .string(let text):
            return text
        case .data(let data):
            guard let text = String(data: data, encoding: .utf8) else {
                throw AudioRealtimeTranscriptionError.invalidServerMessage
            }
            return text
        @unknown default:
            throw AudioRealtimeTranscriptionError.invalidServerMessage
        }
    }

    func close(code: Int, reason: Data?) {
        let closeCode = URLSessionWebSocketTask.CloseCode(rawValue: code) ?? .goingAway
        task?.cancel(with: closeCode, reason: reason)
        task = nil
        session.invalidateAndCancel()
    }
}

enum AudioRealtimeTranscriptionError: Error, Equatable, Sendable {
    case authenticationUnavailable
    case invalidState
    case notConnected
    case audioQueueFull
    case invalidAudioFormat
    case invalidServerMessage
    case serverFailure
    case connectionEndedEarly
    case connectionTimedOut
}

actor AudioRealtimeTranscriptionClient {
    static let model = "voxtral-mini-transcribe-realtime-2602"
    static let targetSampleRate = 16_000
    static let maximumQueuedChunks = 96
    static let maximumChunkBytes = 256 * 1_024
    static let tokenRefreshLeeway: TimeInterval = 30
    static let readinessTimeout: Duration = .seconds(15)
    static let completionTimeout: Duration = .seconds(90)

    struct Authentication: Sendable {
        let apiBaseURL: URL
        let webOrigin: String
        let sessionID: String
        let webSocketToken: String
    }

    struct TranscriptionResult: Equatable, Sendable {
        let transcript: String
        let language: String?
        let model: String
    }

    struct CorrectionResult: Equatable, Sendable {
        let transcript: String
        let language: String?
        let model: String
        let title: String?
        let transcriptOriginal: String
        let transcriptCorrected: String?
        let useCorrected: Bool
        let correctionModel: String?
    }

    enum Status: Equatable, Sendable {
        case connecting
        case listening
        case correcting
        case completed
        case cancelled
        case failed(AudioRealtimeTranscriptionError)
    }

    enum Event: Equatable, Sendable {
        case status(Status)
        case transcript(String)
        case transcriptionDone(TranscriptionResult)
        case correctionDone(CorrectionResult)
    }

    enum Deadline: Sendable {
        case readiness
        case completion
    }

    typealias AuthenticationProvider = @MainActor @Sendable () async throws -> Authentication
    typealias EventHandler = @Sendable (Event) async -> Void
    typealias TransportFactory = @Sendable () -> any AudioRealtimeSocketTransport

    private enum Phase: Equatable {
        case idle
        case connecting
        case ready
        case finishing
        case completed
        case cancelled
        case failed
    }

    private let authenticationProvider: AuthenticationProvider
    private let transportFactory: TransportFactory
    private let eventHandler: EventHandler
    private var transport: (any AudioRealtimeSocketTransport)?
    private var receiveTask: Task<Void, Never>?
    private var readinessTimeoutTask: Task<Void, Never>?
    private var completionTimeoutTask: Task<Void, Never>?
    private var phase: Phase = .idle
    private var queuedAudio: [String] = []
    private var pendingChatID: String?
    private var hasReceivedReady = false
    private var accumulatedTranscript = ""
    private var rawResult: TranscriptionResult?
    private var correctionSettled = false
    private var didSendEnd = false

    init(
        authenticationProvider: @escaping AuthenticationProvider,
        transportFactory: @escaping TransportFactory = { URLSessionAudioRealtimeSocketTransport() },
        eventHandler: @escaping EventHandler
    ) {
        self.authenticationProvider = authenticationProvider
        self.transportFactory = transportFactory
        self.eventHandler = eventHandler
    }

    @MainActor
    static func live(
        authManager: AuthManager,
        eventHandler: @escaping EventHandler
    ) -> AudioRealtimeTranscriptionClient {
        AudioRealtimeTranscriptionClient(
            authenticationProvider: { @MainActor [weak authManager] in
                guard let authManager else { throw AudioRealtimeTranscriptionError.authenticationUnavailable }
                if tokenNeedsRefresh(authManager.webSocketToken) {
                    await authManager.validateSessionAfterOfflineBootstrap()
                }
                guard authManager.state == .authenticated,
                      authManager.sessionValidationState == .onlineAuthenticated,
                      let token = authManager.webSocketToken,
                      !tokenNeedsRefresh(token) else {
                    throw AudioRealtimeTranscriptionError.authenticationUnavailable
                }
                let profile = ServerProfile.current()
                return Authentication(
                    apiBaseURL: profile.apiBaseURL,
                    webOrigin: profile.webBaseURL.absoluteString,
                    sessionID: AuthManager.nativeSessionId,
                    webSocketToken: token
                )
            },
            eventHandler: eventHandler
        )
    }

    func start(chatID: String? = nil) async throws {
        guard phase == .idle else { throw AudioRealtimeTranscriptionError.invalidState }
        phase = .connecting
        pendingChatID = chatID
        await eventHandler(.status(.connecting))

        let authentication: Authentication
        do {
            authentication = try await authenticationProvider()
        } catch let error as AudioRealtimeTranscriptionError {
            await fail(error)
            throw error
        } catch {
            await fail(.authenticationUnavailable)
            throw AudioRealtimeTranscriptionError.authenticationUnavailable
        }

        do {
            let request = try Self.makeRequest(authentication: authentication)
            let activeTransport = transportFactory()
            transport = activeTransport
            try await activeTransport.connect(request)
            receiveTask = Task { [weak self] in
                await self?.receiveLoop()
            }
            scheduleReadinessTimeout()
        } catch let error as AudioRealtimeTranscriptionError {
            await fail(error)
            throw error
        } catch {
            await fail(.connectionEndedEarly)
            throw AudioRealtimeTranscriptionError.connectionEndedEarly
        }
    }

    func append(samples: [Float], sourceSampleRate: Double) async throws {
        let encoded = try Self.pcm16Base64(samples: samples, sourceSampleRate: sourceSampleRate)
        try await appendEncodedPCM(encoded)
    }

    func setChatID(_ chatID: String) async throws {
        guard !chatID.isEmpty, chatID.utf8.count <= 128 else { return }
        pendingChatID = chatID
        if hasReceivedReady && (phase == .ready || phase == .finishing) {
            try await sendJSON(["type": "session.metadata", "chat_id": chatID])
        }
    }

    func finish() async {
        guard phase == .connecting || phase == .ready else { return }
        if phase == .connecting {
            phase = .finishing
            scheduleCompletionTimeoutIfNeeded()
            return
        }
        phase = .finishing
        scheduleCompletionTimeoutIfNeeded()
        await sendEndIfNeeded()
    }

    func cancel() async {
        guard phase != .cancelled, phase != .completed, phase != .failed else { return }
        let canNotifyServer = hasReceivedReady && (phase == .ready || phase == .finishing)
        phase = .cancelled
        queuedAudio.removeAll(keepingCapacity: false)
        accumulatedTranscript = ""
        rawResult = nil
        if canNotifyServer {
            try? await sendJSON(["type": "session.cancel"])
        }
        await closeTransport(code: 1_000, reason: "cancelled")
        await eventHandler(.status(.cancelled))
    }

    private func appendEncodedPCM(_ audio: String) async throws {
        switch phase {
        case .connecting:
            guard queuedAudio.count < Self.maximumQueuedChunks else {
                await fail(.audioQueueFull)
                throw AudioRealtimeTranscriptionError.audioQueueFull
            }
            queuedAudio.append(audio)
        case .ready:
            try await sendJSON(["type": "input_audio.append", "audio": audio])
        default:
            throw AudioRealtimeTranscriptionError.invalidState
        }
    }

    private func receiveLoop() async {
        guard let transport else { return }
        do {
            while !Task.isCancelled {
                let text = try await transport.receive()
                try await handleServerMessage(text)
                if phase == .completed || phase == .cancelled || phase == .failed { return }
            }
        } catch is CancellationError {
            return
        } catch let error as AudioRealtimeTranscriptionError {
            await fail(error)
        } catch {
            await fail(.connectionEndedEarly)
        }
    }

    private func handleServerMessage(_ text: String) async throws {
        guard let data = text.data(using: .utf8),
              let message = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = message["type"] as? String else {
            throw AudioRealtimeTranscriptionError.invalidServerMessage
        }

        switch type {
        case "session.ready":
            guard phase == .connecting || phase == .finishing else { return }
            hasReceivedReady = true
            readinessTimeoutTask?.cancel()
            readinessTimeoutTask = nil
            let finishWasRequested = phase == .finishing
            phase = .ready
            await eventHandler(.status(.listening))
            let buffered = queuedAudio
            queuedAudio.removeAll(keepingCapacity: false)
            for audio in buffered {
                try await sendJSON(["type": "input_audio.append", "audio": audio])
            }
            if let pendingChatID {
                try await sendJSON(["type": "session.metadata", "chat_id": pendingChatID])
            }
            if finishWasRequested {
                phase = .finishing
                await sendEndIfNeeded()
            }

        case "transcription.text.delta", "text.delta":
            guard phase != .completed, phase != .cancelled, phase != .failed else { return }
            accumulatedTranscript += message["text"] as? String ?? ""
            await eventHandler(.transcript(accumulatedTranscript.trimmingCharacters(in: .whitespacesAndNewlines)))

        case "transcription.done":
            guard rawResult == nil else { return }
            scheduleCompletionTimeoutIfNeeded()
            let transcript = (message["transcript"] as? String ?? accumulatedTranscript)
                .trimmingCharacters(in: .whitespacesAndNewlines)
            accumulatedTranscript = transcript
            let result = TranscriptionResult(
                transcript: transcript,
                language: Self.nonemptyString(message["language"]),
                model: Self.nonemptyString(message["model"]) ?? Self.model
            )
            rawResult = result
            await eventHandler(.transcript(transcript))
            await eventHandler(.transcriptionDone(result))

        case "correction.started":
            guard rawResult != nil, !correctionSettled else { return }
            await eventHandler(.status(.correcting))

        case "correction.done":
            guard let rawResult, !correctionSettled else { return }
            correctionSettled = true
            let corrected = Self.nonemptyString(message["transcript"])
            let result = CorrectionResult(
                transcript: corrected ?? rawResult.transcript,
                language: rawResult.language,
                model: rawResult.model,
                title: Self.nonemptyString(message["title"]),
                transcriptOriginal: rawResult.transcript,
                transcriptCorrected: corrected,
                useCorrected: true,
                correctionModel: Self.nonemptyString(message["correction_model"])
            )
            await complete(with: result)

        case "correction.failed":
            guard let rawResult, !correctionSettled else { return }
            correctionSettled = true
            let result = CorrectionResult(
                transcript: rawResult.transcript,
                language: rawResult.language,
                model: rawResult.model,
                title: nil,
                transcriptOriginal: rawResult.transcript,
                transcriptCorrected: nil,
                useCorrected: false,
                correctionModel: nil
            )
            await complete(with: result)

        case "session.error":
            throw AudioRealtimeTranscriptionError.serverFailure

        default:
            return
        }
    }

    private func complete(with result: CorrectionResult) async {
        guard phase != .completed, phase != .cancelled, phase != .failed else { return }
        phase = .completed
        await eventHandler(.correctionDone(result))
        await eventHandler(.status(.completed))
        accumulatedTranscript = ""
        rawResult = nil
        await closeTransport(code: 1_000, reason: "complete")
    }

    private func sendEndIfNeeded() async {
        guard !didSendEnd else { return }
        didSendEnd = true
        do {
            try await sendJSON(["type": "input_audio.end"])
        } catch {
            await fail(.connectionEndedEarly)
        }
    }

    private func sendJSON(_ value: [String: String]) async throws {
        guard let transport else { throw AudioRealtimeTranscriptionError.notConnected }
        let data = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
        guard let text = String(data: data, encoding: .utf8) else {
            throw AudioRealtimeTranscriptionError.invalidServerMessage
        }
        try await transport.send(text)
    }

    private func fail(_ error: AudioRealtimeTranscriptionError) async {
        guard phase != .completed, phase != .cancelled, phase != .failed else { return }
        phase = .failed
        queuedAudio.removeAll(keepingCapacity: false)
        accumulatedTranscript = ""
        rawResult = nil
        await closeTransport(code: 1_011, reason: "failed")
        await eventHandler(.status(.failed(error)))
    }

    private func closeTransport(code: Int, reason: String) async {
        receiveTask?.cancel()
        receiveTask = nil
        readinessTimeoutTask?.cancel()
        readinessTimeoutTask = nil
        completionTimeoutTask?.cancel()
        completionTimeoutTask = nil
        let activeTransport = transport
        transport = nil
        await activeTransport?.close(code: code, reason: Data(reason.utf8))
    }

    private func scheduleReadinessTimeout() {
        readinessTimeoutTask?.cancel()
        readinessTimeoutTask = Task { [weak self] in
            do {
                try await Task.sleep(for: Self.readinessTimeout)
            } catch {
                return
            }
            await self?.deadlineElapsed(.readiness)
        }
    }

    private func scheduleCompletionTimeoutIfNeeded() {
        guard completionTimeoutTask == nil else { return }
        completionTimeoutTask = Task { [weak self] in
            do {
                try await Task.sleep(for: Self.completionTimeout)
            } catch {
                return
            }
            await self?.deadlineElapsed(.completion)
        }
    }

    func deadlineElapsed(_ deadline: Deadline) async {
        switch deadline {
        case .readiness:
            guard !hasReceivedReady && (phase == .connecting || phase == .finishing) else { return }
            await fail(.connectionTimedOut)
        case .completion:
            guard phase == .finishing || (rawResult != nil && !correctionSettled) else { return }
            await fail(.connectionTimedOut)
        }
    }

    static func tokenNeedsRefresh(_ token: String?, now: Date = Date()) -> Bool {
        guard let token, !token.isEmpty else { return true }
        let parts = token.split(separator: ":", maxSplits: 2, omittingEmptySubsequences: false)
        // Keep compatibility with opaque development tokens. Production HMAC
        // tokens always use <token_hash>:<expiry>:<signature>.
        guard parts.count == 3 else { return false }
        guard let expiry = TimeInterval(parts[1]) else { return true }
        return expiry <= now.timeIntervalSince1970 + tokenRefreshLeeway
    }

    static func makeRequest(authentication: Authentication) throws -> URLRequest {
        guard !tokenNeedsRefresh(authentication.webSocketToken),
              var components = URLComponents(url: authentication.apiBaseURL, resolvingAgainstBaseURL: false) else {
            throw AudioRealtimeTranscriptionError.authenticationUnavailable
        }
        components.scheme = components.scheme == "http" ? "ws" : "wss"
        components.path = "/v1/apps/audio/realtime-transcription"
        components.queryItems = [
            URLQueryItem(name: "sessionId", value: authentication.sessionID),
            URLQueryItem(name: "token", value: authentication.webSocketToken),
        ]
        guard let url = components.url else { throw AudioRealtimeTranscriptionError.authenticationUnavailable }
        var request = URLRequest(url: url)
        request.timeoutInterval = 30
        request.setValue(authentication.webOrigin, forHTTPHeaderField: "Origin")
        APIClient.nativeClientHeaders.forEach { key, value in
            request.setValue(value, forHTTPHeaderField: key)
        }
        return request
    }

    static func pcm16Base64(samples: [Float], sourceSampleRate: Double) throws -> String {
        guard !samples.isEmpty, sourceSampleRate.isFinite, sourceSampleRate > 0 else {
            throw AudioRealtimeTranscriptionError.invalidAudioFormat
        }
        let output: [Float]
        if sourceSampleRate == Double(targetSampleRate) {
            output = samples
        } else {
            let ratio = sourceSampleRate / Double(targetSampleRate)
            let outputCount = max(1, Int(floor(Double(samples.count) / ratio)))
            output = (0..<outputCount).map { outputIndex in
                let start = Int(floor(Double(outputIndex) * ratio))
                let proposedEnd = Int(floor(Double(outputIndex + 1) * ratio))
                let end = min(samples.count, max(start + 1, proposedEnd))
                guard start < samples.count, start < end else { return 0 }
                let sum = samples[start..<end].reduce(Float.zero, +)
                return sum / Float(end - start)
            }
        }
        var data = Data(capacity: output.count * MemoryLayout<Int16>.size)
        guard output.count * MemoryLayout<Int16>.size <= maximumChunkBytes else {
            throw AudioRealtimeTranscriptionError.invalidAudioFormat
        }
        for rawSample in output {
            let sample = rawSample.isFinite ? max(-1, min(1, rawSample)) : 0
            let scaled = sample < 0 ? sample * 32_768 : sample * 32_767
            var littleEndian = Int16(scaled).littleEndian
            withUnsafeBytes(of: &littleEndian) { data.append(contentsOf: $0) }
        }
        return data.base64EncodedString()
    }

    private static func nonemptyString(_ value: Any?) -> String? {
        guard let value = value as? String, !value.isEmpty else { return nil }
        return value
    }

}
