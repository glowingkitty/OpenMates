// Coordinates encrypted Apple drafts with the web-compatible WebSocket protocol.
// Transport and offline boundaries accept Format-D ciphertext and metadata only.
// Receipts, broadcasts, reconnect versions, and authoritative chat deletion are
// applied without echoing remote updates or inferring deletion from partial pages.
// Composer rendering and plaintext editor state remain outside this service.

import Foundation

struct DraftSyncMessage {
    let type: String
    let payload: [String: Any]
}

@MainActor
protocol DraftSyncTransport: AnyObject {
    var isConnected: Bool { get }
    func sendDraftSyncMessage(_ message: DraftSyncMessage) async throws
}

@MainActor
protocol DraftSyncOfflineActions: AnyObject {
    func queueDraftUpdate(_ record: ComposerDraftRecord)
    func queueDraftDelete(chatId: String)
    func cascadeDeleteChat(chatId: String)
    func cascadeDeleteDraftOnlyChat(chatId: String)
}

@MainActor
final class DraftSyncCoordinator {
    static let syntheticNewChatId = "composer:new-chat"

    private let repository: any ComposerDraftRepository
    private let chatStore: ChatStore
    private weak var transport: (any DraftSyncTransport)?
    private weak var offlineActions: (any DraftSyncOfflineActions)?
    private let uuid: () -> UUID
    private let onDraftChanged: (String) -> Void
    private var newChatDraftId: String?
    private let expectedScope: UUID?
    private let isCurrentSession: () -> Bool

    var activeNewChatDraftId: String? { newChatDraftId }

    init(
        repository: any ComposerDraftRepository,
        chatStore: ChatStore,
        transport: any DraftSyncTransport,
        offlineActions: any DraftSyncOfflineActions,
        onDraftChanged: @escaping (String) -> Void = { _ in },
        uuid: @escaping () -> UUID = UUID.init,
        expectedScope: UUID? = nil,
        isCurrentSession: @escaping () -> Bool = { true }
    ) {
        self.repository = repository
        self.chatStore = chatStore
        self.transport = transport
        self.offlineActions = offlineActions
        self.onDraftChanged = onDraftChanged
        self.uuid = uuid
        self.expectedScope = expectedScope
        self.isCurrentSession = isCurrentSession
    }

    func resolveChatId(_ chatId: String, hasNonEmptyDraft: Bool) -> String {
        guard chatId == Self.syntheticNewChatId else { return chatId }
        guard hasNonEmptyDraft else { return newChatDraftId ?? chatId }
        if let newChatDraftId { return newChatDraftId }
        let allocated = uuid().uuidString.lowercased()
        newChatDraftId = allocated
        return allocated
    }

    func resetNewChatDraftId() {
        newChatDraftId = nil
    }

    func restoreNewChatDraftId(from records: [ComposerDraftRecord]) {
        guard newChatDraftId == nil else { return }
        let recordIds = Set(records.map(\.chatId))
        newChatDraftId = chatStore.chats.first(where: { chat in
            recordIds.contains(chat.id) && isDraftOnlyChat(chat)
        })?.id
    }

    func restoreDeletionMarkers(_ versions: [String: Int]) {
        guard isCurrentSession() else { return }
        for (chatId, version) in versions {
            publish(ComposerDraftApplication(record: ComposerDraftRecord(chatId: chatId,
                encryptedMarkdown: "", encryptedPreview: "", revision: 0, draftVersion: 0,
                clearedDraftVersion: version, isDeleted: true), applied: false), refresh: false)
        }
    }

    func submitLocalUpdate(_ record: ComposerDraftRecord, resolvedChatId: String) async throws {
        let resolvedRecord = ComposerDraftRecord(
            chatId: resolvedChatId,
            encryptedMarkdown: record.encryptedMarkdown,
            encryptedPreview: record.encryptedPreview,
            revision: record.revision,
            draftVersion: record.draftVersion
        )
        try validateSession()
        try await repository.upsert(resolvedRecord)
        try validateSession()
        if newChatDraftId == resolvedChatId {
            try await repository.remove(chatId: Self.syntheticNewChatId)
        }
        try validateSession()
        upsertLocalDraftChatIfNeeded(resolvedRecord)
        let message = DraftSyncMessage(type: "update_draft", payload: [
            "chat_id": resolvedChatId,
            "encrypted_draft_md": resolvedRecord.encryptedMarkdown,
            "encrypted_draft_preview": resolvedRecord.encryptedPreview,
        ])
        guard let transport, transport.isConnected else {
            offlineActions?.queueDraftUpdate(resolvedRecord)
            return
        }
        do {
            try await transport.sendDraftSyncMessage(message)
        } catch {
            offlineActions?.queueDraftUpdate(resolvedRecord)
            NativeDiagnostics.warning(
                "Draft update transport failed; queued encrypted action errorType=\(type(of: error))",
                category: "draft_sync"
            )
        }
    }

    func submitLocalDelete(chatId: String) async throws {
        let result = try await apply(.localDeletion(chatId: chatId))
        publish(result, refresh: false)
        if newChatDraftId == chatId { resetNewChatDraftId() }
        let message = DraftSyncMessage(type: "delete_draft", payload: ["chat_id": chatId])
        guard let transport, transport.isConnected else {
            offlineActions?.queueDraftDelete(chatId: chatId)
            return
        }
        do {
            try await transport.sendDraftSyncMessage(message)
        } catch {
            offlineActions?.queueDraftDelete(chatId: chatId)
            NativeDiagnostics.warning(
                "Draft delete transport failed; queued encrypted action errorType=\(type(of: error))",
                category: "draft_sync"
            )
        }
    }

    func reconcileAfterReconnect() async throws {
        try validateSession()
        guard let transport, transport.isConnected else { return }
        let records = try await repository.allRecords()
        try validateSession()
        guard !records.isEmpty else { return }
        try await transport.sendDraftSyncMessage(DraftSyncMessage(
            type: "get_draft_versions",
            payload: [
                "chats": records.map {
                    ["chat_id": $0.chatId, "client_draft_v": $0.draftVersion]
                },
            ]
        ))
    }

    func handleEvent(type: String, raw: Data) async throws {
        try validateSession()
        switch type {
        case "draft_update_receipt":
            let envelope = try decoder.decode(DraftReceiptEnvelope.self, from: raw)
            guard envelope.payload.success else { return }
            let result = try await apply(.acknowledgement(chatId: envelope.payload.chatId,
                                                        version: envelope.payload.draftV))
            publish(result, refresh: false)
            // A receipt changes version only, never replays autosave text.

        case "chat_draft_updated":
            let event = try decoder.decode(DraftUpdatedEvent.self, from: raw)
            if event.data.explicitlyClearsDraft {
                let result = try await apply(.deletion(chatId: event.chatId, version: event.versions.draftV))
                publish(result, refresh: true)
            } else if let encryptedMarkdown = event.data.encryptedDraftMd {
                let existing = try await repository.record(chatId: event.chatId)
                try validateSession()
                let record = ComposerDraftRecord(chatId: event.chatId,
                    encryptedMarkdown: encryptedMarkdown,
                    encryptedPreview: event.data.encryptedDraftPreview ?? existing?.encryptedPreview ?? "",
                    revision: existing?.revision ?? 0, draftVersion: event.versions.draftV)
                let result = try await apply(.content(record))
                publish(result, refresh: true, createMissingChat: true,
                        timestamp: event.lastEditedOverallTimestamp)
            }

        case "draft_deleted", "draft_delete_receipt":
            let envelope = try decoder.decode(DraftDeleteEnvelope.self, from: raw)
            guard envelope.payload.success != false else { return }
            let result = try await apply(.deletion(chatId: envelope.payload.chatId,
                                                  version: envelope.payload.draftV))
            publish(result, refresh: type == "draft_deleted")

        case "chat_deleted":
            let envelope = try decoder.decode(DraftDeleteEnvelope.self, from: raw)
            _ = try await apply(.chatDeletion(chatId: envelope.payload.chatId))
            try validateSession()
            offlineActions?.cascadeDeleteChat(chatId: envelope.payload.chatId)

        case "draft_versions_response":
            let envelope = try decoder.decode(DraftVersionsEnvelope.self, from: raw)
            try await reconcileDraftVersions(envelope.payload)

        case "draft_conflict":
            let envelope = try decoder.decode(DraftConflictEnvelope.self, from: raw)
            guard let transport, transport.isConnected else { return }
            try await transport.sendDraftSyncMessage(DraftSyncMessage(
                type: "get_chat_details",
                payload: ["chat_id": envelope.payload.chatId]
            ))

        case "chat_details":
            let envelope = try decoder.decode(ChatDetailsEnvelope.self, from: raw)
            try await applySyncedDraft(envelope.payload)

        default:
            break
        }
    }

    func handleSyncEvent(raw: Data) async throws {
        try validateSession()
        let envelope = try decoder.decode(AuthoritativeSyncEnvelope.self, from: raw)
        for item in envelope.payload.chats ?? [] {
            try validateSession()
            try await applySyncedDraft(item.chatDetails)
        }
        try await reconcileChats(
            authoritative: envelope.payload.authoritative ?? false,
            authoritativeChatIds: envelope.payload.authoritativeChatIds ?? [],
            deletedChatIds: envelope.payload.deletedChatIds ?? []
        )
    }

    func reconcileChats(
        authoritative: Bool,
        authoritativeChatIds: [String],
        deletedChatIds: [String]
    ) async throws {
        try validateSession()
        var idsToDelete = Set(deletedChatIds)
        if authoritative {
            let serverIds = Set(authoritativeChatIds)
            idsToDelete.formUnion(chatStore.chats.filter {
                ChatStore.isServerSyncChatId($0.id)
                    && !serverIds.contains($0.id)
                    && isDraftOnlyChat($0)
            }.map(\.id))
        }
        for chatId in idsToDelete {
            guard ChatStore.isServerSyncChatId(chatId) else { continue }
            try validateSession()
            _ = try await apply(.chatDeletion(chatId: chatId))
            try validateSession()
            chatStore.performWithoutPersistence {
                chatStore.removeChat(chatId)
            }
            offlineActions?.cascadeDeleteChat(chatId: chatId)
            if newChatDraftId == chatId {
                resetNewChatDraftId()
            }
        }
    }

    private func reconcileDraftVersions(_ payload: DraftVersionsPayload) async throws {
        guard let transport else { return }
        let unavailable = Set(payload.unavailableChatIds ?? [])
        for (chatId, serverVersion) in payload.versions where !unavailable.contains(chatId) {
            try validateSession()
            guard let local = try await repository.record(chatId: chatId) else { continue }
            try validateSession()
            if serverVersion == 0 {
                // Missing Redis/Directus data is not a versioned deletion. The web
                // client also keeps local content unless a current tombstone exists.
                guard let tombstone = payload.tombstoneVersions?[chatId], tombstone > 0 else { continue }
                publish(try await apply(.deletion(chatId: chatId, version: tombstone)), refresh: true)
            } else if serverVersion > local.draftVersion, transport.isConnected {
                try await transport.sendDraftSyncMessage(DraftSyncMessage(
                    type: "get_chat_details", payload: ["chat_id": chatId]))
            }
        }
    }

    private func applySyncedDraft(_ details: SyncedDraftDetails) async throws {
        try validateSession()
        guard let draftVersion = details.draftV else { return }
        if details.explicitlyClearsDraft {
            let version = max(draftVersion, details.clearedDraftV ?? 0)
            publish(try await apply(.deletion(chatId: details.id, version: version)), refresh: true)
        } else if let encryptedMarkdown = details.encryptedDraftMd {
            let existing = try await repository.record(chatId: details.id)
            try validateSession()
            let record = ComposerDraftRecord(chatId: details.id,
                encryptedMarkdown: encryptedMarkdown,
                encryptedPreview: details.encryptedDraftPreview ?? existing?.encryptedPreview ?? "",
                revision: existing?.revision ?? 0, draftVersion: draftVersion)
            publish(try await apply(.content(record)), refresh: true)
        }
        // A metadata-only positive version omitting ciphertext must not delete a draft.
    }

    private func validateSession() throws {
        guard !Task.isCancelled, isCurrentSession() else { throw CancellationError() }
    }

    private func apply(_ mutation: ComposerDraftMutation) async throws -> ComposerDraftApplication {
        try validateSession()
        let chat = chatStore.chat(for: mutation.chatId)
        let result = try await repository.apply(mutation, knownVersion: chat?.draftV ?? 0,
            knownClearedVersion: chat?.clearedDraftV ?? 0, expectedScope: expectedScope)
        try validateSession()
        return result
    }

    private func publish(_ result: ComposerDraftApplication, refresh: Bool,
                         createMissingChat: Bool = false, timestamp: Int? = nil) {
        guard isCurrentSession(), let record = result.record else { return }
        let current = chatStore.chat(for: record.chatId)
        if record.isDeleted {
            guard record.clearedDraftVersion >= (current?.draftV ?? 0) else { return }
            chatStore.updateDraftVersion(chatId: record.chatId, draftVersion: 0,
                hasNonEmptyDraft: false, clearedDraftVersion: record.clearedDraftVersion)
            removeDraftOnlyChatIfNeeded(record.chatId)
        } else {
            guard result.applied,
                  ComposerDraftVersionPolicy.acceptsContent(version: record.draftVersion,
                    currentVersion: current?.draftV ?? 0, hasDraft: current?.hasNonEmptyDraft == true,
                    clearedVersion: current?.clearedDraftV ?? 0) else { return }
            if current == nil, createMissingChat {
                let date = ISO8601DateFormatter().string(from: Date(timeIntervalSince1970:
                    TimeInterval(timestamp ?? Int(Date().timeIntervalSince1970))))
                chatStore.upsertChat(Chat(id: record.chatId, title: nil, lastMessageAt: nil,
                    createdAt: date, updatedAt: date, isArchived: false, isPinned: false, appId: "ai",
                    encryptedTitle: nil, encryptedChatKey: nil, draftV: record.draftVersion,
                    hasNonEmptyDraft: !record.encryptedMarkdown.isEmpty,
                    clearedDraftV: record.clearedDraftVersion))
                if newChatDraftId == nil { newChatDraftId = record.chatId }
            }
            chatStore.updateDraftVersion(chatId: record.chatId, draftVersion: record.draftVersion,
                hasNonEmptyDraft: !record.encryptedMarkdown.isEmpty,
                clearedDraftVersion: record.clearedDraftVersion)
        }
        if refresh && result.applied { onDraftChanged(record.chatId) }
    }

    private func removeDraftOnlyChatIfNeeded(_ chatId: String) {
        guard let chat = chatStore.chat(for: chatId),
              isDraftOnlyChat(chat) else { return }
        chatStore.performWithoutPersistence { chatStore.removeChat(chatId) }
        offlineActions?.cascadeDeleteDraftOnlyChat(chatId: chatId)
        if newChatDraftId == chatId {
            resetNewChatDraftId()
        }
    }

    private func isDraftOnlyChat(_ chat: Chat) -> Bool {
        (chat.messagesV ?? 0) == 0
            && chat.lastMessageAt == nil
            && chatStore.messages(for: chat.id).isEmpty
    }

    private func upsertLocalDraftChatIfNeeded(_ record: ComposerDraftRecord) {
        guard chatStore.chat(for: record.chatId) == nil else {
            chatStore.updateDraftVersion(chatId: record.chatId, draftVersion: record.draftVersion, hasNonEmptyDraft: !record.encryptedMarkdown.isEmpty)
            return
        }
        let date = ISO8601DateFormatter().string(from: Date())
        chatStore.upsertChat(Chat(
            id: record.chatId,
            title: nil,
            lastMessageAt: nil,
            createdAt: date,
            updatedAt: date,
            isArchived: false,
            isPinned: false,
            appId: "ai",
            encryptedTitle: nil,
            encryptedChatKey: nil,
            messagesV: 0,
            titleV: 0,
            draftV: record.draftVersion,
            hasNonEmptyDraft: !record.encryptedMarkdown.isEmpty
        ))
    }

    private var decoder: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }
}

private struct DraftReceiptEnvelope: Decodable { let payload: DraftReceiptPayload }
private struct DraftReceiptPayload: Decodable {
    let chatId: String
    let draftV: Int
    let success: Bool
}

private struct DraftUpdatedEvent: Decodable {
    let chatId: String
    let data: DraftUpdatedData
    let versions: DraftUpdatedVersions
    let lastEditedOverallTimestamp: Int?
}

private struct DraftUpdatedData: Decodable {
    let encryptedDraftMd: String?
    let encryptedDraftPreview: String?
    let explicitlyClearsDraft: Bool
    private enum CodingKeys: String, CodingKey { case encryptedDraftMd, encryptedDraftPreview }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        encryptedDraftMd = try c.decodeIfPresent(String.self, forKey: .encryptedDraftMd)
        encryptedDraftPreview = try c.decodeIfPresent(String.self, forKey: .encryptedDraftPreview)
        explicitlyClearsDraft = (c.contains(.encryptedDraftMd) && encryptedDraftMd == nil)
            || (c.contains(.encryptedDraftPreview) && encryptedDraftPreview == nil)
    }
}

private struct DraftUpdatedVersions: Decodable { let draftV: Int }

private struct DraftDeleteEnvelope: Decodable {
    let payload: DraftDeletePayload
}

private struct DraftDeletePayload: Decodable {
    let chatId: String
    let success: Bool?
    let draftV: Int?
}

private struct DraftVersionsEnvelope: Decodable { let payload: DraftVersionsPayload }
private struct DraftVersionsPayload: Decodable {
    let versions: [String: Int]
    let unavailableChatIds: [String]?
    let tombstoneVersions: [String: Int]?
}

private struct DraftConflictEnvelope: Decodable { let payload: DraftConflictPayload }
private struct DraftConflictPayload: Decodable { let chatId: String }

private struct ChatDetailsEnvelope: Decodable { let payload: SyncedDraftDetails }

private struct SyncedDraftDetails: Decodable {
    let id: String
    let encryptedDraftMd: String?
    let encryptedDraftPreview: String?
    let draftV: Int?
    let clearedDraftV: Int?
    let explicitlyClearsDraft: Bool

    private enum CodingKeys: String, CodingKey {
        case id
        case chatId
        case encryptedDraftMd
        case encryptedDraftPreview
        case draftV
        case clearedDraftV
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decodeIfPresent(String.self, forKey: .id)
            ?? container.decode(String.self, forKey: .chatId)
        encryptedDraftMd = try container.decodeIfPresent(String.self, forKey: .encryptedDraftMd)
        encryptedDraftPreview = try container.decodeIfPresent(String.self, forKey: .encryptedDraftPreview)
        draftV = try container.decodeIfPresent(Int.self, forKey: .draftV)
        clearedDraftV = try container.decodeIfPresent(Int.self, forKey: .clearedDraftV)
        explicitlyClearsDraft = (container.contains(.encryptedDraftMd) && encryptedDraftMd == nil)
            || (container.contains(.encryptedDraftPreview) && encryptedDraftPreview == nil)
            || (draftV == 0 && (clearedDraftV ?? 0) > 0)
    }
}

private struct SyncedDraftChatItem: Decodable { let chatDetails: SyncedDraftDetails }

private struct AuthoritativeSyncEnvelope: Decodable { let payload: AuthoritativeSyncPayload }
private struct AuthoritativeSyncPayload: Decodable {
    let chats: [SyncedDraftChatItem]?
    let authoritative: Bool?
    let authoritativeChatIds: [String]?
    let deletedChatIds: [String]?
}
