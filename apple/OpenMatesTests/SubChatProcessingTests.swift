// Unit coverage for Apple sub-chat WebSocket payload parity with the web app.
// These tests intentionally avoid network calls and verify only deterministic
// payload contracts that the backend already accepts from the web client.

import XCTest
@testable import OpenMates

@MainActor
final class SubChatProcessingTests: XCTestCase {
    func testSubChatConfirmationPayloadMatchesWebContract() {
        let payload = ChatSendPipeline().subChatConfirmationPayload(
            chatId: "parent-chat-1",
            taskId: "task-1",
            action: "approve",
            approveCount: 2
        )

        XCTAssertEqual(payload["chat_id"] as? String, "parent-chat-1")
        XCTAssertEqual(payload["task_id"] as? String, "task-1")
        XCTAssertEqual(payload["action"] as? String, "approve")
        XCTAssertEqual(payload["approve_count"] as? Int, 2)
    }

    func testSubChatStopPayloadMatchesWebContract() {
        let payload = ChatSendPipeline().subChatStopPayload(
            chatId: "parent-chat-1",
            taskId: "task-1"
        )

        XCTAssertEqual(payload["chat_id"] as? String, "parent-chat-1")
        XCTAssertEqual(payload["task_id"] as? String, "task-1")
    }

    func testSubChatOptionalPayloadFieldsAreOmittedWhenEmpty() {
        let confirmation = ChatSendPipeline().subChatConfirmationPayload(
            chatId: "parent-chat-1",
            taskId: "task-1",
            action: "cancel",
            approveCount: nil
        )
        let stop = ChatSendPipeline().subChatStopPayload(chatId: "parent-chat-1", taskId: nil)

        XCTAssertNil(confirmation["approve_count"])
        XCTAssertNil(stop["task_id"])
    }

    func testSubChatMessageContextIncludesParentBroadcastAndFocus() {
        let chat = Chat(
            id: "child-chat-1",
            title: "Child",
            lastMessageAt: "2026-01-01T00:00:00Z",
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: "2026-01-01T00:00:00Z",
            isArchived: false,
            isPinned: false,
            appId: "ai",
            encryptedTitle: nil,
            encryptedChatKey: nil,
            parentId: "parent-chat-1",
            isSubChat: true
        )

        let payload = ChatSendPipeline().chatContextPayloadFields(
            for: chat,
            broadcastToSiblings: true,
            activeFocusId: "jobs-career_insights"
        )

        XCTAssertEqual(payload["parent_id"] as? String, "parent-chat-1")
        XCTAssertEqual(payload["broadcast"] as? Bool, true)
        XCTAssertEqual(payload["active_focus_id"] as? String, "jobs-career_insights")
    }

    func testSubChatContextOmitsMissingParentId() {
        let chat = Chat(
            id: "parent-chat-1",
            title: "Parent",
            lastMessageAt: "2026-01-01T00:00:00Z",
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: "2026-01-01T00:00:00Z",
            isArchived: false,
            isPinned: false,
            appId: "ai",
            encryptedTitle: nil,
            encryptedChatKey: nil
        )

        let payload = ChatSendPipeline().chatContextPayloadFields(
            for: chat,
            broadcastToSiblings: false,
            activeFocusId: nil
        )

        XCTAssertNil(payload["parent_id"])
        XCTAssertEqual(payload["broadcast"] as? Bool, false)
        XCTAssertNil(payload["active_focus_id"])
    }
}
