// WebSocket connection manager for real-time sync with the backend.
// Routes AI streaming events to StreamingClient, sync events to SyncManager,
// and chat updates to ChatStore. Uses native URLSessionWebSocketTask.
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.persistence.client-encrypted, chats.streaming.progressive-presentation, chats.rendering.assistant-document-convergence, chats.rendering.inline-entity-interaction
// Specification: specifications/features/app-skills/code-run/specification.yml
// Assertions: code-run.output.chat-bound-encrypted
// Specification: specifications/features/pii-protection/specification.yml
// Assertions: pii.embed.owner-local-reveal-sync, pii.surface.semantic-parity
// Specification: specifications/features/auth/specification.yml
// Assertions: auth.session.lifecycle, auth.session.authoritative-enforcement, auth.session.isolation
// Specification: specifications/architecture/sync/specification.yml
// Assertions: sync.surface.semantic-parity, sync.startup.bounded-phases, sync.access.first-party-authenticated

// Specification: specifications/architecture/storage-lifecycle/specification.yml
// Assertions: storage.background.complete-sealed-recovery, storage.background.saved-output-retention, storage.surface.semantic-parity

import CryptoKit
import Foundation
import Network
#if os(iOS)
import UIKit
#endif
#if os(macOS)
import AppKit
#endif

@MainActor
final class WebSocketManager: NSObject, ObservableObject, URLSessionWebSocketDelegate {
    @Published private(set) var connectionState: ConnectionState = .disconnected
    @Published private(set) var isPhasedSyncActive = false
    private var phasedSyncActivityAttempt = 0

    private var webSocketTask: URLSessionWebSocketTask?
    private var pingTimer: Timer?
    private var socketTimings = WebSocketTimingWindow()
    private var connectionObservation: WebSocketConnectionObservation?
    private var observationGeneration = 0
    private let decoder = WebSocketInboundDecoder()
    private var connectTask: Task<Void, Never>?
    private var reconnectTask: Task<Void, Never>?
    private var reconnectAttempts = 0
    private var connectionGeneration = 0
    private var activeConnectionKey: ConnectionKey?
    private var didOpenCurrentSocket = false
    private var messageWaiters: [UUID: MessageWaiter] = [:]
    private let streamEventDispatcher = OrderedStreamEventDispatcher()
    private(set) var recoveryCoordinator: ChatCompletionRecoveryCoordinator?
    private var metadataRecoveryCoordinator: ChatMetadataRecoveryCoordinator?
    private var embedStreamCoordinator: ChatEmbedStreamCoordinator?
    private let canonicalStorageConfiguration: CanonicalEmbedStorageConfiguration
    private var canonicalStorageProfile: ServerProfile?
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
    enum SessionRecoveryResult {
        case authenticated(sessionID: String, token: String?)
        case unavailable
        case rejected
    }
    private var sessionRecovery: (() async -> SessionRecoveryResult)?

    func configureSessionRecovery(_ recovery: @escaping () async -> SessionRecoveryResult) {
        sessionRecovery = recovery
    }

    private var shouldReconnect = false
    private var maxReconnectAttempts = 10
    private var reconnectDelay: TimeInterval = 1.0
    #if DEBUG
    // Substitute only the transport attempt, preserving production retry and
    // cancellation behavior for deterministic lifecycle tests.
    var debugConnectionAttempt: (() -> Void)?
    var debugReconnectDelay: TimeInterval?
    var debugPingSender: ((@escaping @Sendable (Error?) -> Void) -> Void)?
    var debugPingTimer: Timer? { pingTimer }
    #endif

    override init() {
        canonicalStorageConfiguration = .deployed
        super.init()
    }

    init(canonicalStorageConfiguration: CanonicalEmbedStorageConfiguration) {
        self.canonicalStorageConfiguration = canonicalStorageConfiguration
        super.init()
    }

    var canonicalEmbedReceiptPolicy: CanonicalEmbedReceiptPolicy {
        canonicalStorageConfiguration.receiptPolicy(for: canonicalStorageProfile ?? ServerProfile.current())
    }

    func connectionURL(profile: ServerProfile, sessionID: String, token: String?) -> URL? {
        canonicalStorageConfiguration.socketURL(profile: profile, sessionID: sessionID, token: token,
            additionalCapabilities: metadataRecoveryCoordinator == nil ? [] : ["chat_metadata_recovery"])
    }

    /// A fresh signed ws_token selects this fenced session. The server gives
    /// any refresh cookie precedence over that query token, so automatic cookie
    /// aliases must not shadow it. Nil/empty tokens retain legacy cookie auth.
    func connectionRequest(profile: ServerProfile, sessionID: String, token: String?, origin: String) -> URLRequest? {
        guard let url = connectionURL(profile: profile, sessionID: sessionID, token: token) else { return nil }
        var request = URLRequest(url: url)
        request.timeoutInterval = 30
        request.setValue(origin, forHTTPHeaderField: "Origin")
        APIClient.nativeClientHeaders.forEach { key, value in
            request.setValue(value, forHTTPHeaderField: key)
        }
        if let token, !token.isEmpty {
            request.httpShouldHandleCookies = false
            request.setValue(nil, forHTTPHeaderField: "Cookie")
        }
        return request
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
        // Validation completion and foreground callbacks also call connect().
        // They must not reopen an exhausted logical session merely because
        // /session returned another ws_token. Explicit disconnect or a new
        // native session admits a fresh retry budget without clearing caches.
        if activeConnectionKey?.sessionId == nextKey.sessionId,
           reconnectAttempts > maxReconnectAttempts, !shouldReconnect {
            return
        }
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

        // /session issues a fresh ws_token on recovery. Credential rotation
        // retains this logical session's failed-handshake budget and backoff.
        // A new native session, explicit disconnect, or opened socket resets it.
        if activeConnectionKey?.sessionId != nextKey.sessionId {
            stopConnectionObservation()
            reconnectAttempts = 0
            reconnectDelay = 1.0
        }
        reconnectTask?.cancel()
        reconnectTask = nil
        rejectAllWaiters()
        connectionGeneration += 1
        isPhasedSyncActive = false
        phasedSyncActivityAttempt += 1
        streamEventDispatcher.reset()
        if activeConnectionKey?.sessionId != nextKey.sessionId {
            embedStreamCoordinator?.reset()
        } else {
            embedStreamCoordinator?.transportDisconnected()
        }
        if activeConnectionKey?.sessionId != nextKey.sessionId {
            metadataRecoveryCoordinator?.reset()
        } else {
            metadataRecoveryCoordinator?.disconnected()
        }
        let generation = connectionGeneration
        let connectingProfile = ServerProfile.current()
        canonicalStorageProfile = connectingProfile
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
        socketTimings = WebSocketTimingWindow()
        startConnectionObservationIfNeeded()
        recordSocketEvent("socket_connecting")

        #if DEBUG
        if let debugConnectionAttempt {
            debugConnectionAttempt()
            return
        }
        #endif

        connectTask = Task { [weak self] in
            guard let self else { return }
            let baseURL = await APIClient.shared.baseURL
            let origin = await APIClient.shared.webAppURL.absoluteString
            guard Self.shouldContinueConnectionAttempt(
                expectedGeneration: generation,
                currentGeneration: connectionGeneration,
                isCancelled: Task.isCancelled
            ) else { return }
            guard ServerProfile.current() == connectingProfile, baseURL == connectingProfile.apiBaseURL,
                  let request = connectionRequest(profile: connectingProfile, sessionID: sessionId,
                      token: token, origin: origin) else { return }

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
                NativeDiagnostics.event("socket_open_failed", category: "network", level: .warning)
                handleDisconnect()
                return
            }

            traceNativeStartupSync("phase=socketOpened")
            connectionState = .connected
            reconnectAttempts = 0
            reconnectDelay = 1.0
            startPingTimer()
            receiveMessages(from: connectingTask)
            #if os(macOS)
            // A socket can reconnect while every chat window is inactive. The
            // server defaults each new connection to foreground until told otherwise.
            if !NSApp.isActive || !AppSessionCoordinator.shared.hasVisibleChatWindow {
                await announceMacBackgroundStateIfConnected()
            }
            #endif
            traceNativeStartupSync("phase=socketRecoveryStart")
            await recoveryCoordinator?.handleTransportConnected(requiresForegroundAcknowledgement: true,
                socketGeneration: connectionGeneration)
            await metadataRecoveryCoordinator?.connectedToTransport()
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
            guard generation == connectionGeneration else { return }
            await embedStreamCoordinator?.transportConnected()
            await CodeRunOutputStore.shared.flushPendingUploads()
            await retryPendingCompressionCheckpoints()
        }
    }

    func disconnect() {
        recoveryCoordinator?.handleTransportDisconnected()
        metadataRecoveryCoordinator?.reset()
        rejectAllWaiters()
        connectionGeneration += 1
        isPhasedSyncActive = false
        phasedSyncActivityAttempt += 1
        streamEventDispatcher.reset()
        embedStreamCoordinator?.transportDisconnected()
        // A waiter belongs to the socket/session that sent its request. Resume
        // it before a different account can establish a replacement connection.
        let disconnectedWaiters = Array(messageWaiters.values)
        messageWaiters.removeAll()
        for waiter in disconnectedWaiters {
            waiter.continuation.resume(throwing: WebSocketError.notConnected)
        }
        shouldReconnect = false
        stopConnectionObservation()
        recordSocketEvent("socket_explicit_disconnect")
        reconnectTask?.cancel()
        reconnectTask = nil
        reconnectAttempts = 0
        reconnectDelay = 1.0
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
        observeRecoveryLifecycleSend(message)
        let data = try message.encodedData()
        guard let json = String(data: data, encoding: .utf8) else {
            throw WebSocketError.encodingFailed
        }
        try await webSocketTask.send(.string(json))
    }

    func recoveryLifecycleChanged(isForeground: Bool) {
        recoveryCoordinator?.lifecycleWillSend(isForeground: isForeground, socketGeneration: connectionGeneration)
    }

    private func observeRecoveryLifecycleSend(_ message: WSOutboundMessage) {
        guard message.type == "native_client_lifecycle", let value = message.payload?["is_foreground"]?.value as? Bool else { return }
        recoveryLifecycleChanged(isForeground: value)
    }

    #if os(macOS)
    func announceMacBackgroundStateIfConnected() async {
        guard connectionState == .connected else { return }
        do {
            try await send(WSOutboundMessage(
                type: "native_client_lifecycle",
                payload: ["is_foreground": false]
            ))
            NativeDiagnostics.info("Announced native background state", category: "app_lifecycle")
        } catch {
            NativeDiagnostics.warning(
                "Failed to announce native background state: \(type(of: error))",
                category: "app_lifecycle"
            )
        }
    }
    #endif

    func configureRecoveryCoordinator(_ coordinator: ChatCompletionRecoveryCoordinator) {
        recoveryCoordinator = coordinator
    }

    /// Keys may arrive after reconnect. Call again from scoped key hydration;
    /// journal restoration never rebuilds its ciphertext or committed identity.
    func retryPendingCompressionCheckpoints() async {
        let scope = OfflineStore.shared.scopeGeneration
        let server = ServerProfile.current()
        let team = TeamWorkspaceContext.shared.snapshot
        let transport = connectionGeneration
        guard connectionState == .connected,
              let captured = await MessageHighlightRuntimeScope.capture(scope: scope, server: server, team: team),
              connectionGeneration == transport else { return }
        await MessageCompressionCheckpointRuntime.retryPending(socket: self, captured: captured, transport: transport)
    }

    var advertisedClientCapabilities: [String] {
        (metadataRecoveryCoordinator == nil ? [] : ["chat_metadata_recovery"])
            + canonicalStorageConfiguration.capabilities(for: canonicalStorageProfile ?? ServerProfile.current())
    }

    func configureMetadataRecovery(chatStore: ChatStore) {
        configureMetadataRecovery(ChatMetadataRecoveryCoordinator(transport: self, chatStore: chatStore))
    }

    func configureMetadataRecovery(_ coordinator: ChatMetadataRecoveryCoordinator) {
        metadataRecoveryCoordinator?.reset()
        metadataRecoveryCoordinator = coordinator
    }

    #if DEBUG
    func debugMetadataTransportOpened() async {
        await metadataRecoveryCoordinator?.connectedToTransport()
    }
    #endif

    func configureEmbedStreamCoordinator(_ coordinator: ChatEmbedStreamCoordinator) {
        embedStreamCoordinator = coordinator
    }

    func waitForMessage(
        _ type: String,
        timeout: Duration = .seconds(20),
        matching predicate: @escaping ([String: Any]) -> Bool
    ) async throws -> WebSocketResponse {
        try await awaitMessage(responseTypes: [type], timeout: timeout, matching: predicate)
    }

    func sendAndWait(
        _ message: WSOutboundMessage,
        responseType: String,
        timeout: Duration = .seconds(20),
        matching predicate: @escaping ([String: Any]) -> Bool
    ) async throws -> WebSocketResponse {
        try await sendAndWait(message, responseTypes: [responseType], timeout: timeout, matching: predicate)
    }

    func sendAndWait(
        _ message: WSOutboundMessage,
        responseType: String,
        timeout: Duration,
        matching predicate: @escaping ([String: Any]) -> Bool,
        beforeSend: @escaping @MainActor () throws -> Void
    ) async throws -> WebSocketResponse {
        try await sendAndWait(message, responseTypes: [responseType], timeout: timeout,
                              matching: predicate, preSendValidation: beforeSend)
    }

    var modelPreferenceSocketGeneration: Int { connectionGeneration }
    var modelPreferenceInbound: ((String, [String: Any], Int) -> Void)?

    func sendAndWait(
        _ message: WSOutboundMessage,
        responseTypes: Set<String>,
        timeout: Duration = .seconds(20),
        matching predicate: @escaping ([String: Any]) -> Bool,
        beforeSend: (@MainActor () async throws -> Void)? = nil,
        preSendValidation: (@MainActor () throws -> Void)? = nil
    ) async throws -> WebSocketResponse {
        guard let boundSocket = webSocketTask else { throw WebSocketError.notConnected }
        let expectedGeneration = connectionGeneration
        return try await awaitMessage(responseTypes: responseTypes, timeout: timeout, matching: predicate) {
            try await beforeSend?()
            try Task.checkCancellation()
            guard Self.shouldContinueConnectionAttempt(
                expectedGeneration: expectedGeneration, currentGeneration: self.connectionGeneration,
                isCancelled: Task.isCancelled
            ), self.webSocketTask === boundSocket else { throw WebSocketError.notConnected }
            // Final synchronous fence runs inside the queued sender, after all
            // awaits and immediately before encryption payload reaches the socket.
            try preSendValidation?()
            self.observeRecoveryLifecycleSend(message)
            let data = try message.encodedData()
            guard let json = String(data: data, encoding: .utf8) else { throw WebSocketError.encodingFailed }
            try await boundSocket.send(.string(json))
        }
    }

    /// Registration, send, timeout and caller cancellation share one lifetime.
    /// The cancellation latch is synchronous so cancellation cannot race a
    /// MainActor hop and let a queued private commit start afterward.
    func awaitMessage(
        responseTypes: Set<String>, timeout: Duration,
        matching predicate: @escaping ([String: Any]) -> Bool,
        send: (@MainActor () async throws -> Void)? = nil
    ) async throws -> WebSocketResponse {
        let waiterId = UUID()
        let lifetime = WebSocketWaiterLifetime()
        return try await withTaskCancellationHandler {
            try Task.checkCancellation()
            return try await withCheckedThrowingContinuation { continuation in
                guard !lifetime.isCancelled else {
                    continuation.resume(throwing: CancellationError())
                    return
                }
                messageWaiters[waiterId] = MessageWaiter(types: responseTypes,
                    predicate: predicate, continuation: continuation, lifetime: lifetime)
                if let send {
                    lifetime.add(Task { @MainActor [weak self] in
                        guard let self else { return }
                        do {
                            try Task.checkCancellation()
                            guard !lifetime.isCancelled, self.messageWaiters[waiterId] != nil else {
                                throw CancellationError()
                            }
                            try await send()
                        } catch {
                            self.finishWaiter(waiterId, error: error)
                        }
                    })
                }
                lifetime.add(Task { @MainActor [weak self] in
                    do { try await Task.sleep(for: timeout) } catch { return }
                    self?.finishWaiter(waiterId, error: WebSocketError.messageTimeout)
                })
            }
        } onCancel: {
            lifetime.cancel()
            Task { @MainActor [weak self] in
                self?.finishWaiter(waiterId, error: CancellationError())
            }
        }
    }

    private func finishWaiter(_ id: UUID, error: Error) {
        guard let waiter = messageWaiters.removeValue(forKey: id) else { return }
        waiter.lifetime.cancel()
        waiter.continuation.resume(throwing: error)
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
        phasedSyncActivityAttempt += 1
        let attempt = phasedSyncActivityAttempt
        let generation = connectionGeneration
        isPhasedSyncActive = true
        do {
            try await send(Self.phasedSyncMessage(
                clientChatVersions: clientChatVersions, clientChatIds: clientChatIds,
                clientSuggestionsCount: clientSuggestionsCount, clientEmbedIds: clientEmbedIds
            ))
        } catch {
            if generation == connectionGeneration, attempt == phasedSyncActivityAttempt { isPhasedSyncActive = false }
            throw error
        }
    }

    static func completesPersonalPhasedSync(_ fields: [String: Any]) -> Bool {
        fields["phase"] as? String == "all" && fields["team_id"] as? String == nil
            && (fields["context_epoch"] as? NSNumber)?.intValue == 0
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

    func requestChatContentBatch(
        chatId: String, beforeSend: (@MainActor () async throws -> Void)? = nil
    ) async throws -> WebSocketResponse {
        try await sendAndWait(
            WSOutboundMessage(
                type: "request_chat_content_batch",
                payload: ["chat_ids": [chatId]]
            ),
            responseTypes: ["chat_content_batch_response"],
            timeout: .seconds(20),
            matching: { fields in
                guard let messages = fields["messages_by_chat_id"] as? [String: Any] else { return false }
                return messages[chatId] != nil
            },
            beforeSend: beforeSend
        )
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
                    Self.recordSocketFailure("socket_open_probe_failed", error: error)
                    continuation.resume(returning: false)
                } else {
                    continuation.resume(returning: true)
                }
            }
        }
    }

    // MARK: - Receive loop

    private func receiveMessages(from receivingTask: URLSessionWebSocketTask?) {
        let generation = connectionGeneration
        receivingTask?.receive { [weak self, weak receivingTask] result in
            let callbackUptime = ProcessInfo.processInfo.systemUptime
            // Foundation may deliver receive failure before didClose/didComplete.
            // Capture terminal evidence before MainActor teardown cancels the task.
            let closeCode = receivingTask?.closeCode
            let httpStatus = (receivingTask?.response as? HTTPURLResponse)?.statusCode
            Task { @MainActor in
                guard let self, let receivingTask,
                      generation == self.connectionGeneration,
                      Self.isCurrentSocket(
                          callbackTaskIdentifier: receivingTask.taskIdentifier,
                          currentTaskIdentifier: self.webSocketTask?.taskIdentifier
                      ) else { return }
                self.socketTimings.recordCallback(at: callbackUptime, deliveredAt: ProcessInfo.processInfo.systemUptime)
                switch result {
                case .success(let message):
                    let routeStart = ProcessInfo.processInfo.systemUptime
                    let generation = self.connectionGeneration
                    await self.handleRawMessage(message, taskIdentifier: receivingTask.taskIdentifier, generation: generation)
                    guard generation == self.connectionGeneration,
                          Self.isCurrentSocket(callbackTaskIdentifier: receivingTask.taskIdentifier,
                                               currentTaskIdentifier: self.webSocketTask?.taskIdentifier) else { return }
                    self.socketTimings.recordReceive(routingMilliseconds: WebSocketTimingWindow.milliseconds(since: routeStart))
                    self.receiveMessages(from: receivingTask)
                case .failure(let error):
                    self.handleReceiveFailure(error, taskIdentifier: receivingTask.taskIdentifier,
                        generation: generation, closeCode: closeCode, httpStatus: httpStatus)
                }
            }
        }
    }

    private func handleReceiveFailure(
        _ error: Error, taskIdentifier: Int, generation: Int,
        closeCode: URLSessionWebSocketTask.CloseCode?, httpStatus: Int?
    ) {
        guard generation == connectionGeneration,
              Self.isCurrentSocket(callbackTaskIdentifier: taskIdentifier,
                                   currentTaskIdentifier: webSocketTask?.taskIdentifier) else { return }
        let authenticationRejected = Self.isAuthenticationRejection(closeCode: closeCode, httpStatus: httpStatus)
        Self.recordSocketFailure("socket_receive_failed", error: error,
            extraCounts: ["close_code": closeCode?.rawValue ?? 0, "http_status": httpStatus ?? 0])
        handleDisconnect(authenticationRejected: authenticationRejected)
    }

    nonisolated static func isAuthenticationRejection(
        closeCode: URLSessionWebSocketTask.CloseCode?, httpStatus: Int?
    ) -> Bool {
        closeCode == .policyViolation || httpStatus == 401 || httpStatus == 403
    }

    private func handleRawMessage(_ message: URLSessionWebSocketTask.Message, taskIdentifier: Int, generation: Int) async {
        // Await one actor decode before receiving the next frame: keep socket
        // ordering while large offline-sync payloads leave the UI executor free.
        guard let decoded = try? await decoder.decode(message),
              generation == connectionGeneration,
              Self.isCurrentSocket(callbackTaskIdentifier: taskIdentifier,
                                   currentTaskIdentifier: webSocketTask?.taskIdentifier) else { return }
        routeMessage(decoded.parsed, raw: decoded.raw)
    }

    // MARK: - Message routing

    private func routeMessage(_ msg: WSInboundParsed, raw: Data) {
        AssistantSpeechAppRuntime.shared.receive(type: msg.type, fields: msg.fields, from: self)
        ProjectWorkspaceReviewRuntime.shared.receive(type: msg.type, fields: msg.fields, from: self)
        if msg.type == "error" {
            recoveryCoordinator?.handleRecoveryError(msg.fields)
            if msg.fields["code"] as? String == "recovery_requires_foreground",
               recoveryCoordinator?.needsForegroundAcknowledgement == true {
                let socketGeneration = connectionGeneration
                Task { @MainActor [weak self] in
                    guard let self, self.connectionGeneration == socketGeneration,
                          self.recoveryCoordinator?.needsForegroundAcknowledgement == true else { return }
                    try? await self.send(WSOutboundMessage(type: "native_client_lifecycle",
                        payload: ["is_foreground": true, "client_type": "apple"]))
                }
            }
            rejectWaiters(with: msg.fields)
        }
        resolveWaiters(type: msg.type, payload: msg.fields)
        if ["chat_model_preference", "chat_model_preference_updated", "chat_model_preference_synced"].contains(msg.type) {
            modelPreferenceInbound?(msg.type, msg.fields, connectionGeneration)
        }
        NativeChatActivityStore.shared.consume(type: msg.type, fields: msg.fields, scope: OfflineStore.shared.scopeGeneration)
        if ["message_highlight_added", "message_highlight_updated", "message_highlight_removed", "message_deleted", "chat_deleted"].contains(msg.type) {
            let scope = OfflineStore.shared.scopeGeneration, server = ServerProfile.current(), team = TeamWorkspaceContext.shared.snapshot
            let transport = connectionGeneration
            Task { @MainActor [weak self] in
                guard let self, self.connectionGeneration == transport else { return }
                await HighlightsManager.shared.receive(type: msg.type, fields: msg.fields, scope: scope, server: server, team: team)
            }
        }
        if ["chat_compression_completed", "chat_compression_checkpoint_stored"].contains(msg.type) {
            let scope = OfflineStore.shared.scopeGeneration, server = ServerProfile.current(), team = TeamWorkspaceContext.shared.snapshot
            let transport = connectionGeneration
            Task { @MainActor [weak self] in
                guard let self, self.connectionGeneration == transport,
                      let captured = await MessageHighlightRuntimeScope.capture(scope: scope, server: server, team: team) else { return }
                await MessageCompressionCheckpointRuntime.consume(type: msg.type, fields: msg.fields, socket: self, captured: captured, transport: transport)
            }
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
                userInfo: ["type": msg.type, "raw": raw, "decoded": WebSocketResponse(fields: msg.fields, type: msg.type),
                           "accountScope": OfflineStore.shared.scopeGeneration,
                           "transportGeneration": connectionGeneration]
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
              "chat_compression_started", "chat_compression_completed", "chat_compression_checkpoint_stored",
              "encrypted_metadata_stored", "post_processing_metadata_stored",
              "focus_mode_activated", "focus_phases_updated", "focus_mode_pending",
              "chat_context_applied", "project_authoring_available",
              "spawn_sub_chats", "sub_chat_confirmation_required",
              "sub_chat_confirmation_resolved", "sub_chat_progress", "sub_chat_stopped", "sub_chat_completed",
              "ai_background_response_completed":
            recoveryCoordinator?.handleTerminalStream(msg.fields)
            NotificationCenter.default.post(
                name: .wsMessageReceived, object: nil,
                userInfo: ["type": msg.type, "raw": raw, "decoded": WebSocketResponse(fields: msg.fields, type: msg.type),
                           "accountScope": OfflineStore.shared.scopeGeneration,
                           "transportGeneration": connectionGeneration]
            )

        // Sync phases
        case "initial_sync_response", "initial_sync_error",
             "phase_1_last_chat_ready", "phase_1b_chat_content_ready",
             "phase_2_last_20_chats_ready", "phase_3_last_100_chats_ready",
             "background_message_sync", "cache_primed", "cache_status_response",
             "load_more_chats_response", "sync_metadata_chats_response",
             "phased_sync_complete", "sync_status_response",
             "offline_sync_complete", "chat_content_batch_response",
             "code_run_outputs_sync_ready":
            if msg.type == "phased_sync_complete", Self.completesPersonalPhasedSync(msg.fields) {
                isPhasedSyncActive = false
                phasedSyncActivityAttempt += 1
            }
            socketTimings.recordSyncEvent()
            traceNativeStartupSync("phase=syncEventReceived type=\(msg.type)")
            NotificationCenter.default.post(
                name: .wsSyncEvent, object: nil,
                userInfo: ["type": msg.type, "raw": raw, "decoded": WebSocketResponse(fields: msg.fields, type: msg.type),
                           "accountScope": OfflineStore.shared.scopeGeneration,
                           "transportGeneration": connectionGeneration]
            )

        // Embed updates
        case "code_run_output_synced":
            let expectedScope = OfflineStore.shared.scopeGeneration
            if let payload = CodeRunOutputSyncedPayload.decode(fields: msg.fields) {
                Task { @MainActor in
                    guard expectedScope == OfflineStore.shared.scopeGeneration else { return }
                    await CodeRunOutputStore.shared.ingest(payload, expectedScope: expectedScope)
                }
            }

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
            let socketGeneration = connectionGeneration
            Task { @MainActor [weak self] in
                guard let self, self.connectionGeneration == socketGeneration else { return }
                await self.recoveryCoordinator?.handleLifecycleAcknowledgement(msg.fields, socketGeneration: socketGeneration)
            }

        case "recovery_outputs_available", "recovery_outputs_discovery_complete":
            // No typed replay path is qualified: never fetch, claim, persist, or
            // acknowledge these records. A v2 crypto fixture is insufficient.
            break

        case "metadata_jobs_available":
            metadataRecoveryCoordinator?.available(msg.fields)

        case "metadata_job_claimed", "metadata_job_persisted":
            break

        case "recovery_jobs_available":
            let socketGeneration = connectionGeneration
            let scope = OfflineStore.shared.scopeGeneration
            Task { @MainActor [weak self] in
                guard let self, self.connectionGeneration == socketGeneration,
                      OfflineStore.shared.scopeGeneration == scope else { return }
                await self.recoveryCoordinator?.handleAvailableJobs(msg.fields)
            }

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
        for waiter in pending {
            waiter.lifetime.cancel()
            waiter.continuation.resume(throwing: WebSocketError.notConnected)
        }
    }

    private func resolveWaiters(type: String, payload: [String: Any]) {
        let matches = messageWaiters.filter { _, waiter in
            waiter.types.contains(type) && waiter.predicate(payload)
        }
        for (id, waiter) in matches {
            messageWaiters.removeValue(forKey: id)
            waiter.lifetime.cancel()
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
            waiter.lifetime.cancel()
            waiter.continuation.resume(throwing: WebSocketError.remote(code: code))
        }
    }

    func ownsRecoveryPersistence(messageId: String) -> Bool {
        recoveryCoordinator?.ownsRecoveryPersistence(messageId: messageId) ?? false
    }

    func markRecoveryInitialSyncReady() async {
        await recoveryCoordinator?.markInitialSyncReady()
        await metadataRecoveryCoordinator?.syncReady()
    }

    func handleRecoveryChatKeyAvailabilityChanged() async {
        await recoveryCoordinator?.handleChatKeyAvailabilityChanged()
        metadataRecoveryCoordinator?.keysChanged()
    }

    // MARK: - Ping timer

    private func startPingTimer(interval: TimeInterval = 25) {
        pingTimer?.invalidate()
        let generation = connectionGeneration
        let boundSocket = webSocketTask
        let taskIdentifier = boundSocket?.taskIdentifier
        socketTimings.startPingSchedule(at: ProcessInfo.processInfo.systemUptime, interval: interval)
        // Common modes preserve keepalive scheduling during scrolling/tracking.
        // Capture the socket lifetime before the timer callback queues a MainActor hop.
        let timer = Timer(timeInterval: interval, repeats: true) { [weak self] _ in
            let firedUptime = ProcessInfo.processInfo.systemUptime
            Task { @MainActor [weak self] in
                guard let self,
                      Self.shouldContinueConnectionAttempt(expectedGeneration: generation,
                          currentGeneration: self.connectionGeneration, isCancelled: Task.isCancelled),
                      self.webSocketTask?.taskIdentifier == taskIdentifier else { return }
                self.socketTimings.recordCallback(at: firedUptime, deliveredAt: ProcessInfo.processInfo.systemUptime)
                let drift = self.socketTimings.pingScheduleDrift(at: firedUptime)
                self.recordSocketEvent("socket_ping_scheduled", extraCounts: ["schedule_drift_ms": drift])
                let sentUptime = ProcessInfo.processInfo.systemUptime
                let pongHandler: @Sendable (Error?) -> Void = { [weak self] error in
                    let pongUptime = ProcessInfo.processInfo.systemUptime
                    Task { @MainActor [weak self] in
                        guard let self,
                              Self.shouldContinueConnectionAttempt(expectedGeneration: generation,
                                  currentGeneration: self.connectionGeneration, isCancelled: Task.isCancelled),
                              self.webSocketTask?.taskIdentifier == taskIdentifier else { return }
                        self.socketTimings.recordCallback(at: pongUptime, deliveredAt: ProcessInfo.processInfo.systemUptime)
                        self.recordSocketEvent("socket_ping_completed", extraCounts: [
                            "rtt_ms": WebSocketTimingWindow.milliseconds(from: sentUptime, to: pongUptime)
                        ], flags: ["failed": error != nil])
                        if let error {
                            Self.recordSocketFailure("socket_ping_failed", error: error)
                            self.handleDisconnect()
                        }
                    }
                }
                #if DEBUG
                if let sender = self.debugPingSender {
                    sender(pongHandler)
                    return
                }
                #endif
                boundSocket?.sendPing(pongReceiveHandler: pongHandler)
            }
        }
        pingTimer = timer
        RunLoop.main.add(timer, forMode: .common)
    }

    private func recordSocketEvent(
        _ name: String, level: NativeClientLogLevel = .info,
        extraCounts: [String: Int] = [:], flags: [String: Bool] = [:]
    ) {
        var counts = socketTimings.takeWindowCounts()
        counts["generation"] = connectionGeneration
        counts["uptime_ms"] = WebSocketTimingWindow.milliseconds(from: 0, to: ProcessInfo.processInfo.systemUptime)
        counts.merge(extraCounts) { _, new in new }
        NativeDiagnostics.event(name, category: "network", level: level, flags: flags, counts: counts)
    }

    nonisolated private static func recordSocketFailure(
        _ name: String, error: Error, extraCounts: [String: Int] = [:]
    ) {
        // Unknown domains are intentionally represented as zero: arbitrary NSError
        // domains and descriptions can contain private endpoint or payload details.
        let nsError = error as NSError
        var counts = ["error_domain_class": WebSocketTimingWindow.errorDomainClass(nsError.domain),
                      "error_code": nsError.code]
        counts.merge(extraCounts) { _, new in new }
        NativeDiagnostics.event(name, category: "network", level: .warning, counts: counts)
    }

    private func startConnectionObservationIfNeeded() {
        guard connectionObservation == nil else { return }
        observationGeneration += 1
        let generation = observationGeneration
        #if os(iOS)
        recordSocketEvent("socket_app_lifecycle", flags: ["foreground": UIApplication.shared.applicationState == .active])
        #elseif os(macOS)
        recordSocketEvent("socket_app_lifecycle", flags: ["foreground": NSApp.isActive])
        #endif
        connectionObservation = WebSocketConnectionObservation { [weak self] name, flags, counts, callbackUptime in
            Task { @MainActor [weak self] in
                guard let self, generation == self.observationGeneration, self.shouldReconnect else { return }
                self.socketTimings.recordCallback(at: callbackUptime, deliveredAt: ProcessInfo.processInfo.systemUptime)
                self.recordSocketEvent(name, extraCounts: counts, flags: flags)
            }
        }
    }

    private func stopConnectionObservation() {
        observationGeneration += 1
        connectionObservation = nil
    }

    // MARK: - Reconnect

    private func handleDisconnect(authenticationRejected: Bool = false) {
        let syncSummary = NativeSyncDiagnosticsStore.shared.summary()
        recordSocketEvent("socket_connection_lost", level: .warning, extraCounts: [
            "sync_phase_count": syncSummary["phase_count"] as? Int ?? 0,
            "sync_warning_count": syncSummary["warning_count"] as? Int ?? 0,
            "sync_slowest_elapsed_ms": syncSummary["slowest_elapsed_ms"] as? Int ?? 0
        ], flags: ["authentication_rejected": authenticationRejected])
        reconnectTask?.cancel()
        reconnectTask = nil
        connectTask?.cancel()
        connectTask = nil
        rejectAllWaiters()
        connectionGeneration += 1
        isPhasedSyncActive = false
        phasedSyncActivityAttempt += 1
        streamEventDispatcher.reset()
        embedStreamCoordinator?.transportDisconnected()
        let reconnectGeneration = connectionGeneration
        pingTimer?.invalidate()
        pingTimer = nil
        webSocketTask?.cancel(with: .goingAway, reason: nil)
        webSocketTask = nil
        didOpenCurrentSocket = false
        recoveryCoordinator?.handleTransportDisconnected()
        metadataRecoveryCoordinator?.disconnected()
        guard shouldReconnect else {
            connectionState = .disconnected
            return
        }

        reconnectAttempts += 1
        let currentAttempt = reconnectAttempts

        guard currentAttempt <= maxReconnectAttempts else {
            shouldReconnect = false
            stopConnectionObservation()
            connectionState = .disconnected
            NativeDiagnostics.event("socket_retries_exhausted", category: "network", level: .warning,
                                    counts: ["attempts": currentAttempt - 1])
            return
        }

        connectionState = .reconnecting(attempt: currentAttempt)

        var delay = authenticationRejected ? 0 : reconnectDelay
        #if DEBUG
        delay = debugReconnectDelay ?? delay
        #endif
        reconnectTask = Task { [weak self] in
            do { try await Task.sleep(for: .seconds(delay)) } catch { return }
            guard let self,
                  Self.shouldContinueConnectionAttempt(
                      expectedGeneration: reconnectGeneration,
                      currentGeneration: connectionGeneration,
                      isCancelled: Task.isCancelled
                  ), shouldReconnect else { return }
            reconnectDelay = min(reconnectDelay * 2, 30)
            if let sessionRecovery {
                let recovered = await sessionRecovery()
                guard Self.shouldContinueConnectionAttempt(expectedGeneration: reconnectGeneration,
                    currentGeneration: connectionGeneration, isCancelled: Task.isCancelled), shouldReconnect else { return }
                switch recovered {
                case .authenticated(let sessionID, let token):
                    connect(sessionId: sessionID, token: token, syncState: activeSyncState)
                case .unavailable:
                    // A network/5xx failure retains offline identity and retries
                    // validation later, never the known-rejected credentials.
                    handleDisconnect()
                case .rejected:
                    disconnect()
                }
                return
            }
            if let sessionId {
                connect(sessionId: sessionId, token: authToken, syncState: activeSyncState)
            }
        }
    }

    #if DEBUG
    func debugFailCurrentConnection(authenticationRejected: Bool = false) {
        handleDisconnect(authenticationRejected: authenticationRejected)
    }
    func debugStartPingTimer(interval: TimeInterval) {
        connectionState = .connected
        startPingTimer(interval: interval)
    }
    // Unresumed fixture tasks exercise terminal callbacks without network I/O.
    func debugBindCurrentSocket(_ task: URLSessionWebSocketTask) {
        webSocketTask = task
    }
    func debugReceiveFailure(
        _ error: Error, from task: URLSessionWebSocketTask, generation: Int,
        closeCode: URLSessionWebSocketTask.CloseCode?, httpStatus: Int?
    ) {
        handleReceiveFailure(error, taskIdentifier: task.taskIdentifier, generation: generation,
                             closeCode: closeCode, httpStatus: httpStatus)
    }
    var debugCurrentAuthToken: String? { authToken }
    #endif

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
        let callbackUptime = ProcessInfo.processInfo.systemUptime
        Task { @MainActor [weak self] in
            guard let self, Self.isCurrentSocket(
                callbackTaskIdentifier: webSocketTask.taskIdentifier,
                currentTaskIdentifier: self.webSocketTask?.taskIdentifier
            ) else { return }
            self.socketTimings.recordCallback(at: callbackUptime, deliveredAt: ProcessInfo.processInfo.systemUptime)
            self.didOpenCurrentSocket = true
            self.recordSocketEvent("socket_opened")
        }
    }

    nonisolated func urlSession(
        _ session: URLSession,
        webSocketTask: URLSessionWebSocketTask,
        didCloseWith closeCode: URLSessionWebSocketTask.CloseCode,
        reason: Data?
    ) {
        let callbackUptime = ProcessInfo.processInfo.systemUptime
        Task { @MainActor [weak self] in
            guard let self, Self.isCurrentSocket(
                callbackTaskIdentifier: webSocketTask.taskIdentifier,
                currentTaskIdentifier: self.webSocketTask?.taskIdentifier
            ) else { return }
            self.socketTimings.recordCallback(at: callbackUptime, deliveredAt: ProcessInfo.processInfo.systemUptime)
            self.recordSocketEvent("socket_closed", level: .warning, extraCounts: ["close_code": closeCode.rawValue],
                                   flags: ["authentication_rejected": closeCode == .policyViolation])
            self.handleDisconnect(authenticationRejected: closeCode == .policyViolation)
        }
    }

    nonisolated func urlSession(_ session: URLSession, task: URLSessionTask,
                                didCompleteWithError error: Error?) {
        let callbackUptime = ProcessInfo.processInfo.systemUptime
        Task { @MainActor [weak self] in
            guard let self, Self.isCurrentSocket(callbackTaskIdentifier: task.taskIdentifier,
                currentTaskIdentifier: self.webSocketTask?.taskIdentifier) else { return }
            let status = (task.response as? HTTPURLResponse)?.statusCode
            guard error != nil || status == 401 || status == 403 else { return }
            self.socketTimings.recordCallback(at: callbackUptime, deliveredAt: ProcessInfo.processInfo.systemUptime)
            self.recordSocketEvent("socket_transport_failed", level: .warning, extraCounts: ["http_status": status ?? 0],
                                   flags: ["authentication_rejected": status == 401 || status == 403])
            if let error { Self.recordSocketFailure("socket_transport_error", error: error) }
            self.handleDisconnect(authenticationRejected: status == 401 || status == 403)
        }
    }
}

/// Bounded numeric aggregation: never retains an inbound payload, URL or identity.
/// Receive samples are reported at ping/lifecycle cadence rather than per message.
struct WebSocketTimingWindow {
    private var nextPingUptime: TimeInterval?
    private var pingInterval: TimeInterval = 25
    private var callbackCount = 0
    private var maxCallbackDelayMilliseconds = 0
    private var receiveCount = 0
    private var syncEventCount = 0
    private var routingMilliseconds = 0

    mutating func startPingSchedule(at uptime: TimeInterval, interval: TimeInterval) {
        pingInterval = interval
        nextPingUptime = uptime + interval
    }

    mutating func pingScheduleDrift(at uptime: TimeInterval) -> Int {
        guard let expected = nextPingUptime else { return 0 }
        let drift = Self.milliseconds(from: expected, to: uptime)
        // Repeating Timer skips missed firings. Keep the original cadence and
        // advance beyond now, instead of producing a burst after suspension.
        let intervals = max(1, floor(max(0, uptime - expected) / pingInterval) + 1)
        nextPingUptime = expected + intervals * pingInterval
        return drift
    }

    mutating func recordCallback(at callbackUptime: TimeInterval, deliveredAt uptime: TimeInterval) {
        callbackCount += 1
        maxCallbackDelayMilliseconds = max(maxCallbackDelayMilliseconds,
            Self.milliseconds(from: callbackUptime, to: uptime))
    }

    mutating func recordReceive(routingMilliseconds: Int) {
        receiveCount += 1
        self.routingMilliseconds += max(0, routingMilliseconds)
    }

    mutating func recordSyncEvent() { syncEventCount += 1 }

    mutating func takeWindowCounts() -> [String: Int] {
        let counts = ["callback_count": callbackCount,
                      "callback_main_delay_max_ms": maxCallbackDelayMilliseconds,
                      "received_count": receiveCount, "sync_event_count": syncEventCount,
                      "receive_routing_total_ms": routingMilliseconds]
        callbackCount = 0
        maxCallbackDelayMilliseconds = 0
        receiveCount = 0
        syncEventCount = 0
        routingMilliseconds = 0
        return counts
    }

    static func milliseconds(since uptime: TimeInterval) -> Int {
        milliseconds(from: uptime, to: ProcessInfo.processInfo.systemUptime)
    }

    static func milliseconds(from start: TimeInterval, to end: TimeInterval) -> Int {
        let value = max(0, (end - start) * 1_000)
        guard value.isFinite, value < Double(Int.max) else { return Int.max }
        return Int(value.rounded())
    }

    static func errorDomainClass(_ domain: String) -> Int {
        switch domain {
        case NSURLErrorDomain: return 1
        case NSPOSIXErrorDomain: return 2
        case NSCocoaErrorDomain: return 3
        case NSOSStatusErrorDomain: return 4
        default: return 0
        }
    }
}

/// Owns its monitor/observer cancellation independently from retry generations.
/// A manager generation check fences already-queued callbacks after disconnect.
private final class WebSocketConnectionObservation: @unchecked Sendable {
    typealias Handler = @Sendable (String, [String: Bool], [String: Int], TimeInterval) -> Void
    private let monitor = NWPathMonitor()
    private let pathQueue = DispatchQueue(label: "org.openmates.socket-path-diagnostics")
    private var notificationObservers: [NSObjectProtocol] = []
    private var previousPath: PathSnapshot?

    private struct PathSnapshot: Equatable {
        let status: Int
        let flags: [String: Bool]
    }

    init(handler: @escaping Handler) {
        monitor.pathUpdateHandler = { [weak self] path in
            guard let self else { return }
            let status: Int
            switch path.status {
            case .satisfied: status = 1
            case .unsatisfied: status = 2
            case .requiresConnection: status = 3
            @unknown default: status = 0
            }
            let snapshot = PathSnapshot(status: status, flags: [
                "satisfied": path.status == .satisfied,
                "expensive": path.isExpensive, "constrained": path.isConstrained,
                "wifi": path.usesInterfaceType(.wifi), "cellular": path.usesInterfaceType(.cellular),
                "wired": path.usesInterfaceType(.wiredEthernet)
            ])
            // NWPathMonitor invokes this on its private serial queue.
            guard snapshot != self.previousPath else { return }
            self.previousPath = snapshot
            handler("socket_network_path", snapshot.flags, ["path_status": status], ProcessInfo.processInfo.systemUptime)
        }
        monitor.start(queue: pathQueue)
        #if os(iOS)
        observe(UIApplication.didEnterBackgroundNotification, foreground: false, handler: handler)
        observe(UIApplication.didBecomeActiveNotification, foreground: true, handler: handler)
        #elseif os(macOS)
        observe(NSApplication.didResignActiveNotification, foreground: false, handler: handler)
        observe(NSApplication.didBecomeActiveNotification, foreground: true, handler: handler)
        #endif
    }

    private func observe(_ name: Notification.Name, foreground: Bool, handler: @escaping Handler) {
        notificationObservers.append(NotificationCenter.default.addObserver(forName: name, object: nil, queue: nil) { _ in
            handler("socket_app_lifecycle", ["foreground": foreground], [:], ProcessInfo.processInfo.systemUptime)
        })
    }

    deinit {
        monitor.cancel()
        for observer in notificationObservers { NotificationCenter.default.removeObserver(observer) }
    }
}

/// Mirrors the web client's live embed work below the UI. It discovers embed
/// references in cumulative assistant chunks and client-encrypts finalized
/// `send_embed_data` payloads before any durable local write.
@MainActor
final class ChatEmbedStreamCoordinator {
    typealias HeadReceiptPolicy = CanonicalEmbedReceiptPolicy
    private let transport: ChatWebSocketTransport
    private let chatStore: ChatStore
    private let authenticatedOwnerId: () async -> String?
    private let masterKey: (String) async -> SymmetricKey?
    private let chatKey: (String) -> SymmetricKey?
    private let persistEmbedKeys: ([EmbedKeyRecord]) -> Void
    private let persistOwnerPII: ([PIIMapping], String, String, String, SymmetricKey) async throws -> Void
    private let chatDeletionVersion: (String) -> Int
    private let accountScopeGeneration: () -> UUID
    private let retryDelay: (Int) -> Duration
    private let headReceiptPolicy: HeadReceiptPolicy
    private let headReceiptPolicyProvider: (() -> HeadReceiptPolicy)?
    private var transportPaused = false
    private var preparedWrites: [String: PreparedEmbedWrite] = [:]
    private var latestPayloadByEmbed: [String: String] = [:]
    private var latestVersionByEmbed: [String: Int] = [:]
    private var activeWriters = Set<String>()
    private var writerWaiters: [String: [CheckedContinuation<Void, Never>]] = [:]
    private var generation = UUID()
    private var requestedEmbedIdsByChat: [String: Set<String>] = [:]
    private var processedPayloadKeys = Set<String>()
    private var inFlightPayloadKeys = Set<String>()
    private var pendingRetries: [String: PendingRetry] = [:]
    private var retryTasks: [String: Task<Void, Never>] = [:]
    private var pendingOwnerPayloads: [String: PendingOwnerPayload] = [:]
    private var ownerRetryTasks: [String: Task<Void, Never>] = [:]

    init(
        transport: ChatWebSocketTransport,
        chatStore: ChatStore,
        authenticatedOwnerId: @escaping () async -> String?,
        masterKey: @escaping (String) async -> SymmetricKey?,
        chatKey: @escaping (String) -> SymmetricKey?,
        persistEmbedKeys: @escaping ([EmbedKeyRecord]) -> Void,
        persistOwnerPII: @escaping ([PIIMapping], String, String, String, SymmetricKey) async throws -> Void = {
            mappings, chatId, embedId, ownerId, key in
            try await OwnerEmbedPIIStore.shared.persist(
                mappings, chatId: chatId, embedId: embedId, ownerUserId: ownerId, masterKey: key
            )
        },
        accountScopeGeneration: @escaping () -> UUID = { OfflineStore.shared.scopeGeneration },
        chatDeletionVersion: @escaping (String) -> Int = { OfflineStore.shared.chatDeletionVersion($0) },
        headReceiptPolicy: HeadReceiptPolicy = .requireCanonicalDigest,
        headReceiptPolicyProvider: (() -> HeadReceiptPolicy)? = nil,
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
        self.persistOwnerPII = persistOwnerPII
        self.chatDeletionVersion = chatDeletionVersion
        self.accountScopeGeneration = accountScopeGeneration
        self.retryDelay = retryDelay
        self.headReceiptPolicy = headReceiptPolicy
        self.headReceiptPolicyProvider = headReceiptPolicyProvider
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
            },
            headReceiptPolicy: .allowLegacyReceipt,
            headReceiptPolicyProvider: { (transport as? WebSocketManager)?.canonicalEmbedReceiptPolicy ?? .allowLegacyReceipt }
        )
    }

    func reset() {
        generation = UUID()
        retryTasks.values.forEach { $0.cancel() }
        ownerRetryTasks.values.forEach { $0.cancel() }
        retryTasks.removeAll()
        ownerRetryTasks.removeAll()
        pendingOwnerPayloads.removeAll()
        pendingRetries.removeAll()
        preparedWrites.removeAll()
        latestPayloadByEmbed.removeAll()
        latestVersionByEmbed.removeAll()
        // Keep the writer lock until its old await returns; queued writers then
        // recheck generation before touching the replacement account.
        transportPaused = false
        requestedEmbedIdsByChat.removeAll()
        processedPayloadKeys.removeAll()
        inFlightPayloadKeys.removeAll()
    }

    func transportDisconnected() {
        transportPaused = true
        retryTasks.values.forEach { $0.cancel() }
        ownerRetryTasks.values.forEach { $0.cancel() }
        retryTasks.removeAll()
        ownerRetryTasks.removeAll()
    }

    func transportConnected() async {
        transportPaused = false
        await retryPendingPersistence()
        await retryPendingOwnerPersistence()
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
        if let latest = latestVersionByEmbed[embedId], version == nil || version! < latest { return }
        if let version { latestVersionByEmbed[embedId] = version }
        if let previous = latestPayloadByEmbed[embedId], previous != payloadKey {
            cancelRetry(previous)
            preparedWrites.removeValue(forKey: previous)
            pendingOwnerPayloads.removeValue(forKey: previous)
            ownerRetryTasks.removeValue(forKey: previous)?.cancel()
        }
        latestPayloadByEmbed[embedId] = payloadKey
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
        guard isCurrent(expectedGeneration, expectedScope),
              latestPayloadByEmbed[embedId] == payloadKey else { return }

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
            if let pending = pendingOwnerPayloads[payloadKey] {
                guard isCurrent(pending.generation, pending.scope),
                      chatDeletionVersion(pending.chatId) == pending.deletionVersion else {
                    throw LiveEmbedError.staleContext
                }
            }
            let ownerFields = pendingOwnerPayloads[payloadKey]?.fields ?? fields
            if ownerFields["owner_pii_mappings"] != nil {
                try await persistOwnerMappings(
                    ownerFields, embedId: embedId,
                    expectedGeneration: expectedGeneration, expectedScope: expectedScope
                )
            }
            guard isCurrent(expectedGeneration, expectedScope),
                  latestPayloadByEmbed[embedId] == payloadKey else { throw LiveEmbedError.staleContext }
            if ownerFields["already_encrypted"] as? Bool == true {
                try storeAlreadyEncrypted(
                    ownerFields,
                    embedId: embedId,
                    expectedGeneration: expectedGeneration,
                    expectedScope: expectedScope
                )
            } else {
                try await encryptAndPersist(
                    ownerFields,
                    embedId: embedId,
                    payloadKey: payloadKey,
                    expectedGeneration: expectedGeneration,
                    expectedScope: expectedScope
                )
            }
            guard isCurrent(expectedGeneration, expectedScope), latestPayloadByEmbed[embedId] == payloadKey else { return }
            preparedWrites.removeValue(forKey: payloadKey)
            cancelRetry(payloadKey)
            pendingOwnerPayloads.removeValue(forKey: payloadKey)
            ownerRetryTasks[payloadKey]?.cancel()
            ownerRetryTasks[payloadKey] = nil
            processedPayloadKeys.insert(payloadKey)
            NativeDiagnostics.event("live_embed_persisted", category: "chat_stream", counts: ["children": childIds.count])
        } catch {
            let ownerFields = pendingOwnerPayloads[payloadKey]?.fields ?? fields
            if ownerFields["owner_pii_mappings"] != nil,
               isCurrent(expectedGeneration, expectedScope), latestPayloadByEmbed[embedId] == payloadKey {
                scheduleOwnerRetry(ownerFields, payloadKey: payloadKey,
                                   expectedGeneration: expectedGeneration, expectedScope: expectedScope)
            }
            if let chatId = resolveChatId(fields["chat_id"] as? String),
               isCurrent(expectedGeneration, expectedScope), latestPayloadByEmbed[embedId] == payloadKey {
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

    /// The backend sends Finance originals only in this transient owner payload.
    /// Persist the sidecar before writing or syncing the canonical embed.
    private func persistOwnerMappings(
        _ fields: [String: Any], embedId: String,
        expectedGeneration: UUID, expectedScope: UUID
    ) async throws {
        guard isCurrent(expectedGeneration, expectedScope),
              fields["already_encrypted"] as? Bool != true,
              let chatId = resolveChatId(fields["chat_id"] as? String),
              chatStore.chat(for: chatId) != nil,
              let content = fields["content"] as? String else {
            throw LiveEmbedError.invalidOwnerPIIPayload
        }
        let deletionVersion = chatDeletionVersion(chatId)
        let parsed = EmbedRecord.parseContent(content)
        let appId = fields["app_id"] as? String ?? parsed["app_id"] as? String
        let skillId = fields["skill_id"] as? String ?? parsed["skill_id"] as? String
        guard appId == "finance", skillId == "check_accounts",
              let mappings = Self.normalizedOwnerPIIMappings(fields["owner_pii_mappings"]),
              !content.contains("owner_pii_mappings"),
              !content.contains("_owner_pii_mappings"),
              mappings.allSatisfy({ mapping in
                  !content.contains(mapping.original)
                  && !(fields["text_preview"] as? String ?? "").contains(mapping.original)
              }) else {
            throw LiveEmbedError.invalidOwnerPIIPayload
        }
        guard let ownerId = await authenticatedOwnerId(),
              isCurrent(expectedGeneration, expectedScope),
              fields["user_id"] as? String == ownerId,
              let key = await masterKey(ownerId),
              isCurrent(expectedGeneration, expectedScope),
              chatDeletionVersion(chatId) == deletionVersion,
              chatStore.chat(for: chatId) != nil else {
            throw LiveEmbedError.missingEncryptionContext
        }
        try await persistOwnerPII(mappings, chatId, embedId, ownerId, key)
        guard isCurrent(expectedGeneration, expectedScope),
              chatDeletionVersion(chatId) == deletionVersion,
              chatStore.chat(for: chatId) != nil else {
            throw LiveEmbedError.staleContext
        }
    }

    static func normalizedOwnerPIIMappings(_ value: Any?) -> [PIIMapping]? {
        guard let rows = value as? [[String: Any]], !rows.isEmpty else { return nil }
        var seen = Set<String>()
        var result: [PIIMapping] = []
        for row in rows {
            guard let rawPlaceholder = row["placeholder"] as? String,
                  let rawOriginal = row["original"] as? String else { return nil }
            let placeholder = rawPlaceholder.trimmingCharacters(in: .whitespacesAndNewlines)
            let original = rawOriginal.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !placeholder.isEmpty, !original.isEmpty else { return nil }
            if seen.insert(placeholder).inserted {
                result.append(PIIMapping(placeholder: placeholder, original: original, type: "COUNTERPARTY"))
            }
        }
        return result.isEmpty ? nil : result
    }

    /// Retry the original transient payload locally: request_embed may omit its
    /// owner-only mappings after the first delivery.
    func retryPendingOwnerPersistence() async {
        for payloadKey in pendingOwnerPayloads.keys.sorted() {
            ownerRetryTasks[payloadKey]?.cancel()
            ownerRetryTasks[payloadKey] = nil
            guard let pending = pendingOwnerPayloads[payloadKey],
                  isCurrent(pending.generation, pending.scope),
                  chatDeletionVersion(pending.chatId) == pending.deletionVersion else {
                pendingOwnerPayloads.removeValue(forKey: payloadKey)
                continue
            }
            await handleEmbedData(pending.fields)
        }
    }

    private func scheduleOwnerRetry(
        _ fields: [String: Any], payloadKey: String,
        expectedGeneration: UUID, expectedScope: UUID
    ) {
        let attempt = (pendingOwnerPayloads[payloadKey]?.attempt ?? 0) + 1
        guard let chatId = resolveChatId(fields["chat_id"] as? String) else { return }
        let deletionVersion = pendingOwnerPayloads[payloadKey]?.deletionVersion
            ?? chatDeletionVersion(chatId)
        guard chatDeletionVersion(chatId) == deletionVersion else { return }
        pendingOwnerPayloads[payloadKey] = PendingOwnerPayload(
            fields: fields, chatId: chatId, deletionVersion: deletionVersion, attempt: attempt,
            generation: expectedGeneration, scope: expectedScope
        )
        ownerRetryTasks[payloadKey]?.cancel()
        ownerRetryTasks[payloadKey] = nil
        // Exhausting automatic retries must not discard the owner-only originals
        // or allow a mapping-less delivery to bypass the sidecar persistence gate.
        // Reconnect/manual retry can finish the same retained payload later.
        guard attempt <= 60, !transportPaused else { return }
        ownerRetryTasks[payloadKey] = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(3))
            guard !Task.isCancelled, let self else { return }
            self.ownerRetryTasks[payloadKey] = nil
            await self.retryPendingOwnerPersistence()
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
        payloadKey: String,
        expectedGeneration: UUID,
        expectedScope: UUID
    ) async throws {
        let server = ServerProfile.current()
        await acquireWriter(embedId)
        defer { releaseWriter(embedId) }
        guard isCurrent(expectedGeneration, expectedScope), latestPayloadByEmbed[embedId] == payloadKey,
              server == ServerProfile.current() else {
            throw LiveEmbedError.staleContext
        }
        if let prepared = preparedWrites[payloadKey] {
            try await persistPrepared(prepared)
            return
        }
        guard let rawChatId = resolveChatId(fields["chat_id"] as? String),
              chatStore.chat(for: rawChatId) != nil else {
            throw LiveEmbedError.missingEncryptionContext
        }
        let deletionVersion = chatDeletionVersion(rawChatId)
        guard let rawMessageId = fields["message_id"] as? String,
              let content = fields["content"] as? String,
              let type = fields["type"] as? String,
              let ownerId = await authenticatedOwnerId(),
              let chatKey = chatKey(rawChatId) else {
            throw LiveEmbedError.missingEncryptionContext
        }
        guard isCurrent(expectedGeneration, expectedScope), latestPayloadByEmbed[embedId] == payloadKey,
              chatDeletionVersion(rawChatId) == deletionVersion else {
            throw LiveEmbedError.staleContext
        }

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
            guard isCurrent(expectedGeneration, expectedScope), latestPayloadByEmbed[embedId] == payloadKey else { throw LiveEmbedError.staleContext }
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
            guard isCurrent(expectedGeneration, expectedScope), latestPayloadByEmbed[embedId] == payloadKey else { throw LiveEmbedError.staleContext }
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
        guard isCurrent(expectedGeneration, expectedScope), latestPayloadByEmbed[embedId] == payloadKey,
              chatDeletionVersion(rawChatId) == deletionVersion else {
            throw LiveEmbedError.staleContext
        }
        chatStore.upsertEmbeds([record], for: rawChatId)

        var storePayload: [String: Any] = [
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
        let prepared = PreparedEmbedWrite(
            payloadKey: payloadKey, embedId: embedId, chatId: rawChatId,
            deletionVersion: deletionVersion, generation: expectedGeneration, scope: expectedScope,
            head: storePayload, keys: keyPayloads, server: server
        )
        preparedWrites[payloadKey] = prepared
        try await persistPrepared(prepared)
    }

    private func persistPrepared(_ prepared: PreparedEmbedWrite) async throws {
        try validatePrepared(prepared)
        let policy = headReceiptPolicyProvider?() ?? headReceiptPolicy
        if prepared.confirmedHeadPolicy != policy {
            let requestId = UUID().uuidString
            var payload = prepared.head
            payload["request_id"] = requestId
            // sendAndWait registers its matching waiter before writing the socket.
            let receipt = try await transport.sendAndWait(
                WSOutboundMessage(type: "store_embed", payload: payload),
                responseType: "store_embed_confirmed",
                matching: { fields in
                    fields["request_id"] as? String == requestId
                        && (fields["embed_id"] as? String == prepared.embedId || fields["code"] != nil)
                }, beforeSend: { try self.validatePrepared(prepared) }
            )
            try validatePrepared(prepared)
            try CanonicalEmbedStorageReceipts.validateHead(payload: prepared.head, receipt: receipt.fields,
                requestID: requestId, policy: policy)
            prepared.confirmedHeadPolicy = policy
        }
        try validatePrepared(prepared)
        guard !prepared.keys.isEmpty else { return }
        let requestId = UUID().uuidString
        let receipt = try await transport.sendAndWait(
            WSOutboundMessage(type: "store_embed_keys", payload: ["request_id": requestId, "keys": prepared.keys]),
            responseType: "store_embed_keys_confirmed",
            matching: { $0["request_id"] as? String == requestId },
            beforeSend: { try self.validatePrepared(prepared) }
        )
        try validatePrepared(prepared)
        try CanonicalEmbedStorageReceipts.validateKeys(payload: ["keys": prepared.keys], receipt: receipt.fields,
            requestID: requestId, policy: policy)
    }

    private func validatePrepared(_ prepared: PreparedEmbedWrite) throws {
        guard isCurrent(prepared.generation, prepared.scope),
              latestPayloadByEmbed[prepared.embedId] == prepared.payloadKey,
              chatDeletionVersion(prepared.chatId) == prepared.deletionVersion,
              chatStore.chat(for: prepared.chatId) != nil,
              prepared.server == ServerProfile.current() else {
            throw LiveEmbedError.staleContext
        }
    }

    private func acquireWriter(_ embedId: String) async {
        while activeWriters.contains(embedId) {
            await withCheckedContinuation { writerWaiters[embedId, default: []].append($0) }
        }
        activeWriters.insert(embedId)
    }

    private func releaseWriter(_ embedId: String) {
        activeWriters.remove(embedId)
        let waiters = writerWaiters.removeValue(forKey: embedId) ?? []
        waiters.forEach { $0.resume() }
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
        guard isCurrent(expectedGeneration, expectedScope), chatStore.chat(for: chatId) != nil else { return }
        let attempt = (pendingRetries[payloadKey]?.attempt ?? 0) + 1
        pendingRetries[payloadKey] = PendingRetry(
            embedId: embedId,
            chatId: chatId,
            attempt: attempt,
            generation: expectedGeneration,
            scope: expectedScope
        )
        retryTasks[payloadKey]?.cancel()
        retryTasks[payloadKey] = nil
        // Stop automatic churn after three attempts, but retain the encrypted
        // identity until a duplicate delivery or reconnect can finish both saves.
        guard attempt <= 3, !transportPaused else { return }
        let delay = retryDelay(attempt)
        retryTasks[payloadKey] = Task { @MainActor [weak self] in
            try? await Task.sleep(for: delay)
            guard !Task.isCancelled, let self else { return }
            self.retryTasks[payloadKey] = nil
            await self.performRetry(payloadKey)
        }
    }

    private func performRetry(_ payloadKey: String) async {
        guard !transportPaused, let retry = pendingRetries[payloadKey] else { return }
        guard isCurrent(retry.generation, retry.scope), latestPayloadByEmbed[retry.embedId] == payloadKey else {
            cancelRetry(payloadKey)
            preparedWrites.removeValue(forKey: payloadKey)
            return
        }
        do {
            if let prepared = preparedWrites[payloadKey] {
                await acquireWriter(retry.embedId)
                defer { releaseWriter(retry.embedId) }
                // Another delivery may have completed while this retry waited.
                guard !processedPayloadKeys.contains(payloadKey) else { return }
                try await persistPrepared(prepared)
                cancelRetry(payloadKey)
                preparedWrites.removeValue(forKey: payloadKey)
                pendingOwnerPayloads.removeValue(forKey: payloadKey)
                ownerRetryTasks.removeValue(forKey: payloadKey)?.cancel()
                processedPayloadKeys.insert(payloadKey)
            } else if pendingOwnerPayloads[payloadKey] == nil {
                // Encryption context was unavailable. Re-requesting is not a
                // save receipt: keep pending state until actual persistence.
                requestedEmbedIdsByChat[retry.chatId]?.remove(retry.embedId)
                try await transport.send(WSOutboundMessage(type: "request_embed", payload: ["embed_id": retry.embedId]))
                guard isCurrent(retry.generation, retry.scope) else { return }
                requestedEmbedIdsByChat[retry.chatId, default: []].insert(retry.embedId)
            }
        } catch {
            guard isCurrent(retry.generation, retry.scope), latestPayloadByEmbed[retry.embedId] == payloadKey else { return }
            if let prepared = preparedWrites[payloadKey],
               chatDeletionVersion(prepared.chatId) != prepared.deletionVersion {
                cancelRetry(payloadKey)
                preparedWrites.removeValue(forKey: payloadKey)
                return
            }
            scheduleRetry(payloadKey: payloadKey, embedId: retry.embedId, chatId: retry.chatId,
                          expectedGeneration: retry.generation, expectedScope: retry.scope)
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
        case invalidOwnerPIIPayload
    }

    // Ciphertext and wrapped-key identity are retained across socket retries;
    // plaintext owner PII remains in its separate transient sidecar queue.
    private final class PreparedEmbedWrite {
        let payloadKey: String
        let embedId: String
        let chatId: String
        let deletionVersion: Int
        let generation: UUID
        let scope: UUID
        let head: [String: Any]
        let keys: [[String: Any]]
        let server: ServerProfile
        var confirmedHeadPolicy: HeadReceiptPolicy?

        init(payloadKey: String, embedId: String, chatId: String, deletionVersion: Int,
             generation: UUID, scope: UUID, head: [String: Any], keys: [[String: Any]], server: ServerProfile) {
            self.payloadKey = payloadKey
            self.embedId = embedId
            self.chatId = chatId
            self.deletionVersion = deletionVersion
            self.generation = generation
            self.scope = scope
            self.head = head
            self.keys = keys
            self.server = server
        }
    }

    private struct PendingOwnerPayload {
        let fields: [String: Any]
        let chatId: String
        let deletionVersion: Int
        let attempt: Int
        let generation: UUID
        let scope: UUID
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
    func sendAndWait(
        _ message: WSOutboundMessage,
        responseType: String,
        timeout: Duration,
        matching predicate: @escaping ([String: Any]) -> Bool,
        beforeSend: @escaping @MainActor () throws -> Void
    ) async throws -> WebSocketResponse
    func waitForMessage(
        _ type: String,
        timeout: Duration,
        matching predicate: @escaping ([String: Any]) -> Bool
    ) async throws -> WebSocketResponse
}

private enum ChatTransportFenceError: Error { case unsupported }

extension ChatWebSocketTransport {
    func sendAndWait(
        _ message: WSOutboundMessage,
        responseType: String,
        timeout: Duration,
        matching predicate: @escaping ([String: Any]) -> Bool,
        beforeSend: @escaping @MainActor () throws -> Void
    ) async throws -> WebSocketResponse {
        // Never implement a fence by checking before a transport's queued send.
        // Concrete transports must validate at their actual send boundary.
        throw ChatTransportFenceError.unsupported
    }

    func sendAndWait(
        _ message: WSOutboundMessage,
        responseType: String,
        matching predicate: @escaping ([String: Any]) -> Bool,
        beforeSend: @escaping @MainActor () throws -> Void
    ) async throws -> WebSocketResponse {
        try await sendAndWait(message, responseType: responseType, timeout: .seconds(20),
                              matching: predicate, beforeSend: beforeSend)
    }

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

// Only fresh decoder-owned values cross this boundary; callers never share
// mutable models or JSONDecoder instances with the worker actor.
struct NativeDecodedSyncValue<Value>: @unchecked Sendable {
    let value: Value
    let decodedOnMainThread: Bool
}

actor NativeSyncPayloadDecoder {
    static let shared = NativeSyncPayloadDecoder()

    func decode<Value: Decodable>(_ type: Value.Type, from raw: Data) throws -> NativeDecodedSyncValue<Value> {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return NativeDecodedSyncValue(value: try decoder.decode(type, from: raw),
                                      decodedOnMainThread: Thread.isMainThread)
    }

    func legacyFields(from raw: Data) throws -> WebSocketResponse {
        let envelope = try JSONSerialization.jsonObject(with: raw) as? [String: Any] ?? [:]
        return WebSocketResponse(fields: envelope["payload"] as? [String: Any]
            ?? envelope["data"] as? [String: Any] ?? envelope)
    }

    func decodeFields<Value: Decodable>(_ type: Value.Type, response: WebSocketResponse) throws -> NativeDecodedSyncValue<Value> {
        try decode(type, from: JSONSerialization.data(withJSONObject: response.fields))
    }
}

struct ChatCompressionNotificationReceipt: Sendable {
    let accountScope: UUID
    let transportGeneration: Int?
    let decoded: WebSocketResponse?
    let raw: Data?

    init?(_ notification: Notification) {
        guard let scope = notification.userInfo?["accountScope"] as? UUID else { return nil }
        accountScope = scope
        transportGeneration = notification.userInfo?["transportGeneration"] as? Int
        decoded = notification.userInfo?["decoded"] as? WebSocketResponse
        raw = notification.userInfo?["raw"] as? Data
        guard decoded != nil || raw != nil else { return nil }
    }

    func matches(scope: UUID, transport: Int) -> Bool {
        accountScope == scope && (transportGeneration == nil || transportGeneration == transport)
    }

    func fields() async throws -> WebSocketResponse {
        if let decoded { return decoded }
        guard let raw else { throw CocoaError(.coderReadCorrupt) }
        return try await NativeSyncPayloadDecoder.shared.legacyFields(from: raw)
    }
}

actor WebSocketInboundDecoder {
    struct Frame: Sendable {
        let parsed: WSInboundParsed
        let raw: Data
        let decodedOnMainThread: Bool
    }

    func decode(_ message: URLSessionWebSocketTask.Message) throws -> Frame {
        let data: Data
        switch message {
        case .string(let text): data = Data(text.utf8)
        case .data(let value): data = value
        @unknown default: throw CocoaError(.coderReadCorrupt)
        }
        return Frame(parsed: try JSONDecoder().decode(WSInboundParsed.self, from: data), raw: data,
                     decodedOnMainThread: Thread.isMainThread)
    }
}

// JSONDecoder creates immutable scalar/array/dictionary values owned by this
// frame. They are never mutated after decoding and may cross the decode actor.
struct WSInboundParsed: Decodable, @unchecked Sendable {
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

    /// Retained turns reopen Foundation JSON numbers. Preserve their numeric
    /// identity rather than passing NSNumber(0/1) through a Bool-first encoder.
    /// Optional envelope fields stay omitted; explicitly empty fields stay empty.
    func encodedData() throws -> Data {
        var envelope: [String: Any] = ["type": type]
        if let data { envelope["data"] = data.mapValues(\.value) }
        if let payload { envelope["payload"] = payload.mapValues(\.value) }
        guard JSONSerialization.isValidJSONObject(envelope) else {
            throw WebSocketError.encodingFailed
        }
        return try JSONSerialization.data(withJSONObject: envelope)
    }

    func encode(to encoder: Encoder) throws {
        // Preserve the existing Encodable API used by recording transports.
        // JSONDecoder produces Swift scalars, avoiding Foundation Bool bridging
        // when these validated values pass through AnyCodable's encoder.
        let values = try JSONDecoder().decode([String: AnyCodable].self, from: encodedData())
        var container = encoder.singleValueContainer()
        try container.encode(values)
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
    let lifetime: WebSocketWaiterLifetime
}

private final class WebSocketWaiterLifetime: @unchecked Sendable {
    private let lock = NSLock()
    private var cancelled = false
    private var tasks: [Task<Void, Never>] = []

    var isCancelled: Bool { lock.withLock { cancelled } }

    func add(_ task: Task<Void, Never>) {
        let cancelImmediately = lock.withLock {
            if cancelled { return true }
            tasks.append(task)
            return false
        }
        if cancelImmediately { task.cancel() }
    }

    func cancel() {
        let pending = lock.withLock {
            cancelled = true
            let pending = tasks
            tasks.removeAll()
            return pending
        }
        pending.forEach { $0.cancel() }
    }
}

/// Keeps untyped decoded WebSocket JSON at the main-actor transport boundary.
struct WebSocketResponse: @unchecked Sendable {
    let fields: [String: Any]
    var type: String? = nil
}

// MARK: - Notifications

extension Notification.Name {
    static let compressionCheckpointPersisted = Notification.Name("openmates.compressionCheckpointPersisted")
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
