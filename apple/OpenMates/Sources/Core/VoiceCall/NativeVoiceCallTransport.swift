// Web source: frontend/packages/ui/src/services/voiceCall.ts, voiceCallPrivacy.ts
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.privacy.first-call-warning, video-call.chat.fixed-binding,
// video-call.lifecycle.recovery-and-billing, video-call.provider.boundary

import Foundation

protocol NativeVoiceCallTransport: Sendable {
    func connect(_ request: URLRequest) async throws
    func send(_ text: String) async throws
    func receive() async throws -> String
    func close() async
}

/// One instance per attempt. This transport never reconnects or refreshes a paid
/// call. Watch must separately prove legitimate audio/CallKit network eligibility.
actor NativeVoiceCallURLSessionTransport: NativeVoiceCallTransport {
    private let session: URLSession
    private var socket: URLSessionWebSocketTask?
    private var closed = false

    init(cookieStorage: HTTPCookieStorage) {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpCookieStorage = cookieStorage
        configuration.httpShouldSetCookies = true
        session = URLSession(configuration: configuration)
    }

    func connect(_ request: URLRequest) throws {
        guard !closed, socket == nil else { throw NativeVoiceCallError.invalidState }
        let task = session.webSocketTask(with: request)
        socket = task
        task.resume()
    }

    func send(_ text: String) async throws {
        guard !closed, let socket else { throw NativeVoiceCallError.connectionLost }
        try await socket.send(.string(text))
    }

    func receive() async throws -> String {
        guard !closed, let socket else { throw NativeVoiceCallError.connectionLost }
        switch try await socket.receive() {
        case .string(let value): return value
        case .data(let value):
            guard value.count <= NativeVoiceCallWire.maximumFrameBytes,
                  let text = String(data: value, encoding: .utf8) else { throw NativeVoiceCallError.invalidResponse }
            return text
        @unknown default: throw NativeVoiceCallError.invalidResponse
        }
    }

    func close() {
        closed = true
        socket?.cancel(with: .normalClosure, reason: nil)
        socket = nil
        session.invalidateAndCancel()
    }
}

struct NativeVoiceCallAuthentication: Sendable {
    let apiBaseURL: URL
    let webOrigin: String
    let sessionID: String
    let webSocketToken: String
    let nativeHeaders: [String: String]

    func request() throws -> URLRequest {
        guard !sessionID.isEmpty, !webSocketToken.isEmpty,
              var components = URLComponents(url: apiBaseURL, resolvingAgainstBaseURL: false),
              components.scheme == "https" || components.scheme == "http",
              let origin = URLComponents(string: webOrigin), origin.host != nil,
              origin.scheme == "https" || origin.scheme == "http"
        else { throw NativeVoiceCallError.callUnavailable }
        components.scheme = components.scheme == "https" ? "wss" : "ws"
        components.path = "/v1/voice-call"
        components.queryItems = [URLQueryItem(name: "sessionId", value: sessionID),
                                 URLQueryItem(name: "token", value: webSocketToken)]
        components.fragment = nil
        guard let url = components.url else { throw NativeVoiceCallError.callUnavailable }
        var request = URLRequest(url: url)
        request.timeoutInterval = 10
        for (key, value) in nativeHeaders { request.setValue(value, forHTTPHeaderField: key) }
        request.setValue(webOrigin, forHTTPHeaderField: "Origin")
        return request
    }
}

/// Adapters must verify this scope after every auth/profile/key suspension. The
/// consent adapter reads the selected authenticated profile and, if absent, asks
/// for explicit acceptance then POSTs exactly {version:2}; cancellation throws.
/// Authentication may refresh once BEFORE this socket opens. No retry after open.
struct NativeVoiceCallEnvironment: Sendable {
    let isCurrent: @Sendable (NativeVoiceCallScope) async -> Bool
    let ensureConsent: @Sendable (NativeVoiceCallScope) async throws -> Void
    let authentication: @Sendable (NativeVoiceCallScope) async throws -> NativeVoiceCallAuthentication
    let context: @Sendable (NativeVoiceCallScope) async throws -> NativeVoiceCallContext
    /// After genuine capture starts, confirm the encrypted chat/canonical scope
    /// before any provider connection. Watch low-level networking depends on it.
    let prepare: @Sendable (NativeVoiceCallScope) async throws -> Void
    let submitTurn: @Sendable (NativeVoiceCallScope, NativeVoiceCallTranscript) async throws -> Void
    let interruptAssistant: @Sendable (NativeVoiceCallScope, String?, String?) async throws -> Void
    let now: @Sendable () -> Date
    let sleep: @Sendable (Duration) async throws -> Void

    init(isCurrent: @escaping @Sendable (NativeVoiceCallScope) async -> Bool,
         ensureConsent: @escaping @Sendable (NativeVoiceCallScope) async throws -> Void,
         authentication: @escaping @Sendable (NativeVoiceCallScope) async throws -> NativeVoiceCallAuthentication,
         context: @escaping @Sendable (NativeVoiceCallScope) async throws -> NativeVoiceCallContext,
         prepare: @escaping @Sendable (NativeVoiceCallScope) async throws -> Void = { _ in },
         submitTurn: @escaping @Sendable (NativeVoiceCallScope, NativeVoiceCallTranscript) async throws -> Void = { _, _ in throw NativeVoiceCallError.unsupportedTransport },
         interruptAssistant: @escaping @Sendable (NativeVoiceCallScope, String?, String?) async throws -> Void = { _, _, _ in },
         now: @escaping @Sendable () -> Date = { Date() },
         sleep: @escaping @Sendable (Duration) async throws -> Void = { try await Task.sleep(for: $0) }) {
        self.isCurrent = isCurrent
        self.ensureConsent = ensureConsent
        self.authentication = authentication
        self.context = context
        self.prepare = prepare
        self.submitTurn = submitTurn
        self.interruptAssistant = interruptAssistant
        self.now = now
        self.sleep = sleep
    }
}

/// Serialize actual wire writes across actor reentrancy. End markers cannot
/// overtake PCM and interruption/hangup cannot race an earlier queued send.
actor NativeVoiceCallOrderedWriter {
    private let transport: any NativeVoiceCallTransport
    private let isCurrent: @Sendable () async -> Bool
    private var tail: Task<Void, any Error>?
    private var closed = false

    init(transport: any NativeVoiceCallTransport, isCurrent: @escaping @Sendable () async -> Bool = { true }) {
        self.transport = transport; self.isCurrent = isCurrent
    }

    func send(_ frame: NativeVoiceCallFrame) async throws {
        guard !closed else { throw NativeVoiceCallError.connectionLost }
        let text = try NativeVoiceCallWire.encode(frame)
        let previous = tail
        let transport = transport, isCurrent = isCurrent
        let operation = Task {
            if let previous { try await previous.value }
            try Task.checkCancellation()
            guard await isCurrent() else { throw NativeVoiceCallError.scopeChanged }
            try await transport.send(text)
        }
        tail = operation
        try await operation.value
    }

    func close() async {
        closed = true
        tail?.cancel()
        await transport.close()
        tail = nil
    }
}
