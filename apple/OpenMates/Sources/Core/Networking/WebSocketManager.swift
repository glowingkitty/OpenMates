// WebSocket connection manager for real-time sync with the backend.
// Routes AI streaming events to StreamingClient, sync events to SyncManager,
// and chat updates to ChatStore. Uses native URLSessionWebSocketTask.

import Foundation

@MainActor
final class WebSocketManager: NSObject, ObservableObject, URLSessionWebSocketDelegate {
    @Published private(set) var connectionState: ConnectionState = .disconnected

    private var webSocketTask: URLSessionWebSocketTask?
    private var pingTimer: Timer?
    private let decoder = JSONDecoder()
    private var connectTask: Task<Void, Never>?
    private var activeConnectionKey: ConnectionKey?
    private var didOpenCurrentSocket = false
    private lazy var session: URLSession = {
        let config = URLSessionConfiguration.default
        config.httpCookieAcceptPolicy = .always
        config.httpShouldSetCookies = true
        config.httpCookieStorage = OpenMatesSharedEnvironment.cookieStorage
        return URLSession(configuration: config, delegate: self, delegateQueue: nil)
    }()

    enum ConnectionState: Equatable {
        case disconnected
        case connecting
        case connected
        case reconnecting(attempt: Int)
    }

    private var sessionId: String?
    private var authToken: String?
    private var shouldReconnect = false
    private var maxReconnectAttempts = 10
    private var reconnectDelay: TimeInterval = 1.0

    override init() {
        super.init()
    }

    func connect(
        sessionId: String,
        token: String?,
        syncState: SyncClientState = .empty
    ) {
        let nextKey = ConnectionKey(sessionId: sessionId, token: token)
        if activeConnectionKey == nextKey {
            switch connectionState {
            case .connected:
                return
            case .connecting:
                return
            case .disconnected, .reconnecting:
                break
            }
        }

        connectTask?.cancel()
        pingTimer?.invalidate()
        pingTimer = nil
        webSocketTask?.cancel(with: .goingAway, reason: nil)
        webSocketTask = nil
        didOpenCurrentSocket = false

        self.sessionId = sessionId
        self.authToken = token
        activeConnectionKey = nextKey
        shouldReconnect = true
        connectionState = .connecting

        connectTask = Task { [weak self] in
            guard let self else { return }
            let baseURL = await APIClient.shared.baseURL
            let origin = await APIClient.shared.webAppURL.absoluteString
            guard var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false) else { return }
            components.scheme = components.scheme == "https" ? "wss" : "ws"
            components.path = "/v1/ws"
            var queryItems = [URLQueryItem(name: "sessionId", value: sessionId)]
            if let token, !token.isEmpty {
                queryItems.append(URLQueryItem(name: "token", value: token))
            }
            components.queryItems = queryItems

            guard let url = components.url else { return }

            var request = URLRequest(url: url)
            request.timeoutInterval = 30
            request.setValue(origin, forHTTPHeaderField: "Origin")
            APIClient.nativeClientHeaders.forEach { key, value in
                request.setValue(value, forHTTPHeaderField: key)
            }

            webSocketTask = session.webSocketTask(with: request)
            webSocketTask?.resume()

            guard await waitForOpenSocket(), !Task.isCancelled else {
                print("[WS] Connection probe failed before sync request")
                handleDisconnect()
                return
            }

            connectionState = .connected
            reconnectDelay = 1.0
            startPingTimer()
            receiveMessages()
            try? await requestPhasedSync(syncState: syncState)
        }
    }

    func disconnect() {
        shouldReconnect = false
        connectTask?.cancel()
        connectTask = nil
        pingTimer?.invalidate()
        pingTimer = nil
        webSocketTask?.cancel(with: .normalClosure, reason: nil)
        webSocketTask = nil
        authToken = nil
        activeConnectionKey = nil
        didOpenCurrentSocket = false
        connectionState = .disconnected
    }

    func send(_ message: WSOutboundMessage) async throws {
        guard let webSocketTask else { throw WebSocketError.notConnected }
        let data = try JSONEncoder().encode(message)
        guard let json = String(data: data, encoding: .utf8) else {
            throw WebSocketError.encodingFailed
        }
        try await webSocketTask.send(.string(json))
    }

    func requestPhasedSync(
        clientChatVersions: [String: [String: Int]] = [:],
        clientChatIds: [String] = [],
        clientSuggestionsCount: Int = 0,
        clientEmbedIds: [String] = []
    ) async throws {
        try await send(WSOutboundMessage(
            type: "phased_sync_request",
            payload: [
                "phase": "all",
                "client_chat_versions": clientChatVersions,
                "client_chat_ids": clientChatIds,
                "client_suggestions_count": clientSuggestionsCount,
                "client_embed_ids": clientEmbedIds
            ]
        ))
    }

    func requestPhasedSync(syncState: SyncClientState) async throws {
        try await requestPhasedSync(
            clientChatVersions: syncState.clientChatVersions,
            clientChatIds: syncState.clientChatIds,
            clientSuggestionsCount: syncState.clientSuggestionsCount,
            clientEmbedIds: syncState.clientEmbedIds
        )
    }

    private func waitForOpenSocket() async -> Bool {
        for _ in 0..<30 {
            if Task.isCancelled { return false }
            if didOpenCurrentSocket { return true }
            try? await Task.sleep(for: .milliseconds(100))
        }
        guard let task = webSocketTask else { return false }
        return await withCheckedContinuation { continuation in
            task.sendPing { error in
                if let error {
                    print("[WS] Open probe ping failed: \(error.localizedDescription)")
                    continuation.resume(returning: false)
                } else {
                    continuation.resume(returning: true)
                }
            }
        }
    }

    // MARK: - Receive loop

    private func receiveMessages() {
        webSocketTask?.receive { [weak self] result in
            Task { @MainActor in
                guard let self else { return }
                switch result {
                case .success(let message):
                    self.handleRawMessage(message)
                    self.receiveMessages()
                case .failure(let error):
                    print("[WS] Receive error: \(error.localizedDescription)")
                    self.handleDisconnect()
                }
            }
        }
    }

    private func handleRawMessage(_ message: URLSessionWebSocketTask.Message) {
        let data: Data
        switch message {
        case .string(let text):
            guard let d = text.data(using: .utf8) else { return }
            data = d
        case .data(let d):
            data = d
        @unknown default:
            return
        }

        guard let parsed = try? decoder.decode(WSInboundParsed.self, from: data) else { return }
        routeMessage(parsed, raw: data)
    }

    // MARK: - Message routing

    private func routeMessage(_ msg: WSInboundParsed, raw: Data) {
        switch msg.type {
        // Keepalive
        case "pong":
            break

        // AI streaming — route to StreamingClient
        case "ai_task_initiated":
            let chatId = msg.stringField("chat_id") ?? ""
            let taskId = msg.stringField("ai_task_id") ?? msg.stringField("task_id") ?? ""
            let userMsgId = msg.stringField("user_message_id") ?? ""
            Task {
                await StreamingClient.shared.dispatch(
                    .taskInitiated(chatId: chatId, taskId: taskId, userMessageId: userMsgId),
                    for: chatId
                )
            }

        case "ai_typing_started":
            let chatId = msg.stringField("chat_id") ?? ""
            let messageId = msg.stringField("message_id") ?? ""
            let metadata = StreamingClient.ChatMetadata(
                title: msg.stringField("title"),
                iconNames: msg.stringArrayField("icon_names") ?? [],
                category: msg.stringField("category"),
                modelName: msg.stringField("model_name"),
                providerName: msg.stringField("provider_name"),
                serverRegion: msg.stringField("server_region"),
                userMessageId: msg.stringField("user_message_id"),
                encryptedChatKey: msg.stringField("encrypted_chat_key")
            )
            Task {
                await StreamingClient.shared.dispatch(
                    .typingStarted(chatId: chatId, messageId: messageId, metadata: metadata),
                    for: chatId
                )
            }
            NotificationCenter.default.post(
                name: .wsMessageReceived, object: nil,
                userInfo: ["type": msg.type, "raw": raw]
            )

        case "ai_message_update":
            let chatId = msg.stringField("chat_id") ?? ""
            let messageId = msg.stringField("message_id") ?? ""
            let sequence = msg.intField("sequence") ?? 0
            let content = msg.stringField("full_content_so_far") ?? ""
            let isFinal = msg.boolField("is_final_chunk") ?? false
            let userMessageId = msg.stringField("user_message_id")
            let category = msg.stringField("category")
            let modelName = msg.stringField("model_name")
            let rejectionReason = msg.stringField("rejection_reason")
            Task {
                await StreamingClient.shared.dispatch(
                    .chunk(
                        chatId: chatId,
                        messageId: messageId,
                        sequence: sequence,
                        content: content,
                        isFinal: isFinal,
                        userMessageId: userMessageId,
                        category: category,
                        modelName: modelName,
                        rejectionReason: rejectionReason
                    ),
                    for: chatId
                )
            }

        case "thinking_chunk":
            let chatId = msg.stringField("chat_id") ?? ""
            let messageId = msg.stringField("message_id") ?? ""
            let content = msg.stringField("content") ?? ""
            Task {
                await StreamingClient.shared.dispatch(
                    .thinkingChunk(chatId: chatId, messageId: messageId, content: content),
                    for: chatId
                )
            }

        case "thinking_complete":
            let chatId = msg.stringField("chat_id") ?? ""
            let messageId = msg.stringField("message_id") ?? ""
            Task {
                await StreamingClient.shared.dispatch(
                    .thinkingComplete(chatId: chatId, messageId: messageId),
                    for: chatId
                )
            }

        case "ai_message_ready":
            let chatId = msg.stringField("chat_id") ?? ""
            let messageId = msg.stringField("message_id") ?? ""
            Task {
                await StreamingClient.shared.dispatch(
                    .messageReady(chatId: chatId, messageId: messageId),
                    for: chatId
                )
            }

        case "preprocessing_step":
            let chatId = msg.stringField("chat_id") ?? ""
            let step = msg.stringField("step") ?? ""
            Task {
                await StreamingClient.shared.dispatch(
                    .preprocessingStep(chatId: chatId, step: step, data: nil),
                    for: chatId
                )
            }

        case "post_processing_completed":
            let chatId = msg.stringField("chat_id") ?? ""
            let taskId = msg.stringField("task_id") ?? ""
            Task {
                await StreamingClient.shared.dispatch(
                    .postProcessingCompleted(
                        chatId: chatId,
                        taskId: taskId,
                        followUpSuggestions: msg.stringArrayField("follow_up_request_suggestions") ?? [],
                        newChatSuggestions: msg.stringArrayField("new_chat_request_suggestions") ?? [],
                        chatSummary: msg.stringField("chat_summary"),
                        chatTags: msg.stringArrayField("chat_tags") ?? [],
                        updatedTitle: msg.stringField("updated_chat_title")
                    ),
                    for: chatId
                )
            }

        case "request_chat_history":
            NotificationCenter.default.post(
                name: .wsHistoryRequested, object: nil,
                userInfo: ["raw": raw]
            )

        // Chat updates
        case "new_chat_message", "chat_message_added", "chat_message_confirmed",
              "encrypted_chat_metadata", "chat_update", "new_message", "message_update",
              "chat_draft_updated", "draft_deleted", "chat_deleted", "chat_read_status_updated",
              "chat_pinned_updated", "message_deleted", "message_highlight_added",
              "message_highlight_updated", "message_highlight_removed", "draft_embed_deleted",
              "last_opened_updated", "key_delivery_confirmed", "system_message_confirmed",
              "new_system_message", "reminder_fired", "pending_ai_response",
              "ai_response_storage_confirmed", "ai_background_response_completed",
              "ai_task_cancel_requested", "chat_compression_started", "chat_compression_completed",
              "encrypted_metadata_stored", "post_processing_metadata_stored",
              "ai_typing_ended", "message_queued", "focus_mode_activated",
              "spawn_sub_chats", "sub_chat_confirmation_required",
              "sub_chat_confirmation_resolved", "sub_chat_progress", "sub_chat_stopped":
            NotificationCenter.default.post(
                name: .wsMessageReceived, object: nil,
                userInfo: ["type": msg.type, "raw": raw]
            )

        // Sync phases
        case "initial_sync_response", "initial_sync_error",
             "phase_1_last_chat_ready", "phase_1b_chat_content_ready",
             "phase_2_last_20_chats_ready", "phase_3_last_100_chats_ready",
             "background_message_sync", "cache_primed", "cache_status_response",
             "load_more_chats_response", "sync_metadata_chats_response",
             "phased_sync_complete", "sync_status_response",
             "offline_sync_complete", "chat_content_batch_response":
            NotificationCenter.default.post(
                name: .wsSyncEvent, object: nil,
                userInfo: ["type": msg.type, "raw": raw]
            )

        // Embed updates
        case "embed_update", "embed_updated", "embed_status_changed", "send_embed_data":
            NotificationCenter.default.post(
                name: .wsEmbedUpdate, object: nil,
                userInfo: ["type": msg.type, "raw": raw]
            )

        // Payment
        case "payment_completed":
            NotificationCenter.default.post(name: .paymentCompleted, object: nil)

        case "force_logout":
            let reason = msg.stringField("reason") ?? "session_revoked"
            NotificationCenter.default.post(
                name: .wsForceLogout, object: nil,
                userInfo: ["reason": reason]
            )

        default:
            print("[WS] Unhandled: \(msg.type)")
        }
    }

    // MARK: - Ping timer

    private func startPingTimer() {
        pingTimer?.invalidate()
        pingTimer = Timer.scheduledTimer(withTimeInterval: 25, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.webSocketTask?.sendPing { error in
                    if let error {
                        print("[WS] Ping error: \(error.localizedDescription)")
                        Task { @MainActor in
                            self?.handleDisconnect()
                        }
                    }
                }
            }
        }
    }

    // MARK: - Reconnect

    private func handleDisconnect() {
        pingTimer?.invalidate()
        pingTimer = nil
        webSocketTask = nil
        guard shouldReconnect else {
            connectionState = .disconnected
            return
        }

        let currentAttempt: Int
        if case .reconnecting(let a) = connectionState { currentAttempt = a + 1 }
        else { currentAttempt = 1 }

        guard currentAttempt <= maxReconnectAttempts else {
            connectionState = .disconnected
            return
        }

        connectionState = .reconnecting(attempt: currentAttempt)

        Task {
            try? await Task.sleep(for: .seconds(reconnectDelay))
            reconnectDelay = min(reconnectDelay * 2, 30)
            if let sessionId {
                connect(sessionId: sessionId, token: authToken)
            }
        }
    }

    nonisolated func urlSession(
        _ session: URLSession,
        webSocketTask: URLSessionWebSocketTask,
        didOpenWithProtocol protocol: String?
    ) {
        Task { @MainActor [weak self] in
            guard let self, self.webSocketTask?.taskIdentifier == webSocketTask.taskIdentifier else { return }
            self.didOpenCurrentSocket = true
        }
    }

    nonisolated func urlSession(
        _ session: URLSession,
        webSocketTask: URLSessionWebSocketTask,
        didCloseWith closeCode: URLSessionWebSocketTask.CloseCode,
        reason: Data?
    ) {
        Task { @MainActor [weak self] in
            guard let self, self.webSocketTask?.taskIdentifier == webSocketTask.taskIdentifier else { return }
            self.handleDisconnect()
        }
    }
}

struct SyncClientState: Equatable {
    let clientChatVersions: [String: [String: Int]]
    let clientChatIds: [String]
    let clientSuggestionsCount: Int
    let clientEmbedIds: [String]

    static let empty = SyncClientState(
        clientChatVersions: [:],
        clientChatIds: [],
        clientSuggestionsCount: 0,
        clientEmbedIds: []
    )
}

private struct ConnectionKey: Equatable {
    let sessionId: String
    let token: String?
}

// MARK: - Parsed inbound message with field accessors

private struct WSInboundParsed: Decodable {
    let type: String
    let data: [String: AnyCodable]?
    let payload: [String: AnyCodable]?

    // Nested fields might be at root level or inside data
    private let rootFields: [String: AnyCodable]?

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        type = try container.decode(String.self, forKey: .type)
        data = try container.decodeIfPresent([String: AnyCodable].self, forKey: .data)
        payload = try container.decodeIfPresent([String: AnyCodable].self, forKey: .payload)

        // Capture all fields at root level for flat message formats
        let allContainer = try decoder.singleValueContainer()
        rootFields = try? allContainer.decode([String: AnyCodable].self)
    }

    private enum CodingKeys: String, CodingKey {
        case type, data, payload
    }

    func stringField(_ key: String) -> String? {
        if let v = data?[key]?.value as? String { return v }
        if let v = payload?[key]?.value as? String { return v }
        if let v = rootFields?[key]?.value as? String { return v }
        return nil
    }

    func intField(_ key: String) -> Int? {
        if let v = data?[key]?.value as? Int { return v }
        if let v = payload?[key]?.value as? Int { return v }
        if let v = rootFields?[key]?.value as? Int { return v }
        return nil
    }

    func boolField(_ key: String) -> Bool? {
        if let v = data?[key]?.value as? Bool { return v }
        if let v = payload?[key]?.value as? Bool { return v }
        if let v = rootFields?[key]?.value as? Bool { return v }
        return nil
    }

    func stringArrayField(_ key: String) -> [String]? {
        if let v = data?[key]?.value as? [String] { return v }
        if let v = data?[key]?.value as? [Any] { return v.compactMap { $0 as? String } }
        if let v = payload?[key]?.value as? [String] { return v }
        if let v = payload?[key]?.value as? [Any] { return v.compactMap { $0 as? String } }
        if let v = rootFields?[key]?.value as? [String] { return v }
        if let v = rootFields?[key]?.value as? [Any] { return v.compactMap { $0 as? String } }
        return nil
    }
}

// MARK: - Outbound message

struct WSOutboundMessage: Encodable {
    let type: String
    let data: [String: AnyCodable]?
    let payload: [String: AnyCodable]?

    init(type: String, data: [String: Any]? = nil, payload: [String: Any]? = nil) {
        self.type = type
        self.data = data?.mapValues { AnyCodable($0) }
        self.payload = payload?.mapValues { AnyCodable($0) }
    }
}

private enum WebSocketError: LocalizedError {
    case notConnected
    case encodingFailed

    var errorDescription: String? {
        switch self {
        case .notConnected:
            return "WebSocket is not connected"
        case .encodingFailed:
            return "Failed to encode WebSocket message"
        }
    }
}

// MARK: - Notifications

extension Notification.Name {
    static let wsMessageReceived = Notification.Name("openmates.wsMessageReceived")
    static let wsSyncEvent = Notification.Name("openmates.wsSyncEvent")
    static let wsEmbedUpdate = Notification.Name("openmates.wsEmbedUpdate")
    static let wsForceLogout = Notification.Name("openmates.wsForceLogout")
    static let wsHistoryRequested = Notification.Name("openmates.wsHistoryRequested")
    static let pendingDeferredSendRequested = Notification.Name("openmates.pendingDeferredSendRequested")
    static let paymentCompleted = Notification.Name("openmates.paymentCompleted")
}
