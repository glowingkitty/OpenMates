// Unit coverage for Apple chat-sync metadata parity with the web app.
// These tests are deterministic and do not touch the network, credentials, or
// private persisted chat content. They guard native model changes that would
// otherwise silently drop sub-chat or active-focus metadata during sync.

import XCTest
@testable import OpenMates

@MainActor
final class ChatSyncParityTests: XCTestCase {
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
          "title_v": 1
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
    }

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
            messagesV: 4
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
        XCTAssertEqual(merged?.isHiddenCandidate, true)
    }

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

    func testSpotlightEligibilitySkipsHiddenPublicAndArchivedChats() {
        let privateVisible = makeChat(id: "private-visible", title: "Private but searchable")
        let hidden = makeChat(id: "hidden-chat", title: "Hidden", isHidden: true)
        let archived = makeChat(id: "archived-chat", title: "Archived", isArchived: true)
        let publicChat = makeChat(id: "demo-for-everyone", title: "Public demo")

        XCTAssertTrue(SpotlightIndexer.isEligibleForSpotlight(privateVisible))
        XCTAssertFalse(SpotlightIndexer.isEligibleForSpotlight(hidden))
        XCTAssertFalse(SpotlightIndexer.isEligibleForSpotlight(archived))
        XCTAssertFalse(SpotlightIndexer.isEligibleForSpotlight(publicChat))
    }

    private func makeChat(
        id: String,
        title: String?,
        parentId: String? = nil,
        isSubChat: Bool? = nil,
        encryptedActiveFocusId: String? = nil,
        messagesV: Int? = 1,
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
            parentId: parentId,
            isSubChat: isSubChat,
            encryptedActiveFocusId: encryptedActiveFocusId,
            isHidden: isHidden,
            isHiddenCandidate: isHiddenCandidate
        )
    }
}
