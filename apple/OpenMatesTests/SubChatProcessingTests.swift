// Unit coverage for Apple sub-chat WebSocket payload parity with the web app.
// These tests intentionally avoid network calls and verify only deterministic
// payload contracts that the backend already accepts from the web client.

import XCTest
import CryptoKit
@testable import OpenMates

@MainActor
final class SubChatProcessingTests: XCTestCase {
    // contract-test: direct surface=gui.apple assertions=chats.rendering.assistant-document-convergence,chats.surface.semantic-parity
    func testBatchMarkerBecomesOrderedSemanticBlock() {
        let marker = """
        ```json
        {"type":"sub_chat_batch","batch_id":"batch-1","chat_id":"parent-1","status":"finished","sub_chat_ids":["child-b","child-a"]}
        ```

        Summary follows.
        """
        let blocks = MarkdownParser.parse(marker)
        guard case .subChatBatch(let batch) = blocks.first else {
            return XCTFail("Batch marker was rendered as raw code")
        }
        XCTAssertEqual(batch.batchID, "batch-1")
        XCTAssertEqual(batch.subChatIDs, ["child-b", "child-a"])
        XCTAssertEqual(batch.status, "finished")
        XCTAssertTrue(blocks.contains(.paragraph("Summary follows.")))

        let message = Message(id: "message-1", chatId: "parent-1", role: .assistant,
                              content: marker, encryptedContent: nil, createdAt: "2026-01-01T00:00:00Z",
                              updatedAt: nil, appId: "ai", isStreaming: false, embedRefs: nil)
        let document = ChatHistoryRenderDocument.build(for: message)
        XCTAssertEqual(document?.blocks.first?.kind, .subChatBatch)
        XCTAssertEqual(document?.blocks.first?.subChatBatch, batch)
    }

    // contract-test: direct surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    func testIncompleteOrInvalidBatchProtocolDoesNotShowRawJSON() {
        let invalid = "```json\n{\"type\":\"sub_chat_batch\",\"batch_id\":\"\"}\n```"
        XCTAssertEqual(MarkdownParser.parse(invalid), [.hiddenProtocol])
        let damaged = "```json\n{\"type\": \"sub_chat_batch\", \"batch_id\": }\n```"
        XCTAssertEqual(MarkdownParser.parse(damaged), [.hiddenProtocol])
        let partial = "```json\n{\"type\":\"sub_chat_batch\",\"batch_id\":\"batch-1"
        XCTAssertEqual(ChatMessageStreamingRenderPolicy.visibleContent(partial), "")
        XCTAssertEqual(MarkdownParser.parseSpans(partial, isStreaming: true).map(\.block), [.hiddenProtocol])
    }

    // contract-test: direct surface=gui.apple assertions=chats.surface.semantic-parity
    func testBatchOnlyExposesChildrenOfCurrentParentInMarkerOrder() {
        let descriptor = SubChatBatchDescriptor.parse("""
        {"type":"sub_chat_batch","batch_id":"batch-1","chat_id":"parent-1","sub_chat_ids":["foreign","child-b","child-a","child-b"]}
        """)!
        func chat(_ id: String, parent: String?) -> Chat {
            Chat(id: id, title: id, lastMessageAt: nil, createdAt: "2026-01-01T00:00:00Z",
                 updatedAt: nil, isArchived: false, isPinned: false, appId: "ai",
                 encryptedTitle: nil, encryptedChatKey: nil, parentId: parent, isSubChat: true)
        }
        let chats = [chat("child-a", parent: "parent-1"), chat("foreign", parent: "parent-2"),
                     chat("child-b", parent: "parent-1")]
        XCTAssertEqual(descriptor.orderedChildren(in: chats, parentID: "parent-1").map(\.id), ["child-b", "child-a"])
        XCTAssertTrue(descriptor.orderedChildren(in: chats, parentID: "parent-2").isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence,chats.surface.semantic-parity
    func testImplicitBatchUsesMessageTimeToExcludeOtherBatchChildren() {
        let descriptor = SubChatBatchDescriptor.parse(
            #"{"type":"sub_chat_batch","batch_id":"batch-1","chat_id":"parent-1"}"#
        )!
        func child(_ id: String, at createdAt: String) -> Chat {
            Chat(id: id, title: id, lastMessageAt: nil, createdAt: createdAt,
                 updatedAt: nil, isArchived: false, isPinned: false, appId: "ai",
                 encryptedTitle: nil, encryptedChatKey: nil,
                 parentId: "parent-1", isSubChat: true)
        }
        let chats = [child("near", at: "2026-01-01T00:00:59Z"),
                     child("other-batch", at: "2026-01-01T00:01:00Z")]
        XCTAssertEqual(descriptor.orderedChildren(
            in: chats, parentID: "parent-1", messageCreatedAt: "2026-01-01T00:00:00Z"
        ).map(\.id), ["near"])
        let exampleDescriptor = SubChatBatchDescriptor.parse(
            #"{"type":"sub_chat_batch","batch_id":"batch-1","chat_id":"example-parent-1"}"#
        )!
        let exampleChild = Chat(id: "example-child", title: "Example", lastMessageAt: nil,
                                createdAt: "2026-01-01T01:00:00Z", updatedAt: nil,
                                isArchived: false, isPinned: false, appId: "ai",
                                encryptedTitle: nil, encryptedChatKey: nil,
                                parentId: "example-parent-1", isSubChat: true)
        XCTAssertEqual(exampleDescriptor.orderedChildren(
            in: [exampleChild], parentID: "example-parent-1", messageCreatedAt: "2026-01-01T00:00:00Z"
        ).map(\.id), ["example-child"])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    func testPreviewUsesLatestCompletedAssistantReplyWhenSummaryMissing() {
        let chat = Chat(id: "child-1", title: "Child", lastMessageAt: nil,
                        createdAt: "2026-01-01T00:00:00Z", updatedAt: nil,
                        isArchived: false, isPinned: false, appId: "ai",
                        encryptedTitle: nil, encryptedChatKey: nil,
                        parentId: "parent-1", isSubChat: true)
        func reply(_ id: String, _ content: String, streaming: Bool = false) -> Message {
            Message(id: id, chatId: chat.id, role: .assistant, content: content,
                    encryptedContent: "ciphertext", createdAt: "2026-01-01T00:00:00Z",
                    updatedAt: nil, appId: "ai", isStreaming: streaming, embedRefs: nil)
        }
        let messages = [reply("complete", "Completed answer with  two spaces."),
                        reply("streaming", "Still working", streaming: true)]
        XCTAssertEqual(SubChatBatchPreviewText.summary(for: chat, messages: messages),
                       "Completed answer with two spaces.")
        XCTAssertNil(SubChatBatchPreviewText.summary(
            for: chat, messages: [reply("protocol", "```json\n{\"type\":\"sub_chat_batch\"}\n```")]
        ))
    }

    // contract-test: direct surface=gui.apple assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testEncryptedChildPreviewUsesParentKeyAndCompletedReply() async throws {
        let parentID = "parent-\(UUID().uuidString)"
        let childID = "child-\(UUID().uuidString)"
        let key = SymmetricKey(data: Data(repeating: 0x42, count: 32))
        ChatKeyManager.shared.setKey(key, for: parentID)
        let encryptedTitle = try await CryptoManager.shared.encryptContent("Encrypted child title", key: key)
        let encryptedCategory = try await CryptoManager.shared.encryptContent("finance", key: key)
        let encryptedReply = try await CryptoManager.shared.encryptContent("Confirmed result from child.", key: key)
        let chat = Chat(id: childID, title: nil, lastMessageAt: nil,
                        createdAt: "2026-01-01T00:00:00Z", updatedAt: nil,
                        isArchived: false, isPinned: false, appId: "ai",
                        encryptedTitle: encryptedTitle, encryptedCategory: encryptedCategory,
                        encryptedChatKey: nil, parentId: parentID, isSubChat: true)
        let reply = Message(id: "reply-1", chatId: childID, role: .assistant, content: nil,
                            encryptedContent: encryptedReply, createdAt: "2026-01-01T00:00:01Z",
                            updatedAt: nil, appId: "ai", isStreaming: false, embedRefs: nil)
        let preview = await SubChatPreviewLoader.resolve(chat: chat, parentID: parentID, messages: [reply])
        XCTAssertEqual(preview?.title, "Encrypted child title")
        XCTAssertEqual(preview?.category, "finance")
        XCTAssertEqual(preview?.summary, "Confirmed result from child.")
    }

    // contract-test: direct surface=gui.apple assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testCompletedChildSummaryIsEncryptedBeforeLocalStorage() async throws {
        let childID = "child-\(UUID().uuidString)"
        let key = SymmetricKey(data: Data(repeating: 0x37, count: 32))
        ChatKeyManager.shared.setKey(key, for: childID)
        let child = Chat(id: childID, title: "Child", lastMessageAt: nil,
                         createdAt: "2026-01-01T00:00:00Z", updatedAt: nil,
                         isArchived: false, isPinned: false, appId: "ai",
                         encryptedTitle: nil, encryptedChatKey: "wrapped-key",
                         parentId: "parent-1", isSubChat: true)
        let completed = try await ChatSendPipeline().encryptSubChatSummary(
            child, summary: "Private completed result", key: key
        )
        XCTAssertEqual(completed.chatSummary, "Private completed result")
        let ciphertext = try XCTUnwrap(completed.encryptedChatSummary)
        XCTAssertFalse(ciphertext.contains("Private completed result"))
        let decrypted = try await CryptoManager.shared.decryptContent(base64String: ciphertext, key: key)
        XCTAssertEqual(decrypted, "Private completed result")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testSpawnedChildStoragePackageContainsOnlyEncryptedContentAndParentLink() throws {
        let chat = Chat(id: "child-1", title: "Private child title", lastMessageAt: nil,
                        createdAt: "2026-01-01T00:00:00Z", updatedAt: nil,
                        isArchived: false, isPinned: false, appId: "ai",
                        category: "finance", icon: "money",
                        encryptedTitle: "encrypted-title", encryptedCategory: "encrypted-category",
                        encryptedIcon: "encrypted-icon", encryptedChatKey: "wrapped-parent-key",
                        messagesV: 1, titleV: 0, parentId: "parent-1", isSubChat: true)
        let message = Message(id: "user-1", chatId: "child-1", role: .user,
                              content: "Private child prompt", encryptedContent: "encrypted-prompt",
                              createdAt: "2026-01-01T00:00:00Z", updatedAt: nil,
                              appId: nil, isStreaming: false, embedRefs: nil)
        let payload = try ChatSendPipeline().spawnedSubChatStoragePayload(
            chat: chat, firstMessage: message, encryptedSenderName: "encrypted-sender", timestamp: 1
        )
        XCTAssertEqual(payload["parent_id"] as? String, "parent-1")
        XCTAssertEqual(payload["is_sub_chat"] as? Bool, true)
        XCTAssertEqual(payload["encrypted_chat_key"] as? String, "wrapped-parent-key")
        XCTAssertEqual(payload["encrypted_content"] as? String, "encrypted-prompt")
        XCTAssertEqual(payload["encrypted_title"] as? String, "encrypted-title")
        let serialized = String(data: try JSONSerialization.data(withJSONObject: payload), encoding: .utf8)!
        XCTAssertFalse(serialized.contains("Private child title"))
        XCTAssertFalse(serialized.contains("Private child prompt"))

        let unencrypted = Message(id: "user-1", chatId: "child-1", role: .user,
                                  content: "Private child prompt", encryptedContent: nil,
                                  createdAt: "2026-01-01T00:00:00Z", updatedAt: nil,
                                  appId: nil, isStreaming: false, embedRefs: nil)
        XCTAssertThrowsError(try ChatSendPipeline().spawnedSubChatStoragePayload(
            chat: chat, firstMessage: unencrypted, encryptedSenderName: nil, timestamp: 1
        ))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testSubChatCompletionAndSequentialProgressDecode() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let completion = try decoder.decode(SubChatCompletion.self, from: Data(
            #"{"chat_id":"child-1","parent_id":"parent-1","summary":"Done"}"#.utf8
        ))
        XCTAssertEqual(completion.chatId, "child-1")
        XCTAssertEqual(completion.parentId, "parent-1")
        let progress = try decoder.decode(SubChatProgress.self, from: Data(
            #"{"chat_id":"parent-1","execution_mode":"sequential","status":"running","active_sub_chat_id":"child-1"}"#.utf8
        ))
        XCTAssertEqual(progress.executionMode, "sequential")
        XCTAssertEqual(progress.activeSubChatId, "child-1")
        let resolved = try decoder.decode(SubChatConfirmationResolved.self, from: Data(
            #"{"chat_id":"parent-1","task_id":"task-1","status":"approved"}"#.utf8
        ))
        XCTAssertEqual(resolved.chatId, "parent-1")
        XCTAssertEqual(resolved.taskId, "task-1")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    func testSpawnFenceRejectsAccountKeyAndSocketGenerationChanges() {
        let scope = UUID(), key = UUID()
        let fence = ChatSendPipeline.SubChatSpawnFence(
            accountScope: scope, keyGeneration: key, transportGeneration: 7
        )
        XCTAssertTrue(fence.matches(accountScope: scope, keyGeneration: key, transportGeneration: 7))
        XCTAssertFalse(fence.matches(accountScope: UUID(), keyGeneration: key, transportGeneration: 7))
        XCTAssertFalse(fence.matches(accountScope: scope, keyGeneration: UUID(), transportGeneration: 7))
        XCTAssertFalse(fence.matches(accountScope: scope, keyGeneration: key, transportGeneration: 8))
    }

    // contract-test: direct surface=gui.apple assertions=chats.persistence.client-encrypted
    func testSuspendedChildPreparationCannotSendAfterAccountSwitch() async {
        let originalScope = UUID()
        var currentScope = originalScope
        var resumePreparation: CheckedContinuation<String, Never>?
        var sendCount = 0
        let preparing = expectation(description: "child encryption preparation suspended")
        let operation = Task { @MainActor in
            try? await SubChatSpawnScopedStage.prepareAndSend(
                isCurrent: { currentScope == originalScope },
                prepare: {
                    await withCheckedContinuation { continuation in
                        resumePreparation = continuation
                        preparing.fulfill()
                    }
                },
                send: { _ in sendCount += 1; return "ack" }
            )
        }
        await fulfillment(of: [preparing], timeout: 2)
        currentScope = UUID()
        resumePreparation?.resume(returning: "encrypted-only")
        let result = await operation.value
        XCTAssertNil(result)
        XCTAssertEqual(sendCount, 0)
    }

    // contract-test: direct surface=gui.apple assertions=chats.persistence.client-encrypted
    func testSuspendedChildReceiptCannotCommitAfterAccountSwitch() async {
        let originalScope = UUID()
        var currentScope = originalScope
        var resumeReceipt: CheckedContinuation<String, Never>?
        var localInsertCount = 0
        let sending = expectation(description: "encrypted child send awaiting receipt")
        let operation = Task { @MainActor in
            try? await SubChatSpawnScopedStage.prepareAndSend(
                isCurrent: { currentScope == originalScope },
                prepare: { "encrypted-only" },
                send: { _ in
                    await withCheckedContinuation { continuation in
                        resumeReceipt = continuation
                        sending.fulfill()
                    }
                }
            )
        }
        await fulfillment(of: [sending], timeout: 2)
        currentScope = UUID()
        resumeReceipt?.resume(returning: "accepted")
        let result = await operation.value
        XCTAssertNil(result)
        XCTAssertThrowsError(try SubChatSpawnScopedStage.commitIfCurrent(
            isCurrent: { currentScope == originalScope },
            commit: { localInsertCount += 1 }
        ))
        XCTAssertEqual(localInsertCount, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
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

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testSubChatStopPayloadMatchesWebContract() {
        let payload = ChatSendPipeline().subChatStopPayload(
            chatId: "parent-chat-1",
            taskId: "task-1"
        )

        XCTAssertEqual(payload["chat_id"] as? String, "parent-chat-1")
        XCTAssertEqual(payload["task_id"] as? String, "task-1")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
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

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
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

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
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
