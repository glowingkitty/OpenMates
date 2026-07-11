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

    var activeNewChatDraftId: String? { newChatDraftId }

    init(
        repository: any ComposerDraftRepository,
        chatStore: ChatStore,
        transport: any DraftSyncTransport,
        offlineActions: any DraftSyncOfflineActions,
        onDraftChanged: @escaping (String) -> Void = { _ in },
        uuid: @escaping () -> UUID = UUID.init
    ) {
        self.repository = repository
        self.chatStore = chatStore
        self.transport = transport
        self.offlineActions = offlineActions
        self.onDraftChanged = onDraftChanged
        self.uuid = uuid
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

    func submitLocalUpdate(_ record: ComposerDraftRecord, resolvedChatId: String) async throws {
        let resolvedRecord = ComposerDraftRecord(
            chatId: resolvedChatId,
            encryptedMarkdown: record.encryptedMarkdown,
            encryptedPreview: record.encryptedPreview,
            revision: record.revision,
            draftVersion: record.draftVersion
        )
        try await repository.upsert(resolvedRecord)
        if newChatDraftId == resolvedChatId {
            try await repository.remove(chatId: Self.syntheticNewChatId)
        }
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
        try await repository.remove(chatId: chatId)
        if newChatDraftId == chatId {
            removeDraftOnlyChatIfNeeded(chatId)
            resetNewChatDraftId()
        }
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
        guard let transport, transport.isConnected else { return }
        let records = try await repository.allRecords()
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
        switch type {
        case "draft_update_receipt":
            let envelope = try decoder.decode(DraftReceiptEnvelope.self, from: raw)
            guard envelope.payload.success,
                  let existing = try await repository.record(chatId: envelope.payload.chatId) else { return }
            try await repository.upsert(existing.withDraftVersion(envelope.payload.draftV))
            chatStore.updateDraftVersion(chatId: envelope.payload.chatId, draftVersion: envelope.payload.draftV)
            onDraftChanged(envelope.payload.chatId)

        case "chat_draft_updated":
            let event = try decoder.decode(DraftUpdatedEvent.self, from: raw)
            guard let encryptedMarkdown = event.data.encryptedDraftMd else { return }
            let existing = try await repository.record(chatId: event.chatId)
            let isNewDraftOnlyChat = chatStore.chat(for: event.chatId) == nil
            let record = ComposerDraftRecord(
                chatId: event.chatId,
                encryptedMarkdown: encryptedMarkdown,
                encryptedPreview: event.data.encryptedDraftPreview ?? existing?.encryptedPreview ?? "",
                revision: existing?.revision ?? 0,
                draftVersion: event.versions.draftV
            )
            try await repository.upsert(record)
            upsertDraftChatIfNeeded(event)
            if newChatDraftId == nil, isNewDraftOnlyChat {
                newChatDraftId = event.chatId
            }
            chatStore.updateDraftVersion(chatId: event.chatId, draftVersion: event.versions.draftV)
            onDraftChanged(event.chatId)

        case "draft_deleted", "draft_delete_receipt":
            let envelope = try decoder.decode(DraftDeleteEnvelope.self, from: raw)
            guard envelope.payload.success != false else { return }
            try await repository.remove(chatId: envelope.payload.chatId)
            chatStore.updateDraftVersion(chatId: envelope.payload.chatId, draftVersion: 0)
            onDraftChanged(envelope.payload.chatId)
            removeDraftOnlyChatIfNeeded(envelope.payload.chatId)

        case "chat_deleted":
            let envelope = try decoder.decode(DraftDeleteEnvelope.self, from: raw)
            try await repository.remove(chatId: envelope.payload.chatId)
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
        let envelope = try decoder.decode(AuthoritativeSyncEnvelope.self, from: raw)
        for item in envelope.payload.chats ?? [] {
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
            try await repository.remove(chatId: chatId)
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
            guard let local = try await repository.record(chatId: chatId) else { continue }
            if serverVersion == 0 {
                try await repository.remove(chatId: chatId)
                chatStore.updateDraftVersion(chatId: chatId, draftVersion: 0)
                onDraftChanged(chatId)
            } else if serverVersion > local.draftVersion, transport.isConnected {
                try await transport.sendDraftSyncMessage(DraftSyncMessage(
                    type: "get_chat_details",
                    payload: ["chat_id": chatId]
                ))
            }
        }
    }

    private func applySyncedDraft(_ details: SyncedDraftDetails) async throws {
        guard let draftVersion = details.draftV else { return }
        guard draftVersion > 0, let encryptedMarkdown = details.encryptedDraftMd else {
            try await repository.remove(chatId: details.id)
            chatStore.updateDraftVersion(chatId: details.id, draftVersion: 0)
            onDraftChanged(details.id)
            return
        }
        let existing = try await repository.record(chatId: details.id)
        try await repository.upsert(ComposerDraftRecord(
            chatId: details.id,
            encryptedMarkdown: encryptedMarkdown,
            encryptedPreview: details.encryptedDraftPreview ?? existing?.encryptedPreview ?? "",
            revision: existing?.revision ?? 0,
            draftVersion: draftVersion
        ))
        chatStore.updateDraftVersion(chatId: details.id, draftVersion: draftVersion)
        onDraftChanged(details.id)
    }

    private func upsertDraftChatIfNeeded(_ event: DraftUpdatedEvent) {
        guard chatStore.chat(for: event.chatId) == nil else { return }
        let timestamp = event.lastEditedOverallTimestamp ?? Int(Date().timeIntervalSince1970)
        let date = ISO8601DateFormatter().string(from: Date(timeIntervalSince1970: TimeInterval(timestamp)))
        chatStore.upsertChat(Chat(
            id: event.chatId,
            title: nil,
            lastMessageAt: nil,
            createdAt: date,
            updatedAt: date,
            isArchived: false,
            isPinned: false,
            appId: "ai",
            encryptedTitle: nil,
            encryptedChatKey: nil,
            draftV: event.versions.draftV
        ))
    }

    private func removeDraftOnlyChatIfNeeded(_ chatId: String) {
        guard let chat = chatStore.chat(for: chatId),
              isDraftOnlyChat(chat) else { return }
        chatStore.performWithoutPersistence { chatStore.removeChat(chatId) }
        offlineActions?.cascadeDeleteChat(chatId: chatId)
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
            chatStore.updateDraftVersion(chatId: record.chatId, draftVersion: record.draftVersion)
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
            draftV: record.draftVersion
        ))
    }

    private var decoder: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }
}

private extension ComposerDraftRecord {
    func withDraftVersion(_ draftVersion: Int) -> ComposerDraftRecord {
        ComposerDraftRecord(
            chatId: chatId,
            encryptedMarkdown: encryptedMarkdown,
            encryptedPreview: encryptedPreview,
            revision: revision,
            draftVersion: draftVersion
        )
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
}

private struct DraftUpdatedVersions: Decodable { let draftV: Int }

private struct DraftDeleteEnvelope: Decodable {
    let payload: DraftDeletePayload
}

private struct DraftDeletePayload: Decodable {
    let chatId: String
    let success: Bool?
}

private struct DraftVersionsEnvelope: Decodable { let payload: DraftVersionsPayload }
private struct DraftVersionsPayload: Decodable {
    let versions: [String: Int]
    let unavailableChatIds: [String]?
}

private struct DraftConflictEnvelope: Decodable { let payload: DraftConflictPayload }
private struct DraftConflictPayload: Decodable { let chatId: String }

private struct ChatDetailsEnvelope: Decodable { let payload: SyncedDraftDetails }

private struct SyncedDraftDetails: Decodable {
    let id: String
    let encryptedDraftMd: String?
    let encryptedDraftPreview: String?
    let draftV: Int?

    private enum CodingKeys: String, CodingKey {
        case id
        case chatId
        case encryptedDraftMd
        case encryptedDraftPreview
        case draftV
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decodeIfPresent(String.self, forKey: .id)
            ?? container.decode(String.self, forKey: .chatId)
        encryptedDraftMd = try container.decodeIfPresent(String.self, forKey: .encryptedDraftMd)
        encryptedDraftPreview = try container.decodeIfPresent(String.self, forKey: .encryptedDraftPreview)
        draftV = try container.decodeIfPresent(Int.self, forKey: .draftV)
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
