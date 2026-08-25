// Unit coverage for Apple chat streaming lifecycle parity with the web app.
// These tests are deterministic and avoid network calls, credentials, private
// chat content, and raw encryption keys. They verify that native streaming state
// no longer ignores preprocessing, thinking, queued, and cancellation events.
// Payload assertions cover only existing backend WebSocket contracts.

import XCTest
@testable import OpenMates

@MainActor
final class ChatStreamingLifecycleParityTests: XCTestCase {
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
    func testReplacingStreamKeepsNewestSubscriberRegistered() async {
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

        // Let the first continuation's asynchronous termination callback run.
        try? await Task.sleep(for: .milliseconds(50))
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
            updatedTitle: nil
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

    // contract-test: direct surface=gui.apple assertions=chats.followups.non-destructive-reconciliation
    func testEmptyFollowUpPayloadNeverClearsAcceptedSuggestions() {
        let accepted = ["Question one", "Question two"]

        XCTAssertEqual(
            ChatFollowUpSuggestionPolicy.reconcile(current: accepted, incoming: []),
            accepted
        )
        XCTAssertEqual(
            ChatFollowUpSuggestionPolicy.reconcile(current: accepted, incoming: ["Question three"]),
            ["Question three"]
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
