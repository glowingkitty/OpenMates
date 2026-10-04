// Local real-AsyncSequence fanout and replay tests. No backend or elapsed-time
// assertions: suspension gates control cancellation/reset races deterministically.
import CryptoKit
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
    func testFinishingIntentSubscriptionPreservesOtherChatReaders() async {
        let client = StreamingClient()
        let intentReader = await client.streamForChat("chat")
        let viewReader = await client.streamForChat("chat")
        let intentEvents = Task { await collect(intentReader) }
        await intentReader.finish()
        await client.dispatch(chunk(1, content: "Still visible to the app."), for: "chat")
        await client.removeStream("chat")
        let receivedByIntent = await intentEvents.value
        let receivedByView = await collect(viewReader)
        XCTAssertTrue(receivedByIntent.isEmpty)
        XCTAssertEqual(sequences(receivedByView), [1])
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
                newChatSuggestions: [], chatSummary: "Synthetic summary", chatTags: ["synthetic"], updatedTitle: "Synthetic title",
                sourceTitleVersion: 0, sourceMetadataVersion: 0)
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
              case .postProcessingCompleted(_, _, let suggestions, _, let summary, let tags, let title, let sourceTitleVersion, let sourceMetadataVersion) = last else {
            return XCTFail("Post-processing metadata must remain the final replay event")
        }
        XCTAssertEqual(suggestions, ["Synthetic next step"])
        XCTAssertEqual(summary, "Synthetic summary")
        XCTAssertEqual(tags, ["synthetic"])
        XCTAssertEqual(title, "Synthetic title")
        XCTAssertEqual(sourceTitleVersion, 0)
        XCTAssertEqual(sourceMetadataVersion, 0)
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

    // contract-test: direct surface=gui.apple assertions=chats.streaming.progressive-presentation,chats.rendering.inline-entity-interaction
    func testLiveEmbedReferenceDiscoveryWaitsForClosedBlocksAndDeduplicatesCumulativeFrames() async throws {
        let incomplete = """
        Intro
        ```json
        {"type":"app_skill_use","embed_id":"embed-search","embed_ids":["child-a"]}
        """
        let complete = incomplete + """
        ```
        [Source](embed:child-a) and [[embedref:child-b]]
        """
        XCTAssertEqual(ChatEmbedStreamCoordinator.embedReferences(in: incomplete), [])
        XCTAssertEqual(
            ChatEmbedStreamCoordinator.embedReferences(in: complete),
            ["embed-search", "child-a", "child-b"]
        )

        let transport = ChatEmbedRecordingTransport()
        let coordinator = ChatEmbedStreamCoordinator(
            transport: transport,
            chatStore: ChatStore(),
            authenticatedOwnerId: { "owner" },
            masterKey: { _ in SymmetricKey(size: .bits256) },
            chatKey: { _ in SymmetricKey(size: .bits256) },
            persistEmbedKeys: { _ in }
        )
        coordinator.beginTurn(chatId: "chat")
        await coordinator.processStreamContent(incomplete, chatId: "chat")
        await coordinator.processStreamContent(complete, chatId: "chat")
        await coordinator.processStreamContent(complete, chatId: "chat")

        XCTAssertEqual(transport.sentTypes, ["request_embed", "request_embed", "request_embed"])
        XCTAssertEqual(transport.sentPayloads.compactMap { $0["embed_id"] as? String }, [
            "embed-search", "child-a", "child-b",
        ])
    }

    // contract-test: direct surface=gui.apple assertions=chats.persistence.client-encrypted,chats.streaming.progressive-presentation,chats.rendering.assistant-document-convergence
    func testLiveEmbedProcessingIsVolatileAndFinalizedPayloadIsEncryptedBeforePersistence() async throws {
        let chatId = "chat-live-embed"
        let messageId = "assistant-message"
        let ownerId = "owner-live-embed"
        let chatKey = SymmetricKey(size: .bits256)
        let masterKey = SymmetricKey(size: .bits256)
        let chatStore = ChatStore()
        chatStore.upsertChat(Chat(
            id: chatId,
            title: "Synthetic chat",
            lastMessageAt: nil,
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: nil,
            isArchived: false,
            isPinned: false,
            appId: "ai",
            encryptedTitle: nil,
            encryptedChatKey: nil
        ))
        let transport = ChatEmbedRecordingTransport()
        var persistedKeys: [EmbedKeyRecord] = []
        let coordinator = ChatEmbedStreamCoordinator(
            transport: transport,
            chatStore: chatStore,
            authenticatedOwnerId: { ownerId },
            masterKey: { _ in masterKey },
            chatKey: { requestedChatId in requestedChatId == chatId ? chatKey : nil },
            persistEmbedKeys: { persistedKeys.append(contentsOf: $0) }
        )
        let plaintext = """
        type: app_skill_use
        app_id: web
        skill_id: search
        query: synthetic private query
        embed_ids[1]: child-result
        """
        var fields: [String: Any] = [
            "embed_id": "embed-search",
            "type": "app_skill_use",
            "status": "processing",
            "chat_id": chatId,
            "message_id": messageId,
            "user_id": ownerId,
            "content": plaintext,
            "app_id": "web",
            "skill_id": "search",
            "embed_ids": ["child-result"],
            "createdAt": 1_800_000_000,
            "updatedAt": 1_800_000_001,
        ]

        await coordinator.handleEmbedData(fields)
        let processing = try XCTUnwrap(chatStore.embeds(for: chatId).first)
        XCTAssertEqual(processing.status, .processing)
        XCTAssertNotNil(processing.rawData, "Processing cards need plaintext only in the live in-memory store")
        XCTAssertNil(processing.encryptedContent)
        XCTAssertTrue(persistedKeys.isEmpty)
        XCTAssertEqual(transport.sentTypes, ["request_embed"])

        fields["status"] = "finished"
        await coordinator.handleEmbedData(fields)
        let finalized = try XCTUnwrap(chatStore.embeds(for: chatId).first)
        let encryptedContent = try XCTUnwrap(finalized.encryptedContent)
        let encryptedType = try XCTUnwrap(finalized.encryptedType)
        XCTAssertNil(finalized.data, "The durable record must never retain the plaintext processing payload")
        XCTAssertNotEqual(encryptedContent, plaintext)
        let derivedKey = ComposerEmbedCrypto.deriveKey(chatKey: chatKey, embedId: "embed-search")
        XCTAssertEqual(try ComposerEmbedCrypto.decryptContent(encryptedContent, using: derivedKey), plaintext)
        XCTAssertEqual(try ComposerEmbedCrypto.decryptContent(encryptedType, using: derivedKey), "app_skill_use")
        XCTAssertEqual(persistedKeys.count, 2)
        XCTAssertEqual(transport.sentTypes, ["request_embed", "store_embed", "store_embed_keys"])

        let storePayload = try XCTUnwrap(transport.payload(for: "store_embed"))
        XCTAssertNil(storePayload["content"])
        XCTAssertNil(storePayload["type"])
        XCTAssertNotNil(storePayload["encrypted_content"])
        XCTAssertNotNil(storePayload["encrypted_type"])
        let keyPayload = try XCTUnwrap(transport.payload(for: "store_embed_keys"))
        let keys = try XCTUnwrap(keyPayload["keys"] as? [[String: Any]])
        XCTAssertEqual(keys.count, 2)
        XCTAssertTrue(keys.contains { ($0["key_type"] as? String) == "master" && $0["hashed_chat_id"] is NSNull })

        await coordinator.handleEmbedData(fields)
        XCTAssertEqual(transport.sentTypes, ["request_embed", "store_embed", "store_embed_keys"],
                       "Duplicate finalized delivery must not create new wrappers or rows")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.rendering.assistant-document-convergence
    func testRequestedAlreadyEncryptedEmbedStoresCiphertextAndServerKeyWrappersWithoutRoundTrip() async throws {
        let chatId = "chat-requested-embed"
        let chatStore = ChatStore()
        chatStore.upsertChat(Chat(
            id: chatId,
            title: "Synthetic chat",
            lastMessageAt: nil,
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: nil,
            isArchived: false,
            isPinned: false,
            appId: "ai",
            encryptedTitle: nil,
            encryptedChatKey: nil
        ))
        let transport = ChatEmbedRecordingTransport()
        var persistedKeys: [EmbedKeyRecord] = []
        let coordinator = ChatEmbedStreamCoordinator(
            transport: transport,
            chatStore: chatStore,
            authenticatedOwnerId: { nil },
            masterKey: { _ in nil },
            chatKey: { _ in nil },
            persistEmbedKeys: { persistedKeys.append(contentsOf: $0) }
        )
        let fields: [String: Any] = [
            "embed_id": "requested-parent",
            "type": "server-encrypted-type",
            "content": "server-encrypted-content",
            "status": "finished",
            "chat_id": chatId,
            "message_id": "hashed-or-raw-message",
            "already_encrypted": true,
            "embed_ids": ["requested-child"],
            "embed_keys": [
                [
                    "hashed_embed_id": "hashed-parent",
                    "key_type": "master",
                    "hashed_chat_id": NSNull(),
                    "encrypted_embed_key": "wrapped-master",
                ],
                [
                    "hashed_embed_id": "hashed-parent",
                    "key_type": "chat",
                    "hashed_chat_id": "hashed-chat",
                    "encrypted_embed_key": "wrapped-chat",
                ],
            ],
        ]

        await coordinator.handleEmbedData(fields)

        let stored = try XCTUnwrap(chatStore.embeds(for: chatId).first)
        XCTAssertNil(stored.data)
        XCTAssertEqual(stored.encryptedContent, "server-encrypted-content")
        XCTAssertEqual(stored.encryptedType, "server-encrypted-type")
        XCTAssertEqual(stored.childEmbedIds, ["requested-child"])
        XCTAssertEqual(persistedKeys.map(\.keyType).sorted(), ["chat", "master"])
        XCTAssertEqual(transport.sentTypes, ["request_embed"],
                       "Already encrypted fallback data is local hydration and must not be written back to the server")
    }

    // contract-test: direct surface=gui.apple assertions=chats.persistence.client-encrypted,chats.rendering.assistant-document-convergence
    func testLiveEmbedHeadFailureSendsNoKeysAndRetriesIdenticalCiphertext() async throws {
        let fixture = liveEmbedFixture()
        fixture.transport.failNextResponse(ofType: "store_embed_confirmed")
        await fixture.coordinator.handleEmbedData(fixture.fields)
        XCTAssertEqual(fixture.transport.sentTypes, ["store_embed"])
        let original = try XCTUnwrap(fixture.transport.payload(for: "store_embed")?["encrypted_content"] as? String)
        // Duplicate delivery must reuse the original prepared encryption.
        await fixture.coordinator.handleEmbedData(fixture.fields)
        XCTAssertEqual(fixture.transport.sentTypes, ["store_embed", "store_embed", "store_embed_keys"])
        XCTAssertEqual(fixture.transport.sentPayloads[1]["encrypted_content"] as? String, original)
        await fixture.coordinator.retryPendingPersistence()
        await fixture.coordinator.handleEmbedData(fixture.fields)
        XCTAssertEqual(fixture.transport.sentTypes.count, 3, "Only two durable receipts deduplicate final delivery")
        fixture.coordinator.reset()
    }

    // contract-test: direct surface=gui.apple assertions=chats.persistence.client-encrypted
    func testLiveEmbedRejectsWrongHeadIdentityDigestAndMissingStrictDigest() async throws {
        for invalid in ["digest", "uppercase", "decoded", "embed", "request", "missing", "malformed"] {
            let fixture = liveEmbedFixture()
            fixture.transport.receiptTransform = { type, fields in
                guard type == "store_embed_confirmed" else { return fields }
                var fields = fields
                switch invalid {
                case "digest": fields["canonical_digest"] = String(repeating: "0", count: 64)
                case "uppercase": fields["canonical_digest"] = (fields["canonical_digest"] as? String)?.uppercased()
                case "decoded":
                    let ciphertext = fixture.transport.sentPayloads.last?["encrypted_content"] as? String ?? ""
                    fields["canonical_digest"] = SHA256.hash(data: Data(base64Encoded: ciphertext) ?? Data()).map { String(format: "%02x", $0) }.joined()
                case "embed": fields["embed_id"] = "another-embed"
                case "request": fields["request_id"] = "another-request"
                case "missing": fields.removeValue(forKey: "canonical_digest")
                default: fields["canonical_digest"] = NSNull()
                }
                return fields
            }
            await fixture.coordinator.handleEmbedData(fixture.fields)
            XCTAssertEqual(fixture.transport.sentTypes, ["store_embed"], invalid)
            let ciphertext = fixture.transport.sentPayloads[0]["encrypted_content"] as? String
            fixture.transport.receiptTransform = nil
            await fixture.coordinator.retryPendingPersistence()
            XCTAssertEqual(fixture.transport.sentTypes, ["store_embed", "store_embed", "store_embed_keys"], invalid)
            XCTAssertEqual(fixture.transport.sentPayloads[1]["encrypted_content"] as? String, ciphertext, invalid)
            fixture.coordinator.reset()
        }
    }

    // contract-test: direct surface=gui.apple assertions=chats.persistence.client-encrypted
    func testLiveEmbedLegacyReceiptRequiresExplicitStagedPolicy() async {
        let fixture = liveEmbedFixture(policy: .allowLegacyReceipt)
        fixture.transport.receiptTransform = { _, fields in
            var fields = fields
            fields.removeValue(forKey: "canonical_digest")
            fields.removeValue(forKey: "canonical_source")
            fields.removeValue(forKey: "requested_count")
            return fields
        }
        await fixture.coordinator.handleEmbedData(fixture.fields)
        XCTAssertEqual(fixture.transport.sentTypes, ["store_embed", "store_embed_keys"])
        await fixture.coordinator.handleEmbedData(fixture.fields)
        XCTAssertEqual(fixture.transport.sentTypes.count, 2, "Complete legacy receipts still deduplicate finalized delivery")
        fixture.coordinator.reset()
    }

    // contract-test: direct surface=gui.apple assertions=chats.persistence.client-encrypted
    func testLiveEmbedCanonicalHeadSourceRejectsMalformedValuesAndRetriesOriginalCiphertext() async throws {
        for policy in [ChatEmbedStreamCoordinator.HeadReceiptPolicy.requireCanonicalDigest, .allowLegacyReceipt] {
            let invalidSources: [Any] = ["version_row", "HEAD", "", NSNull(), false, 1]
            for source in invalidSources {
                let fixture = liveEmbedFixture(policy: policy)
                fixture.transport.receiptTransform = { type, fields in
                    guard type == "store_embed_confirmed" else { return fields }
                    return fields.merging(["canonical_source": source]) { _, new in new }
                }
                await fixture.coordinator.handleEmbedData(fixture.fields)
                XCTAssertEqual(fixture.transport.sentTypes, ["store_embed"])
                let original = try XCTUnwrap(fixture.transport.sentPayloads.first?["encrypted_content"] as? String)
                fixture.transport.receiptTransform = nil
                await fixture.coordinator.retryPendingPersistence()
                XCTAssertEqual(fixture.transport.sentTypes, ["store_embed", "store_embed", "store_embed_keys"])
                XCTAssertEqual(fixture.transport.sentPayloads[1]["encrypted_content"] as? String, original)
                await fixture.coordinator.handleEmbedData(fixture.fields)
                XCTAssertEqual(fixture.transport.sentTypes.count, 3)
                fixture.coordinator.reset()
            }
        }
        let strict = liveEmbedFixture()
        strict.transport.receiptTransform = { type, fields in
            var fields = fields
            if type == "store_embed_confirmed" { fields.removeValue(forKey: "canonical_source") }
            return fields
        }
        await strict.coordinator.handleEmbedData(strict.fields)
        XCTAssertEqual(strict.transport.sentTypes, ["store_embed"], "Strict mode must not send wrappers without canonical head proof")
        strict.transport.receiptTransform = nil
        await strict.coordinator.retryPendingPersistence()
        XCTAssertEqual(strict.transport.sentTypes, ["store_embed", "store_embed", "store_embed_keys"])
        strict.coordinator.reset()
    }

    // contract-test: direct surface=gui.apple assertions=chats.persistence.client-encrypted
    func testLiveEmbedRequestedKeyCountRejectsMalformedValuesAndRetriesOriginalWrappers() async throws {
        for policy in [ChatEmbedStreamCoordinator.HeadReceiptPolicy.requireCanonicalDigest, .allowLegacyReceipt] {
            let invalidCounts: [Any] = [0, 1, 3, -1, NSNull(), false, "2", 2.5]
            for count in invalidCounts {
                let fixture = liveEmbedFixture(policy: policy)
                fixture.transport.receiptTransform = { type, fields in
                    guard type == "store_embed_keys_confirmed" else { return fields }
                    return fields.merging(["requested_count": count]) { _, new in new }
                }
                await fixture.coordinator.handleEmbedData(fixture.fields)
                XCTAssertEqual(fixture.transport.sentTypes, ["store_embed", "store_embed_keys"])
                let original = try JSONSerialization.data(withJSONObject: fixture.transport.sentPayloads[1]["keys"]!, options: [.sortedKeys])
                fixture.transport.receiptTransform = nil
                await fixture.coordinator.retryPendingPersistence()
                XCTAssertEqual(fixture.transport.sentTypes, ["store_embed", "store_embed_keys", "store_embed_keys"])
                XCTAssertEqual(try JSONSerialization.data(withJSONObject: fixture.transport.sentPayloads[2]["keys"]!, options: [.sortedKeys]), original)
                await fixture.coordinator.handleEmbedData(fixture.fields)
                XCTAssertEqual(fixture.transport.sentTypes.count, 3, "A rejected count must not mark the finalized payload persisted")
                fixture.coordinator.reset()
            }
        }
        let strict = liveEmbedFixture()
        strict.transport.receiptTransform = { type, fields in
            var fields = fields
            if type == "store_embed_keys_confirmed" { fields.removeValue(forKey: "requested_count") }
            return fields
        }
        await strict.coordinator.handleEmbedData(strict.fields)
        strict.transport.receiptTransform = nil
        await strict.coordinator.retryPendingPersistence()
        XCTAssertEqual(strict.transport.sentTypes, ["store_embed", "store_embed_keys", "store_embed_keys"])
        strict.coordinator.reset()
    }

    // contract-test: direct surface=gui.apple assertions=chats.persistence.client-encrypted,chats.rendering.assistant-document-convergence
    func testLiveEmbedRejectsFailedPartialMissingAndMalformedKeyCounts() async throws {
        let invalidCounts: [[String: Any]] = [
            ["failed_count": 1, "created_count": 1],
            ["failed_count": 0, "created_count": 1],
            ["failed_count": 0, "created_count": 3],
            ["failed_count": NSNull(), "created_count": 2],
            ["failed_count": 0, "created_count": NSNull()],
            ["failed_count": false, "created_count": 2],
            ["failed_count": 0, "created_count": "2"],
            ["failed_count": 0, "created_count": 2.5],
            ["failed_count": -1, "created_count": 2],
        ]
        for counts in invalidCounts {
            let fixture = liveEmbedFixture()
            fixture.transport.receiptTransform = { type, fields in
                guard type == "store_embed_keys_confirmed" else { return fields }
                return fields.merging(counts) { _, new in new }
            }
            await fixture.coordinator.handleEmbedData(fixture.fields)
            XCTAssertEqual(fixture.transport.sentTypes, ["store_embed", "store_embed_keys"])
            let originalKeys = try JSONSerialization.data(withJSONObject: fixture.transport.sentPayloads[1]["keys"]!, options: [.sortedKeys])
            fixture.transport.receiptTransform = nil
            await fixture.coordinator.retryPendingPersistence()
            XCTAssertEqual(fixture.transport.sentTypes, ["store_embed", "store_embed_keys", "store_embed_keys"])
            XCTAssertEqual(try JSONSerialization.data(withJSONObject: fixture.transport.sentPayloads[2]["keys"]!, options: [.sortedKeys]), originalKeys)
            await fixture.coordinator.handleEmbedData(fixture.fields)
            XCTAssertEqual(fixture.transport.sentTypes.count, 3)
            fixture.coordinator.reset()
        }
    }

    // contract-test: direct surface=gui.apple assertions=chats.persistence.client-encrypted,auth.session.isolation
    func testLiveEmbedDisconnectRetainsRetryAfterAutomaticBudgetAndConfirmedHead() async throws {
        let fixture = liveEmbedFixture()
        fixture.transport.failNextResponse(ofType: "store_embed_keys_confirmed")
        await fixture.coordinator.handleEmbedData(fixture.fields)
        let originalKeys = try JSONSerialization.data(withJSONObject: fixture.transport.sentPayloads[1]["keys"]!, options: [.sortedKeys])
        for _ in 0..<4 {
            fixture.transport.failNextResponse(ofType: "store_embed_keys_confirmed")
            await fixture.coordinator.retryPendingPersistence()
        }
        fixture.coordinator.transportDisconnected()
        let pausedCount = fixture.transport.sentTypes.count
        await fixture.coordinator.retryPendingPersistence()
        XCTAssertEqual(fixture.transport.sentTypes.count, pausedCount)
        await fixture.coordinator.transportConnected()
        XCTAssertEqual(fixture.transport.sentTypes.filter { $0 == "store_embed" }.count, 1)
        XCTAssertEqual(try JSONSerialization.data(withJSONObject: try XCTUnwrap(fixture.transport.sentPayloads.last?["keys"]), options: [.sortedKeys]), originalKeys)
        await fixture.coordinator.handleEmbedData(fixture.fields)
        XCTAssertEqual(fixture.transport.sentTypes.count, pausedCount + 1)
        fixture.coordinator.reset()
    }

    // contract-test: direct surface=gui.apple assertions=chats.persistence.client-encrypted
    func testLiveEmbedWaitsForHeadReceiptBeforeKeysAndSuppressesConcurrentDuplicate() async {
        let fixture = liveEmbedFixture()
        let gate = EmbedMasterKeySuspensionGate()
        fixture.transport.beforeReceipt = { type in
            if type == "store_embed_confirmed" { await gate.waitForRelease() }
        }
        let handling = Task { @MainActor in await fixture.coordinator.handleEmbedData(fixture.fields) }
        await gate.waitUntilEntered()
        XCTAssertEqual(fixture.transport.sentTypes, ["store_embed"])
        await fixture.coordinator.handleEmbedData(fixture.fields)
        XCTAssertEqual(fixture.transport.sentTypes, ["store_embed"])
        await gate.release()
        await handling.value
        XCTAssertEqual(fixture.transport.sentTypes, ["store_embed", "store_embed_keys"])
        fixture.coordinator.reset()
    }

    // contract-test: direct surface=gui.apple assertions=chats.persistence.client-encrypted
    func testLiveEmbedSupersededVersionCannotResendOldHeadOrKeys() async throws {
        let fixture = liveEmbedFixture()
        let gate = EmbedMasterKeySuspensionGate()
        fixture.transport.beforeReceipt = { type in
            if type == "store_embed_confirmed" { await gate.waitForRelease() }
        }
        let old = Task { @MainActor in await fixture.coordinator.handleEmbedData(fixture.fields) }
        await gate.waitUntilEntered()
        var newer = fixture.fields
        newer["version_number"] = 2
        newer["embed_ids"] = ["new-version-child"]
        let registered = EmbedMasterKeySuspensionGate()
        fixture.transport.afterSend = { type in
            if type == "request_embed" { await registered.markEntered() }
        }
        newer["content"] = "type: app_skill_use\napp_id: web\nskill_id: search\nquery: newer synthetic content"
        let new = Task { @MainActor in await fixture.coordinator.handleEmbedData(newer) }
        await registered.waitUntilEntered()
        fixture.transport.beforeReceipt = nil
        await gate.release()
        await old.value
        await new.value
        XCTAssertEqual(fixture.transport.sentTypes, ["store_embed", "request_embed", "store_embed", "store_embed_keys"])
        XCTAssertEqual(fixture.transport.sentPayloads[2]["version_number"] as? Int, 2)
        await fixture.coordinator.handleEmbedData(fixture.fields)
        await fixture.coordinator.retryPendingPersistence()
        XCTAssertEqual(fixture.transport.sentTypes.count, 4)
        XCTAssertEqual(fixture.store.embeds(for: "chat-live-receipts").first?.versionNumber, 2)
        fixture.coordinator.reset()
    }

    // contract-test: direct surface=gui.apple assertions=chats.persistence.client-encrypted,chats.rendering.assistant-document-convergence
    func testDelayedOlderProcessingOrEncryptedPayloadCannotReplaceNewerFinalPreview() async {
        for encrypted in [false, true] {
            let fixture = liveEmbedFixture()
            let gate = EmbedMasterKeySuspensionGate()
            fixture.transport.afterSend = { type in
                if type == "request_embed" { await gate.waitForRelease() }
            }
            var older = fixture.fields
            older["embed_ids"] = ["synthetic-delayed-child"]
            older["status"] = encrypted ? "finished" : "processing"
            older["already_encrypted"] = encrypted
            older["encrypted_content"] = "synthetic-old-cipher"
            older["encrypted_type"] = "synthetic-old-type"
            let handling = Task { @MainActor in await fixture.coordinator.handleEmbedData(older) }
            await gate.waitUntilEntered()
            var newer = fixture.fields
            newer["version_number"] = 2
            newer["content"] = "type: app_skill_use\napp_id: web\nskill_id: search\nquery: newer synthetic content"
            await fixture.coordinator.handleEmbedData(newer)
            let expected = fixture.store.embeds(for: "chat-live-receipts").first
            XCTAssertEqual(expected?.versionNumber, 2)
            XCTAssertEqual(expected?.status, .finished)
            await gate.release()
            await handling.value
            let actual = fixture.store.embeds(for: "chat-live-receipts").first
            XCTAssertEqual(actual?.versionNumber, 2)
            XCTAssertEqual(actual?.encryptedContent, expected?.encryptedContent)
            XCTAssertEqual(actual?.status, .finished)
            XCTAssertEqual(fixture.transport.sentTypes, ["request_embed", "store_embed", "store_embed_keys"])
            fixture.coordinator.reset()
        }
    }

    // contract-test: direct surface=gui.apple assertions=chats.persistence.client-encrypted,auth.session.isolation
    func testLiveEmbedScopeChangeWhileHeadWaitsDoesNotSendKeys() async {
        let transport = ChatEmbedRecordingTransport()
        let store = ChatStore()
        var scope = UUID()
        let fixture = liveEmbedFixture(transport: transport, store: store, scope: { scope })
        let gate = EmbedMasterKeySuspensionGate()
        transport.beforeReceipt = { _ in await gate.waitForRelease() }
        let handling = Task { @MainActor in await fixture.coordinator.handleEmbedData(fixture.fields) }
        await gate.waitUntilEntered()
        scope = UUID()
        fixture.coordinator.reset()
        transport.beforeReceipt = nil
        await gate.release()
        await handling.value
        await fixture.coordinator.transportConnected()
        XCTAssertEqual(transport.sentTypes, ["store_embed"])
    }

    // contract-test: direct surface=gui.apple assertions=chats.persistence.client-encrypted,auth.session.isolation
    func testLiveEmbedQueuedSendRechecksScopeBeforeAnySocketWrite() async {
        let transport = ChatEmbedRecordingTransport()
        var scope = UUID()
        let fixture = liveEmbedFixture(transport: transport, scope: { scope })
        let gate = EmbedMasterKeySuspensionGate()
        transport.beforeQueuedSend = { await gate.waitForRelease() }
        let handling = Task { @MainActor in await fixture.coordinator.handleEmbedData(fixture.fields) }
        await gate.waitUntilEntered()
        scope = UUID()
        transport.beforeQueuedSend = nil
        await gate.release()
        await handling.value
        XCTAssertTrue(transport.sentTypes.isEmpty, "Scope must be fenced inside the queued socket sender")
        fixture.coordinator.reset()
    }

    // contract-test: direct surface=gui.apple assertions=chats.persistence.client-encrypted
    func testLiveEmbedAbsentKeyCountsDoNotCompletePersistence() async {
        for absent in ["failed_count", "created_count"] {
            let fixture = liveEmbedFixture()
            fixture.transport.receiptTransform = { type, fields in
                var fields = fields
                if type == "store_embed_keys_confirmed" { fields.removeValue(forKey: absent) }
                return fields
            }
            await fixture.coordinator.handleEmbedData(fixture.fields)
            fixture.transport.receiptTransform = nil
            await fixture.coordinator.retryPendingPersistence()
            XCTAssertEqual(fixture.transport.sentTypes, ["store_embed", "store_embed_keys", "store_embed_keys"])
            fixture.coordinator.reset()
        }
    }

    // contract-test: direct surface=gui.apple assertions=chats.persistence.client-encrypted,auth.session.isolation
    func testLiveEmbedQueuedKeySendRechecksDeletionBeforeSocketWrite() async {
        let transport = ChatEmbedRecordingTransport()
        var deletionVersion = 0
        let fixture = liveEmbedFixture(transport: transport, deletionVersion: { _ in deletionVersion })
        let gate = EmbedMasterKeySuspensionGate()
        var sendCount = 0
        transport.beforeQueuedSend = {
            sendCount += 1
            if sendCount == 2 { await gate.waitForRelease() }
        }
        let handling = Task { @MainActor in await fixture.coordinator.handleEmbedData(fixture.fields) }
        await gate.waitUntilEntered()
        XCTAssertEqual(transport.sentTypes, ["store_embed"])
        deletionVersion = 1
        transport.beforeQueuedSend = nil
        await gate.release()
        await handling.value
        await fixture.coordinator.retryPendingPersistence()
        XCTAssertEqual(transport.sentTypes, ["store_embed"], "Deleted chat keys must never reach a queued sender or retry")
        fixture.coordinator.reset()
    }

    private func liveEmbedFixture(
        policy: ChatEmbedStreamCoordinator.HeadReceiptPolicy = .requireCanonicalDigest,
        transport: ChatEmbedRecordingTransport = ChatEmbedRecordingTransport(),
        store: ChatStore = ChatStore(),
        scope: @escaping () -> UUID = { OfflineStore.shared.scopeGeneration },
        deletionVersion: @escaping (String) -> Int = { _ in 0 }
    ) -> (coordinator: ChatEmbedStreamCoordinator, transport: ChatEmbedRecordingTransport, store: ChatStore, fields: [String: Any]) {
        let chatId = "chat-live-receipts"
        store.upsertChat(Chat(id: chatId, title: "Synthetic receipts", lastMessageAt: nil,
            createdAt: "2026-01-01T00:00:00Z", updatedAt: nil, isArchived: false, isPinned: false,
            appId: "ai", encryptedTitle: nil, encryptedChatKey: nil))
        let chatKey = SymmetricKey(size: .bits256)
        let masterKey = SymmetricKey(size: .bits256)
        let coordinator = ChatEmbedStreamCoordinator(transport: transport, chatStore: store,
            authenticatedOwnerId: { "synthetic-owner" }, masterKey: { _ in masterKey },
            chatKey: { _ in chatKey }, persistEmbedKeys: { _ in }, accountScopeGeneration: scope,
            chatDeletionVersion: deletionVersion, headReceiptPolicy: policy, retryDelay: { _ in .seconds(3_600) })
        return (coordinator, transport, store, ["embed_id": "synthetic-receipt-embed",
            "type": "app_skill_use", "status": "finished", "chat_id": chatId,
            "message_id": "synthetic-message", "version_number": 1,
            "content": "type: app_skill_use\napp_id: web\nskill_id: search"])
    }

    // contract-test: direct surface=gui.apple assertions=chats.persistence.client-encrypted,chats.rendering.assistant-document-convergence
    func testFinanceOwnerPIIRetriesTransientFinalPayloadAndNeverEntersCanonicalEmbed() async throws {
        let chatId = "chat-finance-owner-pii"
        let ownerId = "owner-finance"
        let original = "Private Merchant Example"
        let chatStore = ChatStore()
        chatStore.upsertChat(Chat(
            id: chatId, title: "Synthetic finance chat", lastMessageAt: nil,
            createdAt: "2026-01-01T00:00:00Z", updatedAt: nil,
            isArchived: false, isPinned: false, appId: "ai",
            encryptedTitle: nil, encryptedChatKey: nil
        ))
        let transport = ChatEmbedRecordingTransport()
        let master = SymmetricKey(size: .bits256)
        let chatKey = SymmetricKey(size: .bits256)
        var masterAvailable = false
        var sidecarCiphertext: String?
        let coordinator = ChatEmbedStreamCoordinator(
            transport: transport, chatStore: chatStore,
            authenticatedOwnerId: { ownerId },
            masterKey: { _ in masterAvailable ? master : nil },
            chatKey: { _ in chatKey },
            persistEmbedKeys: { _ in },
            persistOwnerPII: { mappings, storedChatId, embedId, storedOwnerId, key in
                XCTAssertEqual(storedChatId, chatId)
                XCTAssertEqual(embedId, "finance-embed")
                XCTAssertEqual(storedOwnerId, ownerId)
                XCTAssertEqual(mappings, [PIIMapping(
                    placeholder: "[COUNTERPARTY_1]", original: original, type: "COUNTERPARTY"
                )])
                let data = try JSONEncoder().encode(mappings)
                sidecarCiphertext = try await CryptoManager.shared.encryptWithMasterKey(
                    String(decoding: data, as: UTF8.self), masterKey: key
                )
            },
            retryDelay: { _ in .seconds(3_600) }
        )
        let fields: [String: Any] = [
            "embed_id": "finance-embed", "type": "app_skill_use", "status": "finished",
            "chat_id": chatId, "message_id": "assistant-finance", "user_id": ownerId,
            "app_id": "finance", "skill_id": "check_accounts",
            "content": "type: app_skill_use\napp_id: finance\nskill_id: check_accounts\ncounterparty: [COUNTERPARTY_1]",
            "owner_pii_mappings": [[
                "placeholder": "[COUNTERPARTY_1]", "original": original, "type": "COUNTERPARTY",
            ]],
        ]

        await coordinator.handleEmbedData(fields)
        XCTAssertTrue(chatStore.embeds(for: chatId).isEmpty)
        XCTAssertNil(sidecarCiphertext)
        XCTAssertFalse(transport.sentTypes.contains("store_embed"))

        var mappingless = fields
        mappingless.removeValue(forKey: "owner_pii_mappings")
        await coordinator.handleEmbedData(mappingless)
        await coordinator.retryPendingPersistence()
        XCTAssertTrue(chatStore.embeds(for: chatId).isEmpty, "A mapping-less redelivery cannot bypass a retained owner sidecar")
        XCTAssertTrue(transport.sentTypes.isEmpty)

        masterAvailable = true
        await coordinator.retryPendingOwnerPersistence()
        let ciphertext = try XCTUnwrap(sidecarCiphertext)
        XCTAssertFalse(ciphertext.contains(original))
        XCTAssertEqual(chatStore.embeds(for: chatId).count, 1)
        XCTAssertEqual(Array(transport.sentTypes.suffix(2)), ["store_embed", "store_embed_keys"])
        let storedPayload = try XCTUnwrap(transport.payload(for: "store_embed"))
        XCTAssertNil(storedPayload["owner_pii_mappings"])
        XCTAssertFalse(String(describing: storedPayload).contains(original))
        XCTAssertFalse(String(describing: chatStore.embeds(for: chatId)).contains(original))
    }

    // contract-test: direct surface=gui.apple assertions=chats.persistence.client-encrypted
    func testMappinglessRedeliveryCannotBypassFailedOwnerSidecarWithEncryptionKeysReady() async throws {
        let chatId = "synthetic-sidecar-failure", embedId = "synthetic-finance-embed"
        let ownerId = "synthetic-owner", original = "Private Merchant Example"
        let sanitized = "type: app_skill_use\napp_id: finance\nskill_id: check_accounts\ncounterparty: [COUNTERPARTY_1]"
        let store = ChatStore()
        store.performWithoutPersistence {
            store.upsertChat(Chat(id: chatId, title: "Synthetic sidecar retry", lastMessageAt: nil,
                createdAt: "2026-01-01T00:00:00Z", updatedAt: nil, isArchived: false, isPinned: false,
                appId: "ai", encryptedTitle: nil, encryptedChatKey: nil))
        }
        let master = SymmetricKey(size: .bits256), chatKey = SymmetricKey(size: .bits256)
        let transport = ChatEmbedRecordingTransport()
        var sidecarReady = false, sidecarSaved = false
        let coordinator = ChatEmbedStreamCoordinator(transport: transport, chatStore: store,
            authenticatedOwnerId: { ownerId }, masterKey: { _ in master }, chatKey: { _ in chatKey },
            persistEmbedKeys: { _ in },
            persistOwnerPII: { mappings, storedChatId, storedEmbedId, storedOwnerId, _ in
                XCTAssertEqual(storedChatId, chatId); XCTAssertEqual(storedEmbedId, embedId)
                XCTAssertEqual(storedOwnerId, ownerId)
                XCTAssertEqual(mappings, [PIIMapping(placeholder: "[COUNTERPARTY_1]", original: original, type: "COUNTERPARTY")])
                guard sidecarReady else { throw NSError(domain: "SyntheticSidecar", code: 1) }
                sidecarSaved = true
            }, chatDeletionVersion: { _ in 0 }, retryDelay: { _ in .seconds(3_600) })
        let fields: [String: Any] = ["embed_id": embedId, "type": "app_skill_use", "status": "finished",
            "chat_id": chatId, "message_id": "synthetic-finance-message", "user_id": ownerId,
            "app_id": "finance", "skill_id": "check_accounts", "content": sanitized,
            "owner_pii_mappings": [["placeholder": "[COUNTERPARTY_1]", "original": original, "type": "COUNTERPARTY"]]]
        await coordinator.handleEmbedData(fields)
        // Exhaust automatic retry eligibility while keys remain available.
        // The retained originals must still gate reconnect and redelivery.
        for _ in 0..<61 { await coordinator.retryPendingOwnerPersistence() }
        var redelivery = fields
        redelivery.removeValue(forKey: "owner_pii_mappings")
        redelivery["content"] = sanitized.replacingOccurrences(of: "[COUNTERPARTY_1]", with: original)
        await coordinator.handleEmbedData(redelivery)
        await coordinator.retryPendingPersistence()
        coordinator.transportDisconnected()
        await coordinator.transportConnected()
        XCTAssertFalse(sidecarSaved)
        XCTAssertFalse(transport.sentTypes.contains("store_embed"), "Available keys cannot bypass failed owner-only persistence")
        XCTAssertTrue(store.embeds(for: chatId).isEmpty)

        sidecarReady = true
        coordinator.transportDisconnected()
        await coordinator.transportConnected()
        XCTAssertTrue(sidecarSaved)
        XCTAssertEqual(transport.sentTypes, ["store_embed", "store_embed_keys"])
        let cipher = try XCTUnwrap(transport.payload(for: "store_embed")?["encrypted_content"] as? String)
        let restored = try ComposerEmbedCrypto.decryptContent(cipher,
            using: ComposerEmbedCrypto.deriveKey(chatKey: chatKey, embedId: embedId))
        XCTAssertEqual(restored, sanitized, "Retry must retain the original sanitized owner payload")
        XCTAssertFalse(restored.contains(original))
        await coordinator.handleEmbedData(fields)
        XCTAssertEqual(transport.sentTypes, ["store_embed", "store_embed_keys"])
    }

    // contract-test: direct surface=gui.apple assertions=chats.persistence.client-encrypted
    func testFinanceOwnerPIIRejectsMalformedOrWrongOwnerPayload() async {
        let chatId = "chat-finance-rejected"
        let chatStore = ChatStore()
        chatStore.upsertChat(Chat(
            id: chatId, title: "Synthetic finance chat", lastMessageAt: nil,
            createdAt: "2026-01-01T00:00:00Z", updatedAt: nil,
            isArchived: false, isPinned: false, appId: "ai",
            encryptedTitle: nil, encryptedChatKey: nil
        ))
        let transport = ChatEmbedRecordingTransport()
        var persisted = false
        let coordinator = ChatEmbedStreamCoordinator(
            transport: transport, chatStore: chatStore,
            authenticatedOwnerId: { "actual-owner" },
            masterKey: { _ in SymmetricKey(size: .bits256) },
            chatKey: { _ in SymmetricKey(size: .bits256) },
            persistEmbedKeys: { _ in },
            persistOwnerPII: { _, _, _, _, _ in persisted = true },
            retryDelay: { _ in .seconds(3_600) }
        )
        var fields: [String: Any] = [
            "embed_id": "finance-rejected", "type": "app_skill_use", "status": "finished",
            "chat_id": chatId, "message_id": "assistant-finance", "user_id": "other-owner",
            "app_id": "finance", "skill_id": "check_accounts",
            "content": "type: app_skill_use\napp_id: finance\nskill_id: check_accounts\ncounterparty: [COUNTERPARTY_1]",
            "owner_pii_mappings": [["placeholder": "[COUNTERPARTY_1]", "original": "Private Merchant"]],
        ]
        await coordinator.handleEmbedData(fields)
        XCTAssertFalse(persisted)
        XCTAssertTrue(chatStore.embeds(for: chatId).isEmpty)
        XCTAssertFalse(transport.sentTypes.contains("store_embed"))

        fields["user_id"] = "actual-owner"
        fields["content"] = "counterparty: Private Merchant"
        await coordinator.handleEmbedData(fields)
        XCTAssertFalse(persisted, "Unsanitized canonical content must be rejected before owner-sidecar write")
        XCTAssertTrue(chatStore.embeds(for: chatId).isEmpty)
        XCTAssertFalse(transport.sentTypes.contains("store_embed"))
        coordinator.reset()
    }

    // contract-test: direct surface=gui.apple assertions=pii.embed.owner-local-reveal-sync,pii.surface.semantic-parity
    func testFinanceOwnerPIIRowIsCiphertextScopedToOwnerAndRemovedOnChatDelete() async throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("OwnerEmbedPII-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let apiURL = URL(string: "https://fixture.invalid")!
        let ownerStore = try OfflineStore(directory: directory, userId: "owner-a", apiBaseURL: apiURL)
        let key = SymmetricKey(size: .bits256)
        let secret = "Private Merchant Example"
        let mapping = PIIMapping(placeholder: "[COUNTERPARTY_1]", original: secret, type: "COUNTERPARTY")
        let encoded = String(decoding: try JSONEncoder().encode([mapping]), as: UTF8.self)
        let ciphertext = try await CryptoManager.shared.encryptWithMasterKey(encoded, masterKey: key)
        try ownerStore.persistOwnerEmbedPII(PersistedOwnerEmbedPII(
            embedId: "finance-embed", chatId: "finance-chat", ownerUserId: "owner-a",
            encryptedMappings: ciphertext, createdAt: 1_770_000_000
        ))
        let ownerRow = try XCTUnwrap(ownerStore.loadOwnerEmbedPII(chatId: "finance-chat", embedId: "finance-embed"))
        XCTAssertFalse(ownerRow.encryptedMappings.contains(secret))
        let decrypted = try await CryptoManager.shared.decryptContent(
            base64String: ownerRow.encryptedMappings, key: key
        )
        let decoded = try JSONDecoder().decode([PIIMapping].self, from: Data(decrypted.utf8))
        XCTAssertEqual(decoded, [mapping])

        let otherStore = try OfflineStore(directory: directory, userId: "owner-b", apiBaseURL: apiURL)
        XCTAssertNil(try otherStore.loadOwnerEmbedPII(chatId: "finance-chat", embedId: "finance-embed"))
        ownerStore.deleteChat("finance-chat")
        XCTAssertNil(try ownerStore.loadOwnerEmbedPII(chatId: "finance-chat", embedId: "finance-embed"))
    }

    // contract-test: direct surface=gui.apple assertions=chats.persistence.client-encrypted
    func testLiveEmbedLogoutDuringEncryptionDropsAllLatePersistence() async throws {
        let chatId = "chat-live-embed-logout"
        let chatStore = ChatStore()
        chatStore.upsertChat(Chat(
            id: chatId,
            title: "Synthetic logout chat",
            lastMessageAt: nil,
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: nil,
            isArchived: false,
            isPinned: false,
            appId: "ai",
            encryptedTitle: nil,
            encryptedChatKey: nil
        ))
        let transport = ChatEmbedRecordingTransport()
        let gate = EmbedMasterKeySuspensionGate()
        var persistedKeys: [EmbedKeyRecord] = []
        var scope = UUID()
        let coordinator = ChatEmbedStreamCoordinator(
            transport: transport,
            chatStore: chatStore,
            authenticatedOwnerId: { "logout-owner" },
            masterKey: { _ in
                await gate.waitForRelease()
                return SymmetricKey(size: .bits256)
            },
            chatKey: { requestedChatId in
                requestedChatId == chatId ? SymmetricKey(size: .bits256) : nil
            },
            persistEmbedKeys: { persistedKeys.append(contentsOf: $0) },
            accountScopeGeneration: { scope },
            retryDelay: { _ in .seconds(3_600) }
        )
        let handling = Task { @MainActor in
            await coordinator.handleEmbedData([
                "embed_id": "logout-embed",
                "type": "app_skill_use",
                "status": "finished",
                "chat_id": chatId,
                "message_id": "logout-message",
                "content": "type: app_skill_use\napp_id: web\nskill_id: search",
                "app_id": "web",
                "skill_id": "search",
            ])
        }

        await gate.waitUntilEntered()
        scope = UUID()
        coordinator.reset()
        await gate.release()
        await handling.value

        XCTAssertTrue(persistedKeys.isEmpty, "A pre-logout task must not persist key wrappers into the next account scope")
        XCTAssertTrue(chatStore.embeds(for: chatId).isEmpty, "A pre-logout task must not mutate the next account's ChatStore")
        XCTAssertTrue(transport.sentTypes.isEmpty, "A pre-logout task must not write any ciphertext after its scope expires")
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

@MainActor
private final class ChatEmbedRecordingTransport: ChatWebSocketTransport {
    private(set) var sentTypes: [String] = []
    private(set) var sentPayloads: [[String: Any]] = []
    private var failingResponseTypes = Set<String>()
    var receiptTransform: ((String, [String: Any]) -> [String: Any])?
    var beforeReceipt: ((String) async -> Void)?
    var afterSend: ((String) async -> Void)?
    var beforeQueuedSend: (() async -> Void)?

    func failNextResponse(ofType type: String) {
        failingResponseTypes.insert(type)
    }

    func send(_ message: WSOutboundMessage) async throws {
        let decoded = try Self.decode(message)
        sentTypes.append(decoded.type)
        sentPayloads.append(decoded.payload)
        await afterSend?(decoded.type)
    }

    func sendAndWait(
        _ message: WSOutboundMessage,
        responseType: String,
        timeout: Duration,
        matching predicate: @escaping ([String: Any]) -> Bool
    ) async throws -> WebSocketResponse {
        try await sendAndWait(message, responseType: responseType, timeout: timeout,
                              matching: predicate, beforeSend: {})
    }

    func sendAndWait(
        _ message: WSOutboundMessage,
        responseType: String,
        timeout: Duration,
        matching predicate: @escaping ([String: Any]) -> Bool,
        beforeSend: @escaping @MainActor () throws -> Void
    ) async throws -> WebSocketResponse {
        let decoded = try Self.decode(message)
        await beforeQueuedSend?()
        try beforeSend()
        try await send(message)
        await beforeReceipt?(responseType)
        if failingResponseTypes.remove(responseType) != nil {
            throw RecordingTransportError.syntheticFailure
        }
        var responseFields: [String: Any] = [:]
        if let requestId = decoded.payload["request_id"] as? String {
            responseFields["request_id"] = requestId
        }
        if responseType == "store_embed_confirmed" {
            responseFields["embed_id"] = decoded.payload["embed_id"]
            responseFields["canonical_source"] = "head"
            let ciphertext = decoded.payload["encrypted_content"] as? String ?? ""
            responseFields["canonical_digest"] = SHA256.hash(data: Data(ciphertext.utf8)).map { String(format: "%02x", $0) }.joined()
        } else if responseType == "store_embed_keys_confirmed" {
            responseFields["created_count"] = (decoded.payload["keys"] as? [[String: Any]])?.count ?? 0
            responseFields["requested_count"] = (decoded.payload["keys"] as? [[String: Any]])?.count ?? 0
            responseFields["failed_count"] = 0
        }
        responseFields = receiptTransform?(responseType, responseFields) ?? responseFields
        guard predicate(responseFields) else { throw RecordingTransportError.predicateRejected }
        return WebSocketResponse(fields: responseFields, type: responseType)
    }

    func waitForMessage(
        _ type: String,
        timeout: Duration,
        matching predicate: @escaping ([String: Any]) -> Bool
    ) async throws -> WebSocketResponse {
        throw RecordingTransportError.unexpectedWait
    }

    func payload(for type: String) -> [String: Any]? {
        zip(sentTypes, sentPayloads).first { $0.0 == type }?.1
    }

    private static func decode(_ message: WSOutboundMessage) throws -> (type: String, payload: [String: Any]) {
        let encoded = try JSONEncoder().encode(message)
        guard let object = try JSONSerialization.jsonObject(with: encoded) as? [String: Any],
              let type = object["type"] as? String else {
            throw RecordingTransportError.invalidMessage
        }
        return (type, object["payload"] as? [String: Any] ?? [:])
    }

    private enum RecordingTransportError: Error {
        case invalidMessage
        case predicateRejected
        case syntheticFailure
        case unexpectedWait
    }
}

private actor EmbedMasterKeySuspensionGate {
    private var entered = false
    private var entryWaiters: [CheckedContinuation<Void, Never>] = []
    private var releaseWaiters: [CheckedContinuation<Void, Never>] = []

    func markEntered() {
        entered = true
        for waiter in entryWaiters { waiter.resume() }
        entryWaiters.removeAll()
    }
    func waitForRelease() async {
        markEntered()
        await withCheckedContinuation { releaseWaiters.append($0) }
    }

    func waitUntilEntered() async {
        if entered { return }
        await withCheckedContinuation { entryWaiters.append($0) }
    }

    func release() {
        for waiter in releaseWaiters { waiter.resume() }
        releaseWaiters.removeAll()
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
