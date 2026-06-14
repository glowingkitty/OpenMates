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
}
