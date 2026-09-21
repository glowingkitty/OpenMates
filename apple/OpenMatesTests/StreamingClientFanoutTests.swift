// Local real-AsyncSequence fanout and replay tests. No backend or elapsed-time
// assertions: suspension gates control cancellation/reset races deterministically.
import XCTest
@testable import OpenMates

@MainActor
final class StreamingClientFanoutTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.streaming.ordered-final,chats.streaming.progressive-presentation
    func testBufferedFinalIsConsumedOnceAcrossRepeatedMetadataRefreshRequests() async {
        let client = StreamingClient()
        await client.dispatch(task(), for: "chat")
        await client.dispatch(chunk(1, content: "Completed synthetic answer.", final: true), for: "chat")
        var identity = ChatStreamSubscriptionIdentity()
        var readers: [StreamingClient.Subscription] = []
        for _ in 0..<100 {
            if identity.begin(chatID: "chat", session: client.sessionGeneration) != nil {
                readers.append(await client.streamForChat("chat"))
            }
        }
        await client.removeStream("chat")
        var finalEvents = 0
        for reader in readers { finalEvents += sequences(await collect(reader)).count }
        XCTAssertEqual(readers.count, 1)
        XCTAssertEqual(finalEvents, 1, "Repeated store refreshes must not replay the same terminal response")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.streaming.ordered-final,chats.streaming.progressive-presentation
    func testHistoryRefreshKeepsSubscriptionAndDoesNotReplayTerminalSideEffects() {
        let client = StreamingClient()
        var identity = ChatStreamSubscriptionIdentity()
        let first = identity.begin(chatID: "chat", session: client.sessionGeneration)
        XCTAssertNotNil(first)
        for _ in 0..<100 {
            XCTAssertNil(identity.begin(chatID: "chat", session: client.sessionGeneration),
                "Metadata ACK history refreshes must retain the reader, including while recovery is pending")
        }
        identity.finish(first!)
        XCTAssertNotNil(identity.begin(chatID: "chat", session: client.sessionGeneration),
            "A genuinely ended stream may be joined again")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.streaming.ordered-final,chats.streaming.progressive-presentation
    func testChatSessionAndExplicitCancellationReplaceReaderWithoutOldCleanupClearingNewReader() {
        let client = StreamingClient()
        var identity = ChatStreamSubscriptionIdentity()
        let old = identity.begin(chatID: "first", session: client.sessionGeneration)!
        XCTAssertNotNil(identity.begin(chatID: "second", session: client.sessionGeneration))
        identity.finish(old)
        XCTAssertNil(identity.begin(chatID: "second", session: client.sessionGeneration))
        client.resetSession()
        XCTAssertNotNil(identity.begin(chatID: "second", session: client.sessionGeneration))
        identity.invalidate()
        XCTAssertNotNil(identity.begin(chatID: "second", session: client.sessionGeneration),
            "Stop must permit a new reader without buffered replay for cancellation acknowledgement")
    }

    // contract-test: direct surface=gui.apple assertions=chats.streaming.ordered-final,chats.streaming.progressive-presentation
    func testTwoSubscribersBothReceiveLiveChunksAndOnlyTheLateSubscriberReplays() async {
        let client = StreamingClient()
        let first = await client.streamForChat("chat")
        await client.dispatch(task(), for: "chat")
        await client.dispatch(chunk(1, content: "First paragraph."), for: "chat")
        await client.dispatch(chunk(2, content: "First paragraph.\n\nSecond."), for: "chat")
        let second = await client.streamForChat("chat")
        await client.dispatch(chunk(3, content: "First paragraph.\n\nSecond.\n\nFinal.", final: true), for: "chat")
        await client.removeStream("chat")
        let firstEvents = await collect(first)
        let secondEvents = await collect(second)
        XCTAssertEqual(sequences(firstEvents), [1, 2, 3])
        XCTAssertEqual(sequences(secondEvents), [2, 3], "Late replay is one cumulative snapshot, then ordinary live events")
        XCTAssertEqual(taskIDs(firstEvents), ["task"])
        XCTAssertEqual(taskIDs(secondEvents), ["task"])
        XCTAssertEqual(contents(firstEvents).last, contents(secondEvents).last)
    }

    // contract-test: direct surface=gui.apple assertions=chats.streaming.ordered-final,chats.streaming.progressive-presentation
    func testManyCumulativeFramesReplayOneOutputAndCompleteThinkingMetadataAndFinalFlags() async {
        let client = StreamingClient()
        let metadata = StreamingClient.ChatMetadata(title: "Synthetic title", iconNames: ["code"],
            category: "code", modelName: "synthetic-model", providerName: "synthetic-provider",
            serverRegion: "EU", userMessageId: "user", encryptedChatKey: "synthetic-ciphertext")
        await client.dispatch(task(), for: "chat")
        await client.dispatch(.typingStarted(chatId: "chat", messageId: "message", metadata: metadata), for: "chat")
        var thinking = ""
        for index in 1...100 {
            let delta = "Thought \(index). "
            thinking += delta
            await client.dispatch(.thinkingChunk(chatId: "chat", messageId: "message", content: delta), for: "chat")
        }
        await client.dispatch(.thinkingComplete(chatId: "chat", messageId: "message"), for: "chat")
        var content = ""
        for index in 1...120 {
            content += "Paragraph \(index).\n\n"
            await client.dispatch(chunk(index, content: content), for: "chat")
        }
        content += "[A complete source](embed:source-1)."
        await client.dispatch(chunk(0, content: content, final: true), for: "chat")
        // A late stale nonfinal frame must not replace the canonical final replay.
        await client.dispatch(chunk(121, content: "stale and incomplete"), for: "chat")
        let statistics = await client.replayStatistics()
        XCTAssertEqual(statistics.cumulativeContentBytes, content.utf8.count)
        XCTAssertEqual(statistics.thinkingBytes, thinking.utf8.count)
        XCTAssertLessThanOrEqual(statistics.retainedEvents, 6)
        let subscriber = await client.streamForChat("chat")
        await client.removeStream("chat")
        let events = await collect(subscriber)
        XCTAssertEqual(sequences(events), [0])
        XCTAssertEqual(contents(events), [content])
        var state = ChatStreamingLifecycleState()
        for event in events { state.apply(event) }
        XCTAssertEqual(state.phase, .completed)
        XCTAssertEqual(state.thinkingContent, thinking)
        XCTAssertFalse(state.isThinkingStreaming)
        XCTAssertEqual(state.userMessageId, "user")
        for event in events {
            if case .chunk(_, _, _, _, let final, let user, let category, let model, _) = event {
                XCTAssertTrue(final)
                XCTAssertEqual(user, "user")
                XCTAssertEqual(category, "code")
                XCTAssertEqual(model, "synthetic-model")
            }
            if case .typingStarted(_, _, let value) = event {
                XCTAssertEqual(value?.encryptedChatKey, metadata.encryptedChatKey)
                XCTAssertEqual(value?.providerName, metadata.providerName)
            }
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testCancellingOneRealConsumerNeverFinishesTheOtherSubscriber() async {
        let client = StreamingClient()
        let first = await client.streamForChat("chat")
        let firstConsumer = Task { for await _ in first {} }
        let second = await client.streamForChat("chat")
        firstConsumer.cancel()
        await firstConsumer.value
        let active = await client.replayStatistics()
        XCTAssertEqual(active.subscribers, 1, "Cancelled consumption must unregister only that subscriber")
        await client.dispatch(chunk(1, content: "Still live."), for: "chat")
        await client.dispatch(chunk(2, content: "Still live. Complete.", final: true), for: "chat")
        await client.removeStream("chat")
        let events = await collect(second)
        XCTAssertEqual(sequences(events), [1, 2])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testStopResubscriptionSkipsReplayButStillReceivesTheServerFinal() async {
        let client = StreamingClient()
        await client.dispatch(task(), for: "chat")
        await client.dispatch(chunk(1, content: "Active response."), for: "chat")
        let stopped = await client.streamForChat("chat", replayBufferedState: false)
        await client.dispatch(chunk(2, content: "Stopped response.", final: true), for: "chat")
        await client.removeStream("chat")
        let events = await collect(stopped)
        XCTAssertEqual(sequences(events), [2])
        XCTAssertTrue(taskIDs(events).isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testNewTaskClearsPreviousTurnReplayWithoutKeepingItsThinkingOrTerminalState() async {
        let client = StreamingClient()
        await client.dispatch(task(), for: "chat")
        await client.dispatch(.thinkingChunk(chatId: "chat", messageId: "message", content: "Old thinking."), for: "chat")
        await client.dispatch(chunk(1, content: "Old final.", final: true), for: "chat")
        await client.dispatch(.taskInitiated(chatId: "chat", taskId: "next-task", userMessageId: "next-user"), for: "chat")
        let current = await client.streamForChat("chat")
        await client.removeStream("chat")
        let events = await collect(current)
        XCTAssertEqual(taskIDs(events), ["next-task"])
        XCTAssertTrue(contents(events).isEmpty)
        var state = ChatStreamingLifecycleState()
        for event in events { state.apply(event) }
        XCTAssertEqual(state.phase, .sending)
        XCTAssertEqual(state.userMessageId, "next-user")
        XCTAssertEqual(state.thinkingContent, "")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testReplayPreservesProcessingQueueCancellationAndPostProcessingOrder() async {
        let client = StreamingClient()
        let events: [StreamingClient.StreamEvent] = [
            task(), .preprocessingStep(chatId: "chat", step: "mate_selected", data: nil),
            .messageQueued(chatId: "chat", taskId: "task", userMessageId: "user", message: "Queued"),
            .typingStarted(chatId: "chat", messageId: "message", metadata: nil),
            chunk(1, content: "Partial"), .cancelRequested(chatId: "chat", taskId: "task"),
            chunk(2, content: "Partial stopped", final: true),
            .postProcessingCompleted(chatId: "chat", taskId: "task", followUpSuggestions: ["Synthetic next step"],
                newChatSuggestions: [], chatSummary: "Synthetic summary", chatTags: ["synthetic"], updatedTitle: "Synthetic title")
        ]
        var expected = ChatStreamingLifecycleState()
        for event in events { expected.apply(event); await client.dispatch(event, for: "chat") }
        let subscription = await client.streamForChat("chat")
        await client.removeStream("chat")
        let replay = await collect(subscription)
        var actual = ChatStreamingLifecycleState()
        for event in replay { actual.apply(event) }
        XCTAssertEqual(actual.phase, expected.phase)
        XCTAssertEqual(actual.preprocessingStep, expected.preprocessingStep)
        XCTAssertEqual(actual.queuedMessageText, expected.queuedMessageText)
        XCTAssertEqual(actual.taskId, expected.taskId)
        guard let last = replay.last,
              case .postProcessingCompleted(_, _, let suggestions, _, let summary, let tags, let title) = last else {
            return XCTFail("Post-processing metadata must remain the final replay event")
        }
        XCTAssertEqual(suggestions, ["Synthetic next step"])
        XCTAssertEqual(summary, "Synthetic summary")
        XCTAssertEqual(tags, ["synthetic"])
        XCTAssertEqual(title, "Synthetic title")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testInactiveReplayHasCountAndAgeBoundsWhileAnActiveWindowRetainsItsState() async {
        let clock = ReplayClock()
        let client = StreamingClient(maxInactiveReplayChats: 2, replayLifetime: 5, now: { clock.now })
        let active = await client.streamForChat("active")
        await client.dispatch(chunk(1, content: "Pinned", chat: "active"), for: "active")
        for chat in ["oldest", "middle", "newest"] {
            await client.dispatch(chunk(1, content: chat, chat: chat), for: chat)
            clock.advance(1)
        }
        let bounded = await client.replayStatistics()
        XCTAssertEqual(bounded.chats, 3, "One active plus two inactive replay entries")
        let oldest = await client.streamForChat("oldest")
        await client.removeStream("oldest")
        let oldestEvents = await collect(oldest)
        XCTAssertTrue(oldestEvents.isEmpty)
        clock.advance(10)
        let expired = await client.replayStatistics()
        XCTAssertEqual(expired.chats, 1)
        let activeLate = await client.streamForChat("active")
        await client.removeAllStreams()
        let lateActiveEvents = await collect(activeLate)
        XCTAssertEqual(contents(lateActiveEvents), ["Pinned"])
        let activeEvents = await collect(active)
        XCTAssertEqual(contents(activeEvents), ["Pinned"])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testSessionResetRejectsAlreadyBufferedValuesDelayedProducersAndStaleSubscribers() async {
        let client = StreamingClient()
        let oldGeneration = client.sessionGeneration
        let oldSubscriber = await client.streamForChat("same-chat", session: oldGeneration)
        await client.dispatch(chunk(1, content: "Account A data", chat: "same-chat"), for: "same-chat", session: oldGeneration)
        let cleanup = client.resetSession()
        XCTAssertFalse(client.isCurrentSession(oldGeneration), "Account invalidation is synchronous")
        await cleanup.value
        let oldEvents = await collect(oldSubscriber)
        XCTAssertTrue(oldEvents.isEmpty,
                      "Finishing a raw AsyncStream would still expose its old buffered value")
        let current = client.sessionGeneration
        let newSubscriber = await client.streamForChat("same-chat", session: current)
        await client.dispatch(chunk(2, content: "Delayed A frame", chat: "same-chat"), for: "same-chat", session: oldGeneration)
        await client.dispatch(chunk(1, content: "Account B data", chat: "same-chat"), for: "same-chat", session: current)
        let stale = await client.streamForChat("same-chat", session: oldGeneration)
        let staleEvents = await collect(stale)
        XCTAssertTrue(staleEvents.isEmpty)
        await client.removeAllStreams()
        let newEvents = await collect(newSubscriber)
        XCTAssertEqual(contents(newEvents), ["Account B data"])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testRapidAccountResetsCannotLetOlderCleanupEraseCurrentReplay() async {
        let client = StreamingClient()
        let a = client.resetSession()
        let b = client.resetSession()
        let current = client.sessionGeneration
        await client.dispatch(chunk(1, content: "Current account"), for: "chat", session: current)
        await a.value; await b.value
        let stream = await client.streamForChat("chat", session: current)
        await client.removeAllStreams()
        let events = await collect(stream)
        XCTAssertEqual(contents(events), ["Current account"])
    }

    // contract-test: direct surface=gui.apple assertions=chats.streaming.ordered-final
    func testDispatcherDropsQueuedPriorAccountFramesBeforeCallingTheActualClient() async {
        let client = StreamingClient()
        let dispatcher = OrderedStreamEventDispatcher(client: client)
        dispatcher.enqueue(chunk(1, content: "Old queued frame"), for: "chat")
        let cleanup = client.resetSession()
        dispatcher.enqueue(chunk(2, content: "New queued frame"), for: "chat")
        await dispatcher.waitUntilIdle(); await cleanup.value
        let current = await client.streamForChat("chat")
        await client.removeAllStreams()
        let events = await collect(current)
        XCTAssertEqual(contents(events), ["New queued frame"])
    }

    // contract-test: direct surface=gui.apple assertions=chats.streaming.ordered-final
    func testDispatcherResetCancelsInFlightDeliveryWithoutDrainingNewTransportEventsFromOldTask() async {
        let client = StreamingClient()
        let gate = DispatchSuspensionGate()
        let dispatcher = OrderedStreamEventDispatcher({ event, chat in
            await gate.pauseFirstDelivery()
            await client.dispatch(event, for: chat)
            if case .chunk(_, _, let sequence, _, _, _, _, _, _) = event { await gate.finished(sequence) }
        }, client: client)
        let stream = await client.streamForChat("chat")
        dispatcher.enqueue(chunk(1, content: "Suspended old transport"), for: "chat")
        await gate.waitUntilEntered()
        dispatcher.enqueue(chunk(2, content: "Queued old transport"), for: "chat")
        dispatcher.reset()
        dispatcher.enqueue(chunk(3, content: "New transport"), for: "chat")
        await dispatcher.waitUntilIdle()
        await gate.release()
        await gate.waitUntilFinished(1)
        await dispatcher.waitUntilIdle()
        await client.removeAllStreams()
        let events = await collect(stream)
        XCTAssertEqual(sequences(events), [3])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testNewAssistantMessageDoesNotInheritItsPredecessorsThinking() async {
        let client = StreamingClient()
        await client.dispatch(task(), for: "chat")
        await client.dispatch(.typingStarted(chatId: "chat", messageId: "message", metadata: nil), for: "chat")
        await client.dispatch(.thinkingChunk(chatId: "chat", messageId: "message", content: "Previous thought."), for: "chat")
        await client.dispatch(chunk(1, content: "Previous answer", final: true), for: "chat")
        await client.dispatch(.typingStarted(chatId: "chat", messageId: "next-message", metadata: nil), for: "chat")
        await client.dispatch(.thinkingChunk(chatId: "chat", messageId: "next-message", content: "Current thought."), for: "chat")
        await client.dispatch(.chunk(chatId: "chat", messageId: "next-message", sequence: 1,
            content: "Current answer", isFinal: false, userMessageId: nil, category: nil, modelName: nil,
            rejectionReason: nil), for: "chat")
        let stream = await client.streamForChat("chat")
        await client.removeAllStreams()
        let events = await collect(stream)
        var state = ChatStreamingLifecycleState()
        for event in events { state.apply(event) }
        XCTAssertEqual(state.messageId, "next-message")
        XCTAssertEqual(state.thinkingContent, "Current thought.")
        XCTAssertEqual(contents(events), ["Current answer"])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testMaterializedTerminalIsNotReplayedOverCiphertextButPendingRecoveryStillReplays() async {
        func message(_ id: String, chat: String = "chat", encrypted: String? = "synthetic-cipher",
                     streaming: Bool = false) -> Message {
            Message(id: id, chatId: chat, role: .assistant, content: "Answer", encryptedContent: encrypted,
                createdAt: "2026-01-01T00:00:00Z", updatedAt: nil, appId: "code",
                isStreaming: streaming, embedRefs: nil)
        }
        let rows = [message("message"), message("pending"), message("partial", streaming: true),
                    message("plaintext", encrypted: nil), message("foreign", chat: "other")]
        let committed = ChatStreamReplayPolicy.materializedFinalMessageIDs(in: rows, chatID: "chat", pendingMessageIDs: ["pending"])
        XCTAssertEqual(committed, ["message"])
        let client = StreamingClient()
        await client.dispatch(task(), for: "chat")
        await client.dispatch(chunk(1, content: "Answer", final: true), for: "chat")
        let existing = await client.streamForChat("chat", excludingMaterializedFinalMessageIDs: committed)
        let pendingExclusions = ChatStreamReplayPolicy.materializedFinalMessageIDs(in: rows, chatID: "chat", pendingMessageIDs: ["message", "pending"])
        let pending = await client.streamForChat("chat", excludingMaterializedFinalMessageIDs: pendingExclusions)
        await client.removeAllStreams()
        let existingEvents = await collect(existing)
        let pendingEvents = await collect(pending)
        XCTAssertTrue(existingEvents.isEmpty, "A committed row must not be re-appended as transient plaintext")
        XCTAssertEqual(contents(pendingEvents), ["Answer"], "Locally encrypted but uncommitted recovery still needs its terminal state")
        XCTAssertEqual(rows[0].encryptedContent, "synthetic-cipher")
    }

    private func task() -> StreamingClient.StreamEvent {
        .taskInitiated(chatId: "chat", taskId: "task", userMessageId: "user")
    }
    private func chunk(_ sequence: Int, content: String, final: Bool = false, chat: String = "chat") -> StreamingClient.StreamEvent {
        .chunk(chatId: chat, messageId: "message", sequence: sequence, content: content, isFinal: final,
               userMessageId: nil, category: nil, modelName: nil, rejectionReason: nil)
    }
    private func collect(_ stream: StreamingClient.Subscription) async -> [StreamingClient.StreamEvent] {
        var events: [StreamingClient.StreamEvent] = []
        for await event in stream { events.append(event) }
        return events
    }
    private func sequences(_ events: [StreamingClient.StreamEvent]) -> [Int] {
        events.compactMap { if case .chunk(_, _, let sequence, _, _, _, _, _, _) = $0 { return sequence }; return nil }
    }
    private func contents(_ events: [StreamingClient.StreamEvent]) -> [String] {
        events.compactMap { if case .chunk(_, _, _, let content, _, _, _, _, _) = $0 { return content }; return nil }
    }
    private func taskIDs(_ events: [StreamingClient.StreamEvent]) -> [String] {
        events.compactMap { if case .taskInitiated(_, let task, _) = $0 { return task }; return nil }
    }
}

private final class ReplayClock: @unchecked Sendable {
    private let lock = NSLock()
    private var value = Date(timeIntervalSince1970: 1_000)
    var now: Date { lock.lock(); defer { lock.unlock() }; return value }
    func advance(_ seconds: TimeInterval) { lock.lock(); defer { lock.unlock() }; value += seconds }
}

private actor DispatchSuspensionGate {
    private var entered = false
    private var entryWaiters: [CheckedContinuation<Void, Never>] = []
    private var releaseContinuation: CheckedContinuation<Void, Never>?
    private var finishedSequences = Set<Int>()
    private var finishWaiters: [Int: [CheckedContinuation<Void, Never>]] = [:]
    func pauseFirstDelivery() async {
        guard !entered else { return }
        entered = true
        await withCheckedContinuation { continuation in
            releaseContinuation = continuation
            for waiter in entryWaiters { waiter.resume() }
            entryWaiters.removeAll()
        }
    }
    func waitUntilEntered() async {
        if entered { return }
        await withCheckedContinuation { entryWaiters.append($0) }
    }
    func release() { releaseContinuation?.resume(); releaseContinuation = nil }
    func finished(_ sequence: Int) {
        finishedSequences.insert(sequence)
        for waiter in finishWaiters.removeValue(forKey: sequence) ?? [] { waiter.resume() }
    }
    func waitUntilFinished(_ sequence: Int) async {
        if finishedSequences.contains(sequence) { return }
        await withCheckedContinuation { finishWaiters[sequence, default: []].append($0) }
    }
}
