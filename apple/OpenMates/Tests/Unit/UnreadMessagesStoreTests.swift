// UnreadMessagesStore unit tests — validates count tracking and badge.

import XCTest
@testable import OpenMates

final class UnreadMessagesStoreTests: XCTestCase {

    @MainActor func testIncrementUnread() {
        let store = UnreadMessagesStore.shared
        store.clearAll()

        store.incrementUnread(chatId: "chat-1")
        XCTAssertEqual(store.getUnreadCount(chatId: "chat-1"), 1)

        store.incrementUnread(chatId: "chat-1")
        XCTAssertEqual(store.getUnreadCount(chatId: "chat-1"), 2)

        store.clearAll()
    }

    @MainActor func testClearUnread() {
        let store = UnreadMessagesStore.shared
        store.clearAll()

        store.incrementUnread(chatId: "chat-2")
        store.incrementUnread(chatId: "chat-2")
        store.clearUnread(chatId: "chat-2")
        XCTAssertEqual(store.getUnreadCount(chatId: "chat-2"), 0)
        XCTAssertFalse(store.hasUnread(chatId: "chat-2"))

        store.clearAll()
    }

    @MainActor func testTotalUnread() {
        let store = UnreadMessagesStore.shared
        store.clearAll()

        store.incrementUnread(chatId: "chat-a")
        store.incrementUnread(chatId: "chat-b")
        store.incrementUnread(chatId: "chat-b")
        XCTAssertEqual(store.totalUnread, 3)

        store.clearUnread(chatId: "chat-a")
        XCTAssertEqual(store.totalUnread, 2)

        store.clearAll()
        XCTAssertEqual(store.totalUnread, 0)
    }

    @MainActor func testSetUnread() {
        let store = UnreadMessagesStore.shared
        store.clearAll()

        store.setUnread(chatId: "chat-sync", count: 5)
        XCTAssertEqual(store.getUnreadCount(chatId: "chat-sync"), 5)

        store.setUnread(chatId: "chat-sync", count: 0)
        XCTAssertFalse(store.hasUnread(chatId: "chat-sync"))

        store.clearAll()
    }
}
