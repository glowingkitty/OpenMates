// EditMessageStore unit tests — validates edit context tracking.

import XCTest
@testable import OpenMates

final class EditMessageStoreTests: XCTestCase {

    @MainActor func testStartEdit() {
        let store = EditMessageStore.shared
        store.cancelEdit()

        store.startEdit(chatId: "chat-1", messageId: "msg-1", content: "Original", createdAt: "2026-01-01")
        XCTAssertTrue(store.isEditing)
        XCTAssertEqual(store.editingMessageId, "msg-1")
        XCTAssertEqual(store.editingChatId, "chat-1")
        XCTAssertEqual(store.editingContext?.originalContent, "Original")

        store.cancelEdit()
    }

    @MainActor func testCancelEdit() {
        let store = EditMessageStore.shared
        store.startEdit(chatId: "chat-1", messageId: "msg-1", content: "Test", createdAt: "2026-01-01")
        store.cancelEdit()

        XCTAssertFalse(store.isEditing)
        XCTAssertNil(store.editingMessageId)
        XCTAssertNil(store.editingContext)
    }

    @MainActor func testCompleteEdit() {
        let store = EditMessageStore.shared
        store.startEdit(chatId: "chat-1", messageId: "msg-1", content: "Test", createdAt: "2026-01-01")
        store.completeEdit()

        XCTAssertFalse(store.isEditing)
    }

    @MainActor func testIsMessageBeingEdited() {
        let store = EditMessageStore.shared
        store.cancelEdit()

        store.startEdit(chatId: "chat-1", messageId: "msg-42", content: "Test", createdAt: "2026-01-01")
        XCTAssertTrue(store.isMessageBeingEdited("msg-42"))
        XCTAssertFalse(store.isMessageBeingEdited("msg-99"))

        store.cancelEdit()
    }

    @MainActor func testIsInEditModeForChat() {
        let store = EditMessageStore.shared
        store.cancelEdit()

        store.startEdit(chatId: "chat-5", messageId: "msg-1", content: "Test", createdAt: "2026-01-01")
        XCTAssertTrue(store.isInEditMode(chatId: "chat-5"))
        XCTAssertFalse(store.isInEditMode(chatId: "chat-99"))

        store.cancelEdit()
    }
}
