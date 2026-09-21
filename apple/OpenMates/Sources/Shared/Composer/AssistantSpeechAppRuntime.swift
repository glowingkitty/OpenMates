import Foundation
import Combine

// One app-scoped provider playback owner. OfflineStore's scope ID is already a
// digest of actual account + API base URL, and generation changes on logout.
@MainActor
final class AssistantSpeechAppRuntime {
    static let shared = AssistantSpeechAppRuntime()
    private weak var store: ChatStore?
    private weak var socket: WebSocketManager?
    private var scopeGeneration = UUID()
    private var sessionGeneration = UUID()
    private var activationGeneration = UUID()
    private var promotionTasks: [String: Task<Void, Never>] = [:]
    private let player = AssistantSpeechAudioPlayer()
    private var controllers: [String: NativeAssistantSpeech] = [:]
    private var outgoing: [String: String] = [:]
    private var pendingCommitUserIDs: [String: String] = [:]
    private var committedChats = Set<String>()
    private var activeChatID: String?
    private var activeOwnerID: UUID?
    private var metadataSubscription: AnyCancellable?
    private var knownCiphertexts: [String: String] = [:]
    private var earlyEvents: [String: AssistantSpeechEarlyEvents] = [:]
    private lazy var preference = AssistantSpeechPreferenceAdapter(dependencies: .init(
        isCurrent: { [weak self] in self?.current($0) == true },
        metadata: { [weak self] scope in self?.metadata(scope) },
        chatKey: { scope in
            guard let key = ChatKeyManager.shared.key(for: scope.chatID) else { throw WebSocketError.notConnected }
            return key
        },
        sendMetadataAndWait: { [weak self] scope, fields, minimum in
            guard let self, current(scope), let socket else { throw CancellationError() }
            let generation = socket.transportGeneration
            let response = try await socket.sendAndWait(.init(type: "encrypted_chat_metadata", payload: fields),
                responseType: "encrypted_metadata_stored", timeout: .seconds(15)) { payload in
                    AssistantSpeechMetadataAcknowledgement.version(payload, chatID: scope.chatID, minimum: minimum) != nil
                }
            guard current(scope) else { throw CancellationError() }
            guard socket.transportGeneration == generation else { throw WebSocketError.notConnected }
            guard let version = AssistantSpeechMetadataAcknowledgement.version(response.fields, chatID: scope.chatID, minimum: minimum) else {
                throw AssistantSpeechFailure.invalidAcknowledgement
            }
            return version
        },
        storeCiphertext: { [weak self] scope, ciphertext, version in
            guard let self, current(scope), let row = store?.chat(for: scope.chatID) else { throw CancellationError() }
            guard (row.metadataV ?? row.titleV ?? 0) <= version else { throw AssistantSpeechFailure.preferenceChangedElsewhere }
            store?.upsertChat(row.withSpeechPreference(ciphertext, metadataVersion: version))
        }
    ))
    func configure(store: ChatStore, socket: WebSocketManager) {
        if self.store === store, self.socket === socket,
           scopeGeneration == OfflineStore.shared.scopeGeneration { return }
        reset()
        self.store = store; self.socket = socket; scopeGeneration = OfflineStore.shared.scopeGeneration
        metadataSubscription = store.$chats.sink { [weak self] chats in
            guard let self else { return }
            for chat in chats {
                if (chat.messagesV ?? 0) > 0, committedChats.contains(chat.id), let scope = scope(for: chat.id) {
                    schedulePromotion(scope)
                }
                guard let cipher = chat.encryptedAutoSpeakResponse,
                      knownCiphertexts[chat.id] != cipher else { continue }
                knownCiphertexts[chat.id] = cipher
                if let control = controllers[chat.id], control.ready {
                    Task { await control.refreshPreference() }
                }
            }
        }
    }
    func scope(for chatID: String) -> AssistantSpeechScope? {
        guard store != nil, socket != nil, let identity = OfflineStore.shared.activeScopeId,
              scopeGeneration == OfflineStore.shared.scopeGeneration else { return nil }
        return .init(accountID: identity, serverID: identity, chatID: chatID, sessionID: sessionGeneration)
    }
    private func current(_ scope: AssistantSpeechScope) -> Bool { self.scope(for: scope.chatID) == scope }
    func controller(for chatID: String) -> NativeAssistantSpeech {
        if let value = controllers[chatID] { return value }
        let value = NativeAssistantSpeech(dependencies: .init(
            readPreference: { [weak self] scope in
                guard let self else { throw CancellationError() }; return try await preference.read(scope)
            },
            writePreference: { [weak self] scope, enabled in
                guard let self else { throw CancellationError() }; try await preference.write(scope, enabled: enabled)
            },
            resolveAudio: { [weak self] scope, asset in
                guard let self else { throw CancellationError() }
                let media = AssistantSpeechNativeMedia(resolveEmbed: { [weak self] scope, id in
                    guard let self else { throw CancellationError() }; return try await resolve(scope, assetID: id)
                }, isCurrent: { [weak self] in self?.current($0) == true })
                return try await media.audio(scope, assetID: asset)
            }, play: { [weak self] bytes in
                guard let self, activeChatID == chatID else { throw CancellationError() }; try await player.play(bytes)
            }, stopPlayback: { [weak self] in if self?.activeChatID == chatID { self?.player.stop() } },
            cancelResponse: { [weak self] scope, id in
                guard let self, current(scope), let socket else { return }
                try await socket.send(.init(type: "assistant_speech", payload: ["action": "cancel",
                    "chat_id": scope.chatID, "assistant_message_id": id]))
            }, canPlay: { [weak self] scope in self?.current(scope) == true && self?.activeChatID == scope.chatID }))
        controllers[chatID] = value; return value
    }
    func activate(chatID: String, supported: Bool, ownerID: UUID) async -> NativeAssistantSpeech {
        let activation = UUID(); activationGeneration = activation
        let expectedSession = sessionGeneration
        let control = controller(for: chatID)
        if let previous = activeChatID, previous != chatID { await controllers[previous]?.stop() }
        guard activationGeneration == activation, sessionGeneration == expectedSession, !Task.isCancelled else { return control }
        activeChatID = chatID; activeOwnerID = ownerID
        await control.activate(supported ? scope(for: chatID) : nil)
        if activationGeneration == activation, sessionGeneration == expectedSession, !Task.isCancelled {
            control.resumePlaybackIfReady()
        }
        return control
    }
    func deactivate(chatID: String, ownerID: UUID, controller: NativeAssistantSpeech?) {
        guard activeChatID == chatID, activeOwnerID == ownerID, let controller, controllers[chatID] === controller else { return }
        controller.detach()
        activeChatID = nil; activeOwnerID = nil
    }
    func transferDraft(from source: AssistantSpeechScope?, to chatID: String) async throws {
        guard let source else { return }
        guard current(source), let destination = scope(for: chatID) else { throw CancellationError() }
        // An unresolved user-visible toggle/load error requires Retry; do not
        // erase that intent by falling back to the controller's previous value.
        if controllers[source.chatID]?.error != nil { throw AssistantSpeechFailure.preferenceBusy }
        try await preference.transferDraft(from: source, to: destination)
        guard current(source) else { throw CancellationError() }
        await controller(for: chatID).activate(destination)
    }
    func requireCurrent(_ scope: AssistantSpeechScope, socket: WebSocketManager) throws {
        try Task.checkCancellation()
        guard self.socket === socket, current(scope) else { throw CancellationError() }
    }
    func prepareSend(chat: Chat, userMessageID: String, socket: WebSocketManager, expectedScope: AssistantSpeechScope?) async throws -> [String: Any] {
        guard !IncognitoChatSession.isIncognitoChatId(chat.id), let scope = expectedScope else { return [:] }
        try requireCurrent(scope, socket: socket)
        let control = controller(for: chat.id)
        if control.scope != scope { await control.activate(scope) }
        guard current(scope), control.scope == scope, !Task.isCancelled else { throw CancellationError() }
        // A pending write cannot become a silent false/no-speech preflight.
        guard control.ready else { throw WebSocketError.notConnected }
        let fields = control.messageFields(for: scope)
        earlyEvents.removeValue(forKey: chat.id)
        if (chat.messagesV ?? 0) > 0 { committedChats.insert(chat.id) }
        pendingCommitUserIDs[chat.id] = userMessageID
        if !fields.isEmpty { outgoing[chat.id] = userMessageID }
        else { outgoing.removeValue(forKey: chat.id) }
        return fields
    }
    func receive(type: String, fields: [String: Any], from socket: WebSocketManager) {
        guard self.socket === socket, scopeGeneration == OfflineStore.shared.scopeGeneration,
              let chatID = fields["chat_id"] as? String, let scope = scope(for: chatID) else { return }
        if type == "ai_task_initiated", let userID = fields["user_message_id"] as? String,
           pendingCommitUserIDs[chatID] == userID {
            // The inference receipt follows the server's durable user-turn commit;
            // an optimistic local messages_v alone is not this boundary.
            pendingCommitUserIDs.removeValue(forKey: chatID)
            committedChats.insert(chatID); schedulePromotion(scope)
        }
        if type == "encrypted_chat_metadata", let cipher = fields["encrypted_auto_speak_response"] as? String,
           let row = store?.chat(for: chatID),
           let version = (fields["versions"] as? [String: Any])?["metadata_v"] as? Int,
           version >= (row.metadataV ?? row.titleV ?? 0) {
            store?.upsertChat(row.withSpeechPreference(cipher, metadataVersion: version))
            return
        }
        if let messageID = Self.correlatedAssistantMessageID(type: type, fields: fields,
            chatID: chatID, expectedUserMessageID: outgoing[chatID]) {
            let control = controller(for: chatID)
            if outgoing.removeValue(forKey: chatID) != nil { control.expectResponse(messageID, in: scope) }
            for event in earlyEvents.removeValue(forKey: chatID)?.events ?? [] { control.receive(event, in: scope) }
        } else if type == "assistant_speech_status" {
            guard let data = try? JSONSerialization.data(withJSONObject: fields),
                  let event = try? JSONDecoder().decode(AssistantSpeechStatus.self, from: data) else { return }
            if outgoing[chatID] != nil {
                var values = earlyEvents[chatID] ?? AssistantSpeechEarlyEvents()
                values.append(event); earlyEvents[chatID] = values
            } else { controllers[chatID]?.receive(event, in: scope) }
        }
    }
    private func schedulePromotion(_ scope: AssistantSpeechScope) {
        guard current(scope), committedChats.contains(scope.chatID), preference.hasIntent(scope),
              promotionTasks[scope.chatID] == nil else { return }
        promotionTasks[scope.chatID] = Task { [weak self] in
            await Task.yield()
            guard let self, current(scope) else { return }
            defer { if current(scope) { promotionTasks.removeValue(forKey: scope.chatID) } }
            do { try await preference.promote(scope) }
            catch {
                guard current(scope), !(error is CancellationError) else { return }
                controllers[scope.chatID]?.reportPromotionFailure(error)
            }
        }
    }
    static func correlatedAssistantMessageID(type: String, fields: [String: Any], chatID: String, expectedUserMessageID: String?) -> String? {
        guard ["ai_typing_started", "ai_message_update"].contains(type),
              fields["chat_id"] as? String == chatID,
              let expectedUserMessageID, !expectedUserMessageID.isEmpty,
              fields["user_message_id"] as? String == expectedUserMessageID,
              let assistantID = fields["message_id"] as? String, !assistantID.isEmpty else { return nil }
        return assistantID
    }
    func reset() {
        sessionGeneration = UUID(); activationGeneration = UUID()
        metadataSubscription = nil; knownCiphertexts.removeAll()
        promotionTasks.values.forEach { $0.cancel() }; promotionTasks.removeAll()
        controllers.values.forEach { $0.reset() }; controllers.removeAll()
        preference.clear(); outgoing.removeAll(); earlyEvents.removeAll(); player.stop()
        pendingCommitUserIDs.removeAll(); committedChats.removeAll()
        activeChatID = nil; activeOwnerID = nil; store = nil; socket = nil
    }
    private func metadata(_ scope: AssistantSpeechScope) -> AssistantSpeechMetadata? {
        guard current(scope), let chat = store?.chat(for: scope.chatID) else { return nil }
        return .init(encryptedPreference: chat.encryptedAutoSpeakResponse, encryptedChatKey: chat.encryptedChatKey,
            teamID: nil, messagesVersion: chat.messagesV ?? 0, titleVersion: chat.titleV ?? 0,
            metadataVersion: chat.metadataV ?? chat.titleV ?? 0,
            lastEditedTimestamp: Int(chat.updatedDate?.timeIntervalSince1970 ?? 0))
    }
    private func resolve(_ scope: AssistantSpeechScope, assetID: String) async throws -> EmbedRecord {
        // Provider readiness can arrive before encrypted embed sync. Match the web's
        // bounded hydration retry instead of requiring a tap on every fresh segment.
        for attempt in 0..<4 {
            do { return try await resolveOnce(scope, assetID: assetID) }
            catch let error as CocoaError where error.code == .fileReadNoSuchFile {
                guard attempt < 3, current(scope) else { throw error }
                try await Task.sleep(nanoseconds: 250_000_000)
                guard current(scope) else { throw CancellationError() }
            }
        }
        throw CocoaError(.fileReadNoSuchFile)
    }
    private func resolveOnce(_ scope: AssistantSpeechScope, assetID: String) async throws -> EmbedRecord {
        guard current(scope), let socket, store?.chat(for: scope.chatID) != nil else { throw CancellationError() }
        let generation = socket.transportGeneration
        try Task.checkCancellation()
        let bareID = assetID.hasPrefix("embed:") ? String(assetID.dropFirst(6)) : assetID
        // A response paragraph must not fetch/decode the entire conversation.
        // Reuse the web's exact request_embed protocol and its scoped encrypted
        // keys; fresh provider assets may still exist only in the server cache.
        let response = try await socket.sendAndWait(.init(type: "request_embed", payload: ["embed_id": bareID]),
            responseType: "send_embed_data", timeout: .seconds(15)) { fields in
                fields["embed_id"] as? String == bareID
            }
        guard current(scope) else { throw CancellationError() }
        guard socket.transportGeneration == generation else { throw WebSocketError.notConnected }
        let asset = try AssistantSpeechEmbedPayload.decode(response.fields, assetID: bareID, chatID: scope.chatID)
        let record = asset.record
        try Task.checkCancellation()
        EmbedKeyManager.shared.store(asset.keys, source: "assistantSpeech")
        OfflineStore.shared.persistEmbedKeys(asset.keys)
        if record.rawData != nil { return record }
        guard let key = await EmbedKeyManager.shared.key(for: record, chatId: scope.chatID,
                    allEmbeds: EmbedRecord.dictionaryById((store?.embeds(for: scope.chatID) ?? []) + [record], context: "assistantSpeech")) else { throw CocoaError(.fileReadNoPermission) }
        guard current(scope) else { throw CancellationError() }
        guard socket.transportGeneration == generation else { throw WebSocketError.notConnected }
        var content: String?, type: String?
        if let value = record.encryptedContent { content = try await CryptoManager.shared.decryptContent(base64String: value, key: key) }
        if let value = record.encryptedType { type = try await CryptoManager.shared.decryptContent(base64String: value, key: key) }
        guard current(scope) else { throw CancellationError() }
        guard socket.transportGeneration == generation else { throw WebSocketError.notConnected }
        return record.decryptedCopy(content: content, type: type)
    }
}

// Wire normalization only: EmbedRecord remains the single TOON/JSON parser.
struct AssistantSpeechEmbedPayload {
    let record: EmbedRecord
    let keys: [EmbedKeyRecord]
    static func decode(_ fields: [String: Any], assetID: String, chatID: String) throws -> Self {
        let hashedChatID = ChatKeyWrapperRecord.hashedChatId(for: chatID)
        guard fields["embed_id"] as? String == assetID,
              let returnedChat = fields["chat_id"] as? String,
              returnedChat == chatID || returnedChat == hashedChatID else { throw CocoaError(.fileReadNoPermission) }
        if ["error", "cancelled"].contains(fields["status"] as? String ?? "") { throw CocoaError(.fileReadNoSuchFile) }
        var normalized = fields
        normalized["hashed_chat_id"] = hashedChatID
        if fields["already_encrypted"] as? Bool == true {
            normalized["encrypted_content"] = fields["content"]
            if fields["type"] as? String == "app_skill_use" {
                // request_embed's documented fallback when a legacy record has
                // encrypted content but no encrypted_type.
                normalized["type"] = "app_skill_use"
            } else {
                normalized["encrypted_type"] = fields["type"]
                normalized.removeValue(forKey: "type")
            }
            normalized.removeValue(forKey: "content")
        }
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        let record = try decoder.decode(EmbedRecord.self, from: JSONSerialization.data(withJSONObject: normalized))
        let keys = try decoder.decode([EmbedKeyRecord].self, from: JSONSerialization.data(withJSONObject: fields["embed_keys"] ?? []))
        return Self(record: record, keys: keys.filter {
            $0.hashedEmbedId == ChatKeyWrapperRecord.hashedChatId(for: assetID) &&
            ($0.hashedChatId == nil || $0.hashedChatId == hashedChatID)
        })
    }
}

// Keep one latest status per segment, not the last N lifecycle transitions.
// Otherwise a long accepted/generating/ready burst discards sequence zero.
struct AssistantSpeechEarlyEvents {
    private var values: [String: AssistantSpeechStatus] = [:]
    private var order: [String] = []
    private var overflow: AssistantSpeechStatus?
    var events: [AssistantSpeechStatus] { order.compactMap { values[$0] } + (overflow.map { [$0] } ?? []) }
    mutating func append(_ event: AssistantSpeechStatus) {
        guard let message = event.message_id else { return }
        if let children = event.segments {
            for child in children {
                append(.init(chat_id: event.chat_id, message_id: message, status: child.status,
                    segment_id: child.segment_id, sequence: child.sequence,
                    generated_asset_id: child.generated_asset_id, segments: nil))
            }
            return
        }
        let key = message + ":" + (event.segment_id ?? "control")
        if values[key]?.status == "ready", ["queued", "generating"].contains(event.status ?? "") { return }
        if values[key] == nil {
            guard order.count < 64 else {
                overflow = .init(chat_id: event.chat_id, message_id: message, status: "error",
                    segment_id: nil, sequence: nil, generated_asset_id: nil, segments: nil)
                return
            }
            order.append(key)
        }
        values[key] = event
    }
}

// Backend acknowledgements have no request nonce. They do echo message_id;
// exclude user-message persistence ACKs and serialize this chat's speech writes
// through its app-owned adapter. Never fabricate an acknowledged version.
enum AssistantSpeechMetadataAcknowledgement {
    static func version(_ fields: [String: Any], chatID: String, minimum: Int) -> Int? {
        guard fields["chat_id"] as? String == chatID,
              fields["message_id"] == nil || fields["message_id"] is NSNull,
              fields["status"] as? String == "queued_for_storage",
              let version = (fields["versions"] as? [String: Any])?["metadata_v"] as? Int,
              version >= minimum else { return nil }
        return version
    }
}
