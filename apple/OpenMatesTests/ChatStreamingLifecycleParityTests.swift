// Unit coverage for Apple chat streaming lifecycle parity with the web app.
// These tests are deterministic and avoid network calls, credentials, private
// chat content, and raw encryption keys. They verify that native streaming state
// no longer ignores preprocessing, thinking, queued, and cancellation events.
// Payload assertions cover only existing backend WebSocket contracts.

import XCTest
import SwiftData
@testable import OpenMates

@MainActor
final class ChatStreamingLifecycleParityTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.completion.pending-delivery,chats.message.identity-idempotent,chats.persistence.client-encrypted
    func testNotificationCatchUpReadsCachedPartialAndKeepsExactSavedCanonicalRow() async throws {
        var reads = 0
        let fixture = try terminalSyncFixture(decrypt: { rows, _ in
            rows.map { row in var row = row; row.content = "Synthetic completed response"; return row }
        }, window: { id, _, query in
            reads += 1
            XCTAssertEqual(query.direction, .latest)
            XCTAssertEqual(query.limit, 20)
            return try self.terminalPage(chatID: id, messageID: "task")
        })
        fixture.model.seedIsolatedHistory(chat: fixture.chat,
            messages: [terminalRow(id: "task", chatID: fixture.chat.id, cipher: nil, streaming: true)], embeds: [])
        fixture.model.handleStreamEvent(.taskInitiated(chatId: fixture.chat.id, taskId: "task", userMessageId: "user"))
        let finished = await fixture.model.refreshNotificationCompletion(chatID: fixture.chat.id, messageID: "task",
            intentID: UUID(), isCurrent: { true })
        XCTAssertTrue(finished)
        XCTAssertEqual(reads, 1, "Nonempty cached history must still get a bounded authoritative read")
        XCTAssertEqual(fixture.model.messages.map(\.id), ["task"])
        XCTAssertEqual(fixture.model.messages.first?.encryptedContent, "synthetic-saved-ciphertext")
        XCTAssertEqual(fixture.model.messages.first?.content, "Synthetic completed response")
        XCTAssertFalse(fixture.model.isStreaming)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.completion.pending-delivery,apple-offline.interruption-isolation
    func testNotificationCatchUpRejectsChangedIntentAndPreservesNewerTurnDuringRead() async throws {
        weak var model: ChatViewModel?
        var current = true
        let fixture = try terminalSyncFixture(decrypt: { rows, _ in
            rows.map { row in var row = row; row.content = "Synthetic completed response"; return row }
        }, window: { id, _, _ in
            model?.handleStreamEvent(.taskInitiated(chatId: id, taskId: "new-task", userMessageId: "new-user"))
            return try self.terminalPage(chatID: id, messageID: "old-task")
        })
        model = fixture.model
        fixture.model.seedIsolatedHistory(chat: fixture.chat,
            messages: [terminalRow(id: "old-task", chatID: fixture.chat.id, cipher: nil, streaming: true)], embeds: [])
        fixture.model.handleStreamEvent(.taskInitiated(chatId: fixture.chat.id, taskId: "old-task", userMessageId: "old-user"))
        let finished = await fixture.model.refreshNotificationCompletion(chatID: fixture.chat.id, messageID: "old-task",
            intentID: UUID(), isCurrent: { current })
        XCTAssertTrue(finished)
        XCTAssertTrue(fixture.model.isStreaming)
        XCTAssertEqual(fixture.model.streamingLifecycle.taskId, "new-task")
        current = false
        let rejected = await fixture.model.refreshNotificationCompletion(chatID: fixture.chat.id, messageID: "old-task",
            intentID: UUID(), isCurrent: { current })
        XCTAssertFalse(rejected)
        XCTAssertEqual(fixture.model.streamingLifecycle.taskId, "new-task")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.completion.pending-delivery,apple-offline.interruption-isolation
    func testNotificationReadRejectsAccountScopeReplacementDuringRequest() async throws {
        var scope = UUID()
        let fixture = try terminalSyncFixture(decrypt: { rows, _ in
            rows.map { row in var row = row; row.content = "Synthetic completed response"; return row }
        }, scopeProvider: { scope }, window: { id, _, _ in
            scope = UUID()
            return try self.terminalPage(chatID: id, messageID: "task")
        })
        let partial = terminalRow(id: "task", chatID: fixture.chat.id, cipher: nil, streaming: true)
        fixture.model.seedIsolatedHistory(chat: fixture.chat, messages: [partial], embeds: [])
        fixture.model.handleStreamEvent(.taskInitiated(chatId: fixture.chat.id, taskId: "task", userMessageId: "user"))
        let finished = await fixture.model.refreshNotificationCompletion(chatID: fixture.chat.id, messageID: "task",
            intentID: UUID(), isCurrent: { true })
        XCTAssertFalse(finished)
        XCTAssertTrue(fixture.model.isStreaming)
        XCTAssertNil(fixture.model.messages.first?.encryptedContent)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.message.identity-idempotent,chats.persistence.client-encrypted
    func testCanonicalSavedAliasCollapsesOnReopenWithoutCollapsingRepeatedText() {
        let alias = terminalRow(id: "database", chatID: "chat", cipher: nil, streaming: true)
        let canonical = terminalRow(id: "canonical", chatID: "chat", alias: alias.id)
        let repeatedTurn = terminalRow(id: "separate-turn", chatID: "chat")
        let rows = ChatHistoryWindowPolicy.orderedUnique([alias, canonical, repeatedTurn])
        XCTAssertEqual(Set(rows.map(\.id)), [canonical.id, repeatedTurn.id])
        XCTAssertEqual(rows.first { $0.id == canonical.id }?.serverMessageId, alias.id)
        XCTAssertEqual(rows.first { $0.id == canonical.id }?.encryptedContent, canonical.encryptedContent)
        XCTAssertEqual(rows.count, 2, "Identical prose in distinct turns remains distinct")
    }

    private func terminalPage(chatID: String, messageID: String) throws -> ChatMessageWindowPage {
        var row = terminalRow(id: messageID, chatID: chatID)
        row.content = nil
        let cursor = try ChatMessageWindowPage.cursor(for: row)
        return ChatMessageWindowPage(chatId: chatID, messages: [row], hasMoreBefore: false, hasMoreAfter: false,
            startCursor: cursor, endCursor: cursor, anchorFound: true, serverMessageCount: 1, messagesV: 2,
            compressionBoundaryTimestamp: nil, compressionCheckpoints: [], respectCompressionBoundary: false,
            oversizedMessage: nil, oversizedMessageCursor: nil, payloadBytes: nil)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.completion.pending-delivery,chats.message.identity-idempotent
    func testSavedTerminalMatchesTaskBeforeTypingAndPrefersKnownAssistantIdentity() throws {
        var state = ChatStreamingLifecycleState()
        state.apply(.taskInitiated(chatId: "chat", taskId: "task", userMessageId: "user"))
        state.apply(.preprocessingStep(chatId: "chat", step: "model_selected", data: nil))
        let saved = terminalRow(id: "task", chatID: "chat")
        XCTAssertEqual(ChatStreamingSyncCompletionPolicy.matchingMessage(in: [saved], lifecycle: state,
            chatID: "chat", pendingMessageIDs: [])?.id, saved.id)
        XCTAssertTrue(state.completeFromAuthoritativeSync(messageId: saved.id))
        XCTAssertFalse(state.isActive)

        state.apply(.taskInitiated(chatId: "chat", taskId: "task", userMessageId: "user"))
        state.apply(.typingStarted(chatId: "chat", messageId: "assistant-new", metadata: nil))
        XCTAssertNil(ChatStreamingSyncCompletionPolicy.matchingMessage(in: [saved], lifecycle: state,
            chatID: "chat", pendingMessageIDs: []), "An older task row cannot finish a newer known assistant")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.completion.pending-delivery,chats.message.identity-idempotent,chats.persistence.client-encrypted
    func testTerminalSyncRejectsUnrelatedOptimisticStreamingAndPendingRows() {
        var state = ChatStreamingLifecycleState()
        state.apply(.taskInitiated(chatId: "chat", taskId: "task", userMessageId: "user"))
        let invalid = [terminalRow(id: "other", chatID: "chat"),
                       terminalRow(id: "task", chatID: "other-chat"),
                       terminalRow(id: "task", chatID: "chat", role: .user),
                       terminalRow(id: "task", chatID: "chat", cipher: nil),
                       terminalRow(id: "task", chatID: "chat", cipher: ""),
                       terminalRow(id: "task", chatID: "chat", streaming: true)]
        for row in invalid {
            XCTAssertNil(ChatStreamingSyncCompletionPolicy.matchingMessage(in: [row], lifecycle: state,
                chatID: "chat", pendingMessageIDs: []))
        }
        let alias = terminalRow(id: "canonical", chatID: "chat", alias: "task")
        XCTAssertEqual(ChatStreamingSyncCompletionPolicy.matchingMessage(in: [alias], lifecycle: state,
            chatID: "chat", pendingMessageIDs: [])?.id, alias.id)
        for pendingID in ["canonical", "task"] {
            XCTAssertNil(ChatStreamingSyncCompletionPolicy.matchingMessage(in: [alias], lifecycle: state,
                chatID: "chat", pendingMessageIDs: [pendingID]))
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.completion.pending-delivery,chats.surface.semantic-parity
    func testForegroundSyncClearsProcessingBeforeFirstTypingFrame() async throws {
        let fixture = try terminalSyncFixture()
        fixture.model.handleStreamEvent(.taskInitiated(chatId: fixture.chat.id, taskId: "task", userMessageId: "user"))
        fixture.model.handleStreamEvent(.preprocessingStep(chatId: fixture.chat.id, step: "model_selected", data: nil))
        XCTAssertTrue(fixture.model.isStreaming)
        XCTAssertNil(fixture.model.streamingMessageId)
        let saved = terminalRow(id: "task", chatID: fixture.chat.id)
        await fixture.model.applySynced(chat: fixture.chat, messages: [saved])
        XCTAssertEqual(fixture.model.streamingLifecycle.phase, .completed)
        XCTAssertFalse(fixture.model.isStreaming)
        XCTAssertNil(fixture.model.streamingMessageId)
        XCTAssertEqual(fixture.model.messages.first?.encryptedContent, saved.encryptedContent)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.completion.pending-delivery,chats.local-state.precedence,chats.persistence.client-encrypted
    func testBufferedProcessingAndPartialReplayCannotReopenSavedCompletion() throws {
        let fixture = try terminalSyncFixture()
        let saved = terminalRow(id: "task", chatID: fixture.chat.id)
        fixture.model.seedIsolatedHistory(chat: fixture.chat, messages: [saved], embeds: [])
        fixture.model.handleStreamEvent(.taskInitiated(chatId: fixture.chat.id, taskId: "task", userMessageId: "user"))
        fixture.model.handleStreamEvent(.preprocessingStep(chatId: fixture.chat.id, step: "model_selected", data: nil))
        fixture.model.handleStreamEvent(.typingStarted(chatId: fixture.chat.id, messageId: "task", metadata: nil))
        fixture.model.handleStreamEvent(.chunk(chatId: fixture.chat.id, messageId: "task", sequence: 1,
            content: "Stale partial", isFinal: false, userMessageId: "user", category: nil, modelName: nil, rejectionReason: nil))
        XCTAssertFalse(fixture.model.isStreaming)
        XCTAssertEqual(fixture.model.streamingLifecycle.phase, .completed)
        XCTAssertEqual(fixture.model.messages.first?.content, saved.content)
        XCTAssertEqual(fixture.model.messages.first?.encryptedContent, saved.encryptedContent)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.completion.pending-delivery,chats.message.identity-idempotent
    func testForegroundCompletionDuringDecryptionPreservesNewerProcessingTask() async throws {
        weak var model: ChatViewModel?
        let fixture = try terminalSyncFixture(decrypt: { rows, chatID in
            model?.handleStreamEvent(.taskInitiated(chatId: chatID, taskId: "new-task", userMessageId: "new-user"))
            model?.handleStreamEvent(.preprocessingStep(chatId: chatID, step: "model_selected", data: nil))
            return rows
        })
        model = fixture.model
        fixture.model.handleStreamEvent(.taskInitiated(chatId: fixture.chat.id, taskId: "old-task", userMessageId: "old-user"))
        await fixture.model.applySynced(chat: fixture.chat, messages: [terminalRow(id: "old-task", chatID: fixture.chat.id)])
        XCTAssertTrue(fixture.model.isStreaming)
        XCTAssertEqual(fixture.model.streamingLifecycle.taskId, "new-task")
        XCTAssertEqual(fixture.model.streamingLifecycle.phase, .processing)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.completion.pending-delivery,chats.local-state.precedence
    func testPendingRecoveryRowCannotClearForegroundProcessing() async throws {
        let fixture = try terminalSyncFixture()
        let store = ChatStore()
        store.setPendingAssistantRecoveryLookup { _ in ["task"] }
        fixture.model.configure(wsManager: nil, chatStore: store)
        fixture.model.handleStreamEvent(.taskInitiated(chatId: fixture.chat.id, taskId: "task", userMessageId: "user"))
        await fixture.model.applySynced(chat: fixture.chat, messages: [terminalRow(id: "task", chatID: fixture.chat.id)])
        XCTAssertTrue(fixture.model.isStreaming)
        XCTAssertEqual(fixture.model.streamingLifecycle.phase, .sending)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.completion.pending-delivery,chats.surface.semantic-parity
    func testPostprocessingCompletionClearsProcessingAndMessageReadyMatchesTaskBeforeTyping() throws {
        let fixture = try terminalSyncFixture()
        fixture.model.handleStreamEvent(.taskInitiated(chatId: fixture.chat.id, taskId: "task", userMessageId: "user"))
        fixture.model.handleStreamEvent(.postProcessingCompleted(chatId: fixture.chat.id, taskId: "task",
            followUpSuggestions: [], newChatSuggestions: [], chatSummary: nil, chatTags: [], updatedTitle: nil,
            sourceTitleVersion: nil, sourceMetadataVersion: nil))
        XCTAssertFalse(fixture.model.isStreaming)
        XCTAssertFalse(fixture.model.streamingLifecycle.isActive)
        var state = ChatStreamingLifecycleState()
        state.apply(.taskInitiated(chatId: "chat", taskId: "task", userMessageId: "user"))
        XCTAssertFalse(state.apply(.messageReady(chatId: "chat", messageId: "older-task")))
        XCTAssertTrue(state.apply(.messageReady(chatId: "chat", messageId: "task")))
        XCTAssertFalse(state.isActive)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.completion.pending-delivery,chats.message.identity-idempotent
    func testForegroundMergeAdmitsExactTerminalAndRetainsOtherStreamingRows() {
        var state = ChatStreamingLifecycleState()
        state.apply(.taskInitiated(chatId: "chat", taskId: "task", userMessageId: "user"))
        let partial = terminalRow(id: "task", chatID: "chat", cipher: nil, streaming: true)
        let newer = terminalRow(id: "newer", chatID: "chat", cipher: nil, streaming: true)
        let saved = terminalRow(id: "canonical", chatID: "chat", alias: "task")
        let retained = ChatStreamingSyncCompletionPolicy.retainedForegroundMessages([partial, newer],
            incoming: [saved], lifecycle: state, chatID: "chat", pendingMessageIDs: [])
        let merged = ChatMessageWindowPage.merge([saved], preserving: retained)
        XCTAssertEqual(Set(merged.map(\.id)), [saved.id, newer.id])
        XCTAssertEqual(merged.first(where: { $0.id == saved.id })?.encryptedContent, saved.encryptedContent)
        XCTAssertTrue(merged.first(where: { $0.id == newer.id })?.isStreaming == true)
        XCTAssertEqual(ChatStreamingSyncCompletionPolicy.retainedForegroundMessages([partial, newer],
            incoming: [saved], lifecycle: state, chatID: "chat", pendingMessageIDs: ["task"]).count, 2)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.completion.pending-delivery,apple-offline.interruption-isolation
    func testSavedHistoryCannotCompleteProcessingAfterScopeChanges() throws {
        var scope = UUID()
        let fixture = try terminalSyncFixture(scopeProvider: { scope })
        fixture.model.seedIsolatedHistory(chat: fixture.chat,
            messages: [terminalRow(id: "task", chatID: fixture.chat.id)], embeds: [])
        scope = UUID()
        fixture.model.handleStreamEvent(.taskInitiated(chatId: fixture.chat.id, taskId: "task", userMessageId: "user"))
        XCTAssertTrue(fixture.model.isStreaming)
        XCTAssertEqual(fixture.model.streamingLifecycle.phase, .sending)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.completion.pending-delivery,apple-offline.interruption-isolation
    func testForegroundCompletionRejectsScopeChangedDuringDecryption() async throws {
        var scope = UUID()
        let fixture = try terminalSyncFixture(decrypt: { rows, _ in scope = UUID(); return rows }, scopeProvider: { scope })
        fixture.model.handleStreamEvent(.taskInitiated(chatId: fixture.chat.id, taskId: "task", userMessageId: "user"))
        await fixture.model.applySynced(chat: fixture.chat, messages: [terminalRow(id: "task", chatID: fixture.chat.id)])
        XCTAssertTrue(fixture.model.isStreaming)
        XCTAssertEqual(fixture.model.streamingLifecycle.phase, .sending)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.completion.pending-delivery,chats.message.identity-idempotent
    func testForegroundCompletionRejectsMessageDeletedDuringDecryption() async throws {
        weak var model: ChatViewModel?
        let fixture = try terminalSyncFixture(decrypt: { rows, chatID in
            model?.consumeForegroundMessageDeletion(chatId: chatID, messageId: "task")
            return rows
        })
        model = fixture.model
        fixture.model.handleStreamEvent(.taskInitiated(chatId: fixture.chat.id, taskId: "task", userMessageId: "user"))
        await fixture.model.applySynced(chat: fixture.chat, messages: [terminalRow(id: "task", chatID: fixture.chat.id)])
        XCTAssertTrue(fixture.model.isStreaming)
        XCTAssertEqual(fixture.model.streamingLifecycle.phase, .sending)
        XCTAssertFalse(fixture.model.messages.contains { $0.id == "task" })
    }

    // contract-test: supporting surface=gui.apple assertions=chats.completion.pending-delivery,apple-live-activities.processing.widget,apple-live-activities.lifecycle.isolation
    func testForegroundCompletionFinishesOnlyMatchingWidgetTurn() async throws {
        let fixture = try terminalSyncFixture()
        let scope = try XCTUnwrap(fixture.coordinator.currentScope)
        fixture.coordinator.started(chatID: fixture.chat.id, turnID: "user", scope: scope)
        fixture.coordinator.adoptServerTurn(chatID: fixture.chat.id, provisionalTurnID: "user", serverTurnID: "task", scope: scope)
        fixture.model.handleStreamEvent(.taskInitiated(chatId: fixture.chat.id, taskId: "task", userMessageId: "user"))
        await fixture.model.applySynced(chat: fixture.chat, messages: [terminalRow(id: "task", chatID: fixture.chat.id)])
        XCTAssertNil(fixture.coordinator.policy.items[fixture.chat.id])
        XCTAssertTrue(fixture.coordinator.policy.hasCompleted(chatID: fixture.chat.id, turnID: "user"))
        XCTAssertTrue(fixture.coordinator.policy.hasCompleted(chatID: fixture.chat.id, turnID: "task"))

        fixture.coordinator.started(chatID: fixture.chat.id, turnID: "new-user", scope: scope)
        fixture.model.handleStreamEvent(.taskInitiated(chatId: fixture.chat.id, taskId: "task", userMessageId: "user"))
        XCTAssertFalse(fixture.model.isStreaming, "Old buffered processing still stays completed")
        XCTAssertEqual(fixture.coordinator.policy.items[fixture.chat.id]?.turnID, "new-user",
                       "Finishing an exact older alias must retain the widget's newer turn")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testChildCompletionRoutesByParentAndPreservesChildIdentity() async throws {
        let fixture = try terminalSyncFixture()
        let store = ChatStore()
        let child = Chat(id: "synthetic-child", title: "Synthetic child", lastMessageAt: nil,
            createdAt: "2026-01-01T00:00:00Z", updatedAt: nil, isArchived: false, isPinned: false,
            appId: nil, encryptedTitle: nil, encryptedChatKey: nil, parentId: fixture.chat.id, isSubChat: true)
        store.upsertChat(child)
        fixture.model.configure(wsManager: nil, chatStore: store)
        func frame(parent: String) throws -> Data {
            try JSONSerialization.data(withJSONObject: ["payload": ["chat_id": child.id, "parent_id": parent, "summary": ""]])
        }
        let unrelatedFrame = try frame(parent: "unrelated-parent")
        await fixture.model.handleChatLifecycleEvent(type: "sub_chat_completed", raw: unrelatedFrame, activeChatId: fixture.chat.id)
        XCTAssertFalse(fixture.model.completedSubChatIDs.contains(child.id))
        let matchingFrame = try frame(parent: fixture.chat.id)
        await fixture.model.handleChatLifecycleEvent(type: "sub_chat_completed", raw: matchingFrame, activeChatId: fixture.chat.id)
        XCTAssertTrue(fixture.model.completedSubChatIDs.contains(child.id))
        XCTAssertFalse(fixture.model.completedSubChatIDs.contains(fixture.chat.id))
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.send.ownership
    func testSendWithoutCurrentChatReportsRejection() async {
        let model = ChatViewModel()
        let accepted = await model.sendMessage("Synthetic draft")
        XCTAssertFalse(accepted)
        XCTAssertNil(model.error, "A guard rejection does not imply acceptance merely because there is no error")
    }

    private func terminalRow(id: String, chatID: String, role: MessageRole = .assistant,
                             cipher: String? = "synthetic-saved-ciphertext", streaming: Bool = false,
                             alias: String? = nil) -> Message {
        Message(id: id, chatId: chatID, role: role, content: "Synthetic completed response",
            encryptedContent: cipher, createdAt: "2026-01-01T00:00:00Z", updatedAt: nil,
            appId: nil, isStreaming: streaming, embedRefs: nil, serverMessageId: alias)
    }

    private func terminalSyncFixture(decrypt: @escaping @MainActor ([Message], String) async -> [Message] = { rows, _ in rows },
                                     scopeProvider: (@MainActor () -> UUID)? = nil,
                                     window: @escaping @MainActor (String, String?, ChatMessageWindowQuery) async throws -> ChatMessageWindowPage = { _, _, _ in throw CancellationError() })
        throws -> (model: ChatViewModel, chat: Chat, coordinator: ActiveChatsCoordinator) {
        let schema = Schema([PersistedChat.self, PersistedMessage.self, PersistedEmbed.self,
            PersistedEmbedKey.self, PersistedCodeRunOutput.self, PendingOfflineAction.self])
        let configuration = ModelConfiguration("TerminalSync-\(UUID().uuidString)", schema: schema, isStoredInMemoryOnly: true)
        let container = try ModelContainer(for: schema, configurations: [configuration])
        let offline = OfflineStore(modelContainer: container)
        let chat = Chat(id: "synthetic-terminal-\(UUID().uuidString)", title: "Synthetic chat", lastMessageAt: nil,
            createdAt: "2026-01-01T00:00:00Z", updatedAt: nil, isArchived: false, isPinned: false,
            appId: nil, encryptedTitle: nil, encryptedChatKey: nil, messagesV: 1, titleV: 0)
        let coordinator = ActiveChatsCoordinator(publishWidgetSnapshot: { _, _, _ in })
        let team = TeamWorkspaceContext.shared.snapshot
        coordinator.configure(accountID: "synthetic-owner", server: ServerProfile.current(),
            scope: scopeProvider?() ?? offline.scopeGeneration,
            team: .init(epoch: team.epoch, teamID: team.teamID), authenticated: true)
        let model = ChatViewModel(messageDecryptor: decrypt, accountScopeGeneration: { scopeProvider?() ?? offline.scopeGeneration },
            offlineStore: offline, processingCoordinator: coordinator, messageWindowFetcher: window)
        model.chat = chat
        return (model, chat, coordinator)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.streaming.progressive-presentation,chats.surface.semantic-parity
    func testTypingStatusUsesTheCurrentTurnMateAndClearsItForTheNextTurn() throws {
        var state = ChatStreamingLifecycleState()
        state.apply(.taskInitiated(chatId: "chat", taskId: "task-1", userMessageId: "user-1"))
        XCTAssertEqual(ChatTypingPresentation.stageText(for: state), AppStrings.sendingMessage)

        state.apply(.preprocessingStep(chatId: "chat", step: "mate_selected",
                                       data: ["mate_name": "Developer", "mate_category": "software_development"]))
        XCTAssertEqual(ChatTypingPresentation.stageText(for: state), AppStrings.selectingModel)
        state.apply(.preprocessingStep(chatId: "chat", step: "model_selected", data: nil))
        XCTAssertEqual(ChatTypingPresentation.stageText(for: state), AppStrings.mateIsTyping("Developer"))

        state.apply(.typingStarted(
            chatId: "chat", messageId: "assistant-1",
            metadata: .init(title: nil, iconNames: [], category: "software_development",
                            modelName: nil, providerName: nil, serverRegion: nil,
                            userMessageId: "user-1", encryptedChatKey: nil)
        ))
        let developerMate = try XCTUnwrap(CanonicalSettingsMateCatalog.mate(id: "software_development"))
        XCTAssertEqual(ChatTypingPresentation.stageText(for: state), AppStrings.mateIsTyping(developerMate.name))

        state.apply(.thinkingChunk(chatId: "chat", messageId: "assistant-1", content: "reasoning"))
        XCTAssertEqual(ChatTypingPresentation.stageText(for: state), AppStrings.mateIsThinking(developerMate.name))

        state.apply(.taskInitiated(chatId: "chat", taskId: "task-2", userMessageId: "user-2"))
        state.apply(.typingStarted(chatId: "chat", messageId: "assistant-2", metadata: nil))
        XCTAssertNil(state.selectedMateCategory)
        XCTAssertEqual(ChatTypingPresentation.stageText(for: state), AppStrings.selectingMateAndModel)

        state.apply(.chunk(chatId: "chat", messageId: "assistant-2", sequence: 1,
                           content: "Hello", isFinal: false, userMessageId: "user-2",
                           category: "general_knowledge", modelName: nil, rejectionReason: nil))
        let generalMate = try XCTUnwrap(CanonicalSettingsMateCatalog.mate(id: "general_knowledge"))
        XCTAssertEqual(ChatTypingPresentation.stageText(for: state), AppStrings.mateIsTyping(generalMate.name))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testFirstMessageTitleBridgesHeaderUntilGeneratedMetadataArrives() {
        let provisional = ChatHeaderPresentation.provisionalTitle(
            from: "  Compare   OpenAI and Anthropic model releases this week  "
        )
        XCTAssertEqual(provisional, "Compare OpenAI and Anthropic model releases this week")
        XCTAssertEqual(
            ChatHeaderPresentation.title(override: nil, generated: nil, provisional: provisional),
            provisional
        )
        XCTAssertEqual(
            ChatHeaderPresentation.title(
                override: nil,
                generated: "Recent model release comparison",
                provisional: provisional
            ),
            "Recent model release comparison"
        )
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testBannerKeepsTitleVisibleWhileCategoryMetadataIsPending() {
        XCTAssertEqual(
            ChatBannerPresentation.generatedOrProvisionalState(
                title: "Generated title",
                provisionalTitle: "First user message",
                category: nil,
                summary: nil,
                shouldShowLoading: false
            ),
            .loaded(title: "Generated title", appId: "general_knowledge", summary: nil)
        )
        XCTAssertEqual(
            ChatBannerPresentation.generatedOrProvisionalState(
                title: nil,
                provisionalTitle: "First user message",
                category: nil,
                summary: nil,
                shouldShowLoading: true
            ),
            .loaded(title: "First user message", appId: "general_knowledge", summary: nil)
        )
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testContinuationCardsUseActualAvailableGapRatherThanViewportHeight() {
        XCTAssertTrue(
            WelcomeContinuationCarousel.usesLargeCards(for: CGSize(width: 390, height: 454)),
            "A tall iPhone should use the same full continuation card as a tall iPad"
        )
        XCTAssertTrue(WelcomeContinuationCarousel.usesLargeCards(for: CGSize(width: 1024, height: 420)))
        XCTAssertTrue(WelcomeContinuationCarousel.usesLargeCards(for: CGSize(width: 390, height: 404)))
        XCTAssertTrue(WelcomeContinuationCarousel.usesLargeCards(for: CGSize(width: 390, height: 360)))
        XCTAssertFalse(WelcomeContinuationCarousel.usesLargeCards(for: CGSize(width: 390, height: 359)))
    }

    // contract-test: direct surface=gui.apple assertions=chats.surface.semantic-parity
    func testGeneratedMetadataImmediatelyPopulatesActiveChatPresentation() {
        let chat = Chat(
            id: "chat-1", title: nil, lastMessageAt: nil,
            createdAt: "2026-09-24T10:00:00Z", updatedAt: nil,
            isArchived: false, isPinned: false, appId: "ai",
            encryptedTitle: nil, encryptedChatKey: nil,
            messagesV: 1, titleV: 0
        )
        let metadata = StreamingClient.ChatMetadata(
            title: "A generated title", iconNames: ["code"], category: "code",
            modelName: "A model", providerName: nil, serverRegion: nil,
            userMessageId: "user-1", encryptedChatKey: "wrapped-key"
        )

        let updated = ChatGeneratedMetadataPolicy.applying(metadata, to: chat)

        XCTAssertEqual(updated.title, "A generated title")
        XCTAssertEqual(updated.category, "code")
        XCTAssertEqual(updated.icon, "code")
        XCTAssertEqual(updated.encryptedChatKey, "wrapped-key")
        XCTAssertEqual(updated.messagesV, 1)
        XCTAssertEqual(updated.titleV, 0, "Presentation metadata must not invent a server version")
    }

    // contract-test: direct surface=gui.apple assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testGeneratedMetadataRemainsTransientUntilEncryptedStorageIsAccepted() {
        let stored = Chat(
            id: "chat-1", title: nil, lastMessageAt: nil,
            createdAt: "2026-09-24T10:00:00Z", updatedAt: nil,
            isArchived: false, isPinned: false, appId: "ai",
            encryptedTitle: nil, encryptedChatKey: nil,
            messagesV: 1, titleV: 0
        )
        let store = ChatStore()
        store.upsertChat(stored)
        let viewModel = ChatViewModel()
        viewModel.configure(wsManager: nil, chatStore: store)
        viewModel.chat = stored

        viewModel.handleStreamEvent(.typingStarted(
            chatId: "chat-1",
            messageId: "assistant-1",
            metadata: StreamingClient.ChatMetadata(
                title: "Transient title", iconNames: ["code"], category: "code",
                modelName: "A model", providerName: nil, serverRegion: nil,
                userMessageId: "user-1", encryptedChatKey: "wrapped-key"
            )
        ))

        XCTAssertEqual(viewModel.chat?.title, "Transient title")
        XCTAssertNil(store.chat(for: "chat-1")?.title)
        XCTAssertNil(store.chat(for: "chat-1")?.category)
        XCTAssertNil(store.chat(for: "chat-1")?.icon)
    }

    // contract-test: direct surface=gui.apple assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testRejectedEncryptedMetadataAcknowledgementCannotAdvancePersistenceVersions() {
        XCTAssertNil(ChatEncryptedMetadataAcknowledgementPolicy.acceptedVersions(from: [
            "status": "rejected",
            "versions": ["messages_v": 2, "title_v": 1, "metadata_v": 1]
        ]))
        XCTAssertNil(ChatEncryptedMetadataAcknowledgementPolicy.acceptedVersions(from: [
            "code": "incomplete_chat_metadata",
            "versions": ["messages_v": 2, "title_v": 1, "metadata_v": 1]
        ]))

        XCTAssertEqual(
            ChatEncryptedMetadataAcknowledgementPolicy.acceptedVersions(from: [
                "status": "queued_for_storage",
                "versions": ["messages_v": 2, "title_v": 1, "metadata_v": 3]
            ]),
            ChatEncryptedMetadataAcceptedVersions(messages: 2, title: 1, metadata: 3)
        )
    }

    // contract-test: direct surface=gui.apple assertions=chats.surface.semantic-parity
    func testGeneratedMetadataDoesNotReplaceInitializedHeaderIdentity() {
        let chat = Chat(
            id: "chat-1", title: "Existing title", lastMessageAt: nil,
            createdAt: "2026-09-24T10:00:00Z", updatedAt: nil,
            isArchived: false, isPinned: false, appId: "ai",
            category: "web", icon: "search", encryptedTitle: "ciphertext",
            encryptedChatKey: nil,
            messagesV: 4, titleV: 1
        )
        let metadata = StreamingClient.ChatMetadata(
            title: "Unexpected replacement", iconNames: ["code"], category: "code",
            modelName: "A model", providerName: nil, serverRegion: nil,
            userMessageId: "user-4", encryptedChatKey: nil
        )

        let updated = ChatGeneratedMetadataPolicy.applying(metadata, to: chat)

        XCTAssertEqual(updated.title, "Existing title")
        XCTAssertEqual(updated.category, "web")
        XCTAssertEqual(updated.icon, "search")
    }

    // contract-test: direct surface=gui.apple assertions=chats.surface.semantic-parity
    func testGeneratedMetadataReplacesUnversionedProvisionalTitle() {
        let chat = Chat(
            id: "chat-1", title: "First user message", lastMessageAt: nil,
            createdAt: "2026-09-24T10:00:00Z", updatedAt: nil,
            isArchived: false, isPinned: false, appId: "ai",
            encryptedTitle: nil, encryptedChatKey: nil,
            messagesV: 1, titleV: 0
        )
        let metadata = StreamingClient.ChatMetadata(
            title: "Generated topic", iconNames: ["code"], category: "code",
            modelName: nil, providerName: nil, serverRegion: nil,
            userMessageId: "user-1", encryptedChatKey: nil
        )

        let updated = ChatGeneratedMetadataPolicy.applying(metadata, to: chat)

        XCTAssertEqual(updated.title, "Generated topic")
        XCTAssertEqual(updated.category, "code")
        XCTAssertEqual(updated.icon, "code")
    }

    // contract-test: direct surface=gui.apple assertions=chats.surface.semantic-parity,chats.persistence.client-encrypted
    func testGeneratedMetadataReplacesEncryptedEmptyTitlePlaceholder() {
        let chat = Chat(
            id: "chat-1", title: "", lastMessageAt: nil,
            createdAt: "2026-09-24T10:00:00Z", updatedAt: nil,
            isArchived: false, isPinned: false, appId: "ai",
            encryptedTitle: "encrypted-empty-placeholder", encryptedChatKey: nil,
            messagesV: 1, titleV: 1
        )
        let metadata = StreamingClient.ChatMetadata(
            title: "Generated topic", iconNames: ["search"], category: "web",
            modelName: nil, providerName: nil, serverRegion: nil,
            userMessageId: "user-1", encryptedChatKey: nil
        )

        XCTAssertTrue(ChatGeneratedMetadataPolicy.needsGeneratedTitle(chat))
        XCTAssertEqual(ChatGeneratedMetadataPolicy.applying(metadata, to: chat).title, "Generated topic")
        XCTAssertEqual(chat.displayTitle, "New Chat")
    }

    // contract-test: direct surface=gui.apple assertions=chats.surface.semantic-parity
    func testProvisionalTitleOnlyFillsAnUntitledUnversionedChat() {
        let chat = Chat(
            id: "chat-1", title: nil, lastMessageAt: nil,
            createdAt: "2026-09-24T10:00:00Z", updatedAt: nil,
            isArchived: false, isPinned: false, appId: "ai",
            encryptedTitle: nil, encryptedChatKey: nil,
            messagesV: 1, titleV: 0
        )

        let updated = ChatGeneratedMetadataPolicy.applyingProvisionalTitle("First request", to: chat)

        XCTAssertEqual(updated.title, "First request")
        XCTAssertEqual(updated.titleV, 0)
    }

    // contract-test: direct surface=gui.apple assertions=chats.surface.semantic-parity
    func testGeneratedHeaderLoadsOnlyForAnActiveUntitledFirstTurn() {
        XCTAssertTrue(ChatGeneratedHeaderPolicy.shouldShowLoading(
            title: nil, titleVersion: 0, hasMessages: true, isStreaming: true
        ))
        XCTAssertFalse(ChatGeneratedHeaderPolicy.shouldShowLoading(
            title: nil, titleVersion: 0, hasMessages: true, isStreaming: false
        ))
        XCTAssertFalse(ChatGeneratedHeaderPolicy.shouldShowLoading(
            title: "Generated", titleVersion: 0, hasMessages: true, isStreaming: true
        ))
        XCTAssertFalse(ChatGeneratedHeaderPolicy.shouldShowLoading(
            title: nil, titleVersion: 1, hasMessages: true, isStreaming: true
        ))
    }

    // contract-test: direct surface=gui.apple assertions=chats.surface.semantic-parity
    func testGenericAssistantSenderFallsBackToMateCategoryIdentity() {
        XCTAssertNil(ChatAssistantIdentityPolicy.explicitDisplayName("Assistant"))
        XCTAssertNil(ChatAssistantIdentityPolicy.explicitDisplayName(" ai "))
        XCTAssertEqual(ChatAssistantIdentityPolicy.explicitDisplayName("Code Mate"), "Code Mate")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testNewTaskClearsPreviousTurnLifecycleState() {
        var state = ChatStreamingLifecycleState()
        state.apply(.preprocessingStep(chatId: "chat-1", step: "model_selected", data: nil))
        state.apply(.thinkingChunk(chatId: "chat-1", messageId: "assistant-old", content: "Old reasoning"))
        state.apply(.messageQueued(
            chatId: "chat-1",
            taskId: "task-old",
            userMessageId: "user-old",
            message: "Old queued text"
        ))

        state.apply(.taskInitiated(chatId: "chat-1", taskId: "task-new", userMessageId: "user-new"))

        XCTAssertEqual(state.phase, .sending)
        XCTAssertEqual(state.taskId, "task-new")
        XCTAssertEqual(state.userMessageId, "user-new")
        XCTAssertNil(state.messageId)
        XCTAssertNil(state.preprocessingStep)
        XCTAssertEqual(state.thinkingContent, "")
        XCTAssertFalse(state.isThinkingStreaming)
        XCTAssertNil(state.queuedMessageText)
    }

    // contract-test: direct surface=gui.apple assertions=chats.surface.semantic-parity
    func testThinkingChunksAccumulateForOneAssistantMessage() {
        var state = ChatStreamingLifecycleState()

        state.apply(.thinkingChunk(chatId: "chat-1", messageId: "assistant-1", content: "First "))
        state.apply(.thinkingChunk(chatId: "chat-1", messageId: "assistant-1", content: "second"))

        XCTAssertEqual(state.thinkingContent, "First second")
        XCTAssertEqual(state.messageId, "assistant-1")
        XCTAssertTrue(state.isThinkingStreaming)
    }

    // contract-test: direct surface=gui.apple assertions=chats.message.identity-idempotent,chats.surface.semantic-parity
    func testStaleAndDuplicateChunksAreRejected() {
        var state = ChatStreamingLifecycleState()
        let newest = StreamingClient.StreamEvent.chunk(
            chatId: "chat-1", messageId: "assistant-1", sequence: 2,
            content: "newest", isFinal: false, userMessageId: "user-1",
            category: nil, modelName: nil, rejectionReason: nil
        )
        let stale = StreamingClient.StreamEvent.chunk(
            chatId: "chat-1", messageId: "assistant-1", sequence: 1,
            content: "stale", isFinal: false, userMessageId: "user-1",
            category: nil, modelName: nil, rejectionReason: nil
        )

        XCTAssertTrue(state.apply(newest))
        XCTAssertFalse(state.apply(stale))
        XCTAssertFalse(state.apply(newest))
        XCTAssertEqual(state.phase, .streaming)
    }

    // contract-test: direct surface=gui.apple assertions=chats.completion.pending-delivery,chats.surface.semantic-parity
    func testFinalChunkCompletesWhenServerReusesOrOmitsSequence() {
        var state = ChatStreamingLifecycleState()
        state.apply(.chunk(
            chatId: "chat-1", messageId: "assistant-1", sequence: 4,
            content: "Partial", isFinal: false, userMessageId: "user-1",
            category: nil, modelName: nil, rejectionReason: nil
        ))

        XCTAssertTrue(state.apply(.chunk(
            chatId: "chat-1", messageId: "assistant-1", sequence: 0,
            content: "Complete", isFinal: true, userMessageId: "user-1",
            category: nil, modelName: nil, rejectionReason: nil
        )))
        XCTAssertEqual(state.phase, .completed)
        XCTAssertFalse(state.isActive)
        XCTAssertFalse(state.apply(.chunk(
            chatId: "chat-1", messageId: "assistant-1", sequence: 0,
            content: "Complete", isFinal: true, userMessageId: "user-1",
            category: nil, modelName: nil, rejectionReason: nil
        )))
        XCTAssertFalse(state.apply(.chunk(
            chatId: "chat-1", messageId: "assistant-1", sequence: 5,
            content: "Late partial", isFinal: false, userMessageId: "user-1",
            category: nil, modelName: nil, rejectionReason: nil
        )))
        XCTAssertEqual(state.phase, .completed)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testCancellingOneStreamKeepsOtherSubscriberRegistered() async {
        let chatId = "fixture-stream-replacement-\(UUID().uuidString)"
        let firstStream = await StreamingClient.shared.streamForChat(chatId)
        let firstConsumer = Task.detached {
            for await _ in firstStream {}
        }
        let secondStream = await StreamingClient.shared.streamForChat(chatId)
        let received = expectation(description: "Newest stream receives chat event")
        let secondConsumer = Task.detached {
            for await event in secondStream {
                if case .messageReady(let receivedChatId, _) = event,
                   receivedChatId == chatId {
                    received.fulfill()
                    break
                }
            }
        }

        firstConsumer.cancel()
        await firstConsumer.value
        await StreamingClient.shared.dispatch(
            .messageReady(chatId: chatId, messageId: "fixture-assistant-1"),
            for: chatId
        )

        await fulfillment(of: [received], timeout: 1)
        firstConsumer.cancel()
        secondConsumer.cancel()
        await StreamingClient.shared.removeStream(chatId)
    }

    // contract-test: direct surface=gui.apple assertions=chats.completion.pending-delivery,chats.surface.semantic-parity
    func testLifecycleTransitionsThroughProcessingThinkingStreamingAndFinal() {
        var state = ChatStreamingLifecycleState()

        state.apply(.taskInitiated(chatId: "chat-1", taskId: "task-1", userMessageId: "user-1"))
        XCTAssertEqual(state.phase, .sending)
        XCTAssertEqual(state.taskId, "task-1")

        state.apply(.preprocessingStep(chatId: "chat-1", step: "mate_selected", data: nil))
        XCTAssertEqual(state.phase, .processing)
        XCTAssertEqual(state.preprocessingStep, "mate_selected")
        XCTAssertTrue(state.shouldShowProcessingDetails)

        state.apply(.typingStarted(chatId: "chat-1", messageId: "assistant-1", metadata: nil))
        XCTAssertEqual(state.phase, .typing)
        XCTAssertEqual(state.messageId, "assistant-1")
        XCTAssertFalse(state.shouldShowProcessingDetails)

        state.apply(.thinkingChunk(chatId: "chat-1", messageId: "assistant-1", content: "reasoning"))
        XCTAssertEqual(state.phase, .thinking)
        XCTAssertEqual(state.thinkingContent, "reasoning")
        XCTAssertTrue(state.isThinkingStreaming)
        XCTAssertTrue(state.shouldShowThinkingDetails)

        state.apply(.thinkingComplete(chatId: "chat-1", messageId: "assistant-1"))
        XCTAssertEqual(state.phase, .typing)
        XCTAssertFalse(state.isThinkingStreaming)

        state.apply(.chunk(
            chatId: "chat-1",
            messageId: "assistant-1",
            sequence: 1,
            content: "Hello",
            isFinal: false,
            userMessageId: "user-1",
            category: nil,
            modelName: nil,
            rejectionReason: nil
        ))
        XCTAssertEqual(state.phase, .streaming)

        state.apply(.chunk(
            chatId: "chat-1",
            messageId: "assistant-1",
            sequence: 2,
            content: "Hello world",
            isFinal: true,
            userMessageId: "user-1",
            category: nil,
            modelName: nil,
            rejectionReason: nil
        ))
        XCTAssertEqual(state.phase, .completed)
        XCTAssertFalse(state.isActive)
    }

    // contract-test: direct surface=gui.apple assertions=chats.local-state.precedence,chats.surface.semantic-parity
    func testQueuedCancelAndTypingEndedStatesAreIdempotent() {
        var state = ChatStreamingLifecycleState()

        state.apply(.messageQueued(chatId: "chat-1", taskId: "task-1", userMessageId: "user-2", message: "Queued text"))
        XCTAssertEqual(state.phase, .queued)
        XCTAssertEqual(state.taskId, "task-1")
        XCTAssertEqual(state.userMessageId, "user-2")
        XCTAssertEqual(state.queuedMessageText, "Queued text")

        state.apply(.cancelRequested(chatId: "chat-1", taskId: "task-1"))
        XCTAssertEqual(state.phase, .cancelling)
        XCTAssertFalse(state.isThinkingStreaming)

        state.apply(.typingEnded(chatId: "chat-1", messageId: "assistant-1"))
        XCTAssertEqual(state.phase, .cancelling)

        state.reset()
        XCTAssertEqual(state.phase, .idle)
        XCTAssertNil(state.taskId)
        XCTAssertNil(state.queuedMessageText)
    }

    // contract-test: direct surface=gui.apple assertions=chats.message.identity-idempotent,chats.surface.semantic-parity
    func testTypingEndedCannotCompleteAnotherActiveMessage() {
        var state = ChatStreamingLifecycleState()
        state.apply(.typingStarted(chatId: "chat-1", messageId: "assistant-new", metadata: nil))
        state.apply(.chunk(
            chatId: "chat-1", messageId: "assistant-new", sequence: 1,
            content: "Partial", isFinal: false, userMessageId: "user-new",
            category: nil, modelName: nil, rejectionReason: nil
        ))

        XCTAssertFalse(state.apply(.typingEnded(chatId: "chat-1", messageId: "assistant-old")))
        XCTAssertFalse(state.apply(.typingEnded(chatId: "chat-1", messageId: nil)))
        XCTAssertEqual(state.messageId, "assistant-new")
        XCTAssertEqual(state.phase, .streaming)
        XCTAssertTrue(state.isActive)
    }

    // contract-test: direct surface=gui.apple assertions=chats.streaming.ordered-final,chats.message.identity-idempotent
    func testStaleTerminalEventsCannotCompleteCurrentTurn() {
        var state = ChatStreamingLifecycleState()
        state.apply(.taskInitiated(chatId: "chat-1", taskId: "task-new", userMessageId: "user-new"))
        state.apply(.typingStarted(chatId: "chat-1", messageId: "assistant-new", metadata: nil))

        XCTAssertFalse(state.apply(.messageReady(chatId: "chat-1", messageId: "assistant-old")))
        XCTAssertFalse(state.apply(.cancelRequested(chatId: "chat-1", taskId: "task-old")))
        XCTAssertFalse(state.apply(.postProcessingCompleted(
            chatId: "chat-1",
            taskId: "task-old",
            followUpSuggestions: [],
            newChatSuggestions: [],
            chatSummary: nil,
            chatTags: [],
            updatedTitle: nil,
            sourceTitleVersion: nil,
            sourceMetadataVersion: nil
        )))
        XCTAssertEqual(state.phase, .typing)
        XCTAssertEqual(state.messageId, "assistant-new")
        XCTAssertEqual(state.taskId, "task-new")
        XCTAssertTrue(state.isActive)
    }

    // contract-test: direct surface=gui.apple assertions=chats.streaming.ordered-final,chats.message.identity-idempotent
    func testMessageReadyBeforeCurrentAssistantIdentityIsRejected() {
        var state = ChatStreamingLifecycleState()
        state.apply(.taskInitiated(chatId: "chat-1", taskId: "task-new", userMessageId: "user-new"))

        XCTAssertFalse(state.apply(.messageReady(chatId: "chat-1", messageId: "assistant-old")))
        XCTAssertEqual(state.phase, .sending)
        XCTAssertNil(state.messageId)
        XCTAssertTrue(state.isActive)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.streaming.ordered-final
    func testReplacedSocketCallbacksCannotActOnCurrentConnection() {
        XCTAssertTrue(WebSocketManager.isCurrentSocket(
            callbackTaskIdentifier: 12,
            currentTaskIdentifier: 12
        ))
        XCTAssertFalse(WebSocketManager.isCurrentSocket(
            callbackTaskIdentifier: 11,
            currentTaskIdentifier: 12
        ))
        XCTAssertFalse(WebSocketManager.isCurrentSocket(
            callbackTaskIdentifier: 12,
            currentTaskIdentifier: nil
        ))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.streaming.ordered-final
    func testSupersededConnectionAttemptCannotMutateCurrentSocket() {
        XCTAssertTrue(WebSocketManager.shouldContinueConnectionAttempt(
            expectedGeneration: 4,
            currentGeneration: 4,
            isCancelled: false
        ))
        XCTAssertFalse(WebSocketManager.shouldContinueConnectionAttempt(
            expectedGeneration: 3,
            currentGeneration: 4,
            isCancelled: false
        ))
        XCTAssertFalse(WebSocketManager.shouldContinueConnectionAttempt(
            expectedGeneration: 4,
            currentGeneration: 4,
            isCancelled: true
        ))
    }

    // contract-test: direct surface=gui.apple assertions=chats.streaming.ordered-final,chats.message.identity-idempotent
    func testStaleQueuedAndUnidentifiedCancelEventsCannotReplaceCurrentTask() {
        var state = ChatStreamingLifecycleState()
        state.apply(.taskInitiated(chatId: "chat-1", taskId: "task-new", userMessageId: "user-new"))

        XCTAssertFalse(state.apply(.messageQueued(
            chatId: "chat-1",
            taskId: "task-old",
            userMessageId: "user-old",
            message: "Old queued message"
        )))
        XCTAssertFalse(state.apply(.cancelRequested(chatId: "chat-1", taskId: nil)))
        XCTAssertEqual(state.phase, .sending)
        XCTAssertEqual(state.taskId, "task-new")
        XCTAssertNil(state.queuedMessageText)
    }

    // contract-test: direct surface=gui.apple assertions=chats.streaming.progressive-presentation
    func testTerminalEventClearsStreamingMessageSelectionBeforeNextSend() {
        let viewModel = ChatViewModel()
        viewModel.handleStreamEvent(.typingStarted(
            chatId: "chat-1",
            messageId: "assistant-1",
            metadata: nil
        ))
        XCTAssertEqual(viewModel.streamingMessageId, "assistant-1")

        viewModel.handleStreamEvent(.messageReady(chatId: "chat-1", messageId: "assistant-1"))
        XCTAssertNil(viewModel.streamingMessageId)

        viewModel.handleStreamEvent(.taskInitiated(
            chatId: "chat-1",
            taskId: "task-2",
            userMessageId: "user-2"
        ))
        XCTAssertNil(viewModel.streamingMessageId)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testCancelAITaskPayloadMatchesWebContract() {
        let payload = ChatSendPipeline().cancelAITaskPayload(taskId: "task-1", chatId: "chat-1")

        XCTAssertEqual(payload["task_id"] as? String, "task-1")
        XCTAssertEqual(payload["chat_id"] as? String, "chat-1")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testCancelAITaskPayloadOmitsMissingChatId() {
        let payload = ChatSendPipeline().cancelAITaskPayload(taskId: "task-1", chatId: nil)

        XCTAssertEqual(payload["task_id"] as? String, "task-1")
        XCTAssertNil(payload["chat_id"])
    }

    // contract-test: direct surface=gui.apple assertions=chats.local-state.precedence,chats.surface.semantic-parity
    func testLifecycleCapturesErrorAndClearsThinkingStreaming() {
        var state = ChatStreamingLifecycleState()

        state.apply(.thinkingChunk(chatId: "chat-1", messageId: "assistant-1", content: "reasoning"))
        state.apply(.error("failed"))

        XCTAssertEqual(state.phase, .error)
        XCTAssertEqual(state.errorMessage, "failed")
        XCTAssertFalse(state.isThinkingStreaming)
        XCTAssertFalse(state.isActive)
    }

    // contract-test: direct surface=gui.apple assertions=chats.completion.pending-delivery,chats.surface.semantic-parity
    func testAuthoritativeSyncCompletionClearsActiveStreamingState() {
        var state = ChatStreamingLifecycleState()

        state.apply(.typingStarted(chatId: "chat-1", messageId: "assistant-1", metadata: nil))
        state.apply(.chunk(
            chatId: "chat-1",
            messageId: "assistant-1",
            sequence: 1,
            content: "Partial",
            isFinal: false,
            userMessageId: "user-1",
            category: nil,
            modelName: nil,
            rejectionReason: nil
        ))

        XCTAssertTrue(state.isActive)
        XCTAssertTrue(state.completeFromAuthoritativeSync(messageId: "assistant-1"))
        XCTAssertEqual(state.phase, .completed)
        XCTAssertFalse(state.isActive)
        XCTAssertFalse(state.completeFromAuthoritativeSync(messageId: "assistant-2"))
    }

    // contract-test: direct surface=gui.apple assertions=chats.streaming.progressive-presentation
    func testTypingWithoutRenderableContentDoesNotMaterializeAssistantTurn() {
        XCTAssertFalse(ChatStreamingPresentationPolicy.shouldMaterializeAssistant(
            content: "",
            thinkingContent: "",
            embedCount: 0
        ))
        XCTAssertTrue(ChatStreamingPresentationPolicy.shouldMaterializeAssistant(
            content: "First visible chunk",
            thinkingContent: "",
            embedCount: 0
        ))
        XCTAssertTrue(ChatStreamingPresentationPolicy.shouldMaterializeAssistant(
            content: "",
            thinkingContent: "Provider-supplied thinking",
            embedCount: 0
        ))
    }

    // contract-test: direct surface=gui.apple assertions=chats.streaming.progressive-presentation
    func testProtocolOnlyChunkDoesNotMaterializeEmptyAssistantTurn() {
        let protocolOnlyContent = """
        ```json_embed
        {"type":"app_skill_use","embed_id":"embed-search"}
        ```
        """

        XCTAssertFalse(ChatStreamingPresentationPolicy.shouldMaterializeAssistant(
            content: protocolOnlyContent,
            thinkingContent: "",
            embedCount: 0
        ))
        XCTAssertTrue(ChatStreamingPresentationPolicy.shouldMaterializeAssistant(
            content: "Visible answer",
            thinkingContent: "",
            embedCount: 0
        ))
        XCTAssertTrue(ChatStreamingPresentationPolicy.shouldMaterializeAssistant(
            content: protocolOnlyContent,
            thinkingContent: "Provider-supplied thinking",
            embedCount: 0
        ))
    }

    // contract-test: direct surface=gui.apple assertions=chats.streaming.progressive-presentation
    func testNonfinalSkillReferenceMaterializesAndPersistsThroughFinalChunk() throws {
        let viewModel = ChatViewModel()
        viewModel.chat = Chat(
            id: "chat-1", title: "Streaming", lastMessageAt: nil,
            createdAt: "2026-09-24T10:00:00Z", updatedAt: nil,
            isArchived: false, isPinned: false, appId: "web",
            encryptedTitle: nil, encryptedChatKey: nil
        )
        let content = """
        ```json
        {"type":"app_skill_use","embed_id":"embed-search","app_id":"web","skill_id":"search"}
        ```
        """

        viewModel.handleStreamEvent(.chunk(
            chatId: "chat-1", messageId: "assistant-1", sequence: 1,
            content: content, isFinal: false, userMessageId: "user-1",
            category: "web", modelName: "test-model", rejectionReason: nil
        ))

        let partial = try XCTUnwrap(viewModel.messages.first)
        XCTAssertEqual(partial.isStreaming, true)
        XCTAssertEqual(partial.embedRefs?.map(\.id), ["embed-search"])
        XCTAssertNotNil(viewModel.embedRecords["embed-search"])

        viewModel.handleStreamEvent(.chunk(
            chatId: "chat-1", messageId: "assistant-1", sequence: 2,
            content: content, isFinal: true, userMessageId: "user-1",
            category: "web", modelName: "test-model", rejectionReason: nil
        ))

        let completed = try XCTUnwrap(viewModel.messages.first)
        XCTAssertEqual(completed.isStreaming, false)
        XCTAssertEqual(completed.embedRefs?.map(\.id), ["embed-search"])
        XCTAssertNotNil(viewModel.embedRecords["embed-search"])
    }

    // contract-test: direct surface=gui.apple assertions=chats.completion.pending-delivery,chats.surface.semantic-parity
    func testNativeLifecycleCompletionCapabilityMatchesPlatformSceneSemantics() {
        XCTAssertTrue(NativeClientLifecyclePolicy.isCompletionCapable(.active))
        XCTAssertFalse(NativeClientLifecyclePolicy.isCompletionCapable(.background))
        #if os(macOS)
        XCTAssertTrue(NativeClientLifecyclePolicy.isCompletionCapable(.inactive))
        #else
        XCTAssertFalse(NativeClientLifecyclePolicy.isCompletionCapable(.inactive))
        #endif
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.delivery.idempotent-visible,chats.completion.pending-delivery
    func testMacAppDeactivationStopsReportingForegroundChatVisibility() {
        XCTAssertTrue(NativeClientLifecyclePolicy.isMacForeground(.active, appIsActive: true))
        XCTAssertTrue(NativeClientLifecyclePolicy.isMacForeground(.inactive, appIsActive: true))
        XCTAssertFalse(NativeClientLifecyclePolicy.isMacForeground(.active, appIsActive: false))
        XCTAssertFalse(NativeClientLifecyclePolicy.isMacForeground(.inactive, appIsActive: false))
        XCTAssertFalse(NativeClientLifecyclePolicy.isMacForeground(.background, appIsActive: true))
    }

    // contract-test: direct surface=gui.apple assertions=chats.followups.non-destructive-reconciliation
    func testAcceptedSendClearsPriorFollowUpsAndEmptyResponseKeepsThemCleared() {
        let priorTurn = ["Question one", "Question two"]
        let afterAcceptedSend = ChatFollowUpSuggestionPolicy.clearForAcceptedSend(priorTurn)
        let afterEmptyCompletion = ChatFollowUpSuggestionPolicy.acceptCompletedResponse([])
        let persistedEmpty = ChatViewModel.decodeFollowUpSuggestions("[]")
        let afterReload = ChatFollowUpSuggestionPolicy.restore(
            stored: persistedEmpty,
            hasStoredCiphertext: true,
            legacyExtracted: priorTurn
        )

        XCTAssertEqual(afterAcceptedSend, [])
        XCTAssertEqual(afterEmptyCompletion, [])
        XCTAssertEqual(afterReload, [])
        XCTAssertEqual(
            ChatFollowUpSuggestionPolicy.reconcile(current: afterAcceptedSend, incoming: ["Question three"]),
            ["Question three"]
        )
    }

    // contract-test: direct surface=gui.apple assertions=chats.followups.non-destructive-reconciliation
    func testLegacyEmptyFollowUpPayloadDoesNotEraseAcceptedSuggestionsWithoutStoredCiphertext() {
        let accepted = ["Question one", "Question two"]

        XCTAssertEqual(
            ChatFollowUpSuggestionPolicy.restore(
                stored: accepted,
                hasStoredCiphertext: false,
                legacyExtracted: []
            ),
            accepted
        )
    }

    // contract-test: direct surface=gui.apple assertions=chats.streaming.ordered-final,chats.streaming.progressive-presentation
    func testInboundStreamingEventsDispatchInEnqueueOrder() async {
        let recorder = StreamEventOrderRecorder()
        let dispatcher = OrderedStreamEventDispatcher { event, _ in
            let label: String
            switch event {
            case .typingStarted:
                label = "typing"
            case .chunk(_, _, let sequence, _, _, _, _, _, _):
                label = "chunk-\(sequence)"
            case .messageReady:
                label = "ready"
            default:
                label = "other"
            }
            await recorder.append(label)
        }

        dispatcher.enqueue(.typingStarted(chatId: "chat-1", messageId: "assistant-1", metadata: nil), for: "chat-1")
        dispatcher.enqueue(.chunk(
            chatId: "chat-1", messageId: "assistant-1", sequence: 1,
            content: "First", isFinal: false, userMessageId: "user-1",
            category: nil, modelName: nil, rejectionReason: nil
        ), for: "chat-1")
        dispatcher.enqueue(.chunk(
            chatId: "chat-1", messageId: "assistant-1", sequence: 2,
            content: "First second", isFinal: false, userMessageId: "user-1",
            category: nil, modelName: nil, rejectionReason: nil
        ), for: "chat-1")
        dispatcher.enqueue(.messageReady(chatId: "chat-1", messageId: "assistant-1"), for: "chat-1")

        await dispatcher.waitUntilIdle()
        let events = await recorder.events
        XCTAssertEqual(events, ["typing", "chunk-1", "chunk-2", "ready"])
    }
}

private actor StreamEventOrderRecorder {
    private(set) var events: [String] = []

    func append(_ event: String) {
        events.append(event)
    }
}
