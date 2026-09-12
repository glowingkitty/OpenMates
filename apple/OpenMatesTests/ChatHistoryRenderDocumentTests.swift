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
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,pii.surface.semantic-parity
    func testTranscriptDisplayProjectionRestoresSharedEmbedsOnceAndKeepsUserMappingPrecedence() {
        let placeholder = "[PERSON_NAME_1]"
        let old = PIIMapping(placeholder: placeholder, original: "Earlier synthetic name", type: "person_name")
        let latest = PIIMapping(placeholder: placeholder, original: "Updated synthetic name", type: "person_name")
        let ignored = PIIMapping(placeholder: placeholder, original: "Assistant mapping must not override", type: "person_name")
        let source = EmbedRecord(id: "shared-source", type: "website", status: .finished,
                                 data: .raw(["title": AnyCodable(placeholder)]),
                                 parentEmbedId: nil, appId: "web", skillId: nil,
                                 embedIds: nil, createdAt: nil)
        let rows = (0..<120).map { index in
            Message(id: "projection-row-\(index)", chatId: "projection-chat",
                    role: index < 2 ? .user : .assistant, content: placeholder,
                    encryptedContent: nil, createdAt: "2026-01-01T00:00:00Z", updatedAt: nil,
                    appId: nil, isStreaming: false,
                    embedRefs: [EmbedRef(id: source.id, type: source.type, status: nil, data: nil)],
                    piiMappings: [index == 0 ? old : (index == 1 ? latest : ignored)])
        }
        var restoredIds: [String] = []
        let projection = ChatTranscriptDisplayProjection(messages: rows, embedRecords: [source.id: source],
                                                        isPIIRevealed: true) { embed, mappings in
            restoredIds.append(embed.id)
            return PIIDetector.restorePII(in: embed, mappings: mappings)
        }
        XCTAssertEqual(projection.piiMappings, [latest])
        for row in rows {
            XCTAssertEqual(projection.embeds(for: row).first?.rawData?["title"]?.value as? String, latest.original)
        }
        XCTAssertEqual(restoredIds, [source.id], "120 row lookups must reuse the one restored shared embed")
        XCTAssertEqual(source.rawData?["title"]?.value as? String, placeholder,
                       "Revealing PII must not mutate the canonical stored record")

        let hidden = ChatTranscriptDisplayProjection(messages: rows, embedRecords: [source.id: source],
                                                    isPIIRevealed: false) { embed, _ in
            XCTFail("Hidden mode must never restore embed content")
            return embed
        }
        XCTAssertEqual(hidden.embeds(for: rows[0]).first?.rawData?["title"]?.value as? String, placeholder)
        XCTAssertEqual(hidden.piiMappings, [latest], "Message rendering still receives the same mapping collection")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chat-navigation.open.local-first-coherent
    func testInlineFlowReusesMeasurementsAndPreservesWrapping() {
        var cache = InlineMarkdownFlowMeasurements(idealSizes: [
            CGSize(width: 40, height: 20),
            CGSize(width: 50, height: 20),
            CGSize(width: 30, height: 24)
        ])
        var constrainedMeasurements = 0
        let measure: (Int, CGFloat) -> CGSize = { _, width in
            constrainedMeasurements += 1
            return CGSize(width: width, height: 20)
        }

        let measured = cache.arrangement(width: 100, spacing: 0, lineSpacing: 2, measureConstrained: measure)
        let placed = cache.arrangement(width: 100, spacing: 0, lineSpacing: 2, measureConstrained: measure)

        XCTAssertEqual(measured, placed)
        XCTAssertEqual(measured.origins, [CGPoint(x: 0, y: 0), CGPoint(x: 40, y: 0), CGPoint(x: 0, y: 22)])
        XCTAssertEqual(measured.size, CGSize(width: 90, height: 46))
        XCTAssertEqual(constrainedMeasurements, 0, "Ordinary text/chips should use their intrinsic size without a second measurement")

        let resized = cache.arrangement(width: 130, spacing: 0, lineSpacing: 2, measureConstrained: measure)
        XCTAssertEqual(resized.origins, [CGPoint(x: 0, y: 0), CGPoint(x: 40, y: 0), CGPoint(x: 90, y: 0)])
        XCTAssertEqual(resized.size, CGSize(width: 120, height: 24))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chat-navigation.open.local-first-coherent
    func testInlineFlowConstrainsOversizedChipOncePerLayoutProposal() {
        var cache = InlineMarkdownFlowMeasurements(idealSizes: [
            CGSize(width: 200, height: 20),
            CGSize(width: 20, height: 20)
        ])
        var constrainedMeasurements = 0
        let measure: (Int, CGFloat) -> CGSize = { index, width in
            XCTAssertEqual(index, 0)
            constrainedMeasurements += 1
            return CGSize(width: width, height: 40)
        }

        let measured = cache.arrangement(width: 100, spacing: 0, lineSpacing: 2, measureConstrained: measure)
        let placed = cache.arrangement(width: 100, spacing: 0, lineSpacing: 2, measureConstrained: measure)
        XCTAssertEqual(measured, placed)
        XCTAssertEqual(measured.sizes.first, CGSize(width: 100, height: 40))
        XCTAssertEqual(measured.origins.last, CGPoint(x: 0, y: 42))
        XCTAssertEqual(constrainedMeasurements, 1)

        let resized = cache.arrangement(width: 80, spacing: 0, lineSpacing: 2, measureConstrained: measure)
        XCTAssertEqual(resized.sizes.first, CGSize(width: 80, height: 40))
        XCTAssertEqual(constrainedMeasurements, 2)
        let spaced = cache.arrangement(width: 80, spacing: 0, lineSpacing: 4, measureConstrained: measure)
        XCTAssertEqual(spaced.origins.last, CGPoint(x: 0, y: 44))
        XCTAssertEqual(constrainedMeasurements, 3)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chat-navigation.open.local-first-coherent
    func testInlineFlowPreservesOriginalProposalWhenChipHugsWrappedText() {
        var cache = InlineMarkdownFlowMeasurements(idealSizes: [
            CGSize(width: 200, height: 20),
            CGSize(width: 20, height: 20)
        ])
        let measure: (Int, CGFloat) -> CGSize = { _, width in
            // Multiline Text may return its longest wrapped line's width,
            // which is narrower than the width offered by its parent.
            CGSize(width: width - 10, height: width >= 100 ? 40 : 60)
        }

        let measured = cache.arrangement(width: 100, spacing: 0, lineSpacing: 2, measureConstrained: measure)
        XCTAssertEqual(measured.size, CGSize(width: 90, height: 62))
        XCTAssertEqual(measured.proposedWidths, [100, nil])
        XCTAssertEqual(measured.origins.last, CGPoint(x: 0, y: 42))

        // Placement must retain the original container and child proposals.
        // Reusing the returned 90-point width would incorrectly add a line.
        let placed = cache.arrangement(width: 100, spacing: 0, lineSpacing: 2, measureConstrained: measure)
        XCTAssertEqual(placed, measured)
        let incorrectlyRewrapped = cache.arrangement(width: measured.size.width, spacing: 0, lineSpacing: 2, measureConstrained: measure)
        XCTAssertEqual(incorrectlyRewrapped.size.height, 82)
        XCTAssertNotEqual(incorrectlyRewrapped.size.height, placed.size.height)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chat-navigation.open.local-first-coherent
    func testInlineMarkdownMakesProgressPastLiteralAndMalformedDelimiters() {
        let cases = [
            ("[literal] then [source](embed:source)", "[literal] then source"),
            ("An unmatched ` marker and [source](embed:source)", "An unmatched ` marker and source"),
            ("![alt](https://example.com/image.png) and [source](embed:source)", "![alt](https://example.com/image.png) and source"),
            ("[ [ [", "[ [ ["),
            ("Unicode 🪐 [plain] and `unfinished", "Unicode 🪐 [plain] and `unfinished")
        ]
        for (source, expected) in cases {
            XCTAssertEqual(InlineMarkdownTokenizer.parse(source).map(\.searchText).joined(), expected)
        }
        XCTAssertTrue(InlineMarkdownTokenizer.parse(cases[0].0).contains(
            .embed(displayText: "source", embedRef: "source", isBold: false)))
    }

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

    // contract-test: direct surface=gui.apple assertions=chats.rendering.assistant-document-convergence,chats.rendering.inline-entity-interaction,chats.surface.semantic-parity
    func testStableMessageBuildsOrderedWebSemanticBlocksOnce() throws {
        let content = """
        # Synthetic result

        Intro with [OpenMates](wiki:OpenMates), [the source](embed:source-inline), and @researcher.

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
            embedRefs: [
                EmbedRef(id: "embed-search", type: "app_skill_use", status: "finished", data: nil),
                EmbedRef(id: "source-inline", type: "web-website", status: "finished", data: nil),
            ],
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
        XCTAssertEqual(document.blocks[1].inlineEntities.map(\.kind), [.wiki, .embed, .mention])
        XCTAssertEqual(message.renderDocumentForDisplay, document)
    }

    // contract-test: direct surface=gui.apple assertions=chats.rendering.inline-entity-interaction
    func testUnresolvedInlineEntitiesRetainReadableFallbackText() {
        let entities = ChatHistoryInlineEntity.parse(
            "Compare [Kyoto](wiki:Kyoto) with [the source](embed:missing-ref)."
        )

        XCTAssertEqual(entities.map(\.kind), [.wiki, .embed])
        XCTAssertEqual(entities.map(\.displayText), ["Kyoto", "the source"])
        XCTAssertEqual(entities.map(\.target), ["Kyoto", "missing-ref"])
    }

    // contract-test: direct surface=gui.apple assertions=chats.layout.responsive-history,message-input.layout.responsive-parity
    func testResponsiveChatLayoutMatchesWebBreakpoints() {
        XCTAssertEqual(ChatResponsiveLayoutPolicy.contentMaximumWidth, 1_000)
        XCTAssertTrue(ChatResponsiveLayoutPolicy.stacksAssistantIdentity(containerWidth: 500))
        XCTAssertFalse(ChatResponsiveLayoutPolicy.stacksAssistantIdentity(containerWidth: 501))
        XCTAssertEqual(ChatResponsiveLayoutPolicy.inlineCompactComposerHeight, 48)
    }

    // contract-test: direct surface=gui.apple assertions=chats.surface.semantic-parity
    func testResultsViewProtocolBuildsEmbedGroupWithoutExposingMetadata() throws {
        let message = Message(
            id: "message-results-view",
            chatId: "chat-synthetic",
            role: .assistant,
            content: """
            ```embeds_results_view
            title: Mapped results
            embeds: result-one, result-two
            sources: source-one, result-two
            highlight: source-one
            ```
            """,
            encryptedContent: nil,
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: nil,
            appId: "maps",
            isStreaming: false,
            embedRefs: [
                EmbedRef(id: "result-one", type: "maps-place", status: "finished", data: nil),
                EmbedRef(id: "result-two", type: "maps-place", status: "finished", data: nil),
                EmbedRef(id: "source-one", type: "web-website", status: "finished", data: nil),
            ]
        )

        let document = try XCTUnwrap(message.renderDocumentForDisplay)

        XCTAssertEqual(document.blocks.map(\.kind), [.embedGroup])
        XCTAssertEqual(
            document.blocks[0].embedReferences.map(\.id),
            ["result-one", "result-two", "source-one"]
        )
        XCTAssertFalse(document.blocks.contains { $0.kind == .codeBlock })
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testInlineEmbedGroupsBoundAccessibilityCardCount() {
        let embeds = (1...12).map { index in
            EmbedRecord(
                id: "result-\(index)",
                type: "maps-place",
                status: .finished,
                data: nil,
                parentEmbedId: nil,
                appId: "maps",
                skillId: "search",
                embedIds: nil,
                createdAt: nil
            )
        }

        let groups = EmbedGrouper.groupForInlineDisplay(embeds)

        XCTAssertEqual(groups.flatMap(\.embeds).map(\.id), Array(embeds.prefix(6)).map(\.id))
        XCTAssertEqual(embeds.count, 12)
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
    func testStreamingRenderPolicyPreservesVisibleMarkdownForRichRendering() {
        let content = "Comparing **[Kyoto](wiki:Kyoto)** and [Osaka](wiki:Osaka)."

        XCTAssertEqual(ChatMessageStreamingRenderPolicy.visibleContent(content), content)
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
            "```json\n{\"type\":\"app_skill_use\""
        )
        XCTAssertEqual(
            ChatMessageStreamingRenderPolicy.visibleContent("```json\n{\"type\":\"app_skill_use\",\"embed_id\":\"embed-search\""),
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
