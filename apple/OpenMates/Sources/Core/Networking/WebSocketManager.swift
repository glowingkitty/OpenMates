// WebSocket connection manager for real-time sync with the backend.
// Routes AI streaming events to StreamingClient, sync events to SyncManager,
// and chat updates to ChatStore. Uses native URLSessionWebSocketTask.

import Foundation

@MainActor
final class WebSocketManager: ObservableObject {
    @Published private(set) var connectionState: ConnectionState = .disconnected

    private var webSocketTask: URLSessionWebSocketTask?
    private var pingTimer: Timer?
    private let session: URLSession
    private let decoder = JSONDecoder()

    enum ConnectionState: Equatable {
        case disconnected
        case connecting
        case connected
        case reconnecting(attempt: Int)
    }

    private var sessionId: String?
    private var maxReconnectAttempts = 10
    private var reconnectDelay: TimeInterval = 1.0

    init() {
        let config = URLSessionConfiguration.default
        config.httpCookieAcceptPolicy = .always
        config.httpShouldSetCookies = true
        config.httpCookieStorage = .shared
        self.session = URLSession(configuration: config)
    }

    func connect(sessionId: String) {
        self.sessionId = sessionId
        connectionState = .connecting

        Task {
            let baseURL = await APIClient.shared.baseURL
            guard var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false) else { return }
            components.scheme = components.scheme == "https" ? "wss" : "ws"
            components.path = "/v1/ws"
            components.queryItems = [URLQueryItem(name: "sessionId", value: sessionId)]

            guard let url = components.url else { return }

            webSocketTask = session.webSocketTask(with: url)
            webSocketTask?.resume()
            connectionState = .connected
            reconnectDelay = 1.0

            startPingTimer()
            receiveMessages()

            // Request initial sync
            try? await send(WSOutboundMessage(type: "phased_sync_request", data: ["phase": "all"]))
        }
    }

    func disconnect() {
        pingTimer?.invalidate()
        pingTimer = nil
        webSocketTask?.cancel(with: .normalClosure, reason: nil)
        webSocketTask = nil
        connectionState = .disconnected
    }

    func send(_ message: WSOutboundMessage) async throws {
        let data = try JSONEncoder().encode(message)
        try await webSocketTask?.send(.data(data))
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
                encryptedTitle: msg.stringField("encrypted_title"),
                encryptedIcon: msg.stringField("encrypted_icon"),
                encryptedCategory: msg.stringField("encrypted_category"),
                encryptedChatKey: msg.stringField("encrypted_chat_key")
            )
            Task {
                await StreamingClient.shared.dispatch(
                    .typingStarted(chatId: chatId, messageId: messageId, metadata: metadata),
                    for: chatId
                )
            }

        case "ai_message_update":
            let chatId = msg.stringField("chat_id") ?? ""
            let messageId = msg.stringField("message_id") ?? ""
            let sequence = msg.intField("sequence") ?? 0
            let content = msg.stringField("full_content_so_far") ?? ""
            let isFinal = msg.boolField("is_final_chunk") ?? false
            Task {
                await StreamingClient.shared.dispatch(
                    .chunk(chatId: chatId, messageId: messageId, sequence: sequence, content: content, isFinal: isFinal),
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

        // Chat updates
        case "chat_message_added", "chat_update", "new_message", "message_update":
            NotificationCenter.default.post(
                name: .wsMessageReceived, object: nil,
                userInfo: ["type": msg.type, "raw": raw]
            )

        // Sync phases
        case "phase_1_last_chat_ready", "phase_1b_chat_content_ready",
             "phase_2_last_20_chats_ready", "phase_3_last_100_chats_ready",
             "background_message_sync", "sync_metadata_chats_response",
             "phased_sync_complete":
            NotificationCenter.default.post(
                name: .wsSyncEvent, object: nil,
                userInfo: ["type": msg.type, "raw": raw]
            )

        // Embed updates
        case "embed_updated", "embed_status_changed":
            NotificationCenter.default.post(
                name: .wsEmbedUpdate, object: nil,
                userInfo: ["type": msg.type, "raw": raw]
            )

        // Payment
        case "payment_completed":
            NotificationCenter.default.post(name: .paymentCompleted, object: nil)

        default:
            print("[WS] Unhandled: \(msg.type)")
        }
    }

    // MARK: - Ping timer

    private func startPingTimer() {
        pingTimer?.invalidate()
        pingTimer = Timer.scheduledTimer(withTimeInterval: 25, repeats: true) { [weak self] _ in
            self?.webSocketTask?.sendPing { error in
                if let error {
                    print("[WS] Ping error: \(error.localizedDescription)")
                }
            }
        }
    }

    // MARK: - Reconnect

    private func handleDisconnect() {
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
                connect(sessionId: sessionId)
            }
        }
    }
}

// MARK: - Parsed inbound message with field accessors

private struct WSInboundParsed: Decodable {
    let type: String
    let data: [String: AnyCodable]?

    // Nested fields might be at root level or inside data
    private let rootFields: [String: AnyCodable]?

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        type = try container.decode(String.self, forKey: .type)
        data = try container.decodeIfPresent([String: AnyCodable].self, forKey: .data)

        // Capture all fields at root level for flat message formats
        let allContainer = try decoder.singleValueContainer()
        rootFields = try? allContainer.decode([String: AnyCodable].self)
    }

    private enum CodingKeys: String, CodingKey {
        case type, data
    }

    func stringField(_ key: String) -> String? {
        if let v = data?[key]?.value as? String { return v }
        if let v = rootFields?[key]?.value as? String { return v }
        return nil
    }

    func intField(_ key: String) -> Int? {
        if let v = data?[key]?.value as? Int { return v }
        if let v = rootFields?[key]?.value as? Int { return v }
        return nil
    }

    func boolField(_ key: String) -> Bool? {
        if let v = data?[key]?.value as? Bool { return v }
        if let v = rootFields?[key]?.value as? Bool { return v }
        return nil
    }
}

// MARK: - Outbound message

struct WSOutboundMessage: Encodable {
    let type: String
    let data: [String: String]?
}

// MARK: - Notifications

extension Notification.Name {
    static let wsMessageReceived = Notification.Name("openmates.wsMessageReceived")
    static let wsSyncEvent = Notification.Name("openmates.wsSyncEvent")
    static let wsEmbedUpdate = Notification.Name("openmates.wsEmbedUpdate")
    static let paymentCompleted = Notification.Name("openmates.paymentCompleted")
}
