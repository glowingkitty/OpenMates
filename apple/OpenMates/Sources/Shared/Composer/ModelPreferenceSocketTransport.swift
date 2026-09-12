import Foundation

// One app-owned instance must be shared across windows, never per-composer.
@MainActor final class ModelPreferenceSocketTransport {
    private struct Lane { let id: UUID; let completion: Task<Void, Never> }
    private var lanes: [ModelPreferenceScope: Lane] = [:]
    typealias Exchange = @MainActor (String, [String: Any], Set<String>, Duration) async throws -> ModelPreferenceWireResponse
    private let generation: () -> Int
    private let exchange: Exchange
    private let current: () -> ModelPreferenceConnection?
    init(socket: WebSocketManager, current: @escaping () -> ModelPreferenceConnection?) {
        self.generation = { socket.modelPreferenceSocketGeneration }; self.current = current
        self.exchange = { type, payload, events, timeout in
            guard socket.isConnected else { throw WebSocketError.notConnected }
            let response = try await socket.sendAndWait(WSOutboundMessage(type: type, payload: payload), responseTypes: events, timeout: timeout) {
                $0["chat_id"] as? String == payload["chat_id"] as? String
            }
            guard let type = response.type else { throw ModelPreferenceFailure.invalidAcknowledgement }
            return ModelPreferenceWireResponse(type: type, fields: response.fields)
        }
    }
    init(current: @escaping () -> ModelPreferenceConnection?, generation: @escaping () -> Int, exchange: @escaping Exchange) {
        self.current = current; self.generation = generation; self.exchange = exchange
    }
    func request(_ connection: ModelPreferenceConnection, type: String, payload: [String: Any], events: Set<String>, timeout: Duration) async throws -> ModelPreferenceWireResponse {
        guard let chat = payload["chat_id"] as? String else { throw ModelPreferenceFailure.invalidPayload }
        let scope = ModelPreferenceScope(server: connection.server, userID: connection.userID, chatID: chat)
        let previous = lanes[scope]?.completion
        let id = UUID()
        // Identity is captured BEFORE suspension in the previous lane.
        let expectedGeneration = generation()
        let operation = Task { @MainActor [self] in
            await previous?.value
            try Task.checkCancellation()
            guard current() == connection, generation() == expectedGeneration,
                  expectedGeneration == connection.socketGeneration else { throw ModelPreferenceFailure.staleContext }
            let response = try await exchange(type, payload, events, timeout)
            guard current() == connection, generation() == expectedGeneration else { throw ModelPreferenceFailure.staleContext }
            return response
        }
        lanes[scope] = Lane(id: id, completion: Task { _ = try? await operation.value })
        defer { if lanes[scope]?.id == id { lanes.removeValue(forKey: scope) } }
        return try await withTaskCancellationHandler(operation: { try await operation.value }, onCancel: { operation.cancel() })
    }
}

// App-wide encrypted subscription. It does not need a currently visible composer
// and never decrypts metadata for background chats. Current ownership is injected
// from the account-scoped authoritative ChatStore, not inferred from event IDs.
@MainActor final class ModelPreferenceInboundCoordinator {
    private let repository: ModelPreferenceEncryptedRepository
    private let current: () -> ModelPreferenceConnection?
    private let ownsChat: (String) -> Bool
    private var waitingForOwnership: [String: (ModelPreferenceConnection, String, [String: Any])] = [:]
    private var listeners: [UUID: (ModelPreferenceScope, EncryptedModelPreference) -> Void] = [:]
    init(repository: ModelPreferenceEncryptedRepository, current: @escaping () -> ModelPreferenceConnection?, ownsChat: @escaping (String) -> Bool) {
        self.repository = repository; self.current = current; self.ownsChat = ownsChat
    }
    func subscribe(_ listener: @escaping (ModelPreferenceScope, EncryptedModelPreference) -> Void) -> UUID {
        let id = UUID(); listeners[id] = listener; return id
    }
    func unsubscribe(_ id: UUID) { listeners.removeValue(forKey: id) }
    func ownershipDidChange() throws {
        let pending = waitingForOwnership
        waitingForOwnership.removeAll()
        for (chatID, value) in pending where value.0 == current() {
            if ownsChat(chatID) { try receive(type: value.1, fields: value.2, generation: value.0.socketGeneration) }
            else { waitingForOwnership[chatID] = value }
        }
    }
    func clearAccount() { waitingForOwnership.removeAll(); listeners.removeAll() }
    func receive(type: String, fields: [String: Any], generation: Int) throws {
        guard ["chat_model_preference", "chat_model_preference_updated", "chat_model_preference_synced"].contains(type),
              let context = current(), context.socketGeneration == generation,
              let chatID = fields["chat_id"] as? String else { return }
        waitingForOwnership = waitingForOwnership.filter { $0.value.0 == context }
        guard ownsChat(chatID) else {
            let incomingVersion = (fields["preference"] as? [String: Any])?["preference_v"] as? Int ?? -1
            let priorVersion = (waitingForOwnership[chatID]?.2["preference"] as? [String: Any])?["preference_v"] as? Int ?? -1
            guard incomingVersion >= priorVersion else { return }
            // Bounded metadata race buffer; never evict staged disk intent.
            if waitingForOwnership[chatID] == nil && waitingForOwnership.count >= 512 { return }
            waitingForOwnership[chatID] = (context, type, fields)
            return
        }
        guard let raw = fields["preference"] as? [String: Any] else { return }
        guard let ciphertext = raw["encrypted_selected_ai_model"] as? String, !ciphertext.isEmpty,
              let version = raw["preference_v"] as? Int, version >= 0 else { throw ModelPreferenceFailure.invalidPayload }
        let scope = ModelPreferenceScope(server: context.server, userID: context.userID, chatID: chatID)
        let incoming = EncryptedModelPreference(ciphertext: ciphertext, version: version)
        let retained: EncryptedModelPreference
        if let local = try repository.read(scope), let expected = local.pendingExpectedVersion {
            if incoming.ciphertext == local.ciphertext && incoming.version >= expected + 1 {
                try repository.write(incoming, scope: scope); retained = incoming
            } else { retained = local }
        } else { retained = try repository.writeIfNewer(incoming, scope: scope) }
        // Never dispatch provisional records as remote ACKs; staged intent stays
        // visible in its owner's service until restore/retry reconciles it.
        if retained.pendingExpectedVersion == nil {
            for listener in listeners.values { listener(scope, retained) }
        }
    }
}

// Socket lanes alone are insufficient: two windows could stage competing local
// records before either ACK, letting the first ACK erase the second outbox.
// Serialize the complete mutation while retaining parallelism across chats.
@MainActor final class ModelPreferenceMutationCoordinator {
    private struct Lane { let id: UUID; let completion: Task<Void, Never> }
    private var lanes: [ModelPreferenceScope: Lane] = [:]
    func perform(_ scope: ModelPreferenceScope, operation: @escaping @MainActor () async throws -> String) async throws -> String {
        let previous = lanes[scope]?.completion
        let id = UUID()
        let task = Task { @MainActor in
            await previous?.value
            try Task.checkCancellation()
            return try await operation()
        }
        lanes[scope] = .init(id: id, completion: Task { _ = try? await task.value })
        defer { if lanes[scope]?.id == id { lanes.removeValue(forKey: scope) } }
        return try await withTaskCancellationHandler(operation: { try await task.value }, onCancel: { task.cancel() })
    }
}
