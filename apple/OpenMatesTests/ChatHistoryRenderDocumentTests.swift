// Contract tests for stable native chat-history render documents.
// Covers web-equivalent mixed markdown and embed ordering without UI rendering.
// Verifies encrypted message identity survives SwiftData cold-boot restoration.
// Uses synthetic content and placeholder identifiers only.
// Guards message-scoped parsing from moving back into SwiftUI body evaluation.

import CryptoKit
import SwiftData
import XCTest
@testable import OpenMates

@MainActor
final class ChatHistoryRenderDocumentTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testImportedProviderMetadataDecryptsIntoRenderIdentity() async throws {
        let chatId = "chat-imported-provider"
        let key = SymmetricKey(data: Data(repeating: 7, count: 32))
        ChatKeyManager.shared.setKey(key, for: chatId)
        defer { ChatKeyManager.shared.removeKey(for: chatId) }

        let crypto = CryptoManager.shared
        let message = Message(
            id: "message-imported-provider",
            chatId: chatId,
            role: .assistant,
            content: nil,
            encryptedContent: try await crypto.encryptContent("Synthetic imported reply", key: key),
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: nil,
            appId: nil,
            isStreaming: false,
            embedRefs: nil,
            encryptedSenderName: try await crypto.encryptContent("Gemini", key: key),
            encryptedCategory: try await crypto.encryptContent("gemini", key: key),
            encryptedModelName: try await crypto.encryptContent("gemini-import", key: key)
        )

        let decryptedMessages = await ChatViewModel.decryptMessagesForDisplay([message], chatId: chatId)
        let decrypted = try XCTUnwrap(decryptedMessages.first)

        XCTAssertEqual(decrypted.content, "Synthetic imported reply")
        XCTAssertEqual(decrypted.senderName, "Gemini")
        XCTAssertEqual(decrypted.category, "gemini")
        XCTAssertEqual(decrypted.modelName, "gemini-import")
        XCTAssertEqual(decrypted.renderDocumentForDisplay?.identity.senderName, "Gemini")
        XCTAssertEqual(decrypted.renderDocumentForDisplay?.identity.category, "gemini")
        XCTAssertEqual(decrypted.renderDocumentForDisplay?.identity.modelName, "gemini-import")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testImportedProviderMappingMatchesWebContract() {
        XCTAssertEqual(ImportedAssistantProvider.resolve(category: "openmates")?.iconName, "openmates")
        XCTAssertEqual(ImportedAssistantProvider.resolve(category: "chatgpt")?.iconName, "openai")
        XCTAssertEqual(ImportedAssistantProvider.resolve(category: "claude")?.iconName, "claude")
        XCTAssertEqual(ImportedAssistantProvider.resolve(category: "gemini")?.iconName, "google")
        XCTAssertEqual(ImportedAssistantProvider.resolve(category: "opencode")?.iconName, "coding")
        XCTAssertEqual(ImportedAssistantProvider.resolve(category: "other")?.displayName, "AI assistant")
        XCTAssertNil(ImportedAssistantProvider.resolve(category: "openmates", isOfficialOpenMatesChat: true))
        XCTAssertNil(ImportedAssistantProvider.resolve(category: "research"))
    }

    // contract-test: direct surface=gui.apple assertions=chats.surface.semantic-parity
    func testStableMessageBuildsOrderedWebSemanticBlocksOnce() throws {
        let content = """
        # Synthetic result

        Intro with [OpenMates](wiki:OpenMates) and @researcher.

        ```json
        {"type":"app_skill_use","embed_id":"embed-search","app_id":"web","skill_id":"search"}
        ```

        > [Verified synthetic quote](embed:source-result)

        - First item
        - Second item
        """
        let message = Message(
            id: "message-assistant",
            chatId: "chat-synthetic",
            role: .assistant,
            content: content,
            encryptedContent: "ciphertext-content",
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: nil,
            appId: "web",
            isStreaming: false,
            embedRefs: [EmbedRef(id: "embed-search", type: "app_skill_use", status: "finished", data: nil)],
            modelName: "Synthetic Model",
            senderName: "Synthetic Mate",
            category: "research",
            encryptedSenderName: "ciphertext-sender",
            encryptedCategory: "ciphertext-category",
            encryptedModelName: "ciphertext-model"
        )

        let document = try XCTUnwrap(message.renderDocumentForDisplay)

        XCTAssertEqual(document.messageId, message.id)
        XCTAssertEqual(document.identity.senderName, "Synthetic Mate")
        XCTAssertEqual(document.identity.category, "research")
        XCTAssertEqual(document.identity.modelName, "Synthetic Model")
        XCTAssertEqual(document.identity.role, .assistant)
        XCTAssertEqual(document.blocks.map(\.kind), [
            .heading,
            .paragraph,
            .embedGroup,
            .sourceQuote,
            .unorderedList,
        ])
        XCTAssertEqual(document.blocks[2].embedReferences.map(\.id), ["embed-search"])
        XCTAssertEqual(document.blocks[3].embedReferences.map(\.id), ["source-result"])
        XCTAssertEqual(document.blocks[1].inlineEntities.map(\.kind), [.wiki, .mention])
        XCTAssertEqual(message.renderDocumentForDisplay, document)
    }

    // contract-test: direct surface=gui.apple assertions=chats.surface.semantic-parity
    func testSystemMessageRetainsRoleWithoutAssistantOwnership() throws {
        let message = Message(
            id: "message-system",
            chatId: "chat-synthetic",
            role: .system,
            content: "System-only synthetic content.",
            encryptedContent: nil,
            createdAt: "2026-01-01T00:00:01Z",
            updatedAt: nil,
            appId: nil,
            isStreaming: false,
            embedRefs: nil
        )

        let document = try XCTUnwrap(message.renderDocumentForDisplay)
        XCTAssertEqual(document.identity.role, .system)
        XCTAssertNil(document.identity.senderName)
        XCTAssertEqual(document.blocks.map(\.kind), [.paragraph])
        XCTAssertTrue(document.blocks.allSatisfy { $0.messageId == message.id })
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testColdBootRestoresEncryptedIdentityAndExactRenderDocument() throws {
        let schema = Schema([PersistedChat.self, PersistedMessage.self])
        let configuration = ModelConfiguration(
            "ChatHistoryRenderDocumentTests",
            schema: schema,
            isStoredInMemoryOnly: true
        )
        let container = try ModelContainer(for: schema, configurations: [configuration])
        let store = OfflineStore(modelContainer: container)
        let message = Message(
            id: "message-restored",
            chatId: "chat-restored",
            role: .assistant,
            content: "Before.\n\n[[embed:embed-restored]]\n\nAfter.",
            encryptedContent: "ciphertext-content",
            createdAt: "2026-01-01T00:00:02Z",
            updatedAt: nil,
            appId: "web",
            isStreaming: false,
            embedRefs: [EmbedRef(id: "embed-restored", type: "web-website", status: "finished", data: nil)],
            modelName: "Synthetic Model",
            senderName: "Synthetic Mate",
            category: "research",
            encryptedSenderName: "ciphertext-sender",
            encryptedCategory: "ciphertext-category",
            encryptedModelName: "ciphertext-model"
        )
        let originalDocument = try XCTUnwrap(message.renderDocumentForDisplay)

        store.persistMessages([message], chatId: message.chatId)
        let restored = try XCTUnwrap(store.loadMessages(chatId: message.chatId).first)

        XCTAssertEqual(restored.id, message.id)
        XCTAssertEqual(restored.senderName, "Synthetic Mate")
        XCTAssertEqual(restored.category, "research")
        XCTAssertEqual(restored.modelName, "Synthetic Model")
        XCTAssertEqual(restored.encryptedSenderName, "ciphertext-sender")
        XCTAssertEqual(restored.encryptedCategory, "ciphertext-category")
        XCTAssertEqual(restored.encryptedModelName, "ciphertext-model")
        XCTAssertEqual(restored.renderDocumentForDisplay, originalDocument)
        XCTAssertEqual(restored.renderDocumentForDisplay?.blocks.map(\.kind), [
            .paragraph,
            .embedGroup,
            .paragraph,
        ])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testDecodedSyncMessageAcceptsEncryptedIdentityAliases() throws {
        let payload = """
        {
          "message_id": "message-decoded",
          "chat_id": "chat-decoded",
          "role": "assistant",
          "content": "Synthetic content",
          "created_at": "2026-01-01T00:00:03Z",
          "sender_name": "Synthetic Mate",
          "category": "research",
          "model_name": "Synthetic Model",
          "encrypted_sender_name": "ciphertext-sender",
          "encrypted_category": "ciphertext-category",
          "encrypted_model_name": "ciphertext-model"
        }
        """

        let message = try JSONDecoder().decode(Message.self, from: Data(payload.utf8))

        XCTAssertEqual(message.senderName, "Synthetic Mate")
        XCTAssertEqual(message.category, "research")
        XCTAssertEqual(message.modelName, "Synthetic Model")
        XCTAssertEqual(message.encryptedSenderName, "ciphertext-sender")
        XCTAssertEqual(message.encryptedCategory, "ciphertext-category")
        XCTAssertEqual(message.encryptedModelName, "ciphertext-model")
        XCTAssertEqual(message.renderDocumentForDisplay?.messageId, "message-decoded")
    }

    // contract-test: direct surface=gui.apple assertions=chats.surface.semantic-parity
    func testMessageAccessibilityPolicyPrefersSemanticTextOverChildren() {
        XCTAssertEqual(
            ChatMessageAccessibilityPolicy.semanticLabel(
                content: "  User-visible prompt  ",
                thinkingContent: nil,
                embedTypes: [],
                fallback: "message-user"
            ),
            "User-visible prompt"
        )
        XCTAssertEqual(
            ChatMessageAccessibilityPolicy.semanticLabel(
                content: "",
                thinkingContent: "  Thinking summary  ",
                embedTypes: [],
                fallback: "message-assistant"
            ),
            "Thinking summary"
        )
        XCTAssertEqual(
            ChatMessageAccessibilityPolicy.semanticLabel(
                content: "",
                thinkingContent: nil,
                embedTypes: [EmbedType.financeCheckAccounts.rawValue],
                fallback: "message-assistant"
            ),
            "Check accounts"
        )
    }

    // contract-test: direct surface=gui.apple assertions=chats.surface.semantic-parity
    func testStreamingRenderPolicyUsesTransientPlainTextOnlyForActiveStream() {
        XCTAssertTrue(ChatMessageStreamingRenderPolicy.usesTransientPlainText(streamingContent: "partial answer"))
        XCTAssertFalse(ChatMessageStreamingRenderPolicy.usesTransientPlainText(streamingContent: nil))
    }

    // contract-test: direct surface=gui.apple assertions=chats.surface.semantic-parity
    func testStreamingRenderPolicyHidesInternalProtocolFences() {
        let content = """
        ```json
        {"type":"app_skill_use","embed_id":"embed-search","app_id":"web","skill_id":"search"}
        ```

        Visible answer.
        """

        XCTAssertEqual(ChatMessageStreamingRenderPolicy.visibleContent(content), "\nVisible answer.")
        XCTAssertEqual(
            ChatMessageStreamingRenderPolicy.visibleContent("```json\n{\"type\":\"app_skill_use\""),
            ""
        )
        XCTAssertEqual(
            ChatMessageStreamingRenderPolicy.visibleContent("```json\n{\"answer\":true"),
            "```json\n{\"answer\":true"
        )
        XCTAssertEqual(
            ChatMessageStreamingRenderPolicy.visibleContent("```json\n{\"answer\":true}\n```"),
            "```json\n{\"answer\":true}\n```"
        )
    }
}
