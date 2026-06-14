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

    func testChatStoreMergePreservesSubChatAndFocusMetadata() {
        let store = ChatStore()
        let base = makeChat(
            id: "child-chat-1",
            title: "Child",
            parentId: "parent-chat-1",
            isSubChat: true,
            encryptedActiveFocusId: "encrypted-focus"
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
    }

    private func makeChat(
        id: String,
        title: String?,
        parentId: String?,
        isSubChat: Bool?,
        encryptedActiveFocusId: String?,
        messagesV: Int? = 1
    ) -> Chat {
        Chat(
            id: id,
            title: title,
            lastMessageAt: "2026-01-01T00:00:00Z",
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: "2026-01-01T00:00:00Z",
            isArchived: false,
            isPinned: false,
            appId: "ai",
            encryptedTitle: nil,
            encryptedChatKey: nil,
            messagesV: messagesV,
            titleV: title == nil ? 0 : 1,
            parentId: parentId,
            isSubChat: isSubChat,
            encryptedActiveFocusId: encryptedActiveFocusId
        )
    }
}
