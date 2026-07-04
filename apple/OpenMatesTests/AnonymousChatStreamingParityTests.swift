// Unit coverage for Apple anonymous chat streaming parity.
// Anonymous chats start signed out, stay local until promotion, and must reuse
// the same foreground lifecycle reducer without durable plaintext storage. These
// tests exercise deterministic contracts only: no network calls, credentials,
// private chat content, or raw encryption keys.

import XCTest
@testable import OpenMates

final class AnonymousChatStreamingParityTests: XCTestCase {
    func testAnonymousStreamingUsesSharedLifecycleReducer() {
        var state = ChatStreamingLifecycleState()

        state.apply(.processingStarted(
            chatId: "anonymous-chat-1",
            messageId: "assistant-1",
            taskId: "task-1",
            message: "Processing"
        ))
        state.apply(.thinkingUpdate(
            chatId: "anonymous-chat-1",
            messageId: "assistant-1",
            text: "Thinking",
            isStreaming: true
        ))
        state.apply(.chunk(
            chatId: "anonymous-chat-1",
            messageId: "assistant-1",
            sequence: 1,
            content: "Partial anonymous response",
            isFinal: false,
            userMessageId: "user-1",
            category: "ai",
            modelName: "model-1",
            rejectionReason: nil
        ))

        XCTAssertEqual(state.phase, .streaming)
        XCTAssertEqual(state.messageId, "assistant-1")
        XCTAssertEqual(state.latestThinkingText, "Thinking")
        XCTAssertTrue(state.isThinkingStreaming)
        XCTAssertTrue(state.isActive)

        state.apply(.final(
            chatId: "anonymous-chat-1",
            messageId: "assistant-1",
            content: "Final anonymous response",
            userMessageId: "user-1",
            category: "ai",
            modelName: "model-1"
        ))

        XCTAssertEqual(state.phase, .completed)
        XCTAssertFalse(state.isThinkingStreaming)
        XCTAssertFalse(state.isActive)
    }

    func testPromotionPayloadContainsEncryptedMetadataAndVersionsOnly() throws {
        let payload = AnonymousChatPromotionPayload(
            chatId: "anonymous-chat-1",
            createdAtUnix: 1_780_000_000,
            messageHistory: [[
                "message_id": "user-1",
                "chat_id": "anonymous-chat-1",
                "role": "user",
                "created_at": 1_780_000_001,
                "encrypted_content": "encrypted-user-message",
                "encrypted_sender_name": "encrypted-user"
            ]],
            messagesV: 2,
            titleV: 1,
            lastEditedOverallTimestamp: 1_780_000_002,
            encryptedChatKey: "encrypted-chat-key",
            encryptedTitle: "encrypted-title",
            encryptedIcon: "encrypted-icon",
            encryptedCategory: "encrypted-category"
        ).dictionary

        XCTAssertEqual(payload["chat_id"] as? String, "anonymous-chat-1")
        XCTAssertEqual(payload["created_at"] as? Int, 1_780_000_000)
        XCTAssertEqual(payload["encrypted_chat_key"] as? String, "encrypted-chat-key")
        XCTAssertEqual(payload["encrypted_title"] as? String, "encrypted-title")
        XCTAssertEqual(payload["encrypted_icon"] as? String, "encrypted-icon")
        XCTAssertEqual(payload["encrypted_chat_category"] as? String, "encrypted-category")
        XCTAssertNil(payload["title"])
        XCTAssertNil(payload["content"])
        XCTAssertNil(payload["plaintext"])

        let versions = try XCTUnwrap(payload["versions"] as? [String: Int])
        XCTAssertEqual(versions["messages_v"], 2)
        XCTAssertEqual(versions["title_v"], 1)
        XCTAssertEqual(versions["last_edited_overall_timestamp"], 1_780_000_002)

        let history = try XCTUnwrap(payload["message_history"] as? [[String: Any]])
        XCTAssertEqual(history.count, 1)
        XCTAssertEqual(history.first?["encrypted_content"] as? String, "encrypted-user-message")
        XCTAssertNil(history.first?["content"])
        XCTAssertNil(history.first?["plaintext"])
    }
}
