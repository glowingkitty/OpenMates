// Cross-client contract coverage for encrypted Apple draft synchronization.
// Tests use synthetic ciphertext and IDs; no draft plaintext, credentials, or
// network access enters durable storage. Web draft events remain authoritative.
// Partial sync pages must never become deletion evidence.
// The focused coordinator is tested independently from composer rendering.

import XCTest
@testable import OpenMates

@MainActor
final class DraftSyncParityTests: XCTestCase {
    func testFirstNewChatDraftAllocatesOneStableUUIDAndSendsOnlyCiphertext() async throws {
        let repository = DraftSyncRecordingRepository(records: [
            "composer:new-chat": ComposerDraftRecord(
                chatId: "composer:new-chat",
                encryptedMarkdown: "legacy-format-d-markdown",
                encryptedPreview: "legacy-format-d-preview",
                revision: 12,
                draftVersion: 0
            ),
        ])
        let transport = DraftSyncRecordingTransport(isConnected: true)
        let offline = DraftSyncRecordingOfflineActions()
        let coordinator = DraftSyncCoordinator(
            repository: repository,
            chatStore: ChatStore(),
            transport: transport,
            offlineActions: offline,
            uuid: { UUID(uuidString: "A4AA24E7-6682-4D50-89B4-BEC4423C4E86")! }
        )
        let record = ComposerDraftRecord(
            chatId: "composer:new-chat",
            encryptedMarkdown: "format-d-encrypted-markdown",
            encryptedPreview: "format-d-encrypted-preview",
            revision: 13,
            draftVersion: 0
        )

        let firstId = coordinator.resolveChatId(record.chatId, hasNonEmptyDraft: true)
        let secondId = coordinator.resolveChatId(record.chatId, hasNonEmptyDraft: true)
        XCTAssertEqual(firstId, "a4aa24e7-6682-4d50-89b4-bec4423c4e86")
        XCTAssertEqual(secondId, firstId)
        XCTAssertEqual(coordinator.activeNewChatDraftId, firstId)

        try await coordinator.submitLocalUpdate(record, resolvedChatId: firstId)

        let message = try XCTUnwrap(transport.sent.last)
        XCTAssertEqual(message.type, "update_draft")
        XCTAssertEqual(message.payload["chat_id"] as? String, firstId)
        XCTAssertEqual(message.payload["encrypted_draft_md"] as? String, record.encryptedMarkdown)
        XCTAssertEqual(message.payload["encrypted_draft_preview"] as? String, record.encryptedPreview)
        XCTAssertFalse(String(reflecting: message.payload).contains("composer:new-chat"))
        XCTAssertTrue(offline.queuedUpdates.isEmpty)
        let syntheticRecord = try await repository.record(chatId: "composer:new-chat")
        XCTAssertNil(syntheticRecord, "Synthetic composer IDs must never remain in durable storage")
    }

    func testOfflineUpdateAndDeleteQueueOnlyEncryptedProtocolFields() async throws {
        let repository = DraftSyncRecordingRepository()
        let transport = DraftSyncRecordingTransport(isConnected: false)
        let offline = DraftSyncRecordingOfflineActions()
        let coordinator = DraftSyncCoordinator(
            repository: repository,
            chatStore: ChatStore(),
            transport: transport,
            offlineActions: offline
        )
        let record = ComposerDraftRecord(
            chatId: "chat-1",
            encryptedMarkdown: "format-d-md",
            encryptedPreview: "format-d-preview",
            revision: 7,
            draftVersion: 2
        )

        try await coordinator.submitLocalUpdate(record, resolvedChatId: record.chatId)
        try await coordinator.submitLocalDelete(chatId: record.chatId)

        XCTAssertEqual(offline.queuedUpdates.count, 1)
        XCTAssertEqual(offline.queuedUpdates.first?.chatId, record.chatId)
        XCTAssertEqual(offline.queuedUpdates.first?.encryptedMarkdown, record.encryptedMarkdown)
        XCTAssertEqual(offline.queuedDeletes, [record.chatId])
        XCTAssertTrue(transport.sent.isEmpty)
        XCTAssertFalse(String(reflecting: offline.queuedUpdates).contains("plaintext"))
    }

    func testClearingNewChatDraftAfterSendPreservesPersistedChat() async throws {
        let repository = DraftSyncRecordingRepository()
        let transport = DraftSyncRecordingTransport(isConnected: true)
        let offline = DraftSyncRecordingOfflineActions()
        let chatStore = ChatStore()
        let coordinator = DraftSyncCoordinator(
            repository: repository,
            chatStore: chatStore,
            transport: transport,
            offlineActions: offline,
            uuid: { UUID(uuidString: "A4AA24E7-6682-4D50-89B4-BEC4423C4E86")! }
        )
        let chatId = coordinator.resolveChatId("composer:new-chat", hasNonEmptyDraft: true)
        chatStore.performWithoutPersistence {
            chatStore.upsertChat(makeChat(id: chatId, messagesV: 1))
        }

        try await coordinator.submitLocalDelete(chatId: chatId)

        XCTAssertNotNil(chatStore.chat(for: chatId))
        XCTAssertTrue(offline.cascadedChatIds.isEmpty)
        XCTAssertNil(coordinator.activeNewChatDraftId)
        XCTAssertEqual(transport.sent.last?.type, "delete_draft")
    }

    func testReceiptAndBroadcastPersistAuthoritativeVersionWithoutEcho() async throws {
        let repository = DraftSyncRecordingRepository(records: [
            "chat-1": ComposerDraftRecord(
                chatId: "chat-1",
                encryptedMarkdown: "local-md",
                encryptedPreview: "local-preview",
                revision: 4,
                draftVersion: 1
            ),
        ])
        let transport = DraftSyncRecordingTransport(isConnected: true)
        var changedChatIds: [String] = []
        let coordinator = DraftSyncCoordinator(
            repository: repository,
            chatStore: ChatStore(),
            transport: transport,
            offlineActions: DraftSyncRecordingOfflineActions(),
            onDraftChanged: { changedChatIds.append($0) }
        )

        try await coordinator.handleEvent(type: "draft_update_receipt", raw: jsonData([
            "type": "draft_update_receipt",
            "payload": ["chat_id": "chat-1", "draft_v": 2, "success": true],
        ]))
        var storedRecord = try await repository.record(chatId: "chat-1")
        var stored = try XCTUnwrap(storedRecord)
        XCTAssertEqual(stored.draftVersion, 2)

        try await coordinator.handleEvent(type: "chat_draft_updated", raw: jsonData([
            "event": "chat_draft_updated",
            "chat_id": "chat-1",
            "data": [
                "encrypted_draft_md": "remote-md",
                "encrypted_draft_preview": "remote-preview",
            ],
            "versions": ["draft_v": 3],
            "last_edited_overall_timestamp": 1_780_000_000,
        ]))
        storedRecord = try await repository.record(chatId: "chat-1")
        stored = try XCTUnwrap(storedRecord)
        XCTAssertEqual(stored.encryptedMarkdown, "remote-md")
        XCTAssertEqual(stored.encryptedPreview, "remote-preview")
        XCTAssertEqual(stored.draftVersion, 3)
        XCTAssertTrue(transport.sent.isEmpty, "Inbound broadcasts must not echo update_draft")
        XCTAssertEqual(changedChatIds, ["chat-1", "chat-1"])
    }

    func testPersistedDraftOnlyChatRestoresSyntheticNewChatAlias() {
        let chatStore = ChatStore()
        chatStore.performWithoutPersistence {
            chatStore.upsertChat(makeChat(id: "restored-draft", draftV: 2))
            chatStore.upsertChat(makeChat(id: "existing-chat", messagesV: 1, draftV: 2))
        }
        let coordinator = DraftSyncCoordinator(
            repository: DraftSyncRecordingRepository(),
            chatStore: chatStore,
            transport: DraftSyncRecordingTransport(isConnected: true),
            offlineActions: DraftSyncRecordingOfflineActions()
        )

        coordinator.restoreNewChatDraftId(from: [
            ComposerDraftRecord(chatId: "restored-draft", encryptedMarkdown: "md", encryptedPreview: "preview", revision: 1, draftVersion: 2),
            ComposerDraftRecord(chatId: "existing-chat", encryptedMarkdown: "md", encryptedPreview: "preview", revision: 1, draftVersion: 2),
        ])

        XCTAssertEqual(
            coordinator.resolveChatId(DraftSyncCoordinator.syntheticNewChatId, hasNonEmptyDraft: false),
            "restored-draft"
        )
    }

    func testInboundDraftOnlyChatBecomesActiveNewChatDraft() async throws {
        let coordinator = DraftSyncCoordinator(
            repository: DraftSyncRecordingRepository(),
            chatStore: ChatStore(),
            transport: DraftSyncRecordingTransport(isConnected: true),
            offlineActions: DraftSyncRecordingOfflineActions()
        )

        try await coordinator.handleEvent(type: "chat_draft_updated", raw: jsonData([
            "event": "chat_draft_updated",
            "chat_id": "remote-draft",
            "data": [
                "encrypted_draft_md": "remote-md",
                "encrypted_draft_preview": "remote-preview",
            ],
            "versions": ["draft_v": 1],
            "last_edited_overall_timestamp": 1_780_000_000,
        ]))

        XCTAssertEqual(coordinator.activeNewChatDraftId, "remote-draft")
    }

    func testReconnectRequestsVersionsAndClearsServerDeletedDrafts() async throws {
        let repository = DraftSyncRecordingRepository(records: [
            "chat-1": ComposerDraftRecord(
                chatId: "chat-1",
                encryptedMarkdown: "ciphertext",
                encryptedPreview: "preview-ciphertext",
                revision: 2,
                draftVersion: 4
            ),
        ])
        let transport = DraftSyncRecordingTransport(isConnected: true)
        let coordinator = DraftSyncCoordinator(
            repository: repository,
            chatStore: ChatStore(),
            transport: transport,
            offlineActions: DraftSyncRecordingOfflineActions()
        )

        try await coordinator.reconcileAfterReconnect()
        XCTAssertEqual(transport.sent.last?.type, "get_draft_versions")

        try await coordinator.handleEvent(type: "draft_versions_response", raw: jsonData([
            "type": "draft_versions_response",
            "payload": ["versions": ["chat-1": 0]],
        ]))
        let deletedDraft = try await repository.record(chatId: "chat-1")
        XCTAssertNil(deletedDraft)
    }

    func testRemoteDraftDeletionRemovesOnlyEmptyDraftChatShell() async throws {
        let repository = DraftSyncRecordingRepository(records: [
            "draft-only": ComposerDraftRecord(chatId: "draft-only", encryptedMarkdown: "md", encryptedPreview: "preview", revision: 1, draftVersion: 1),
            "persisted": ComposerDraftRecord(chatId: "persisted", encryptedMarkdown: "md", encryptedPreview: "preview", revision: 1, draftVersion: 1),
        ])
        let chatStore = ChatStore()
        chatStore.performWithoutPersistence {
            chatStore.upsertChat(makeChat(id: "draft-only"))
            chatStore.upsertChat(makeChat(id: "persisted", messagesV: 2))
        }
        let offline = DraftSyncRecordingOfflineActions()
        var changedChatIds: [String] = []
        let coordinator = DraftSyncCoordinator(
            repository: repository,
            chatStore: chatStore,
            transport: DraftSyncRecordingTransport(isConnected: true),
            offlineActions: offline,
            onDraftChanged: { changedChatIds.append($0) }
        )

        for chatId in ["draft-only", "persisted"] {
            try await coordinator.handleEvent(type: "draft_deleted", raw: jsonData([
                "type": "draft_deleted",
                "payload": ["chat_id": chatId],
            ]))
        }

        XCTAssertNil(chatStore.chat(for: "draft-only"))
        XCTAssertNotNil(chatStore.chat(for: "persisted"))
        XCTAssertEqual(offline.cascadedChatIds, ["draft-only"])
        XCTAssertEqual(changedChatIds, ["draft-only", "persisted"])
    }

    func testOnlyAuthoritativeSyncOrExplicitTombstonesCascadeDeletion() async throws {
        let repository = DraftSyncRecordingRepository(records: [
            "keep": ComposerDraftRecord(chatId: "keep", encryptedMarkdown: "md", encryptedPreview: "preview", revision: 1, draftVersion: 1),
            "omitted": ComposerDraftRecord(chatId: "omitted", encryptedMarkdown: "md", encryptedPreview: "preview", revision: 1, draftVersion: 1),
            "tombstone": ComposerDraftRecord(chatId: "tombstone", encryptedMarkdown: "md", encryptedPreview: "preview", revision: 1, draftVersion: 1),
        ])
        let chatStore = ChatStore()
        chatStore.performWithoutPersistence {
            chatStore.upsertChat(makeChat(id: "keep"))
            chatStore.upsertChat(makeChat(id: "omitted"))
            chatStore.upsertChat(makeChat(id: "tombstone"))
        }
        let offline = DraftSyncRecordingOfflineActions()
        let coordinator = DraftSyncCoordinator(
            repository: repository,
            chatStore: chatStore,
            transport: DraftSyncRecordingTransport(isConnected: true),
            offlineActions: offline
        )

        try await coordinator.reconcileChats(
            authoritative: false,
            authoritativeChatIds: ["keep"],
            deletedChatIds: []
        )
        XCTAssertNotNil(chatStore.chat(for: "omitted"), "Partial pages must not prune omitted chats")

        try await coordinator.reconcileChats(
            authoritative: true,
            authoritativeChatIds: ["keep"],
            deletedChatIds: ["tombstone"]
        )
        XCTAssertNil(chatStore.chat(for: "omitted"))
        XCTAssertNil(chatStore.chat(for: "tombstone"))
        let omittedDraft = try await repository.record(chatId: "omitted")
        let tombstoneDraft = try await repository.record(chatId: "tombstone")
        XCTAssertNil(omittedDraft)
        XCTAssertNil(tombstoneDraft)
        XCTAssertEqual(Set(offline.cascadedChatIds), ["omitted", "tombstone"])
    }

    func testAuthoritativeDraftSyncPreservesOptimisticChatWithSentMessage() async throws {
        let repository = DraftSyncRecordingRepository(records: [
            "optimistic-chat": ComposerDraftRecord(
                chatId: "optimistic-chat",
                encryptedMarkdown: "md",
                encryptedPreview: "preview",
                revision: 1,
                draftVersion: 1
            ),
        ])
        let chatStore = ChatStore()
        chatStore.performWithoutPersistence {
            chatStore.upsertChat(makeChat(id: "optimistic-chat", messagesV: 1))
            chatStore.appendMessage(makeUserMessage(chatId: "optimistic-chat"), to: "optimistic-chat")
        }
        let offline = DraftSyncRecordingOfflineActions()
        let coordinator = DraftSyncCoordinator(
            repository: repository,
            chatStore: chatStore,
            transport: DraftSyncRecordingTransport(isConnected: true),
            offlineActions: offline
        )

        try await coordinator.reconcileChats(
            authoritative: true,
            authoritativeChatIds: [],
            deletedChatIds: []
        )

        XCTAssertNotNil(chatStore.chat(for: "optimistic-chat"))
        XCTAssertEqual(chatStore.messages(for: "optimistic-chat").map(\.id), ["user-1"])
        XCTAssertNotNil(try await repository.record(chatId: "optimistic-chat"))
        XCTAssertTrue(offline.cascadedChatIds.isEmpty)
    }

    private func jsonData(_ value: [String: Any]) throws -> Data {
        try JSONSerialization.data(withJSONObject: value)
    }

    private func makeChat(id: String, messagesV: Int = 0, draftV: Int = 1) -> Chat {
        Chat(
            id: id,
            title: id,
            lastMessageAt: nil,
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: nil,
            isArchived: false,
            isPinned: false,
            appId: "ai",
            encryptedTitle: nil,
            encryptedChatKey: nil,
            messagesV: messagesV,
            draftV: draftV
        )
    }

    private func makeUserMessage(chatId: String) -> Message {
        Message(
            id: "user-1",
            chatId: chatId,
            role: .user,
            content: "Synthetic prompt",
            encryptedContent: "encrypted-user",
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: nil,
            appId: nil,
            isStreaming: false,
            embedRefs: nil
        )
    }
}

private actor DraftSyncRecordingRepository: ComposerDraftRepository {
    private var records: [String: ComposerDraftRecord]

    init(records: [String: ComposerDraftRecord] = [:]) {
        self.records = records
    }

    func upsert(_ record: ComposerDraftRecord) async throws { records[record.chatId] = record }
    func record(chatId: String) async throws -> ComposerDraftRecord? { records[chatId] }
    func remove(chatId: String) async throws { records.removeValue(forKey: chatId) }
    func removeAll() async throws { records.removeAll() }
    func allRecords() async throws -> [ComposerDraftRecord] { Array(records.values) }
}

@MainActor
private final class DraftSyncRecordingTransport: DraftSyncTransport {
    var isConnected: Bool
    private(set) var sent: [DraftSyncMessage] = []

    init(isConnected: Bool) {
        self.isConnected = isConnected
    }

    func sendDraftSyncMessage(_ message: DraftSyncMessage) async throws {
        sent.append(message)
    }
}

@MainActor
private final class DraftSyncRecordingOfflineActions: DraftSyncOfflineActions {
    private(set) var queuedUpdates: [ComposerDraftRecord] = []
    private(set) var queuedDeletes: [String] = []
    private(set) var cascadedChatIds: [String] = []

    func queueDraftUpdate(_ record: ComposerDraftRecord) { queuedUpdates.append(record) }
    func queueDraftDelete(chatId: String) { queuedDeletes.append(chatId) }
    func cascadeDeleteChat(chatId: String) { cascadedChatIds.append(chatId) }
}
