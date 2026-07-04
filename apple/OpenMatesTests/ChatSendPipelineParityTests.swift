// Unit coverage for Apple chat-send pipeline parity with web chat storage.
// These tests avoid network calls, credentials, private chat content, and raw
// encryption keys. They guard the deterministic payload and retry contracts that
// make Apple-created chats decryptable from other clients such as OpenMates CLI.
// Keep assertions payload-level so the suite remains deterministic on Linux CI
// orchestration and remote Mac runners.

import XCTest
@testable import OpenMates

@MainActor
final class ChatSendPipelineParityTests: XCTestCase {
    func testCompletedAssistantVersionAdvancesPastUserMessageVersion() {
        let pipeline = ChatSendPipeline()

        XCTAssertEqual(
            pipeline.completedAssistantMessagesVersion(
                currentMessagesV: 1,
                localMessageCountAfterAppendingAssistant: 2
            ),
            2
        )
        XCTAssertEqual(
            pipeline.completedAssistantMessagesVersion(
                currentMessagesV: 5,
                localMessageCountAfterAppendingAssistant: 6
            ),
            6
        )
        XCTAssertEqual(
            pipeline.completedAssistantMessagesVersion(
                currentMessagesV: 1,
                localMessageCountAfterAppendingAssistant: 6
            ),
            6
        )
    }

    func testAssistantCompletionPayloadContainsOnlyEncryptedContentAndAdvancedVersion() {
        let pipeline = ChatSendPipeline()
        let createdAt = 1_780_000_000
        let message = Message(
            id: "assistant-1",
            chatId: "chat-1",
            role: .assistant,
            content: "Plaintext must stay local",
            encryptedContent: "encrypted-content",
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: nil,
            appId: "general_knowledge",
            isStreaming: false,
            embedRefs: nil,
            modelName: "test-model"
        )

        let payload = pipeline.assistantCompletionPayload(
            for: message,
            userMessageId: "user-1",
            encryptedContent: "encrypted-content",
            encryptedCategory: "encrypted-category",
            encryptedModelName: "encrypted-model",
            createdAtUnix: createdAt,
            currentMessagesV: 1,
            localMessageCountAfterAppendingAssistant: 2
        )

        XCTAssertEqual(payload["chat_id"] as? String, "chat-1")
        let messagePayload = payload["message"] as? [String: Any]
        XCTAssertEqual(messagePayload?["message_id"] as? String, "assistant-1")
        XCTAssertEqual(messagePayload?["encrypted_content"] as? String, "encrypted-content")
        XCTAssertNil(messagePayload?["content"])
        XCTAssertNil(messagePayload?["plaintext"])
        let versions = payload["versions"] as? [String: Int]
        XCTAssertEqual(versions?["messages_v"], 2)
        XCTAssertEqual(versions?["last_edited_overall_timestamp"], createdAt)
    }

    func testPendingAssistantResponseQueueStoresOnlyIdsAndDedupes() throws {
        let suiteName = "ChatSendPipelineParityTests"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
        defaults.removePersistentDomain(forName: suiteName)
        let queue = PendingAssistantResponseQueue(defaults: defaults, storageKey: "pending-test")

        queue.add(messageId: "assistant-1", chatId: "chat-1")
        queue.add(messageId: "assistant-1", chatId: "chat-1")
        queue.add(messageId: "assistant-2", chatId: "chat-1")

        XCTAssertEqual(queue.all(), [
            PendingAssistantResponseQueue.Entry(messageId: "assistant-1", chatId: "chat-1"),
            PendingAssistantResponseQueue.Entry(messageId: "assistant-2", chatId: "chat-1")
        ])
        let storedJSON = defaults.data(forKey: "pending-test").flatMap { String(data: $0, encoding: .utf8) } ?? ""
        XCTAssertFalse(storedJSON.contains("Plaintext"))

        queue.remove(messageId: "assistant-1")
        XCTAssertEqual(queue.all(), [
            PendingAssistantResponseQueue.Entry(messageId: "assistant-2", chatId: "chat-1")
        ])
        queue.clear()
    }

    func testCachedKeyWithProvidedWrappedKeyRequiresValidation() {
        let pipeline = ChatSendPipeline()

        XCTAssertTrue(pipeline.requiresCachedChatKeyValidation(cachedKeyExists: true, encryptedChatKey: "wrapped-key"))
        XCTAssertFalse(pipeline.requiresCachedChatKeyValidation(cachedKeyExists: true, encryptedChatKey: nil))
        XCTAssertFalse(pipeline.requiresCachedChatKeyValidation(cachedKeyExists: false, encryptedChatKey: "wrapped-key"))
    }

    func testPendingRetryInfersPrecedingUserMessageId() {
        let pipeline = ChatSendPipeline()
        let userMessage = Message(
            id: "user-1",
            chatId: "chat-1",
            role: .user,
            content: "User prompt",
            encryptedContent: "encrypted-user",
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: nil,
            appId: nil,
            isStreaming: false,
            embedRefs: nil
        )
        let assistantMessage = Message(
            id: "assistant-1",
            chatId: "chat-1",
            role: .assistant,
            content: "Assistant response",
            encryptedContent: "encrypted-assistant",
            createdAt: "2026-01-01T00:00:01Z",
            updatedAt: nil,
            appId: nil,
            isStreaming: false,
            embedRefs: nil
        )

        XCTAssertEqual(
            pipeline.inferredUserMessageId(before: assistantMessage, in: [assistantMessage, userMessage]),
            "user-1"
        )
    }
}
