// Web sources: services/voiceCall.ts, voiceCallMessages.ts, voiceCallPrivacy.ts.
// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.fixed-binding, video-call.chat.transcripts,
// video-call.chat.compressed-context, video-call.privacy.first-call-warning,
// video-call.audio.spoken-rich-response, video-call.audio.complete-turn-admission, video-call.audio.intentional-interruption
#if !os(watchOS)
import Foundation
import CryptoKit

/// Root passes its allocated draft UUID; this factory never creates an alternate
/// chat identity. Existing chats must already have their canonical key wrapper.
enum NativeVoiceCallAppDestination: Sendable {
    case existing(chatID: String)
    case newPersonal(chatID: UUID, mateCategory: String)
}

@MainActor
protocol NativeVoiceCallAppDriving: AnyObject {
    func bind(consent: @escaping @MainActor @Sendable () async -> Bool,
              event: @escaping @MainActor @Sendable (NativeVoiceCallEvent) async -> Void)
    func start(_ destination: NativeVoiceCallAppDestination) async throws
    func sendText(_ text: String) async throws -> String
    func setMuted(_ muted: Bool) async
    func hangup() async
    func invalidate() async
    func snapshot() async -> NativeVoiceCallSnapshot
    func respondToTool(_ frame: NativeVoiceCallFrame) async throws
}

/// Retain once per authenticated app root, outside navigation destinations.
/// All transport requests use the real owner/profile/workspace and personal
/// context fences. No overview page is used to assert history completeness.
@MainActor
final class NativeVoiceCallAppFactory: NativeVoiceCallAppDriving {
    private let auth: AuthManager
    private let store: ChatStore
    private let socket: WebSocketManager
    private let profile: ServerProfile
    private let ordinaryInferenceActive: @MainActor (String) -> Bool
    private var consent: (@MainActor @Sendable () async -> Bool)?
    private var downstream: (@MainActor @Sendable (NativeVoiceCallEvent) async -> Void)?
    private var binding: (scope: NativeVoiceCallScope, team: TeamWorkspaceSnapshot, keyGeneration: UUID)?
    private var prepared: (chat: Chat, needsConfirmation: Bool)?
    private var metadata: NativeVoiceCallFrame = [:]
    private var pump: Task<Void, Never>?
    private var pumpDirty = false
    private var pumpID: UUID?
    private let directory: URL
    private let sendPipeline = ChatSendPipeline()

    init(auth: AuthManager, store: ChatStore, socket: WebSocketManager,
         ordinaryInferenceActive: @escaping @MainActor (String) -> Bool) {
        self.auth = auth; self.store = store; self.socket = socket
        self.profile = ServerProfile.current(); self.ordinaryInferenceActive = ordinaryInferenceActive
        directory = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("OpenMates/voice-call", isDirectory: true)
    }
    func bind(consent: @escaping @MainActor @Sendable () async -> Bool,
              event: @escaping @MainActor @Sendable (NativeVoiceCallEvent) async -> Void) {
        self.consent = consent; downstream = event
    }
    private func check(_ scope: NativeVoiceCallScope) throws {
        guard !Task.isCancelled, let binding, binding.scope == scope,
              auth.state == .authenticated, auth.currentUser?.id == scope.accountID,
              profile == ServerProfile.current(), scope.profileID == profile.id,
              scope.workspaceGeneration == OfflineStore.shared.scopeGeneration,
              binding.keyGeneration == ChatKeyManager.shared.cacheGeneration,
              binding.team.teamID == nil, TeamWorkspaceContext.shared.isCurrent(binding.team)
        else { throw NativeVoiceCallError.scopeChanged }
    }
    private func current(_ scope: NativeVoiceCallScope) -> Bool { (try? check(scope)) != nil }
    private lazy var crypto = NativeVoiceCallChatCryptography(key: { @MainActor [weak self] scope in
        guard let self else { throw NativeVoiceCallError.scopeChanged }; try check(scope)
        guard let key = ChatKeyManager.shared.key(for: scope.chatID) else { throw NativeVoiceCallError.contextUnavailable }
        return key
    }, isCurrent: { [weak self] scope in await self?.current(scope) == true })
    private lazy var storage = NativeVoiceCallFileOutboxStorage(directory: directory)
    private lazy var canonical = NativeVoiceCallCanonicalPersistence(crypto: crypto,
        storage: NativeVoiceCallFileAuxiliaryStorage(directory: directory),
        isCurrent: { [weak self] scope in await self?.current(scope) == true },
        keyVersion: { @MainActor [weak self] scope in
            guard let self else { throw NativeVoiceCallError.scopeChanged }; try check(scope)
            guard let value = metadata["key_version"]?.number else { return nil }
            guard value >= 1, value <= Double(UInt32.max), value.rounded(.down) == value
            else { throw NativeVoiceCallError.contextUnavailable }; return Int(value)
        }, request: { [weak self] scope, frame, response in
            guard let self else { throw NativeVoiceCallError.scopeChanged }
            return try await self.request(scope, frame: frame, response: response)
        })
    private lazy var outbox = NativeVoiceCallOutbox(crypto: crypto, storage: storage,
        isCurrent: { [weak self] scope in await self?.current(scope) == true },
        checkpoint: { [weak self] scope, callID, frame in
            guard let self else { throw NativeVoiceCallError.scopeChanged }
            return try await self.canonical.persist(scope: scope, callID: callID, frame: frame)
        })
    private lazy var audio: NativeVoiceCallAppleAudio = NativeVoiceCallAppleAudio(invalidated: { [weak self] in
        await self?.audioInvalidated()
    })
    private lazy var environment: NativeVoiceCallEnvironment = {
        let base = NativeVoiceCallAppleEnvironment.make(authManager: auth, profile: profile,
            consentDecision: { [weak self] in await self?.consent?() ?? false },
            context: { [weak self] scope in
                guard let self else { throw NativeVoiceCallError.scopeChanged }
                try await self.check(scope)
                return try .init(messages: [], mateCategory: scope.mateCategory, canonicalRangeComplete: true)
            })
        return NativeVoiceCallEnvironment(isCurrent: { [weak self] scope in await self?.current(scope) == true },
            ensureConsent: base.ensureConsent, authentication: base.authentication, context: base.context,
            prepare: { [weak self] scope in
                guard let self else { throw NativeVoiceCallError.scopeChanged }; try await self.confirm(scope)
            }, submitTurn: { [weak self] scope, transcript in
                guard let self else { throw NativeVoiceCallError.scopeChanged }
                try await self.submitTurn(scope: scope, transcript: transcript)
            }, interruptAssistant: { [weak self] scope, id, taskID in
                guard let self else { throw NativeVoiceCallError.scopeChanged }
                try await self.interruptAssistant(scope: scope, messageID: id, taskID: taskID)
            }, now: base.now, sleep: base.sleep)
    }()
    private lazy var controller: NativeVoiceCallController = NativeVoiceCallController(environment: environment, audio: audio, persistence: outbox,
        transportFactory: { NativeVoiceCallURLSessionTransport(cookieStorage: OpenMatesSharedEnvironment.cookieStorage) },
        eventHandler: { [weak self] event in await self?.receive(event) })

    private func audioInvalidated() async { await controller.invalidateScope() }

    func start(_ destination: NativeVoiceCallAppDestination) async throws {
        let state = await controller.snapshot()
        guard state.status != .live, state.status != .connecting, consent != nil, downstream != nil,
              auth.state == .authenticated, let owner = auth.currentUser?.id,
              profile == ServerProfile.current(), TeamWorkspaceContext.shared.snapshot.teamID == nil
        else { throw NativeVoiceCallError.callUnavailable }
        let generation = OfflineStore.shared.scopeGeneration
        let keyGeneration = ChatKeyManager.shared.cacheGeneration
        let team = TeamWorkspaceContext.shared.snapshot
        let chat: Chat
        let fresh: Bool
        let localDraftWasPresent: Bool
        let selectedMate: String
        switch destination {
        case .existing(let id):
            guard UUID(uuidString: id) != nil, let existing = store.chat(for: id),
                  existing.teamId == nil, existing.isSharedByOthers != true,
                  let wrapper = existing.encryptedChatKey, !wrapper.isEmpty
            else { throw NativeVoiceCallError.contextUnavailable }
            chat = existing; fresh = false; localDraftWasPresent = false
            selectedMate = existing.category ?? "general_knowledge"
        case .newPersonal(let id, let mate):
            guard !mate.isEmpty else { throw NativeVoiceCallError.invalidState }
            let chatID = id.uuidString.lowercased()
            if let local = store.chat(for: chatID) {
                guard NativeVoiceCallLocalDraftPromotion.eligible(local, chatID: chatID),
                      store.messages(for: chatID).isEmpty,
                      local.hasNonEmptyDraft == true || DraftService.shared.activeNewChatDraftId == chatID
                else { throw NativeVoiceCallError.contextUnavailable }
                chat = local; localDraftWasPresent = true
            } else {
                let now = ISO8601DateFormatter().string(from: Date())
                chat = Chat(id: chatID, title: nil, lastMessageAt: nil, createdAt: now,
                    updatedAt: nil, isArchived: false, isPinned: false, appId: nil, category: mate,
                    encryptedTitle: nil, encryptedChatKey: nil, messagesV: 0, titleV: 0, metadataV: 0)
                localDraftWasPresent = false
            }
            fresh = true; selectedMate = mate
        }
        let scope = NativeVoiceCallScope(accountID: owner, profileID: profile.id,
            workspaceGeneration: generation, chatID: chat.id, mateCategory: selectedMate)
        let previousPump = pump; previousPump?.cancel(); await previousPump?.value
        pump = nil; pumpDirty = false
        guard !ordinaryInferenceActive(scope.chatID) else { throw NativeVoiceCallError.callUnavailable }
        binding = (scope, team, keyGeneration); prepared = nil; metadata = [:]
        do {
            try check(scope)
            guard let master = try await CryptoManager.shared.loadMasterKey(for: owner)
            else { throw NativeVoiceCallError.contextUnavailable }
            try check(scope)
            let wrapper: String
            if let existing = chat.encryptedChatKey {
                let key = try await CryptoManager.shared.unwrapChatKey(encryptedChatKeyBase64: existing, masterKey: master)
                try check(scope)
                guard ChatKeyManager.shared.installValidatedKey(key, encryptedKey: existing, for: chat.id,
                    expectedGeneration: keyGeneration) == existing else { throw NativeVoiceCallError.scopeChanged }
                wrapper = existing
            } else {
                let key = await ChatKeyManager.shared.createKeyForNewChat(chat.id)
                try check(scope)
                let proposed = try await CryptoManager.shared.wrapChatKey(key, masterKey: master)
                try check(scope)
                guard let stored = ChatKeyManager.shared.rememberNewEncryptedKeyIfAbsent(proposed, for: chat.id,
                    matching: key, expectedGeneration: keyGeneration) else { throw NativeVoiceCallError.scopeChanged }
                wrapper = stored
            }
            var preparedChat = chat
            if fresh {
                let latest = store.chat(for: chat.id)
                guard !localDraftWasPresent || latest != nil, store.messages(for: chat.id).isEmpty else { throw NativeVoiceCallError.scopeChanged }
                // Key wrapping suspends. Preserve newer draft version/flags and
                // refuse deletion, canonical ownership or a changed Mate.
                preparedChat = try NativeVoiceCallLocalDraftPromotion.prepare(latest ?? chat,
                    chatID: chat.id, encryptedChatKey: wrapper, mate: scope.mateCategory)
                store.upsertChat(preparedChat)
            }
            prepared = (preparedChat, fresh)
            try check(scope)
            try await controller.start(scope: scope)
        } catch { binding = nil; prepared = nil; throw error }
    }
    private func expected() throws -> NativeVoiceCallChatAdmissionProof.Expected {
        guard let chat = prepared?.chat, let wrapper = chat.encryptedChatKey,
              let messages = chat.messagesV, let title = chat.titleV, let metadata = chat.metadataV
        else { throw NativeVoiceCallError.contextUnavailable }
        return .init(chatID: chat.id, encryptedChatKey: wrapper,
            versions: .init(messages: messages, title: title, metadata: metadata))
    }
    private func confirm(_ scope: NativeVoiceCallScope) async throws {
        try check(scope)
        guard socket.isConnected, let prepared else { throw NativeVoiceCallError.connectionLost }
        if prepared.needsConfirmation {
            let expected = try expected(), now = floor(Date().timeIntervalSince1970)
            let category = try await crypto.encrypt(scope.mateCategory, scope: scope)
            let ack = try await request(scope, frame: ["type": .string("encrypted_chat_metadata"),
                "chat_id": .string(scope.chatID), "encrypted_chat_key": .string(expected.encryptedChatKey),
                "encrypted_category": .string(category), "created_at": .number(now),
                "versions": .object(["messages_v": .number(0), "title_v": .number(0),
                    "metadata_v": .number(0), "last_edited_overall_timestamp": .number(now)])], response: "encrypted_metadata_stored")
            let proof = NativeVoiceCallChatAdmissionProof(readAuthoritative: { [weak self] in
                guard let self else { throw NativeVoiceCallError.scopeChanged }
                let data = try await self.get(scope, path: "/v1/chats?limit=100&offset=0")
                guard data.count <= 2 * 1_024 * 1_024,
                      let frame = try? JSONDecoder().decode(NativeVoiceCallFrame.self, from: data),
                      case .array(let rows)? = frame["chats"], rows.count <= 100,
                      rows.allSatisfy({ $0.object != nil }) else { throw NativeVoiceCallError.persistenceFailed }
                return rows.compactMap(\.object)
            }, checkCurrent: { [weak self] in
                guard let self else { throw NativeVoiceCallError.scopeChanged }; try await self.check(scope)
            })
            _ = try await proof.confirm(queueReceipt: ack, expected: expected)
            try check(scope); self.prepared = (prepared.chat, false)
        }
        _ = try await freshMetadata(scope)
        try await AssistantSpeechAppRuntime.shared.beginLiveCallSpeech(chatID: scope.chatID) { [weak self] speaking, generating, id, taskID, text, language in
            await self?.controller.updateAssistantState(speaking: speaking, generating: generating, messageID: id, taskID: taskID, text: text, language: language)
        }
        // Retained final revisions from an interrupted earlier call must reach
        // canonical history before this call reads context or opens a provider.
        startPump(scope)
        await pump?.value
        try check(scope)
        guard try await outbox.pendingFrames(scope: scope).isEmpty else {
            throw NativeVoiceCallError.persistenceFailed
        }
    }
    private func freshMetadata(_ scope: NativeVoiceCallScope) async throws -> NativeVoiceCallFrame {
        let frame = try await request(scope, frame: ["type": .string("phased_sync_request"), "phase": .string("phase2"),
            "refresh_chat_ids": .array([.string(scope.chatID)]), "client_chat_ids": .array([.string(scope.chatID)]),
            "client_chat_versions": .object([:]), "team_id": .null,
            "context_epoch": .number(Double(binding?.team.epoch ?? 0))], response: "phase_2_last_20_chats_ready")
        let rows: [NativeVoiceCallFrame]
        if case .array(let items)? = frame["chats"] { rows = items.compactMap { $0.object?["chat_details"]?.object ?? $0.object } }
        else if case .array(let items)? = frame["recent_chat_metadata"] { rows = items.compactMap(\.object) }
        else { throw NativeVoiceCallError.contextUnavailable }
        let matches = rows.filter { ($0["id"]?.string ?? $0["chat_id"]?.string) == scope.chatID }
        guard matches.count == 1, let selected = matches.first,
              selected["chat_visibility"]?.string != "public", selected["is_shared_by_others"]?.bool != true
        else { throw NativeVoiceCallError.contextUnavailable }
        _ = try NativeVoiceCallChatAdmissionProof.validate(selected, expected: expected(), exactVersions: false)
        try check(scope); metadata = selected; return selected
    }
    private func get(_ scope: NativeVoiceCallScope, path: String) async throws -> Data {
        try check(scope)
        guard let binding else { throw NativeVoiceCallError.scopeChanged }
        let data = try await APIClient.shared.request(.get, path: path, serverProfile: profile,
            headers: ["Cache-Control": "no-cache", "Pragma": "no-cache"], expectedAccountID: scope.accountID,
            expectedScope: scope.workspaceGeneration,
            expectedTeamContext: .init(epoch: binding.team.epoch, teamID: nil))
        try check(scope); return data
    }
    private func freshMemoryMetadata(_ scope: NativeVoiceCallScope) async throws -> [String] {
        try check(scope)
        let receipt = try await NativePersonalPrivacyRuntime.shared.freshForQueuedRevision(
            requestID: UUID().uuidString, socket: socket)
        try check(scope)
        return receipt.privacy.metadataKeys
    }
    private func loadContext(_ scope: NativeVoiceCallScope) async throws -> NativeVoiceCallContext {
        let loader = NativeVoiceCallCanonicalContextLoader(request: { [weak self] scope, path in
            guard let self else { throw NativeVoiceCallError.scopeChanged }; return try await self.get(scope, path: path)
        }, decrypt: { [weak self] cipher, scope in
            guard let self else { throw NativeVoiceCallError.scopeChanged }; return try await self.crypto.decrypt(cipher, scope: scope)
        }, metadata: { [weak self] scope in
            guard let self else { throw NativeVoiceCallError.scopeChanged }; return try await self.freshMetadata(scope)
        }, isCurrent: { [weak self] scope in await self?.current(scope) == true },
        projectContext: { [weak self] scope, activeFocus in
            guard let self else { throw NativeVoiceCallError.scopeChanged }
            try await self.check(scope)
            let reader = await NativeVoiceCallProjectContext(scope: scope, request: { [weak self] path in
                guard let self else { throw NativeVoiceCallError.scopeChanged }
                return try await self.get(scope, path: path)
            }, checkCurrent: { [weak self] in
                guard let self else { throw NativeVoiceCallError.scopeChanged }; try self.check(scope)
            })
            var fields = try await reader.load(activeFocus: activeFocus)
            try await self.check(scope)
            // Existing first-party snapshot compiler verifies actual encrypted
            // Personal rows and reconciles current privacy. Only availability
            // keys cross the call context; bodies still require explicit consent.
            let metadata = try await self.freshMemoryMetadata(scope)
            try await self.check(scope)
            fields["app_settings_memories_metadata"] = .array(metadata.map(NativeVoiceCallJSON.string))
            return fields
        })
        return try await loader.load(scope: scope)
    }
    private func request(_ scope: NativeVoiceCallScope, frame: NativeVoiceCallFrame,
                         response: String) async throws -> NativeVoiceCallFrame {
        try check(scope)
        guard socket.isConnected, let type = frame["type"]?.string else { throw NativeVoiceCallError.connectionLost }
        let generation = socket.transportGeneration
        let data = try JSONEncoder().encode(frame)
        guard data.count <= NativeVoiceCallWire.maximumFrameBytes,
              var payload = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { throw NativeVoiceCallError.invalidResponse }
        payload.removeValue(forKey: "type")
        let requestID = frame["request_id"]?.string
        let messageID = frame["message_id"]?.string ?? frame["message"]?.object?["message_id"]?.string
        let checkpointID = frame["checkpoint_id"]?.string
        let timeout: Duration = response == "chat_compression_checkpoint_stored" ? .seconds(30)
            : response == "call_message_confirmed" || response == "system_message_confirmed" ? .seconds(15) : .seconds(5)
        let answer = try await socket.sendAndWait(WSOutboundMessage(type: type, payload: payload),
            responseType: response, timeout: timeout, matching: { fields in
                if let id = fields["chat_id"] as? String, id != scope.chatID { return false }
                if response != "phase_2_last_20_chats_ready", fields["chat_id"] as? String != scope.chatID { return false }
                if let requestID, fields["request_id"] as? String != requestID { return false }
                if let messageID, fields["message_id"] as? String != messageID { return false }
                if let checkpointID,
                   (fields["checkpoint"] as? [String: Any])?["id"] as? String != checkpointID { return false }
                return true
            }, beforeSend: { [weak self] in
                guard let self else { throw NativeVoiceCallError.scopeChanged }; try check(scope)
                guard socket.transportGeneration == generation else { throw NativeVoiceCallError.connectionLost }
            })
        try check(scope)
        guard socket.transportGeneration == generation else { throw NativeVoiceCallError.connectionLost }
        let result = try JSONSerialization.data(withJSONObject: answer.fields)
        guard result.count <= 2 * 1_024 * 1_024 else { throw NativeVoiceCallError.invalidResponse }
        var decoded = try JSONDecoder().decode(NativeVoiceCallFrame.self, from: result)
        decoded["type"] = .string(response); return decoded
    }
    private func submitTurn(scope: NativeVoiceCallScope, transcript: NativeVoiceCallTranscript) async throws {
        try check(scope)
        guard transcript.role == .user, transcript.final, let chat = store.chat(for: scope.chatID) else {
            throw NativeVoiceCallError.contextUnavailable
        }
        await controller.updateAssistantState(speaking: false, generating: true, messageID: nil, text: "")
        let heardBoundary = AssistantSpeechAppRuntime.shared.pendingHeardBoundary(chatID: scope.chatID)
        let result = try await sendPipeline.sendUserMessage(content: transcript.text, in: chat,
            existingMessages: store.messages(for: scope.chatID), wsManager: socket, chatStore: store,
            waitForInferenceReceipt: true,
            createdAtOverride: ISO8601DateFormatter().string(from: Date(timeIntervalSince1970: Double(transcript.createdAt))),
            validateRemoteSend: { [weak self] in
                guard let self else { throw NativeVoiceCallError.scopeChanged }; try self.check(scope)
            }, voiceCallTurn: .init(callID: transcript.callID, turnID: transcript.messageID, heardBoundary: heardBoundary),
            messageId: transcript.messageID)
        try check(scope)
        store.upsertChat(result.chat)
        store.appendMessage(result.message, to: scope.chatID)
        AssistantSpeechAppRuntime.shared.acceptHeardBoundary(heardBoundary, chatID: scope.chatID)
    }
    private func interruptAssistant(scope: NativeVoiceCallScope, messageID: String?, taskID: String?) async throws {
        try check(scope)
        guard await AssistantSpeechAppRuntime.shared.interruptLiveCallSpeech(chatID: scope.chatID, messageID: messageID, taskID: taskID) else { return }
        try check(scope)
        try await sendPipeline.sendCancelAITask(taskId: taskID, chatId: scope.chatID, wsManager: socket)
    }
    private func receive(_ event: NativeVoiceCallEvent) async {
        if case .state(let snapshot) = event, snapshot.status == .live {
            AssistantSpeechAppRuntime.shared.bindLiveCallID(snapshot.callID)
        }
        // Ordinary chat sync owns all assistant markdown, embeds and attribution.
        // The call event is only a final user/composer acceptance signal.
        await downstream?(event)
    }
    private func startPump(_ scope: NativeVoiceCallScope) {
        guard pump == nil else { pumpDirty = true; return }; pumpDirty = false
        let token = UUID(); pumpID = token
        pump = Task { [weak self] in
            guard let self else { return }
            defer {
                if pumpID == token {
                    pump = nil; pumpID = nil
                    if pumpDirty, current(scope) { pumpDirty = false; startPump(scope) }
                }
            }
            do {
                while current(scope) {
                    let frames = try await outbox.pendingFrames(scope: scope)
                    if frames.isEmpty { return }
                    for frame in frames {
                        var accepted = false
                        for attempt in 0..<3 {
                            do {
                                let ack = try await request(scope, frame: frame, response: "call_message_confirmed")
                                guard try await outbox.acknowledge(scope: scope, frame: ack) else { throw NativeVoiceCallError.persistenceFailed }
                                accepted = true; break
                            } catch {
                                guard !Task.isCancelled, current(scope) else { throw CancellationError() }
                                if attempt < 2 { try await Task.sleep(for: .milliseconds(250 * (attempt + 1))) }
                            }
                        }
                        guard accepted else { throw NativeVoiceCallError.persistenceFailed }
                    }
                }
            } catch { pumpDirty = false; if !Task.isCancelled, current(scope) { await controller.persistenceFailed() } }
        }
    }
    /// Root calls only after the same shared embed coordinator confirms canonical
    /// encrypted storage. The controller additionally checks its issued origin.
    func associateCommittedArtifact(scope: NativeVoiceCallScope, callID: String, functionCallID: String,
        assistantMessageID: String, userMessageID: String, reference: NativeVoiceCallFrame
    ) async throws {
        try check(scope)
        try await controller.associateCommittedArtifact(scope: scope, callID: callID, functionCallID: functionCallID,
            assistantMessageID: assistantMessageID, userMessageID: userMessageID, reference: reference)
        try check(scope)
        // Do not release the post-hangup admission claim before the linked
        // ciphertext revision reaches the existing canonical message receipt.
        startPump(scope); await pump?.value
        try check(scope)
        guard try await outbox.pendingFrames(scope: scope).isEmpty else { throw NativeVoiceCallError.persistenceFailed }
    }
    func sendText(_ text: String) async throws -> String { try await controller.sendText(text) }
    func setMuted(_ muted: Bool) async { await controller.setMuted(muted) }
    func hangup() async { await controller.hangup() }
    func snapshot() async -> NativeVoiceCallSnapshot { await controller.snapshot() }
    func respondToTool(_ frame: NativeVoiceCallFrame) async throws { try await controller.sendToolResponse(frame) }
    func invalidate() async {
        await controller.invalidateScope()
        pumpID = nil; pumpDirty = false; pump?.cancel(); pump = nil; binding = nil; prepared = nil; metadata = [:]
    }
}
#endif
