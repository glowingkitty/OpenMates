// Unit coverage for bounded native chat-window loading helpers.
// These tests use deterministic in-memory chat data and never touch network,
// credentials, encryption keys, or private persisted chat content.
// They guard the Apple chat-opening path against accidentally materializing
// full large-chat histories before first render.

import XCTest
@testable import OpenMates

@MainActor
final class ChatWindowLoadingTests: XCTestCase {
    func testInitialWindowReturnsLatestBoundedMessages() {
        let store = seededStore(messageCount: 120)

        let window = store.initialMessageWindow(for: "unit-large-chat")

        XCTAssertEqual(window.count, ChatStore.boundedWindowSize)
        XCTAssertEqual(window.first?.id, "message-071")
        XCTAssertEqual(window.last?.id, "message-120")
    }

    func testOlderWindowReturnsOneBoundedPageBeforeBoundary() {
        let store = seededStore(messageCount: 120)

        let older = store.olderMessageWindow(for: "unit-large-chat", before: "message-071")

        XCTAssertEqual(older.count, ChatStore.boundedWindowSize)
        XCTAssertEqual(older.first?.id, "message-021")
        XCTAssertEqual(older.last?.id, "message-070")
    }

    func testHasOlderMessagesStopsAtOldestBoundary() {
        let store = seededStore(messageCount: 120)

        XCTAssertTrue(store.hasOlderMessages(for: "unit-large-chat", before: "message-021"))
        XCTAssertFalse(store.hasOlderMessages(for: "unit-large-chat", before: "message-001"))
        XCTAssertFalse(store.hasOlderMessages(for: "unit-large-chat", before: nil))
    }

    func testOpeningFallbackFetchesWhenSyncedChatHasMessagesButEmptyInitialWindow() {
        XCTAssertTrue(
            ChatOpeningFallbackPolicy.shouldFetchMissingSyncedMessages(
                messagesV: 2,
                lastMessageAt: nil
            )
        )
        XCTAssertTrue(
            ChatOpeningFallbackPolicy.shouldFetchMissingSyncedMessages(
                messagesV: nil,
                lastMessageAt: "2026-01-01T00:00:00Z"
            )
        )
        XCTAssertFalse(
            ChatOpeningFallbackPolicy.shouldFetchMissingSyncedMessages(
                messagesV: 0,
                lastMessageAt: nil
            )
        )
    }

    func testBatchUpsertMergesChatsWithoutRepeatedLookupSideEffects() {
        let store = ChatStore()
        store.performWithoutPersistence {
            store.upsertChats([
                makeChat(id: "chat-a", title: "A", updatedAt: "2026-01-01T00:00:00Z", messagesV: 1),
                makeChat(id: "chat-b", title: "B", updatedAt: "2026-01-02T00:00:00Z", messagesV: 1)
            ])
            store.upsertChats([
                makeChat(id: "chat-a", title: "A updated", updatedAt: "2026-01-03T00:00:00Z", messagesV: 2),
                makeChat(id: "chat-c", title: "C", updatedAt: "2026-01-04T00:00:00Z", messagesV: 1)
            ], serverSortOrder: ["chat-c", "chat-a", "chat-b"])
        }

        XCTAssertEqual(store.chats.map(\.id), ["chat-c", "chat-a", "chat-b"])
        XCTAssertEqual(store.chat(for: "chat-a")?.title, "A updated")
        XCTAssertEqual(store.chat(for: "chat-a")?.messagesV, 2)
        XCTAssertEqual(store.chats.count, 3)
    }

    private func seededStore(messageCount: Int) -> ChatStore {
        let store = ChatStore()
        store.performWithoutPersistence {
            store.setMessages(for: "unit-large-chat", messages: makeMessages(count: messageCount))
        }
        return store
    }

    private func makeMessages(count: Int) -> [Message] {
        (1...count).map { index in
            let id = String(format: "message-%03d", index)
            return Message(
                id: id,
                chatId: "unit-large-chat",
                role: index.isMultiple(of: 2) ? .assistant : .user,
                content: "Synthetic message \(index)",
                encryptedContent: nil,
                createdAt: String(format: "2026-01-01T00:%02d:%02dZ", index / 60, index % 60),
                updatedAt: nil,
                appId: nil,
                isStreaming: false,
                embedRefs: nil
            )
        }
    }

    private func makeChat(id: String, title: String, updatedAt: String, messagesV: Int) -> Chat {
        Chat(
            id: id,
            title: title,
            lastMessageAt: updatedAt,
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: updatedAt,
            isArchived: false,
            isPinned: false,
            appId: "ai",
            encryptedTitle: nil,
            encryptedChatKey: nil,
            messagesV: messagesV,
            titleV: messagesV
        )
    }
}
