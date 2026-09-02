// Unit coverage for Apple chat-sync metadata parity with the web app.
// These tests are deterministic and do not touch the network, credentials, or
// private persisted chat content. They guard native model changes that would
// otherwise silently drop sub-chat or active-focus metadata during sync.

import XCTest
@testable import OpenMates

@MainActor
final class ChatSyncParityTests: XCTestCase {
    // contract-test: direct surface=gui.apple assertions=sync.surface.semantic-parity
    func testChatDecodesWebSubChatAndFocusFields() throws {
        let json = """
        {
          "chat_id": "child-chat-1",
          "title": "Research Apple Q1",
          "created_at": 1770000000,
          "updated_at": 1770000300,
          "parent_id": "parent-chat-1",
          "is_sub_chat": true,
          "sub_chat_settings": { "wait_for_completion": true, "report_trigger": "all" },
          "budget_limit": 12,
          "budget_spent": 3,
          "encrypted_active_focus_id": "encrypted-focus",
          "messages_v": 2,
          "title_v": 1,
          "metadata_v": 7
        }
        """.data(using: .utf8)!

        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let chat = try decoder.decode(Chat.self, from: json)

        XCTAssertEqual(chat.id, "child-chat-1")
        XCTAssertEqual(chat.parentId, "parent-chat-1")
        XCTAssertEqual(chat.isSubChat, true)
        XCTAssertEqual(chat.subChatSettings?.waitForCompletion, true)
        XCTAssertEqual(chat.subChatSettings?.reportTrigger, "all")
        XCTAssertEqual(chat.budgetLimit, 12)
        XCTAssertEqual(chat.budgetSpent, 3)
        XCTAssertEqual(chat.encryptedActiveFocusId, "encrypted-focus")
        XCTAssertEqual(chat.metadataV, 7)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.local-state.precedence
    func testChatDecodesVisibilityFieldsUsedByNativeOfflineAndSpotlightGuards() throws {
        let json = """
        {
          "chat_id": "hidden-chat-1",
          "title": "Hidden research",
          "created_at": 1770000000,
          "updated_at": 1770000300,
          "is_private": true,
          "is_hidden": true,
          "is_hidden_candidate": true
        }
        """.data(using: .utf8)!

        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let chat = try decoder.decode(Chat.self, from: json)

        XCTAssertEqual(chat.isPrivate, true)
        XCTAssertEqual(chat.isHidden, true)
        XCTAssertEqual(chat.isHiddenCandidate, true)
        XCTAssertTrue(chat.isHiddenFromNormalSurfaces)
    }

    // contract-test: direct surface=gui.apple assertions=sync.surface.semantic-parity,chats.local-state.precedence
    func testChatStoreMergePreservesSubChatAndFocusMetadata() {
        let store = ChatStore()
        let base = makeChat(
            id: "child-chat-1",
            title: "Child",
            parentId: "parent-chat-1",
            isSubChat: true,
            encryptedActiveFocusId: "encrypted-focus",
            isHiddenCandidate: true
        )
        let incoming = makeChat(
            id: "child-chat-1",
            title: nil,
            parentId: nil,
            isSubChat: nil,
            encryptedActiveFocusId: nil,
            messagesV: 4,
            metadataV: 5
        )

        store.performWithoutPersistence {
            store.upsertChat(base)
            store.upsertChat(incoming)
        }

        let merged = store.chat(for: "child-chat-1")
        XCTAssertEqual(merged?.title, "Child")
        XCTAssertEqual(merged?.parentId, "parent-chat-1")
        XCTAssertEqual(merged?.isSubChat, true)
        XCTAssertEqual(merged?.encryptedActiveFocusId, "encrypted-focus")
        XCTAssertEqual(merged?.messagesV, 4)
        XCTAssertEqual(merged?.metadataV, 5)
        XCTAssertEqual(merged?.isHiddenCandidate, true)
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.open.local-first-coherent
    func testWelcomeResumeAndRecentChatsExcludeHiddenCandidates() {
        let visible = makeChat(id: "visible-chat", title: "Visible", lastMessageAt: "2026-01-02T00:00:00Z")
        let hidden = makeChat(
            id: "hidden-chat",
            title: "Hidden",
            lastMessageAt: "2026-01-03T00:00:00Z",
            isHiddenCandidate: true
        )

        XCTAssertNil(WelcomeScreenState.resumeChat(from: [hidden, visible], lastOpened: "hidden-chat"))
        XCTAssertEqual(WelcomeScreenState.resumeChat(from: [hidden, visible], lastOpened: "visible-chat")?.id, "visible-chat")

        let recent = WelcomeScreenState.recentChats(from: [hidden, visible], excluding: nil)
        XCTAssertEqual(recent.map(\.id), ["visible-chat"])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.local-state.precedence
    func testSpotlightEligibilitySkipsHiddenPublicAndArchivedChats() {
        let privateVisible = makeChat(id: "private-visible", title: "Private but searchable")
        let hidden = makeChat(id: "hidden-chat", title: "Hidden", isHidden: true)
        let archived = makeChat(id: "archived-chat", title: "Archived", isArchived: true)
        let publicChat = makeChat(id: "example-gigantic-airplanes", title: "Public example")

        XCTAssertTrue(SpotlightIndexer.isEligibleForSpotlight(privateVisible))
        XCTAssertFalse(SpotlightIndexer.isEligibleForSpotlight(hidden))
        XCTAssertFalse(SpotlightIndexer.isEligibleForSpotlight(archived))
        XCTAssertFalse(SpotlightIndexer.isEligibleForSpotlight(publicChat))
    }

    // contract-test: direct surface=gui.apple assertions=sync.startup.bounded-phases,sync.surface.semantic-parity
    func testSyncClientStateExcludesIncognitoChats() {
        let store = ChatStore()
        let saved = makeChat(id: "saved-chat", title: "Saved")
        let incognito = makeChat(id: IncognitoChatSession.makeChatId(), title: "Private")

        store.performWithoutPersistence {
            store.upsertChat(saved)
            store.upsertChat(incognito)
        }

        let state = store.makeSyncClientState(clientSuggestionsCount: 0)
        XCTAssertEqual(state.clientChatIds, ["saved-chat"])
        XCTAssertNotNil(state.clientChatVersions["saved-chat"])
        XCTAssertEqual(state.clientChatVersions["saved-chat"]?["metadata_v"], 1)
        XCTAssertFalse(state.clientChatVersions.keys.contains(incognito.id))
    }

    // contract-test: direct surface=gui.apple assertions=chat-navigation.open.local-first-coherent,sync.deletion.partial-window-not-authoritative
    func testPartialSyncNeverClearsCurrentSelectionWithoutExplicitTombstone() {
        XCTAssertFalse(ChatSelectionSyncPolicy.shouldClearSelection(
            selectedChatId: "chat-1",
            eventType: "phase_2_last_20_chats_ready",
            eventChatId: nil
        ))
        XCTAssertFalse(ChatSelectionSyncPolicy.shouldClearSelection(
            selectedChatId: "chat-1",
            eventType: "sync_metadata_chats_response",
            eventChatId: "chat-1"
        ))
        XCTAssertTrue(ChatSelectionSyncPolicy.shouldClearSelection(
            selectedChatId: "chat-1",
            eventType: "chat_deleted",
            eventChatId: "chat-1"
        ))
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity,chats.persistence.client-encrypted
    func testTypingMetadataWaitsForOriginatingUserMessage() throws {
        let data = """
        {
          "chat_id": "chat-1",
          "message_id": "assistant-1",
          "user_message_id": "user-1",
          "encrypted_chat_key": "wrapped-key"
        }
        """.data(using: .utf8)!
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let payload = try decoder.decode(AITypingStartedSyncPayload.self, from: data)
        var buffer = TypingMetadataReplayBuffer()

        XCTAssertTrue(buffer.deferIfMessageMissing(payload, messageExists: false))
        XCTAssertEqual(buffer.take(for: "user-1")?.messageId, "assistant-1")
        XCTAssertNil(buffer.take(for: "user-1"))
        XCTAssertFalse(buffer.deferIfMessageMissing(payload, messageExists: true))
    }

    // contract-test: direct surface=gui.apple assertions=sync.surface.semantic-parity,chats.sync.key-gated-recovery,chat-navigation.open.local-first-coherent
    func testContentBatchDecodesVersionsAndKeyMaterialForStoreReconciliation() throws {
        let fields: [String: Any] = [
            "messages_by_chat_id": ["chat-1": []],
            "versions_by_chat_id": ["chat-1": ["messages_v": 7, "server_message_count": 6]],
            "embeds": [],
            "embed_keys": [],
            "chat_key_wrappers": [[
                "id": "wrapper-2",
                "hashed_chat_id": ChatKeyWrapperRecord.hashedChatId(for: "chat-1"),
                "key_type": "master",
                "encrypted_chat_key": "wrapped-key",
                "wrapper_version": 2,
                "created_at": "2026-08-24T00:00:00Z",
            ]],
        ]

        let payload = try ChatContentBatchPayload.decode(fields)

        XCTAssertEqual(try payload.messages(for: "chat-1").count, 0)
        XCTAssertEqual(payload.messagesVersion(for: "chat-1"), 7)
        XCTAssertEqual(payload.chatKeyWrappers.count, 1)
        XCTAssertEqual(payload.chatKeyWrappers.first?.hashedChatId, ChatKeyWrapperRecord.hashedChatId(for: "chat-1"))
        XCTAssertEqual(payload.chatKeyWrappers.first?.encryptedChatKey, "wrapped-key")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.sync.key-gated-recovery
    func testNewestMasterChatKeyWrapperIsTriedFirst() throws {
        let data = """
        [
          {"id":"old","hashed_chat_id":"\(ChatKeyWrapperRecord.hashedChatId(for: "chat-1"))","key_type":"master","encrypted_chat_key":"old-key","wrapper_version":1,"created_at":"2026-08-23T00:00:00Z"},
          {"id":"other","hashed_chat_id":"\(ChatKeyWrapperRecord.hashedChatId(for: "chat-2"))","key_type":"master","encrypted_chat_key":"other-key","wrapper_version":9,"created_at":"2026-08-24T00:00:00Z"},
          {"id":"new","hashed_chat_id":"\(ChatKeyWrapperRecord.hashedChatId(for: "chat-1"))","key_type":"master","encrypted_chat_key":"new-key","wrapper_version":2,"created_at":"2026-08-24T00:00:00Z"}
        ]
        """.data(using: .utf8)!
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let wrappers = try decoder.decode([ChatKeyWrapperRecord].self, from: data)

        let ordered = ChatKeyWrapperRecord.orderedMasterWrappers(wrappers, for: "chat-1")

        XCTAssertEqual(ordered.map(\.id), ["new", "old"])
    }

    // contract-test: direct surface=gui.apple assertions=chat-navigation.open.local-first-coherent
    func testContentBatchMergePreservesMessagesThatArrivedDuringHydration() {
        let snapshot = [makeMessage(id: "snapshot", createdAt: "2026-01-01T00:00:00Z")]
        let realtime = [makeMessage(id: "realtime", createdAt: "2026-01-01T00:00:01Z")]

        let merged = ChatContentBatchPayload.mergedMessages(snapshot: snapshot, preserving: realtime)

        XCTAssertEqual(merged.map(\.id), ["snapshot", "realtime"])
    }

    private func makeChat(
        id: String,
        title: String?,
        parentId: String? = nil,
        isSubChat: Bool? = nil,
        encryptedActiveFocusId: String? = nil,
        messagesV: Int? = 1,
        metadataV: Int? = 1,
        lastMessageAt: String = "2026-01-01T00:00:00Z",
        isArchived: Bool = false,
        isHidden: Bool? = nil,
        isHiddenCandidate: Bool? = nil
    ) -> Chat {
        Chat(
            id: id,
            title: title,
            lastMessageAt: lastMessageAt,
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: "2026-01-01T00:00:00Z",
            isArchived: isArchived,
            isPinned: false,
            appId: "ai",
            encryptedTitle: nil,
            encryptedChatKey: nil,
            messagesV: messagesV,
            titleV: title == nil ? 0 : 1,
            metadataV: metadataV,
            parentId: parentId,
            isSubChat: isSubChat,
            encryptedActiveFocusId: encryptedActiveFocusId,
            isHidden: isHidden,
            isHiddenCandidate: isHiddenCandidate
        )
    }

    private func makeMessage(id: String, createdAt: String) -> Message {
        Message(
            id: id,
            chatId: "chat-1",
            role: .user,
            content: id,
            encryptedContent: nil,
            createdAt: createdAt,
            updatedAt: nil,
            appId: nil,
            isStreaming: false,
            embedRefs: nil
        )
    }
}
