import Combine
import XCTest
@testable import OpenMates

@MainActor
final class SubChatActivityProvenanceTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence,chats.surface.semantic-parity
    func testMarkerRetainsItsExplicitTaskAndParentMessageProvenance() throws {
        let parsed = try XCTUnwrap(SubChatBatchDescriptor.parse(#"{"type":"sub_chat_batch","batch_id":"batch-a","chat_id":"parent","task_id":"task-a","parent_message_id":"message-a","sub_chat_ids":["child-a"]}"#))
        XCTAssertEqual(parsed.taskID, "task-a"); XCTAssertEqual(parsed.parentMessageID, "message-a")
        XCTAssertEqual(try JSONDecoder().decode(SubChatBatchDescriptor.self, from: JSONEncoder().encode(parsed)), parsed)
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testProgressMustMatchParentTaskMessageAndExplicitChildMembership() {
        let batch = descriptor("a")
        XCTAssertNotNil(SubChatActivityProvenance.progress(progress("a"), for: batch, parentID: "parent", messageID: "message-a"))
        var foreign = progress("a"); foreign.messageId = "foreign-message"
        let candidates = [progress("a", parent: "foreign-parent"), progress("b"), foreign,
                          progress("a", child: "child-b")]
        for candidate in candidates {
            XCTAssertNil(SubChatActivityProvenance.progress(candidate, for: batch, parentID: "parent", messageID: "message-a"))
        }
        var mismatchedMarker = batch; mismatchedMarker.parentMessageID = "foreign-marker-message"
        XCTAssertNil(SubChatActivityProvenance.progress(progress("a"), for: mismatchedMarker, parentID: "parent", messageID: "message-a"))
        var legacy = batch; legacy.taskID = nil; legacy.parentMessageID = nil
        XCTAssertNil(SubChatActivityProvenance.progress(progress("a"), for: legacy, parentID: "parent", messageID: "message-a"))
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testOneCompletedBatchNeverCompletesAnotherBatchInSameParent() {
        let first = descriptor("a"), second = descriptor("b")
        let event = progress("a", status: "completed", child: nil)
        XCTAssertEqual(SubChatActivityProvenance.status(for: first, parentID: "parent", messageID: "message-a", progress: event, terminalChildIDs: []), "finished")
        XCTAssertEqual(SubChatActivityProvenance.status(for: second, parentID: "parent", messageID: "message-b", progress: event, terminalChildIDs: []), "processing")
        XCTAssertEqual(SubChatActivityProvenance.status(for: second, parentID: "parent", messageID: "message-b", progress: nil, terminalChildIDs: ["child-a"]), "processing")
        XCTAssertEqual(SubChatActivityProvenance.status(for: second, parentID: "parent", messageID: "message-b", progress: nil, terminalChildIDs: ["child-b"]), "finished")
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testObservedTerminalBatchSurvivesNextBatchAndDelayedRunningEvents() {
        let first = descriptor("a"), second = descriptor("b")
        var state = SubChatActivityCompletionState()
        state.observe(progress("a", status: "completed"), descriptors: [first, second], parentID: "parent", messageID: "message-a")
        let later = progress("b", status: "running", child: "child-b")
        XCTAssertEqual(SubChatActivityProvenance.status(for: first, parentID: "parent", messageID: "message-a", progress: later, terminalChildIDs: [], retainedTerminalStatuses: state.terminalStatuses), "finished")
        XCTAssertEqual(SubChatActivityProvenance.status(for: second, parentID: "parent", messageID: "message-b", progress: later, terminalChildIDs: [], retainedTerminalStatuses: state.terminalStatuses), "processing")
        state.observe(progress("a", status: "running"), descriptors: [first, second], parentID: "parent", messageID: "message-a")
        XCTAssertEqual(SubChatActivityProvenance.status(for: first, parentID: "parent", messageID: "message-a", progress: progress("a", status: "running"), terminalChildIDs: [], retainedTerminalStatuses: state.terminalStatuses), "finished")
        XCTAssertEqual(state.terminalStatuses.count, 1)
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testTerminalDescriptorCannotBeRevivedByLateRunningProgress() {
        let batch = descriptor("a", status: "cancelled")
        XCTAssertEqual(SubChatActivityProvenance.status(for: batch, parentID: "parent", messageID: "message-a", progress: progress("a", status: "running"), terminalChildIDs: []), "cancelled")
        XCTAssertEqual(SubChatActivityProvenance.status(for: descriptor("a"), parentID: "parent", messageID: "message-a", progress: progress("a", status: "failed"), terminalChildIDs: []), "error")
    }
    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence,chats.surface.semantic-parity
    func testHistoryObserverTracksHydrationAndRejectsForeignParentAndAccountScope() {
        var scope = UUID()
        let store = ChatStore()
        store.performWithoutPersistence {
            store.chats = [child("a"), child("b", parent: "foreign")]
            store.setMessages(for: "child-a", messages: [message("child-a", role: .user)])
            store.setMessages(for: "child-b", messages: [message("child-b", role: .assistant)])
        }
        let observer = SubChatActivityStoreObserver(store: store, scopeGeneration: { scope })
        let batches = [descriptor("a"), descriptor("b")]
        XCTAssertEqual(observer.terminalChildIDs(descriptors: batches, parentID: "parent"), [])
        var changes = 0
        let subscription = observer.objectWillChange.sink { changes += 1 }
        store.performWithoutPersistence { store.setMessages(for: "child-a", messages: [message("child-a", role: .assistant)]) }
        XCTAssertGreaterThan(changes, 0)
        XCTAssertEqual(observer.terminalChildIDs(descriptors: batches, parentID: "parent"), ["child-a"])
        scope = UUID()
        XCTAssertEqual(observer.terminalChildIDs(descriptors: batches, parentID: "parent"), [])
        withExtendedLifetime(subscription) {}
    }
    // contract-test: supporting surface=gui.apple assertions=chats.completion.pending-delivery,chats.surface.semantic-parity
    func testPendingRecoveryOrActiveStreamCannotSettleHistoricalChild() {
        let child = child("a")
        let active = message("child-a", role: .assistant, streaming: true)
        XCTAssertFalse(SubChatActivityProvenance.isTerminalChild(child, parentID: "parent", messages: [active], pendingRecoveryIDs: []))
        let terminal = message("child-a", role: .assistant)
        XCTAssertFalse(SubChatActivityProvenance.isTerminalChild(child, parentID: "parent", messages: [terminal], pendingRecoveryIDs: [terminal.id]))
        XCTAssertTrue(SubChatActivityProvenance.isTerminalChild(child, parentID: "parent", messages: [terminal], pendingRecoveryIDs: []))
    }
    // contract-test: supporting surface=gui.apple assertions=chats.streaming.progressive-presentation,chats.surface.semantic-parity
    func testSettledFocusAndBatchLeaveAutomaticLiveBodyButRemainInManualDisclosure() throws {
        let blocks = [block(.embedGroup([
            .init(value: "focus", isRef: false, isLargePreview: false, type: "focus-mode-activation"),
            .init(value: "skill", isRef: false, isLargePreview: false, type: "app-skill-use")]), 0),
            block(.subChatBatch(descriptor("a", status: "finished")), 1),
            block(.subChatBatch(descriptor("b")), 2)]
        let segment = try XCTUnwrap(AssistantActivityProjection.segments(blocks: blocks, embeds: [:]).first)
        let automatic = AssistantActivityProjection.visibleUnits(in: segment, automaticallyExpandedActive: true, visibleFocusIDs: [], activeBatchIDs: ["batch-b"])
        XCTAssertEqual(automatic.flatMap(\.items).map(\.id), ["skill", "batch-b"])
        let acknowledging = AssistantActivityProjection.visibleUnits(in: segment, automaticallyExpandedActive: true, visibleFocusIDs: ["focus"], activeBatchIDs: ["batch-b"])
        XCTAssertEqual(acknowledging.flatMap(\.items).map(\.id), ["focus", "skill", "batch-b"])
        XCTAssertEqual(AssistantActivityProjection.visibleUnits(in: segment, automaticallyExpandedActive: false, visibleFocusIDs: [], activeBatchIDs: []), segment.units)
        XCTAssertEqual(automatic.last?.id, segment.units.last?.id)
    }
    private func descriptor(_ suffix: String, status: String = "processing") -> SubChatBatchDescriptor {
        .init(batchID: "batch-" + suffix, parentChatID: "parent", status: status, subChatIDs: ["child-" + suffix], executionMode: "parallel", taskID: "task-" + suffix, parentMessageID: "message-" + suffix)
    }
    private func progress(_ suffix: String, parent: String = "parent", status: String = "running", child: String? = "child-a") -> SubChatProgress {
        .init(chatId: parent, taskId: "task-" + suffix, executionMode: "parallel", status: status, total: 1, completed: 0, activeSubChatId: child, messageId: "message-" + suffix)
    }
    private func child(_ suffix: String, parent: String = "parent") -> Chat {
        .init(id: "child-" + suffix, title: "Child " + suffix, lastMessageAt: nil, createdAt: "2026-10-19T00:00:00Z", updatedAt: nil, isArchived: false, isPinned: false, appId: "ai", encryptedTitle: nil, encryptedChatKey: nil, parentId: parent, isSubChat: true)
    }
    private func message(_ chatID: String, role: MessageRole, streaming: Bool = false) -> Message {
        .init(id: chatID + "-message", chatId: chatID, role: role, content: "Synthetic result", encryptedContent: nil, createdAt: "2026-10-19T00:00:00Z", updatedAt: nil, appId: "ai", isStreaming: streaming, embedRefs: nil)
    }
    private func block(_ markdown: MarkdownBlock, _ ordinal: Int) -> ProgressiveMarkdownBlock {
        .init(ordinal: ordinal, markdown: markdown, document: .init(messageId: "parent-response", index: ordinal, markdownBlock: markdown, embedRefsById: [:]), sourceStartUTF8: 0, sourceEndUTF8: 0)
    }
}
