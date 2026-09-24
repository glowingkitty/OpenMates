// WebSocket connection manager for real-time sync with the backend.
// Routes AI streaming events to StreamingClient, sync events to SyncManager,
// and chat updates to ChatStore. Uses native URLSessionWebSocketTask.
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.persistence.client-encrypted, chats.streaming.progressive-presentation, chats.rendering.assistant-document-convergence, chats.rendering.inline-entity-interaction

import CryptoKit
import Foundation

@MainActor
final class WebSocketManager: NSObject, ObservableObject, URLSessionWebSocketDelegate {
    @Published private(set) var connectionState: ConnectionState = .disconnected

    private var webSocketTask: URLSessionWebSocketTask?
    private var pingTimer: Timer?
    private let decoder = JSONDecoder()
    private var connectTask: Task<Void, Never>?
    private var connectionGeneration = 0
    private var activeConnectionKey: ConnectionKey?
    private var didOpenCurrentSocket = false
    private var messageWaiters: [UUID: MessageWaiter] = [:]
    private let streamEventDispatcher = OrderedStreamEventDispatcher()
    private(set) var recoveryCoordinator: ChatCompletionRecoveryCoordinator?
    private var embedStreamCoordinator: ChatEmbedStreamCoordinator?
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
    private var activeSyncState: SyncClientState = .empty
    private var syncStateProvider: (() -> SyncClientState)?
    private var shouldReconnect = false
    private var maxReconnectAttempts = 10
    private var reconnectDelay: TimeInterval = 1.0

    override init() {
        super.init()
    }

    func configureSyncStateProvider(_ provider: @escaping () -> SyncClientState) {
        syncStateProvider = provider
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

        rejectAllWaiters()
        connectionGeneration += 1
        streamEventDispatcher.reset()
        embedStreamCoordinator?.reset()
        let generation = connectionGeneration
        connectTask?.cancel()
        pingTimer?.invalidate()
        pingTimer = nil
        webSocketTask?.cancel(with: .goingAway, reason: nil)
        webSocketTask = nil
        didOpenCurrentSocket = false

        self.sessionId = sessionId
        self.authToken = token
        self.activeSyncState = syncState
        activeConnectionKey = nextKey
        shouldReconnect = true
        connectionState = .connecting

        connectTask = Task { [weak self] in
            guard let self else { return }
            let baseURL = await APIClient.shared.baseURL
            let origin = await APIClient.shared.webAppURL.absoluteString
            guard Self.shouldContinueConnectionAttempt(
                expectedGeneration: generation,
                currentGeneration: connectionGeneration,
                isCancelled: Task.isCancelled
            ) else { return }
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

            let connectingTask = session.webSocketTask(with: request)
            webSocketTask = connectingTask
            connectingTask.resume()

            guard await waitForOpenSocket(connectingTask, generation: generation),
                  Self.shouldContinueConnectionAttempt(
                      expectedGeneration: generation,
                      currentGeneration: connectionGeneration,
                      isCancelled: Task.isCancelled
                  ) else {
                guard generation == connectionGeneration else { return }
                print("[WS] Connection probe failed before sync request")
                handleDisconnect()
                return
            }

            traceNativeStartupSync("phase=socketOpened")
            connectionState = .connected
            reconnectDelay = 1.0
            startPingTimer()
            receiveMessages(from: connectingTask)
            traceNativeStartupSync("phase=socketRecoveryStart")
            await recoveryCoordinator?.handleTransportConnected()
            traceNativeStartupSync("phase=socketRecoveryReturned")
            let currentSyncState = syncStateProvider?() ?? activeSyncState
            activeSyncState = currentSyncState
            traceNativeStartupSync("phase=phasedSyncSendStart")
            do {
                try await requestPhasedSync(syncState: currentSyncState)
                traceNativeStartupSync("phase=phasedSyncSendReturned")
            } catch {
                traceNativeStartupSync("phase=phasedSyncSendFailed errorType=\(type(of: error))")
            }
        }
    }

    func disconnect() {
        rejectAllWaiters()
        connectionGeneration += 1
        streamEventDispatcher.reset()
        embedStreamCoordinator?.reset()
        // A waiter belongs to the socket/session that sent its request. Resume
        // it before a different account can establish a replacement connection.
        let disconnectedWaiters = Array(messageWaiters.values)
        messageWaiters.removeAll()
        for waiter in disconnectedWaiters {
            waiter.continuation.resume(throwing: WebSocketError.notConnected)
        }
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

    func configureRecoveryCoordinator(_ coordinator: ChatCompletionRecoveryCoordinator) {
        recoveryCoordinator = coordinator
    }

    func configureEmbedStreamCoordinator(_ coordinator: ChatEmbedStreamCoordinator) {
        embedStreamCoordinator = coordinator
    }

    func waitForMessage(
        _ type: String,
        timeout: Duration = .seconds(20),
        matching predicate: @escaping ([String: Any]) -> Bool
    ) async throws -> WebSocketResponse {
        let waiterId = UUID()
        return try await withCheckedThrowingContinuation { continuation in
            messageWaiters[waiterId] = MessageWaiter(types: [type], predicate: predicate, continuation: continuation)
            Task { @MainActor [weak self] in
                try? await Task.sleep(for: timeout)
                guard let waiter = self?.messageWaiters.removeValue(forKey: waiterId) else { return }
                waiter.continuation.resume(throwing: WebSocketError.messageTimeout)
            }
        }
    }

    func sendAndWait(
        _ message: WSOutboundMessage,
        responseType: String,
        timeout: Duration = .seconds(20),
        matching predicate: @escaping ([String: Any]) -> Bool
    ) async throws -> WebSocketResponse {
        try await sendAndWait(message, responseTypes: [responseType], timeout: timeout, matching: predicate)
    }

    var modelPreferenceSocketGeneration: Int { connectionGeneration }
    var modelPreferenceInbound: ((String, [String: Any], Int) -> Void)?

    func sendAndWait(
        _ message: WSOutboundMessage,
        responseTypes: Set<String>,
        timeout: Duration = .seconds(20),
        matching predicate: @escaping ([String: Any]) -> Bool
    ) async throws -> WebSocketResponse {
        guard let boundSocket = webSocketTask else { throw WebSocketError.notConnected }
        let waiterId = UUID()
        let expectedGeneration = connectionGeneration
        return try await withCheckedThrowingContinuation { continuation in
            messageWaiters[waiterId] = MessageWaiter(
                types: responseTypes,
                predicate: predicate,
                continuation: continuation
            )
            Task { @MainActor [weak self] in
                guard let self else { return }
                do {
                    guard messageWaiters[waiterId] != nil,
                          Self.shouldContinueConnectionAttempt(
                            expectedGeneration: expectedGeneration,
                            currentGeneration: connectionGeneration,
                            isCancelled: Task.isCancelled
                          ) else { throw WebSocketError.notConnected }
                    guard webSocketTask === boundSocket else { throw WebSocketError.notConnected }
                    let data = try JSONEncoder().encode(message)
                    guard let json = String(data: data, encoding: .utf8) else { throw WebSocketError.encodingFailed }
                    try await boundSocket.send(.string(json))
                } catch {
                    guard let waiter = messageWaiters.removeValue(forKey: waiterId) else { return }
                    waiter.continuation.resume(throwing: error)
                }
            }
            Task { @MainActor [weak self] in
                try? await Task.sleep(for: timeout)
                guard let waiter = self?.messageWaiters.removeValue(forKey: waiterId) else { return }
                waiter.continuation.resume(throwing: WebSocketError.messageTimeout)
            }
        }
    }

    var isConnected: Bool {
        connectionState == .connected
    }

    /// Captured by durable sends to keep their plaintext commit bound to the
    /// same authenticated transport across preflight suspension points.
    var transportGeneration: Int { connectionGeneration }

    func sendDraftSyncMessage(_ message: DraftSyncMessage) async throws {
        try await send(WSOutboundMessage(type: message.type, payload: message.payload))
    }

    func requestPhasedSync(
        clientChatVersions: [String: [String: Int]] = [:],
        clientChatIds: [String] = [],
        clientSuggestionsCount: Int = 0,
        clientEmbedIds: [String] = []
    ) async throws {
        try await send(Self.phasedSyncMessage(
            clientChatVersions: clientChatVersions, clientChatIds: clientChatIds,
            clientSuggestionsCount: clientSuggestionsCount, clientEmbedIds: clientEmbedIds
        ))
    }

    static func phasedSyncMessage(
        clientChatVersions: [String: [String: Int]] = [:],
        clientChatIds: [String] = [],
        clientSuggestionsCount: Int = 0,
        clientEmbedIds: [String] = []
    ) -> WSOutboundMessage {
        WSOutboundMessage(
            type: "phased_sync_request",
            payload: [
                "phase": "all",
                // Apple currently uses personal scope. The server requires an
                // explicit epoch even when no team has been selected.
                "context_epoch": 0,
                "client_chat_versions": clientChatVersions,
                "client_chat_ids": clientChatIds,
                "client_suggestions_count": clientSuggestionsCount,
                "client_embed_ids": clientEmbedIds
            ]
        )
    }

    func requestPhasedSync(syncState: SyncClientState) async throws {
        try await requestPhasedSync(
            clientChatVersions: syncState.clientChatVersions,
            clientChatIds: syncState.clientChatIds,
            clientSuggestionsCount: syncState.clientSuggestionsCount,
            clientEmbedIds: syncState.clientEmbedIds
        )
    }

    func requestChatContentBatch(chatId: String) async throws -> WebSocketResponse {
        try await sendAndWait(
            WSOutboundMessage(
                type: "request_chat_content_batch",
                payload: ["chat_ids": [chatId]]
            ),
            responseType: "chat_content_batch_response",
            timeout: .seconds(20)
        ) { fields in
            guard let messages = fields["messages_by_chat_id"] as? [String: Any] else { return false }
            return messages[chatId] != nil
        }
    }

    private func waitForOpenSocket(
        _ connectingTask: URLSessionWebSocketTask,
        generation: Int
    ) async -> Bool {
        for _ in 0..<30 {
            guard Self.shouldContinueConnectionAttempt(
                expectedGeneration: generation,
                currentGeneration: connectionGeneration,
                isCancelled: Task.isCancelled
            ) else { return false }
            if didOpenCurrentSocket { return true }
            try? await Task.sleep(for: .milliseconds(100))
        }
        return await withCheckedContinuation { continuation in
            connectingTask.sendPing { error in
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

    private func receiveMessages(from receivingTask: URLSessionWebSocketTask?) {
        receivingTask?.receive { [weak self, weak receivingTask] result in
            Task { @MainActor in
                guard let self, let receivingTask,
                      Self.isCurrentSocket(
                          callbackTaskIdentifier: receivingTask.taskIdentifier,
                          currentTaskIdentifier: self.webSocketTask?.taskIdentifier
                      ) else { return }
                switch result {
                case .success(let message):
                    self.handleRawMessage(message)
                    self.receiveMessages(from: receivingTask)
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
        AssistantSpeechAppRuntime.shared.receive(type: msg.type, fields: msg.fields, from: self)
        if msg.type == "error" {
            rejectWaiters(with: msg.fields)
        }
        resolveWaiters(type: msg.type, payload: msg.fields)
        if ["chat_model_preference", "chat_model_preference_updated", "chat_model_preference_synced"].contains(msg.type) {
            modelPreferenceInbound?(msg.type, msg.fields, connectionGeneration)
        }
        switch msg.type {
        // Keepalive
        case "pong":
            break

        // AI streaming — route to StreamingClient
        case "ai_task_initiated":
            let chatId = msg.stringField("chat_id") ?? ""
            let taskId = msg.stringField("ai_task_id") ?? msg.stringField("task_id") ?? ""
            let userMsgId = msg.stringField("user_message_id") ?? ""
            streamEventDispatcher.enqueue(
                .taskInitiated(chatId: chatId, taskId: taskId, userMessageId: userMsgId),
                for: chatId
            )
            embedStreamCoordinator?.beginTurn(chatId: chatId)

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
            streamEventDispatcher.enqueue(
                .typingStarted(chatId: chatId, messageId: messageId, metadata: metadata),
                for: chatId
            )
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
            recoveryCoordinator?.handleTerminalStream(msg.fields)
            streamEventDispatcher.enqueue(
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
            if !content.isEmpty {
                Task { [weak self] in
                    await self?.embedStreamCoordinator?.processStreamContent(content, chatId: chatId)
                }
            }

        case "thinking_chunk":
            let chatId = msg.stringField("chat_id") ?? ""
            let messageId = msg.stringField("message_id") ?? ""
            let content = msg.stringField("content") ?? ""
            streamEventDispatcher.enqueue(
                .thinkingChunk(chatId: chatId, messageId: messageId, content: content),
                for: chatId
            )

        case "thinking_complete":
            let chatId = msg.stringField("chat_id") ?? ""
            let messageId = msg.stringField("message_id") ?? ""
            streamEventDispatcher.enqueue(
                .thinkingComplete(chatId: chatId, messageId: messageId),
                for: chatId
            )

        case "ai_message_ready":
            let chatId = msg.stringField("chat_id") ?? ""
            let messageId = msg.stringField("message_id") ?? ""
            streamEventDispatcher.enqueue(
                .messageReady(chatId: chatId, messageId: messageId),
                for: chatId
            )

        case "awaiting_user_input":
            let chatId = msg.stringField("chat_id") ?? ""
            let messageId = msg.stringField("message_id") ?? msg.stringField("task_id") ?? ""
            let question = msg.stringField("question") ?? ""
            guard !chatId.isEmpty, !messageId.isEmpty, !question.isEmpty else { break }
            streamEventDispatcher.enqueue(
                .chunk(
                    chatId: chatId,
                    messageId: messageId,
                    sequence: 0,
                    content: question,
                    isFinal: true,
                    userMessageId: msg.stringField("user_message_id"),
                    category: nil,
                    modelName: nil,
                    rejectionReason: nil
                ),
                for: chatId
            )

        case "preprocessing_step":
            guard msg.fields["skipped"] as? Bool != true else { break }
            let chatId = msg.stringField("chat_id") ?? ""
            let step = msg.stringField("step") ?? ""
            streamEventDispatcher.enqueue(
                .preprocessingStep(chatId: chatId, step: step, data: msg.fields["data"] as? [String: Any]),
                for: chatId
            )

        case "ai_typing_ended":
            let chatId = msg.stringField("chat_id") ?? ""
            let messageId = msg.stringField("message_id")
            streamEventDispatcher.enqueue(
                .typingEnded(chatId: chatId, messageId: messageId),
                for: chatId
            )

        case "message_queued":
            let chatId = msg.stringField("chat_id") ?? ""
            streamEventDispatcher.enqueue(
                .messageQueued(
                    chatId: chatId,
                    taskId: msg.stringField("task_id"),
                    userMessageId: msg.stringField("user_message_id"),
                    message: msg.stringField("message")
                ),
                for: chatId
            )

        case "ai_task_cancel_requested":
            let chatId = msg.stringField("chat_id") ?? ""
            streamEventDispatcher.enqueue(
                .cancelRequested(chatId: chatId, taskId: msg.stringField("task_id")),
                for: chatId
            )

        case "post_processing_completed":
            let chatId = msg.stringField("chat_id") ?? ""
            let taskId = msg.stringField("task_id") ?? ""
            streamEventDispatcher.enqueue(
                .postProcessingCompleted(
                    chatId: chatId,
                    taskId: taskId,
                    followUpSuggestions: msg.stringArrayField("follow_up_request_suggestions") ?? [],
                    newChatSuggestions: msg.stringArrayField("new_chat_request_suggestions") ?? [],
                    chatSummary: msg.stringField("chat_summary"),
                    chatTags: msg.stringArrayField("chat_tags") ?? [],
                    updatedTitle: msg.stringField("updated_chat_title"),
                    sourceTitleVersion: msg.intField("source_title_v"),
                    sourceMetadataVersion: msg.intField("source_metadata_v")
                ),
                for: chatId
            )

        case "request_chat_history":
            NotificationCenter.default.post(
                name: .wsHistoryRequested, object: nil,
                userInfo: ["raw": raw]
            )

        // Chat updates
        case "new_chat_message", "chat_message_added", "chat_message_confirmed",
              "encrypted_chat_metadata", "chat_update", "new_message", "message_update",
              "chat_draft_updated", "draft_update_receipt", "draft_deleted", "draft_delete_receipt",
              "draft_versions_response", "draft_conflict", "chat_details",
              "chat_deleted", "chat_read_status_updated",
              "chat_pinned_updated", "message_deleted", "message_highlight_added",
              "message_highlight_updated", "message_highlight_removed", "draft_embed_deleted",
              "last_opened_updated", "key_delivery_confirmed", "system_message_confirmed",
              "new_system_message", "reminder_fired", "pending_ai_response",
              "ai_response_storage_confirmed",
              "chat_compression_started", "chat_compression_completed",
              "encrypted_metadata_stored", "post_processing_metadata_stored",
              "focus_mode_activated",
              "spawn_sub_chats", "sub_chat_confirmation_required",
              "sub_chat_confirmation_resolved", "sub_chat_progress", "sub_chat_stopped",
              "ai_background_response_completed":
            recoveryCoordinator?.handleTerminalStream(msg.fields)
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
            traceNativeStartupSync("phase=syncEventReceived type=\(msg.type)")
            NotificationCenter.default.post(
                name: .wsSyncEvent, object: nil,
                userInfo: ["type": msg.type, "raw": raw]
            )

        // Embed updates
        case "send_embed_data":
            guard let embedStreamCoordinator else {
                NotificationCenter.default.post(
                    name: .wsEmbedUpdate, object: nil,
                    userInfo: ["type": msg.type, "raw": raw]
                )
                break
            }
            let embedConnectionGeneration = connectionGeneration
            let embedAccountScope = OfflineStore.shared.scopeGeneration
            Task { [weak self] in
                guard let self,
                      self.connectionGeneration == embedConnectionGeneration,
                      OfflineStore.shared.scopeGeneration == embedAccountScope else { return }
                await embedStreamCoordinator.handleEmbedData(msg.fields)
                guard self.connectionGeneration == embedConnectionGeneration,
                      OfflineStore.shared.scopeGeneration == embedAccountScope else { return }
                NotificationCenter.default.post(
                    name: .wsEmbedUpdate, object: nil,
                    userInfo: ["type": msg.type, "raw": raw]
                )
            }

        case "embed_update", "embed_updated", "embed_status_changed":
            NotificationCenter.default.post(
                name: .wsEmbedUpdate, object: nil,
                userInfo: ["type": msg.type, "raw": raw]
            )

        // Payment
        case "payment_completed":
            NotificationCenter.default.post(name: .paymentCompleted, object: nil)

        case "native_client_lifecycle_ack":
            break

        case "recovery_jobs_available":
            Task { await recoveryCoordinator?.handleAvailableJobs(msg.fields) }

        case "chat_turn_preflight_ack", "recovery_job_claimed", "recovery_job_persisted":
            break

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

    private func rejectAllWaiters() {
        let pending = Array(messageWaiters.values)
        messageWaiters.removeAll()
        for waiter in pending { waiter.continuation.resume(throwing: WebSocketError.notConnected) }
    }

    private func resolveWaiters(type: String, payload: [String: Any]) {
        let matches = messageWaiters.filter { _, waiter in
            waiter.types.contains(type) && waiter.predicate(payload)
        }
        for (id, waiter) in matches {
            messageWaiters.removeValue(forKey: id)
            waiter.continuation.resume(returning: WebSocketResponse(fields: payload, type: type))
        }
    }

    private func rejectWaiters(with payload: [String: Any]) {
        let code = payload["code"] as? String ?? "server_error"
        let matchingWaiters = messageWaiters.filter { _, waiter in waiter.predicate(payload) }
        for id in matchingWaiters.keys {
            messageWaiters.removeValue(forKey: id)
        }
        for waiter in matchingWaiters.values {
            waiter.continuation.resume(throwing: WebSocketError.remote(code: code))
        }
    }

    func ownsRecoveryPersistence(messageId: String) -> Bool {
        recoveryCoordinator?.ownsRecoveryPersistence(messageId: messageId) ?? false
    }

    func markRecoveryInitialSyncReady() async {
        await recoveryCoordinator?.markInitialSyncReady()
    }

    func handleRecoveryChatKeyAvailabilityChanged() async {
        await recoveryCoordinator?.handleChatKeyAvailabilityChanged()
    }

    // MARK: - Ping timer

    private func startPingTimer() {
        pingTimer?.invalidate()
        pingTimer = Timer.scheduledTimer(withTimeInterval: 25, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self, let pingTask = self.webSocketTask else { return }
                let taskIdentifier = pingTask.taskIdentifier
                pingTask.sendPing { error in
                    if let error {
                        print("[WS] Ping error: \(error.localizedDescription)")
                        Task { @MainActor [weak self] in
                            guard let self,
                                  Self.isCurrentSocket(
                                      callbackTaskIdentifier: taskIdentifier,
                                      currentTaskIdentifier: self.webSocketTask?.taskIdentifier
                                  ) else { return }
                            self.handleDisconnect()
                        }
                    }
                }
            }
        }
    }

    // MARK: - Reconnect

    private func handleDisconnect() {
        rejectAllWaiters()
        connectionGeneration += 1
        streamEventDispatcher.reset()
        embedStreamCoordinator?.reset()
        let reconnectGeneration = connectionGeneration
        pingTimer?.invalidate()
        pingTimer = nil
        webSocketTask = nil
        recoveryCoordinator?.handleTransportDisconnected()
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

        let delay = reconnectDelay
        Task { [weak self] in
            try? await Task.sleep(for: .seconds(delay))
            guard let self,
                  Self.shouldContinueConnectionAttempt(
                      expectedGeneration: reconnectGeneration,
                      currentGeneration: connectionGeneration,
                      isCancelled: Task.isCancelled
                  ), shouldReconnect else { return }
            reconnectDelay = min(reconnectDelay * 2, 30)
            if let sessionId {
                connect(sessionId: sessionId, token: authToken, syncState: activeSyncState)
            }
        }
    }

    static func isCurrentSocket(
        callbackTaskIdentifier: Int,
        currentTaskIdentifier: Int?
    ) -> Bool {
        guard let currentTaskIdentifier else { return false }
        return callbackTaskIdentifier == currentTaskIdentifier
    }

    static func shouldContinueConnectionAttempt(
        expectedGeneration: Int,
        currentGeneration: Int,
        isCancelled: Bool
    ) -> Bool {
        !isCancelled && expectedGeneration == currentGeneration
    }

    nonisolated func urlSession(
        _ session: URLSession,
        webSocketTask: URLSessionWebSocketTask,
        didOpenWithProtocol protocol: String?
    ) {
        Task { @MainActor [weak self] in
            guard let self, Self.isCurrentSocket(
                callbackTaskIdentifier: webSocketTask.taskIdentifier,
                currentTaskIdentifier: self.webSocketTask?.taskIdentifier
            ) else { return }
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
            guard let self, Self.isCurrentSocket(
                callbackTaskIdentifier: webSocketTask.taskIdentifier,
                currentTaskIdentifier: self.webSocketTask?.taskIdentifier
            ) else { return }
            self.handleDisconnect()
        }
    }
}

/// Mirrors the web client's live embed work below the UI. It discovers embed
/// references in cumulative assistant chunks and client-encrypts finalized
/// `send_embed_data` payloads before any durable local write.
@MainActor
final class ChatEmbedStreamCoordinator {
    private let transport: ChatWebSocketTransport
    private let chatStore: ChatStore
    private let authenticatedOwnerId: () async -> String?
    private let masterKey: (String) async -> SymmetricKey?
    private let chatKey: (String) -> SymmetricKey?
    private let persistEmbedKeys: ([EmbedKeyRecord]) -> Void
    private let accountScopeGeneration: () -> UUID
    private let retryDelay: (Int) -> Duration
    private var generation = UUID()
    private var requestedEmbedIdsByChat: [String: Set<String>] = [:]
    private var processedPayloadKeys = Set<String>()
    private var inFlightPayloadKeys = Set<String>()
    private var pendingRetries: [String: PendingRetry] = [:]
    private var retryTasks: [String: Task<Void, Never>] = [:]

    init(
        transport: ChatWebSocketTransport,
        chatStore: ChatStore,
        authenticatedOwnerId: @escaping () async -> String?,
        masterKey: @escaping (String) async -> SymmetricKey?,
        chatKey: @escaping (String) -> SymmetricKey?,
        persistEmbedKeys: @escaping ([EmbedKeyRecord]) -> Void,
        accountScopeGeneration: @escaping () -> UUID = { OfflineStore.shared.scopeGeneration },
        retryDelay: @escaping (Int) -> Duration = { attempt in
            switch attempt {
            case 1: return .milliseconds(350)
            case 2: return .seconds(1)
            default: return .seconds(3)
            }
        }
    ) {
        self.transport = transport
        self.chatStore = chatStore
        self.authenticatedOwnerId = authenticatedOwnerId
        self.masterKey = masterKey
        self.chatKey = chatKey
        self.persistEmbedKeys = persistEmbedKeys
        self.accountScopeGeneration = accountScopeGeneration
        self.retryDelay = retryDelay
    }

    convenience init(transport: ChatWebSocketTransport, chatStore: ChatStore) {
        self.init(
            transport: transport,
            chatStore: chatStore,
            authenticatedOwnerId: { await AuthManager.currentUserId() },
            masterKey: { ownerId in try? await CryptoManager.shared.loadMasterKey(for: ownerId) },
            chatKey: { ChatKeyManager.shared.key(for: $0) },
            persistEmbedKeys: { entries in
                EmbedKeyManager.shared.store(entries, source: "liveEmbedStream")
                OfflineStore.shared.persistEmbedKeys(entries)
            }
        )
    }

    func reset() {
        generation = UUID()
        retryTasks.values.forEach { $0.cancel() }
        retryTasks.removeAll()
        pendingRetries.removeAll()
        requestedEmbedIdsByChat.removeAll()
        processedPayloadKeys.removeAll()
        inFlightPayloadKeys.removeAll()
    }

    func beginTurn(chatId: String) {
        requestedEmbedIdsByChat[chatId] = []
    }

    func processStreamContent(_ content: String, chatId: String) async {
        let expectedGeneration = generation
        let expectedScope = accountScopeGeneration()
        await requestEmbeds(
            Self.embedReferences(in: content),
            chatId: chatId,
            expectedGeneration: expectedGeneration,
            expectedScope: expectedScope
        )
    }

    func handleEmbedData(_ fields: [String: Any]) async {
        let expectedGeneration = generation
        let expectedScope = accountScopeGeneration()
        guard let embedId = fields["embed_id"] as? String, !embedId.isEmpty else { return }
        let version = fields["version_number"] as? Int
        let payloadKey = version.map { "\(embedId):v\($0)" } ?? embedId
        let status = EmbedStatus(rawValue: fields["status"] as? String ?? "") ?? .finished
        let inFlightKey = "\(payloadKey):\(status.rawValue)"
        guard !processedPayloadKeys.contains(payloadKey), inFlightPayloadKeys.insert(inFlightKey).inserted else { return }
        defer { inFlightPayloadKeys.remove(inFlightKey) }

        let childIds = Self.stringArray(fields["embed_ids"] ?? fields["child_embed_ids"])
        if let chatId = resolveChatId(fields["chat_id"] as? String) {
            await requestEmbeds(
                childIds,
                chatId: chatId,
                expectedGeneration: expectedGeneration,
                expectedScope: expectedScope
            )
        }
        guard isCurrent(expectedGeneration, expectedScope) else { return }

        do {
            if status == .processing {
                guard !processedPayloadKeys.contains(payloadKey),
                      !inFlightPayloadKeys.contains("\(payloadKey):\(EmbedStatus.finished.rawValue)") else { return }
                try storeProcessingEmbed(
                    fields,
                    embedId: embedId,
                    expectedGeneration: expectedGeneration,
                    expectedScope: expectedScope
                )
                return
            }
            if status == .error || status == .cancelled {
                return
            }
            if fields["already_encrypted"] as? Bool == true {
                try storeAlreadyEncrypted(
                    fields,
                    embedId: embedId,
                    expectedGeneration: expectedGeneration,
                    expectedScope: expectedScope
                )
            } else {
                try await encryptAndPersist(
                    fields,
                    embedId: embedId,
                    expectedGeneration: expectedGeneration,
                    expectedScope: expectedScope
                )
            }
            guard isCurrent(expectedGeneration, expectedScope) else { return }
            cancelRetry(payloadKey)
            processedPayloadKeys.insert(payloadKey)
            NativeDiagnostics.event("live_embed_persisted", category: "chat_stream", counts: ["children": childIds.count])
        } catch {
            if let chatId = resolveChatId(fields["chat_id"] as? String),
               isCurrent(expectedGeneration, expectedScope) {
                scheduleRetry(
                    payloadKey: payloadKey,
                    embedId: embedId,
                    chatId: chatId,
                    expectedGeneration: expectedGeneration,
                    expectedScope: expectedScope
                )
            }
            NativeDiagnostics.failure("live_embed_persistence_failed", category: "chat_stream", level: .warning, error: error)
        }
    }

    /// Processing payloads are intentionally volatile plaintext. They let the
    /// current chat render the card while the skill runs, but never cross the
    /// persistence boundary before the finalized payload has been encrypted.
    private func storeProcessingEmbed(
        _ fields: [String: Any],
        embedId: String,
        expectedGeneration: UUID,
        expectedScope: UUID
    ) throws {
        guard isCurrent(expectedGeneration, expectedScope) else { throw LiveEmbedError.staleContext }
        guard let rawChatId = resolveChatId(fields["chat_id"] as? String),
              let content = fields["content"] as? String,
              let type = fields["type"] as? String else {
            throw LiveEmbedError.missingEncryptionContext
        }
        let parsed = EmbedRecord.parseContent(content)
        let appId = fields["app_id"] as? String ?? parsed["app_id"] as? String
        let skillId = fields["skill_id"] as? String ?? parsed["skill_id"] as? String
        let childIds = Self.stringArray(fields["embed_ids"] ?? fields["child_embed_ids"])
        let base = EmbedRecord(
            id: embedId,
            type: Self.displayType(type: type, appId: appId, skillId: skillId),
            status: .processing,
            data: nil,
            parentEmbedId: fields["parent_embed_id"] as? String,
            appId: appId,
            skillId: skillId,
            embedIds: childIds.isEmpty ? nil : childIds.joined(separator: "|"),
            versionNumber: fields["version_number"] as? Int,
            contentHash: fields["content_hash"] as? String,
            createdAt: String(Self.timestamp(fields["createdAt"] ?? fields["created_at"]))
        )
        let record = base.decryptedCopy(content: content, type: type)
        guard isCurrent(expectedGeneration, expectedScope) else { throw LiveEmbedError.staleContext }
        chatStore.performWithoutPersistence {
            chatStore.upsertEmbeds([record], for: rawChatId)
        }
    }

    static func embedReferences(in content: String) -> [String] {
        var ordered: [String] = []
        var seen = Set<String>()
        func append(_ value: String) {
            let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmed.isEmpty, seen.insert(trimmed).inserted { ordered.append(trimmed) }
        }

        let range = NSRange(content.startIndex..., in: content)
        // Stream chunk boundaries can join the closing fence directly to the
        // final JSON byte even when the completed markdown later gains a line
        // break. Require a real closing fence, then let JSON decoding reject
        // incomplete or non-embed blocks.
        if let expression = try? NSRegularExpression(
            pattern: #"```(?:json|json_embed)[ \t]*\r?\n([\s\S]*?)(?:\r?\n)?[ \t]*```"#
        ) {
            for match in expression.matches(in: content, range: range) {
                guard let bodyRange = Range(match.range(at: 1), in: content),
                      let data = String(content[bodyRange]).data(using: .utf8),
                      let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      object["type"] != nil,
                      let embedId = object["embed_id"] as? String else { continue }
                append(embedId)
                Self.stringArray(object["embed_ids"] ?? object["child_embed_ids"]).forEach(append)
            }
        }
        if let expression = try? NSRegularExpression(pattern: #"\[[^\]]*\]\(embed:([^\)]+)\)|\[\[embed(?:ref)?:([^\]]+)\]\]"#) {
            for match in expression.matches(in: content, range: range) {
                for capture in 1..<match.numberOfRanges where match.range(at: capture).location != NSNotFound {
                    if let idRange = Range(match.range(at: capture), in: content) { append(String(content[idRange])) }
                }
            }
        }
        return ordered
    }

    private func requestEmbeds(
        _ embedIds: [String],
        chatId: String,
        expectedGeneration: UUID,
        expectedScope: UUID
    ) async {
        for embedId in embedIds where !embedId.isEmpty {
            guard isCurrent(expectedGeneration, expectedScope) else { return }
            guard requestedEmbedIdsByChat[chatId, default: []].insert(embedId).inserted else { continue }
            do {
                try await transport.send(WSOutboundMessage(type: "request_embed", payload: ["embed_id": embedId]))
                guard isCurrent(expectedGeneration, expectedScope) else { return }
            } catch {
                guard isCurrent(expectedGeneration, expectedScope) else { return }
                requestedEmbedIdsByChat[chatId]?.remove(embedId)
                NativeDiagnostics.failure("live_embed_request_failed", category: "chat_stream", level: .warning, error: error)
            }
        }
    }

    private func encryptAndPersist(
        _ fields: [String: Any],
        embedId: String,
        expectedGeneration: UUID,
        expectedScope: UUID
    ) async throws {
        guard isCurrent(expectedGeneration, expectedScope) else { throw LiveEmbedError.staleContext }
        guard let rawChatId = resolveChatId(fields["chat_id"] as? String),
              let rawMessageId = fields["message_id"] as? String,
              let content = fields["content"] as? String,
              let type = fields["type"] as? String,
              let ownerId = await authenticatedOwnerId(),
              let chatKey = chatKey(rawChatId) else {
            throw LiveEmbedError.missingEncryptionContext
        }
        guard isCurrent(expectedGeneration, expectedScope) else { throw LiveEmbedError.staleContext }

        let parentEmbedId = fields["parent_embed_id"] as? String
        let keyOwnerId = parentEmbedId?.isEmpty == false ? parentEmbedId! : embedId
        let embedKey = ComposerEmbedCrypto.deriveKey(chatKey: chatKey, embedId: keyOwnerId)
        let encryptedContent = try ComposerEmbedCrypto.encryptContent(content, using: embedKey)
        let encryptedType = try ComposerEmbedCrypto.encryptContent(type, using: embedKey)
        let encryptedTextPreview = try (fields["text_preview"] as? String).map {
            try ComposerEmbedCrypto.encryptContent($0, using: embedKey)
        }
        let hashedChatId = Self.sha256Hex(rawChatId)
        let hashedMessageId = Self.sha256Hex(rawMessageId)
        let hashedOwnerId = Self.sha256Hex(ownerId)
        let childIds = Self.stringArray(fields["embed_ids"] ?? fields["child_embed_ids"])
        let createdAt = Self.timestamp(fields["createdAt"] ?? fields["created_at"])
        let updatedAt = Self.timestamp(fields["updatedAt"] ?? fields["updated_at"])
        let status = EmbedStatus(rawValue: fields["status"] as? String ?? "") ?? .finished
        let parsed = EmbedRecord.parseContent(content)
        let appId = fields["app_id"] as? String ?? parsed["app_id"] as? String
        let skillId = fields["skill_id"] as? String ?? parsed["skill_id"] as? String

        var keyRecords: [EmbedKeyRecord] = []
        if parentEmbedId?.isEmpty != false {
            guard let masterKey = await masterKey(ownerId) else {
                throw LiveEmbedError.missingEncryptionContext
            }
            guard isCurrent(expectedGeneration, expectedScope) else { throw LiveEmbedError.staleContext }
            let hashedEmbedId = Self.sha256Hex(embedId)
            keyRecords = [
                EmbedKeyRecord(
                    hashedEmbedId: hashedEmbedId,
                    keyType: "master",
                    hashedChatId: nil,
                    encryptedEmbedKey: try ComposerEmbedCrypto.wrapKey(embedKey, using: masterKey)
                ),
                EmbedKeyRecord(
                    hashedEmbedId: hashedEmbedId,
                    keyType: "chat",
                    hashedChatId: hashedChatId,
                    encryptedEmbedKey: try ComposerEmbedCrypto.wrapKey(embedKey, using: chatKey)
                ),
            ]
            guard isCurrent(expectedGeneration, expectedScope) else { throw LiveEmbedError.staleContext }
            persistEmbedKeys(keyRecords)
        }

        let record = EmbedRecord(
            id: embedId,
            type: Self.displayType(type: type, appId: appId, skillId: skillId),
            status: status,
            data: nil,
            encryptedContent: encryptedContent,
            encryptedType: encryptedType,
            encryptedTextPreview: encryptedTextPreview,
            parentEmbedId: parentEmbedId,
            appId: appId,
            skillId: skillId,
            embedIds: childIds.isEmpty ? nil : childIds.joined(separator: "|"),
            hashedChatId: hashedChatId,
            hashedMessageId: hashedMessageId,
            hashedUserId: hashedOwnerId,
            versionNumber: fields["version_number"] as? Int,
            contentHash: fields["content_hash"] as? String,
            createdAt: String(createdAt)
        )
        guard isCurrent(expectedGeneration, expectedScope) else { throw LiveEmbedError.staleContext }
        chatStore.upsertEmbeds([record], for: rawChatId)

        if !keyRecords.isEmpty {
            let requestId = UUID().uuidString
            let keyPayloads: [[String: Any]] = keyRecords.map { key in
                [
                    "hashed_embed_id": key.hashedEmbedId,
                    "key_type": key.keyType,
                    "hashed_chat_id": key.hashedChatId.map { $0 as Any } ?? NSNull(),
                    "encrypted_embed_key": key.encryptedEmbedKey,
                    "hashed_user_id": hashedOwnerId,
                    "created_at": createdAt,
                ]
            }
            _ = try await transport.sendAndWait(
                WSOutboundMessage(type: "store_embed_keys", payload: [
                    "request_id": requestId,
                    "keys": keyPayloads,
                ]),
                responseType: "store_embed_keys_confirmed"
            ) { $0["request_id"] as? String == requestId }
            guard isCurrent(expectedGeneration, expectedScope) else { throw LiveEmbedError.staleContext }
        }

        guard isCurrent(expectedGeneration, expectedScope) else { throw LiveEmbedError.staleContext }
        let requestId = UUID().uuidString
        var storePayload: [String: Any] = [
            "request_id": requestId,
            "embed_id": embedId,
            "encrypted_type": encryptedType,
            "encrypted_content": encryptedContent,
            "status": status.rawValue,
            "hashed_chat_id": hashedChatId,
            "hashed_message_id": hashedMessageId,
            "hashed_user_id": hashedOwnerId,
            "embed_ids": childIds,
            "is_private": fields["is_private"] as? Bool ?? false,
            "is_shared": fields["is_shared"] as? Bool ?? false,
            "created_at": createdAt,
            "updated_at": updatedAt,
        ]
        if let encryptedTextPreview { storePayload["encrypted_text_preview"] = encryptedTextPreview }
        if let parentEmbedId { storePayload["parent_embed_id"] = parentEmbedId }
        if let taskId = fields["task_id"] as? String { storePayload["hashed_task_id"] = Self.sha256Hex(taskId) }
        for key in ["version_number", "file_path", "content_hash", "text_length_chars"] {
            if let value = fields[key] { storePayload[key] = value }
        }
        _ = try await transport.sendAndWait(
            WSOutboundMessage(type: "store_embed", payload: storePayload),
            responseType: "store_embed_confirmed"
        ) { $0["request_id"] as? String == requestId }
        guard isCurrent(expectedGeneration, expectedScope) else { throw LiveEmbedError.staleContext }
    }

    private func storeAlreadyEncrypted(
        _ fields: [String: Any],
        embedId: String,
        expectedGeneration: UUID,
        expectedScope: UUID
    ) throws {
        guard isCurrent(expectedGeneration, expectedScope) else { throw LiveEmbedError.staleContext }
        guard let rawChatId = resolveChatId(fields["chat_id"] as? String),
              let encryptedContent = fields["content"] as? String,
              let encryptedType = fields["type"] as? String else {
            throw LiveEmbedError.missingEncryptionContext
        }
        let keyRecords = Self.embedKeyRecords(fields["embed_keys"])
        if !keyRecords.isEmpty {
            guard isCurrent(expectedGeneration, expectedScope) else { throw LiveEmbedError.staleContext }
            persistEmbedKeys(keyRecords)
        }
        let childIds = Self.stringArray(fields["embed_ids"] ?? fields["child_embed_ids"])
        let record = EmbedRecord(
            id: embedId,
            type: "app-skill-use",
            status: EmbedStatus(rawValue: fields["status"] as? String ?? "") ?? .finished,
            data: nil,
            encryptedContent: encryptedContent,
            encryptedType: encryptedType,
            encryptedTextPreview: fields["text_preview"] as? String,
            parentEmbedId: fields["parent_embed_id"] as? String,
            appId: fields["app_id"] as? String,
            skillId: fields["skill_id"] as? String,
            embedIds: childIds.isEmpty ? nil : childIds.joined(separator: "|"),
            hashedChatId: Self.sha256Hex(rawChatId),
            hashedMessageId: (fields["message_id"] as? String).map(Self.hashIfNeeded),
            hashedUserId: fields["hashed_user_id"] as? String,
            versionNumber: fields["version_number"] as? Int,
            contentHash: fields["content_hash"] as? String,
            createdAt: String(Self.timestamp(fields["createdAt"] ?? fields["created_at"]))
        )
        guard isCurrent(expectedGeneration, expectedScope) else { throw LiveEmbedError.staleContext }
        chatStore.upsertEmbeds([record], for: rawChatId)
    }

    /// Immediately retries queued persistence failures. Production retries call
    /// this after a bounded delay; focused tests use it without wall-clock waits.
    func retryPendingPersistence() async {
        for payloadKey in pendingRetries.keys.sorted() {
            retryTasks[payloadKey]?.cancel()
            retryTasks[payloadKey] = nil
            await performRetry(payloadKey)
        }
    }

    private func scheduleRetry(
        payloadKey: String,
        embedId: String,
        chatId: String,
        expectedGeneration: UUID,
        expectedScope: UUID
    ) {
        guard isCurrent(expectedGeneration, expectedScope) else { return }
        let attempt = (pendingRetries[payloadKey]?.attempt ?? 0) + 1
        guard attempt <= 3 else {
            pendingRetries.removeValue(forKey: payloadKey)
            retryTasks[payloadKey]?.cancel()
            retryTasks[payloadKey] = nil
            return
        }
        pendingRetries[payloadKey] = PendingRetry(
            embedId: embedId,
            chatId: chatId,
            attempt: attempt,
            generation: expectedGeneration,
            scope: expectedScope
        )
        retryTasks[payloadKey]?.cancel()
        let delay = retryDelay(attempt)
        retryTasks[payloadKey] = Task { @MainActor [weak self] in
            try? await Task.sleep(for: delay)
            guard !Task.isCancelled, let self else { return }
            self.retryTasks[payloadKey] = nil
            await self.performRetry(payloadKey)
        }
    }

    private func performRetry(_ payloadKey: String) async {
        guard let retry = pendingRetries[payloadKey] else { return }
        guard isCurrent(retry.generation, retry.scope) else {
            pendingRetries.removeValue(forKey: payloadKey)
            return
        }
        requestedEmbedIdsByChat[retry.chatId]?.remove(retry.embedId)
        do {
            try await transport.send(WSOutboundMessage(
                type: "request_embed",
                payload: ["embed_id": retry.embedId]
            ))
            guard isCurrent(retry.generation, retry.scope) else {
                pendingRetries.removeValue(forKey: payloadKey)
                return
            }
            requestedEmbedIdsByChat[retry.chatId, default: []].insert(retry.embedId)
            pendingRetries.removeValue(forKey: payloadKey)
        } catch {
            guard isCurrent(retry.generation, retry.scope) else { return }
            scheduleRetry(
                payloadKey: payloadKey,
                embedId: retry.embedId,
                chatId: retry.chatId,
                expectedGeneration: retry.generation,
                expectedScope: retry.scope
            )
        }
    }

    private func cancelRetry(_ payloadKey: String) {
        pendingRetries.removeValue(forKey: payloadKey)
        retryTasks[payloadKey]?.cancel()
        retryTasks[payloadKey] = nil
    }

    private func isCurrent(_ expectedGeneration: UUID, _ expectedScope: UUID) -> Bool {
        generation == expectedGeneration && accountScopeGeneration() == expectedScope && !Task.isCancelled
    }

    private func resolveChatId(_ candidate: String?) -> String? {
        guard let candidate, !candidate.isEmpty else { return nil }
        if chatStore.chat(for: candidate) != nil { return candidate }
        guard candidate.count == 64 else { return candidate }
        return chatStore.chats.first { Self.sha256Hex($0.id) == candidate.lowercased() }?.id
    }

    private static func displayType(type: String, appId: String?, skillId: String?) -> String {
        if type == "app_skill_use", let appId, let skillId { return "app:\(appId):\(skillId)" }
        return EmbedType.normalized(rawValue: type)?.rawValue ?? type.replacingOccurrences(of: "_", with: "-")
    }

    private static func stringArray(_ value: Any?) -> [String] {
        if let values = value as? [String] { return values.filter { !$0.isEmpty } }
        if let values = value as? [Any] { return values.compactMap { $0 as? String }.filter { !$0.isEmpty } }
        if let value = value as? String {
            return value.split { $0 == "|" || $0 == "," }
                .map { String($0).trimmingCharacters(in: .whitespacesAndNewlines) }
                .filter { !$0.isEmpty }
        }
        return []
    }

    private static func embedKeyRecords(_ value: Any?) -> [EmbedKeyRecord] {
        guard let rows = value as? [[String: Any]] else { return [] }
        return rows.compactMap { row in
            guard let hashedEmbedId = row["hashed_embed_id"] as? String,
                  let keyType = row["key_type"] as? String,
                  let encryptedEmbedKey = row["encrypted_embed_key"] as? String else { return nil }
            return EmbedKeyRecord(
                hashedEmbedId: hashedEmbedId,
                keyType: keyType,
                hashedChatId: row["hashed_chat_id"] as? String,
                encryptedEmbedKey: encryptedEmbedKey
            )
        }
    }

    private static func timestamp(_ value: Any?) -> Int {
        if let value = value as? Int { return value > 10_000_000_000 ? value / 1000 : value }
        if let value = value as? Double { return Int(value > 10_000_000_000 ? value / 1000 : value) }
        if let value = value as? String, let number = Double(value) {
            return Int(number > 10_000_000_000 ? number / 1000 : number)
        }
        return Int(Date().timeIntervalSince1970)
    }

    private static func sha256Hex(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private static func hashIfNeeded(_ value: String) -> String {
        value.count == 64 && value.allSatisfy(\.isHexDigit) ? value.lowercased() : sha256Hex(value)
    }

    private enum LiveEmbedError: Error {
        case missingEncryptionContext
        case staleContext
    }

    private struct PendingRetry {
        let embedId: String
        let chatId: String
        let attempt: Int
        let generation: UUID
        let scope: UUID
    }
}

@MainActor
protocol ChatWebSocketTransport: AnyObject {
    func send(_ message: WSOutboundMessage) async throws
    func sendAndWait(
        _ message: WSOutboundMessage,
        responseType: String,
        timeout: Duration,
        matching predicate: @escaping ([String: Any]) -> Bool
    ) async throws -> WebSocketResponse
    func waitForMessage(
        _ type: String,
        timeout: Duration,
        matching predicate: @escaping ([String: Any]) -> Bool
    ) async throws -> WebSocketResponse
}

extension ChatWebSocketTransport {
    func sendAndWait(
        _ message: WSOutboundMessage,
        responseType: String,
        matching predicate: @escaping ([String: Any]) -> Bool
    ) async throws -> WebSocketResponse {
        try await sendAndWait(message, responseType: responseType, timeout: .seconds(20), matching: predicate)
    }
    func waitForMessage(
        _ type: String,
        matching predicate: @escaping ([String: Any]) -> Bool
    ) async throws -> WebSocketResponse {
        try await waitForMessage(type, timeout: .seconds(20), matching: predicate)
    }
}

extension WebSocketManager: ChatWebSocketTransport {}

extension WebSocketManager: DraftSyncTransport {}

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
        type = try container.decodeIfPresent(String.self, forKey: .type)
            ?? container.decode(String.self, forKey: .event)
        data = try container.decodeIfPresent([String: AnyCodable].self, forKey: .data)
        payload = try container.decodeIfPresent([String: AnyCodable].self, forKey: .payload)

        // Capture all fields at root level for flat message formats
        let allContainer = try decoder.singleValueContainer()
        rootFields = try? allContainer.decode([String: AnyCodable].self)
    }

    private enum CodingKeys: String, CodingKey {
        case type, event, data, payload
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

    var fields: [String: Any] {
        var values = rootFields?.mapValues(\.value) ?? [:]
        data?.forEach { values[$0.key] = $0.value.value }
        payload?.forEach { values[$0.key] = $0.value.value }
        return values
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

enum WebSocketError: LocalizedError {
    case notConnected
    case encodingFailed
    case messageTimeout
    case remote(code: String)

    var errorDescription: String? {
        switch self {
        case .notConnected:
            return "WebSocket is not connected"
        case .encodingFailed:
            return "Failed to encode WebSocket message"
        case .messageTimeout:
            return "Timed out waiting for WebSocket message"
        case .remote(let code):
            return "WebSocket request was rejected: \(code)"
        }
    }
}

private struct MessageWaiter {
    let types: Set<String>
    let predicate: ([String: Any]) -> Bool
    let continuation: CheckedContinuation<WebSocketResponse, Error>
}

/// Keeps untyped decoded WebSocket JSON at the main-actor transport boundary.
struct WebSocketResponse: @unchecked Sendable {
    let fields: [String: Any]
    var type: String? = nil
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

// Opt-in UI recovery tracing. No payload, account, chat or session identifiers.
func traceNativeStartupSync(_ message: @autoclosure () -> String) {
    #if DEBUG
    guard ProcessInfo.processInfo.arguments.contains("--ui-test-expose-chat-ids") else { return }
    NativeSyncPerfLog.info(message())
    #endif
}
