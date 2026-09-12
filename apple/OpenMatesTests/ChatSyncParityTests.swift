// Unit coverage for Apple chat-sync metadata parity with the web app.
// These tests are deterministic and do not touch the network, credentials, or
// private persisted chat content. They guard native model changes that would
// otherwise silently drop sub-chat or active-focus metadata during sync.

import XCTest
import CoreFoundation
import SwiftData
@testable import OpenMates

@MainActor
final class ChatSyncParityTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=drafts.sync.version-authoritative,chat-navigation.open.local-first-coherent
    func testChatMergeKeepsDraftDeletionFenceThroughLatePageAndPersistenceCopies() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        func wire(_ fields: [String: Any]) throws -> Chat {
            var row: [String: Any] = ["id": "chat-1", "created_at": "2026-01-01T00:00:00Z"]
            row.merge(fields) { _, incoming in incoming }
            return try decoder.decode(Chat.self, from: JSONSerialization.data(withJSONObject: row))
        }
        let store = ChatStore()
        store.upsertChat(try wire(["draft_v": 7, "messages_v": 2, "encrypted_draft_md": "cipher-seven"]))
        store.upsertChat(try wire(["draft_v": 4, "encrypted_draft_md": "older-cipher"]))
        XCTAssertEqual(store.chat(for: "chat-1")?.draftV, 7)
        store.upsertChat(try wire(["draft_v": 0, "cleared_draft_v": 8,
                                   "encrypted_draft_md": NSNull()]))
        store.upsertChat(try wire(["draft_v": 7, "encrypted_draft_md": "late-cipher"]))
        store.updateLastVisibleMessage(chatId: "chat-1", messageId: "last")
        store.advanceMessagesVersion(chatId: "chat-1", to: 4)
        let cleared = try XCTUnwrap(store.chat(for: "chat-1"))
        XCTAssertEqual(cleared.draftV, 0)
        XCTAssertEqual(cleared.hasNonEmptyDraft, false)
        XCTAssertEqual(cleared.clearedDraftV, 8)
        let persisted = PersistedChat(from: cleared).toChat()
        XCTAssertEqual(persisted.clearedDraftV, 8)
        XCTAssertEqual(persisted.hasNonEmptyDraft, false)
        store.upsertChat(try wire(["draft_v": 9, "encrypted_draft_md": "fresh-cipher"]))
        XCTAssertEqual(store.chat(for: "chat-1")?.draftV, 9)
        XCTAssertEqual(store.chat(for: "chat-1")?.hasNonEmptyDraft, true)
        store.upsertChat(try wire(["draft_v": 0, "cleared_draft_v": 8, "encrypted_draft_md": NSNull()]))
        XCTAssertEqual(store.chat(for: "chat-1")?.draftV, 9)
        XCTAssertEqual(store.chat(for: "chat-1")?.hasNonEmptyDraft, true)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testFinalStreamAppendKeepsMatchingPendingCiphertextAndThinkingMetadata() {
        let store = ChatStore()
        let persisted = Message(id: "reply", chatId: "chat-1", role: .assistant,
                                content: "A complete response", encryptedContent: "local-ciphertext",
                                createdAt: "2026-01-01T00:00:01Z", updatedAt: nil,
                                appId: "ai", isStreaming: false, embedRefs: nil,
                                modelName: "fixture-model", encryptedModelName: "encrypted-model",
                                thinkingContent: "Fixture reasoning", encryptedThinkingContent: "encrypted-thinking")
        let lateStream = Message(id: persisted.id, chatId: persisted.chatId, role: .assistant,
                                 content: persisted.content, encryptedContent: nil,
                                 createdAt: persisted.createdAt, updatedAt: nil,
                                 appId: nil, isStreaming: false, embedRefs: nil)
        store.setPendingAssistantRecoveryLookup { _ in ["reply"] }
        store.appendMessage(persisted, to: "chat-1")
        store.appendMessage(lateStream, to: "chat-1")
        let result = store.messages(for: "chat-1").first
        XCTAssertEqual(result?.encryptedContent, "local-ciphertext")
        XCTAssertEqual(result?.thinkingContent, "Fixture reasoning")
        XCTAssertEqual(result?.encryptedThinkingContent, "encrypted-thinking")
        XCTAssertEqual(result?.modelName, "fixture-model")
        XCTAssertEqual(store.messages(for: "chat-1").count, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testPendingReplyNeverAttachesPriorCiphertextToChangedPlaintext() {
        let store = ChatStore()
        let persisted = makeMessage(id: "reply", createdAt: "2026-01-01T00:00:01Z",
                                    role: .assistant, encryptedContent: "previous-ciphertext")
        var changed = makeMessage(id: "reply", createdAt: persisted.createdAt, role: .assistant)
        changed.content = "Updated terminal content"
        store.setPendingAssistantRecoveryLookup { _ in ["reply"] }
        store.appendMessage(persisted, to: "chat-1")
        store.appendMessage(changed, to: "chat-1")
        XCTAssertEqual(store.messages(for: "chat-1").first?.content, "Updated terminal content")
        XCTAssertNil(store.messages(for: "chat-1").first?.encryptedContent)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testOrdinaryAppendDoesNotTreatOldCiphertextAsPendingRecovery() {
        let store = ChatStore()
        let persisted = makeMessage(id: "reply", createdAt: "2026-01-01T00:00:01Z",
                                    role: .assistant, encryptedContent: "previous-ciphertext")
        let replacement = makeMessage(id: "reply", createdAt: persisted.createdAt, role: .assistant)
        store.appendMessage(persisted, to: "chat-1")
        store.appendMessage(replacement, to: "chat-1")
        XCTAssertNil(store.messages(for: "chat-1").first?.encryptedContent)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testSyncRetainsOnlyPendingAssistantRepliesUntilTheirServerCommit() {
        let store = ChatStore()
        let user = makeMessage(id: "user", createdAt: "2026-01-01T00:00:00Z")
        let pending = makeMessage(id: "pending", createdAt: "2026-01-01T00:00:02Z", role: .assistant)
        let deleted = makeMessage(id: "deleted", createdAt: "2026-01-01T00:00:01Z", role: .assistant)
        store.setMessages(for: "chat-1", messages: [user, deleted, pending])
        var pendingIds: Set<String> = ["pending"]
        store.setPendingAssistantRecoveryLookup { $0 == "chat-1" ? pendingIds : [] }

        store.applySyncedContent(messagesByChat: ["chat-1": [user]], embedsByChat: [:])
        XCTAssertEqual(store.messages(for: "chat-1").map(\.id), ["user", "pending"])

        pendingIds.removeAll()
        store.applySyncedContent(messagesByChat: ["chat-1": [user]], embedsByChat: [:])
        XCTAssertEqual(store.messages(for: "chat-1").map(\.id), ["user"], "Completed or discarded jobs must not pin absent history forever")
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testServerCiphertextReplacesPendingReplyWithoutDuplicatingIt() {
        let store = ChatStore()
        let pending = makeMessage(id: "reply", createdAt: "2026-01-01T00:00:01Z", role: .assistant)
        let committed = makeMessage(id: "reply", createdAt: pending.createdAt, role: .assistant,
                                    encryptedContent: "server-ciphertext")
        store.setMessages(for: "chat-1", messages: [pending])
        store.setPendingAssistantRecoveryLookup { _ in ["reply"] }
        store.applySyncedContent(messagesByChat: ["chat-1": [committed]], embedsByChat: [:])
        XCTAssertEqual(store.messages(for: "chat-1").count, 1)
        XCTAssertEqual(store.messages(for: "chat-1").first?.encryptedContent, "server-ciphertext")
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testPendingRecoveryCannotRetainUserRowsOrRowsFromAnotherChat() {
        let store = ChatStore()
        let user = makeMessage(id: "user", createdAt: "2026-01-01T00:00:00Z")
        let foreign = makeMessage(id: "foreign", createdAt: "2026-01-01T00:00:01Z", role: .assistant, chatId: "chat-2")
        store.setMessages(for: "chat-1", messages: [user, foreign])
        store.setPendingAssistantRecoveryLookup { _ in ["user", "foreign"] }
        store.applySyncedContent(messagesByChat: ["chat-1": []], embedsByChat: [:])
        XCTAssertTrue(store.messages(for: "chat-1").isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testSyncPreservingPendingReplyDoesNotAdvanceAdvertisedMessageVersion() {
        let store = ChatStore()
        store.upsertChat(makeChat(id: "chat-1", title: "Fixture"))
        let before = store.makeSyncClientState(clientSuggestionsCount: 0).clientChatVersions
        store.setMessages(for: "chat-1", messages: [makeMessage(id: "reply", createdAt: "2026-01-01T00:00:01Z", role: .assistant)])
        store.setPendingAssistantRecoveryLookup { _ in ["reply"] }
        store.applySyncedContent(messagesByChat: ["chat-1": []], embedsByChat: [:])
        XCTAssertEqual(store.makeSyncClientState(clientSuggestionsCount: 0).clientChatVersions, before)
        XCTAssertEqual(store.messages(for: "chat-1").map(\.id), ["reply"])
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testSearchMetadataExpansionIncludesOlderEncryptedTitlesWithoutReplacingLiveRows() {
        let live = makeChat(id: "loaded", title: "Current decrypted title")
        let cachedOld = makeChat(id: "older", title: nil, encryptedTitle: "encrypted-title-fixture")
        let stale = makeChat(id: "loaded", title: "Old cached title")
        let privateChat = makeChat(id: "incognito-private", title: "Private")
        let missing = ChatSearchMetadata.missingCachedChats([stale, cachedOld, cachedOld, privateChat], loaded: [live])
        XCTAssertEqual(missing.map(\.id), ["older"])
        XCTAssertEqual(missing.first?.encryptedTitle, "encrypted-title-fixture")
        XCTAssertNil(missing.first?.title)
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.open.local-first-coherent
    func testChatSortDatesPreserveFractionsAndTimeZonesAcrossRepeatedReads() throws {
        let precise = makeChat(id: "fractional", title: "Fixture", lastMessageAt: "2026-03-01T12:00:00.125Z")
        let offset = makeChat(id: "offset", title: "Fixture", lastMessageAt: "2026-03-01T13:00:00+01:00")
        let invalid = makeChat(id: "invalid", title: "Fixture", lastMessageAt: "not-a-date")
        let timestamp = try XCTUnwrap(precise.lastMessageDate)
        XCTAssertEqual(timestamp.timeIntervalSince(try XCTUnwrap(offset.lastMessageDate)), 0.125, accuracy: 0.001)
        for _ in 0..<1000 { XCTAssertEqual(precise.lastMessageDate, timestamp) }
        XCTAssertNil(invalid.lastMessageDate)
    }

    // contract-test: direct surface=gui.apple assertions=sync.surface.semantic-parity
    func testPersonalStartupSyncSendsRequiredIntegerContextEpoch() throws {
        let request = WebSocketManager.phasedSyncMessage(clientChatIds: ["known-chat"])
        let wire = try JSONSerialization.jsonObject(with: JSONEncoder().encode(request)) as? [String: Any]
        let payload = try XCTUnwrap(wire?["payload"] as? [String: Any])
        let epoch = try XCTUnwrap(payload["context_epoch"] as? NSNumber)
        XCTAssertNotEqual(CFGetTypeID(epoch), CFBooleanGetTypeID(), "The server rejects boolean epochs")
        XCTAssertEqual(epoch.intValue, 0)
        XCTAssertNil(payload["team_id"], "Personal sync must not select a team")
        XCTAssertEqual(payload["client_chat_ids"] as? [String], ["known-chat"])
    }

    // contract-test: direct surface=gui.apple assertions=sync.surface.semantic-parity
    func testOlderMetadataPagePreservesServerOrderAfterTheInitialWindow() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let page = try decoder.decode(ChatMetadataPage.self, from: Data("""
        {"offset":2,"total_count":3,"has_more":false,"chats":[
          {"chat_details":{"id":"older","created_at":1770000000}}
        ]}
        """.utf8))
        let initial = try decoder.decode([Chat].self, from: Data("""
        [{"id":"first","created_at":1770000000},{"id":"second","created_at":1770000000}]
        """.utf8))
        let store = ChatStore()
        store.upsertChats(initial, serverSortOrder: initial.map(\.id))
        let older = try XCTUnwrap(page.chats?.compactMap(\.chatDetails))
        store.upsertChats(older, serverSortOrder: older.map(\.id), serverSortOffset: page.offset)
        XCTAssertEqual(store.sortedChats.map(\.id), ["first", "second", "older"])
        XCTAssertEqual(page.totalCount, 3)
        XCTAssertEqual(page.hasMore, false)
    }

    // contract-test: direct surface=gui.apple assertions=sync.deletion.partial-window-not-authoritative,sync.surface.semantic-parity
    func testMetadataSyncRetainsExplicitServerTombstonesEvenForAnEmptyWindow() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let payload = try decoder.decode(PhaseBulkSyncPayload.self, from: Data("""
        {"chats":[],"total_chat_count":150,"deleted_chat_ids":["deleted-while-offline"]}
        """.utf8))
        XCTAssertEqual(payload.deletedChatIds, ["deleted-while-offline"], "Metadata decoding must not discard explicit server deletions")
        XCTAssertEqual(payload.totalChatCount, 150)
    }

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

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity,chat-navigation.open.local-first-coherent
    func testContinuationUsesActualWireDraftPresenceInsteadOfVersion() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        func decoded(_ id: String, encryptedDraft: Any, version: Int, timestamp: Int) throws -> Chat {
            try decoder.decode(Chat.self, from: JSONSerialization.data(withJSONObject: [
                "id": id, "title": id, "created_at": 1, "updated_at": timestamp,
                "last_edited_overall_timestamp": timestamp, "draft_v": version,
                "encrypted_draft_md": encryptedDraft
            ]))
        }
        let cleared = try decoded("cleared", encryptedDraft: NSNull(), version: 9, timestamp: 30)
        let empty = try decoded("empty", encryptedDraft: "", version: 4, timestamp: 20)
        let actual = try decoded("actual", encryptedDraft: "encrypted-body", version: 0, timestamp: 10)
        XCTAssertEqual(WelcomeScreenState.recentChats(from: [cleared, empty, actual], excluding: nil).map(\.id),
                       ["actual", "cleared", "empty"])
        XCTAssertEqual(PersistedChat(from: actual).toChat().hasNonEmptyDraft, true)
        XCTAssertEqual(PersistedChat(from: cleared).toChat().hasNonEmptyDraft, false)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testMetadataUpdateDoesNotInventMessageRecencyAndEqualTiesIgnoreSidebarOrder() throws {
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        let onlyMetadata = try decoder.decode(Chat.self, from: Data(#"{"id":"metadata-only","title":"Metadata","created_at":1,"updated_at":9999999999}"#.utf8))
        XCTAssertNil(onlyMetadata.lastMessageAt, "Editing metadata must not become a message timestamp")
        let a = makeChat(id: "a", title: "A")
        let z = makeChat(id: "z", title: "Z")
        let store = ChatStore()
        store.upsertChats([a, z, onlyMetadata], serverSortOrder: ["a", "z"])
        XCTAssertEqual(WelcomeScreenState.recentChats(from: store.chats, excluding: nil).map(\.id), ["z", "a", "metadata-only"])
    }

    // contract-test: supporting surface=gui.apple assertions=drafts.sync.version-authoritative,chat-navigation.open.local-first-coherent
    func testDraftPresenceSurvivesPartialMetadataAndClearsOnActualDelete() {
        let store = ChatStore()
        store.upsertChat(makeChat(id: "draft", title: "Draft", draftV: 7, hasNonEmptyDraft: true))
        store.upsertChat(makeChat(id: "draft", title: "Metadata", draftV: 7))
        XCTAssertEqual(store.chat(for: "draft")?.hasNonEmptyDraft, true)
        store.advanceMessagesVersion(chatId: "draft", to: 3)
        store.updateLastVisibleMessage(chatId: "draft", messageId: "message")
        XCTAssertEqual(store.chat(for: "draft")?.hasNonEmptyDraft, true)
        store.updateDraftVersion(chatId: "draft", draftVersion: 0)
        XCTAssertEqual(store.chat(for: "draft")?.hasNonEmptyDraft, false)
        store.updateDraftVersion(chatId: "draft", draftVersion: 1, hasNonEmptyDraft: true)
        XCTAssertEqual(store.chat(for: "draft")?.hasNonEmptyDraft, true)
        store.upsertChat(makeChat(id: "draft", title: "Deleted", draftV: 8, hasNonEmptyDraft: false))
        XCTAssertEqual(store.chat(for: "draft")?.hasNonEmptyDraft, false)
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.open.local-first-coherent
    func testContinuationCapKeepsViewedChatFirstWithoutResortingOtherChatsByOpening() {
        let older = makeChat(id: "viewed", title: "Viewed", lastMessageAt: "2025-01-01T00:00:00Z")
        let recent = (0..<15).map { makeChat(id: String(format: "recent-%02d", $0), title: "Recent") }
        let chats = recent + [older]
        let resume = WelcomeScreenState.resumeChat(from: chats, lastOpened: older.id)
        let other = WelcomeScreenState.recentChats(from: chats, excluding: resume?.id, activeChatId: "recent-14")
        XCTAssertEqual(resume?.id, older.id)
        XCTAssertEqual(other.count, 9)
        XCTAssertEqual(other.first?.id, "recent-13")
        XCTAssertFalse(other.contains { $0.id == older.id || $0.id == "recent-14" })
        XCTAssertEqual(WelcomeScreenState.recentChats(from: chats, excluding: nil).count, 10)
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.open.local-first-coherent,chats.local-state.precedence
    func testColdStartupIncludesOlderPinnedDraftAndUnpinnedDraftMetadataBeyondRecentPage() throws {
        let schema = Schema([PersistedChat.self, PersistedMessage.self])
        let configuration = ModelConfiguration("ContinuationPolicyTests", schema: schema, isStoredInMemoryOnly: true)
        let store = OfflineStore(modelContainer: try ModelContainer(for: schema, configurations: [configuration]))
        let recent = (0..<40).map { makeChat(id: "recent-\($0)", title: "Recent", lastMessageAt: "2026-09-12T00:00:00Z") }
        let pinnedRecent = (0..<30).map { makeChat(id: "pinned-\($0)", title: "Pinned", lastMessageAt: "2026-01-01T00:00:00Z", isPinned: true) }
        let pinnedDraft = makeChat(id: "older-pinned-draft", title: "Pinned draft", lastMessageAt: "2025-01-01T00:00:00Z", isPinned: true, draftV: 3, hasNonEmptyDraft: true)
        let draft = makeChat(id: "older-draft", title: "Draft", lastMessageAt: "2025-01-02T00:00:00Z", draftV: 2, hasNonEmptyDraft: true)
        store.persistChats(recent + pinnedRecent + [pinnedDraft, draft])
        let loaded = store.loadStartupChats(lastOpenedChatId: nil, limit: 20)
        XCTAssertTrue(loaded.contains { $0.id == pinnedDraft.id })
        XCTAssertTrue(loaded.contains { $0.id == draft.id })
        XCTAssertLessThanOrEqual(loaded.count, 80, "Four metadata groups remain bounded; no transcript is loaded")
        XCTAssertEqual(WelcomeScreenState.recentChats(from: loaded, excluding: nil).first?.id, pinnedDraft.id)
        XCTAssertTrue(store.loadMessages(chatId: pinnedDraft.id).isEmpty)
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

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.open.local-first-coherent
    func testContinuationMatchesPinnedDraftRecentOrderAndSkipsSubChats() {
        let recent = makeChat(id: "recent", title: "Recent", lastMessageAt: "2026-03-01T00:00:00Z")
        let draft = makeChat(id: "draft", title: nil, messagesV: 0, draftV: 2, hasNonEmptyDraft: true)
        let pinned = makeChat(id: "pinned", title: "Pinned", isPinned: true)
        let child = makeChat(id: "child", title: "Child", parentId: "recent", isSubChat: true)
        let incognito = makeChat(id: "incognito-private", title: "Private")
        let chats = [recent, child, incognito, draft, pinned]
        XCTAssertEqual(WelcomeScreenState.recentChats(from: chats, excluding: nil).map(\.id), ["pinned", "draft", "recent"])
        XCTAssertNil(WelcomeScreenState.resumeChat(from: chats, lastOpened: "draft"))
        XCTAssertNil(WelcomeScreenState.resumeChat(from: chats, lastOpened: "child"))
        XCTAssertEqual(WelcomeScreenState.resumeChat(from: chats, lastOpened: "recent")?.id, "recent")
        XCTAssertEqual(WelcomeScreenState.recentChats(from: chats, excluding: "recent").map(\.id), ["pinned", "draft"])
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.open.local-first-coherent,drafts.persistence.local-first-encrypted
    func testContinuationDraftCardUsesPreviewWithoutMisclassifyingUntitledMessages() {
        let draft = makeChat(id: "draft", title: nil, messagesV: 0, draftV: 1)
        let existing = makeChat(id: "existing", title: nil, messagesV: 2, draftV: 1)
        let preview = String(repeating: "a", count: 90)
        let card = WelcomeScreenState.cardData(for: draft, draftPreview: preview)
        XCTAssertTrue(card.isDraftOnly)
        XCTAssertEqual(card.title, AppStrings.draftBadge)
        XCTAssertEqual(card.draftPreview, String(repeating: "a", count: 80) + "…")
        XCTAssertFalse(WelcomeScreenState.cardData(for: existing, draftPreview: "Unsent follow-up").isDraftOnly)
        XCTAssertEqual(WelcomeScreenState.resumeChat(from: [existing], lastOpened: "existing")?.id, "existing")
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
        isHiddenCandidate: Bool? = nil,
        isPinned: Bool = false,
        draftV: Int? = nil,
        encryptedTitle: String? = nil,
        hasNonEmptyDraft: Bool? = nil
    ) -> Chat {
        Chat(
            id: id,
            title: title,
            lastMessageAt: lastMessageAt,
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: "2026-01-01T00:00:00Z",
            isArchived: isArchived,
            isPinned: isPinned,
            appId: "ai",
            encryptedTitle: encryptedTitle,
            encryptedChatKey: nil,
            messagesV: messagesV,
            titleV: title == nil ? 0 : 1,
            draftV: draftV,
            metadataV: metadataV,
            parentId: parentId,
            isSubChat: isSubChat,
            encryptedActiveFocusId: encryptedActiveFocusId,
            isHidden: isHidden,
            isHiddenCandidate: isHiddenCandidate,
            hasNonEmptyDraft: hasNonEmptyDraft
        )
    }

    private func makeMessage(id: String, createdAt: String, role: MessageRole = .user,
                             chatId: String = "chat-1", encryptedContent: String? = nil) -> Message {
        Message(
            id: id,
            chatId: chatId,
            role: role,
            content: id,
            encryptedContent: encryptedContent,
            createdAt: createdAt,
            updatedAt: nil,
            appId: nil,
            isStreaming: false,
            embedRefs: nil
        )
    }
}
