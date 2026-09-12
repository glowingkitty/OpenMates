// Unit coverage for bounded native chat-window loading helpers.
// These tests use deterministic in-memory chat data and never touch network,
// credentials, encryption keys, or private persisted chat content.
// They guard the Apple chat-opening path against accidentally materializing
// full large-chat histories before first render.

import XCTest
@testable import OpenMates

@MainActor
final class ChatWindowLoadingTests: XCTestCase {
    // contract-test: direct surface=gui.apple assertions=chat-navigation.open.local-first-coherent
    func testDelayedOlderPageCannotChangeAnotherChatsRowsEmbedsOrLoadingState() async throws {
        for usesStore in [false, true] {
            try await assertSupersededOlderPageIsDiscarded(usesStore: usesStore, reloadsSameChat: false)
        }
    }

    // contract-test: direct surface=gui.apple assertions=chat-navigation.open.local-first-coherent
    func testDelayedOlderPageCannotChangeANewerLoadOfTheSameChat() async throws {
        for usesStore in [false, true] {
            try await assertSupersededOlderPageIsDiscarded(usesStore: usesStore, reloadsSameChat: true)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.local-state.precedence
    func testDelayedOlderPageCannotPublishAfterAccountScopeChanges() async throws {
        let gate = OlderMessageDecryptionGate()
        var scope = UUID()
        let model = ChatViewModel(messageDecryptor: { await gate.decrypt($0, chatId: $1) },
                                  accountScopeGeneration: { scope })
        let chat = makeChat(id: "scope-chat", title: "Fixture", updatedAt: "2026-01-01T00:01:00Z", messagesV: 1)
        let rows = makePagingMessages(chatId: chat.id, prefix: "old-scope")
        await model.loadChat(id: chat.id, initialChat: chat, initialMessages: rows)
        let visibleIDs = model.messages.map(\.id)
        let page = try XCTUnwrap(model.loadOlderMessages())
        await gate.waitUntilStarted(0)

        // Changing account scope is independent from a chat-load generation.
        // A completion belonging to the old scope must not clear current flags.
        scope = UUID()
        model.isLoadingOlder = true
        gate.release(0)
        await page.value

        XCTAssertEqual(model.messages.map(\.id), visibleIDs)
        XCTAssertTrue(model.embedRecords.isEmpty)
        XCTAssertTrue(model.hasOlderMessages)
        XCTAssertTrue(model.isLoadingOlder)
    }

    // contract-test: direct surface=gui.apple assertions=chat-navigation.open.local-first-coherent
    func testColdAndWarmSavedAnchorsUseTheSameBoundedWindowAndReachBothEnds() async throws {
        let rows = makeMessages(count: 200)
        let chat = makeChat(id: "unit-large-chat", title: "Fixture",
                            updatedAt: "2026-01-01T00:04:00Z", messagesV: 200,
                            lastVisibleMessageId: "message-096")
        let seed = ChatHistoryWindowPolicy.initialMessages(rows, anchor: chat.lastVisibleMessageId)
        XCTAssertEqual(seed.count, 50)
        XCTAssertEqual(seed.first?.id, "message-088")
        XCTAssertEqual(seed.last?.id, "message-137")

        for usesWarmSeed in [false, true] {
            let store = usesWarmSeed ? seededStore(messageCount: 200) : nil
            let model = ChatViewModel(messageDecryptor: { messages, _ in messages })
            model.configure(wsManager: nil, chatStore: store)
            await model.loadChat(id: chat.id, initialChat: chat, initialMessages: usesWarmSeed ? seed : rows)
            XCTAssertEqual(model.messages.map(\.id), seed.map(\.id))
            XCTAssertTrue(model.hasOlderMessages)
            XCTAssertTrue(model.hasNewerMessages)

            let oldest = try XCTUnwrap(model.loadMessageWindow(.oldest))
            await oldest.value
            XCTAssertEqual(model.messages.map(\.id), rows.prefix(50).map(\.id))
            XCTAssertFalse(model.hasOlderMessages)
            XCTAssertTrue(model.hasNewerMessages)
            let latest = try XCTUnwrap(model.loadMessageWindow(.latest))
            await latest.value
            XCTAssertEqual(model.messages.map(\.id), rows.suffix(50).map(\.id))
            XCTAssertTrue(model.hasOlderMessages)
            XCTAssertFalse(model.hasNewerMessages)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testSlidingWindowsTraverseEveryMessageWithBoundedRowsAndOverlap() throws {
        let rows = makeMessages(count: 1000)
        var current = try XCTUnwrap(ChatHistoryWindowPolicy.range(in: rows, destination: .oldest))
        var visited = Set(rows[current].map(\.id))
        while current.upperBound < rows.count {
            let next = try XCTUnwrap(ChatHistoryWindowPolicy.range(in: rows, destination: .newer, current: current))
            XCTAssertGreaterThan(next.lowerBound, current.lowerBound)
            XCTAssertLessThanOrEqual(next.count, 50)
            XCTAssertGreaterThanOrEqual(Set(rows[current].map(\.id)).intersection(rows[next].map(\.id)).count, 10)
            visited.formUnion(rows[next].map(\.id))
            current = next
        }
        XCTAssertEqual(visited, Set(rows.map(\.id)))
        XCTAssertEqual(rows[current].last?.id, "message-1000")
        while current.lowerBound > 0 {
            let next = try XCTUnwrap(ChatHistoryWindowPolicy.range(in: rows, destination: .older, current: current))
            XCTAssertLessThan(next.lowerBound, current.lowerBound)
            XCTAssertLessThanOrEqual(next.count, 50)
            XCTAssertGreaterThanOrEqual(Set(rows[current].map(\.id)).intersection(rows[next].map(\.id)).count, 10)
            current = next
        }
        XCTAssertEqual(rows[current].first?.id, "message-001")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testDirectSearchAndBackgroundSyncPreserveTheReadingWindow() async throws {
        let rows = makeMessages(count: 200)
        let chat = makeChat(id: "unit-large-chat", title: "Fixture",
                            updatedAt: "2026-01-01T00:04:00Z", messagesV: 200)
        let model = ChatViewModel(messageDecryptor: { messages, _ in messages })
        await model.loadChat(id: chat.id, initialChat: chat, initialMessages: rows)
        let search = try XCTUnwrap(model.loadMessageWindow(.message("message-080")))
        await search.value
        XCTAssertTrue(model.messages.contains { $0.id == "message-080" })
        let readingIDs = model.messages.map(\.id)
        XCTAssertTrue(model.hasNewerMessages)
        await model.applySynced(chat: chat, messages: makeMessages(count: 201))
        XCTAssertEqual(model.messages.map(\.id), readingIDs)
        XCTAssertEqual(model.messages.count, 50)
        XCTAssertNil(model.loadMessageWindow(.message("deleted-message")))
        XCTAssertEqual(model.messages.map(\.id), readingIDs)

        let latest = try XCTUnwrap(model.loadMessageWindow(.latest))
        await latest.value
        XCTAssertEqual(model.messages.last?.id, "message-201")
        await model.applySynced(chat: chat, messages: makeMessages(count: 202))
        XCTAssertEqual(model.messages.last?.id, "message-202")
        XCTAssertEqual(model.messages.count, 50)
        XCTAssertFalse(model.hasNewerMessages)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.streaming.progressive-presentation
    func testStreamingAddsNoExtraRowsToTailOrUnrelatedHistoricalWindow() async throws {
        for browsesOlderWindow in [false, true] {
            let rows = makeMessages(count: 200)
            let chat = makeChat(id: "unit-large-chat", title: "Fixture",
                                updatedAt: "2026-01-01T00:04:00Z", messagesV: 200)
            let model = ChatViewModel(messageDecryptor: { messages, _ in messages })
            await model.loadChat(id: chat.id, initialChat: chat, initialMessages: rows)
            if browsesOlderWindow, let older = model.loadMessageWindow(.oldest) { await older.value }
            let beforeIDs = model.messages.map(\.id)
            model.handleStreamEvent(.taskInitiated(chatId: chat.id, taskId: "fixture-task", userMessageId: "fixture-user"))
            model.handleStreamEvent(.chunk(chatId: chat.id, messageId: "fixture-stream", sequence: 0,
                content: "A live synthetic response", isFinal: false, userMessageId: "fixture-user",
                category: nil, modelName: nil, rejectionReason: nil))
            XCTAssertEqual(model.messages.count, 50)
            if browsesOlderWindow {
                XCTAssertEqual(model.messages.map(\.id), beforeIDs)
                XCTAssertTrue(model.hasNewerMessages)
                XCTAssertEqual(model.newerMessageCount, 151,
                               "A delivered stream must remain reachable while reading older history")
                let latest = try XCTUnwrap(model.loadMessageWindow(.latest))
                await latest.value
            }
            XCTAssertEqual(model.messages.last?.id, "fixture-stream")
            XCTAssertEqual(model.messages.count, 50)
            XCTAssertFalse(model.hasNewerMessages)
            XCTAssertEqual(model.newerMessageCount, 0)
        }
    }

    // contract-test: direct surface=gui.apple assertions=chat-navigation.open.local-first-coherent
    func testDirectLatestCancelsSuspendedOlderWindowWithoutMovingRows() async throws {
        let gate = OlderMessageDecryptionGate()
        let model = ChatViewModel(messageDecryptor: { await gate.decrypt($0, chatId: $1) })
        let chat = makeChat(id: "paging-direct", title: "Fixture",
                            updatedAt: "2026-01-01T00:01:00Z", messagesV: 60)
        let rows = makePagingMessages(chatId: chat.id, prefix: "direct")
        await model.loadChat(id: chat.id, initialChat: chat, initialMessages: rows)
        let page = try XCTUnwrap(model.loadOlderMessages())
        await gate.waitUntilStarted(0)
        XCTAssertNil(model.loadMessageWindow(.latest), "Already at the tail; cancel the old request without rebuilding")
        gate.release(0)
        await page.value
        XCTAssertEqual(model.messages.map(\.id), rows.suffix(50).map(\.id))
        XCTAssertFalse(model.isLoadingOlder)
        XCTAssertFalse(model.hasNewerMessages)
        XCTAssertNil(model.embedRecords["direct-embed"])
    }

    // contract-test: direct surface=gui.apple assertions=chat-navigation.open.local-first-coherent,chats.streaming.progressive-presentation
    func testLiveChunkDuringInitialDecryptCompletesLoadingAndPreservesChosenWindow() async throws {
        for savedAnchor in [nil, "message-096"] as [String?] {
            let gate = SuspendedHistoryLoad()
            let model = ChatViewModel(messageDecryptor: { rows, _ in await gate.decrypt(rows) })
            let chat = makeChat(id: "unit-large-chat", title: "Fixture",
                updatedAt: "2026-01-01T00:04:00Z", messagesV: 200, lastVisibleMessageId: savedAnchor)
            let rows = makeMessages(count: 200)
            gate.arm()
            let load = Task { await model.loadChat(id: chat.id, initialChat: chat, initialMessages: rows) }
            await gate.waitUntilStarted()
            model.handleStreamEvent(.taskInitiated(chatId: chat.id, taskId: "during-load", userMessageId: "fixture-user"))
            model.handleStreamEvent(.chunk(chatId: chat.id, messageId: "during-load-response", sequence: 0,
                content: "A response received during decryption", isFinal: false,
                userMessageId: "fixture-user", category: nil, modelName: nil, rejectionReason: nil))
            gate.release()
            await load.value
            XCTAssertFalse(model.isLoading, "A live source update must not leave initial loading stuck")
            XCTAssertEqual(model.messages.count, 50)
            if savedAnchor == nil {
                XCTAssertEqual(model.messages.last?.id, "during-load-response")
                XCTAssertFalse(model.hasNewerMessages)
            } else {
                XCTAssertEqual(model.messages.first?.id, "message-088")
                XCTAssertEqual(model.messages.last?.id, "message-137")
                XCTAssertFalse(model.messages.contains { $0.id == "during-load-response" })
                XCTAssertTrue(model.hasNewerMessages)
            }
        }
    }

    // contract-test: direct surface=gui.apple assertions=chat-navigation.open.local-first-coherent
    func testExplicitPageWinsAgainstAnOlderSuspendedSyncSelection() async throws {
        let gate = SuspendedHistoryLoad()
        let model = ChatViewModel(messageDecryptor: { rows, _ in await gate.decrypt(rows) })
        let chat = makeChat(id: "unit-large-chat", title: "Fixture",
            updatedAt: "2026-01-01T00:04:00Z", messagesV: 200)
        await model.loadChat(id: chat.id, initialChat: chat, initialMessages: makeMessages(count: 200))
        gate.arm()
        let sync = Task { await model.applySynced(chat: chat, messages: makeMessages(count: 201)) }
        await gate.waitUntilStarted()
        let page = try XCTUnwrap(model.loadMessageWindow(.oldest))
        await page.value
        gate.release()
        await sync.value
        XCTAssertEqual(model.messages.first?.id, "message-001")
        XCTAssertEqual(model.messages.last?.id, "message-050")
        XCTAssertFalse(model.isLoading)
        XCTAssertFalse(model.isLoadingOlder)
        XCTAssertTrue(model.hasNewerMessages)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testOpeningFullscreenCancelsPageBeforeItsEmbedGraphCanBePruned() async throws {
        let gate = OlderMessageDecryptionGate()
        let model = ChatViewModel(messageDecryptor: { await gate.decrypt($0, chatId: $1) })
        let chat = makeChat(id: "paging-overlay", title: "Fixture",
            updatedAt: "2026-01-01T00:01:00Z", messagesV: 60)
        let rows = makePagingMessages(chatId: chat.id, prefix: "overlay")
        await model.loadChat(id: chat.id, initialChat: chat, initialMessages: rows)
        let parent = EmbedRecord(id: "visible-parent", type: "app-skill-use", status: .finished,
            data: .raw([:]), parentEmbedId: nil, appId: "web", skillId: "search",
            embedIds: "visible-child", createdAt: nil)
        let child = EmbedRecord(id: "visible-child", type: "web-website", status: .finished,
            data: .raw(["title": AnyCodable("Visible result")]), parentEmbedId: parent.id,
            appId: "web", skillId: nil, embedIds: nil, createdAt: nil)
        model.embedRecords = [parent.id: parent, child.id: child]
        let currentIDs = model.messages.map(\.id)
        let page = try XCTUnwrap(model.loadOlderMessages())
        await gate.waitUntilStarted(0)
        // This is the same cancellation invoked by ChatView.openEmbedFullscreen.
        model.cancelHistoryWindowNavigation()
        gate.release(0)
        await page.value
        XCTAssertEqual(model.messages.map(\.id), currentIDs)
        XCTAssertEqual(Set(model.embedRecords.keys), [parent.id, child.id])
        XCTAssertFalse(model.isLoadingOlder)
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.open.local-first-coherent
    func testInitialWindowReturnsLatestBoundedMessages() {
        let store = seededStore(messageCount: 120)

        let window = store.initialMessageWindow(for: "unit-large-chat")

        XCTAssertEqual(window.count, ChatStore.boundedWindowSize)
        XCTAssertEqual(window.first?.id, "message-071")
        XCTAssertEqual(window.last?.id, "message-120")
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.open.local-first-coherent
    func testOlderWindowReturnsOneBoundedPageBeforeBoundary() {
        let store = seededStore(messageCount: 120)

        let older = store.olderMessageWindow(for: "unit-large-chat", before: "message-071")

        XCTAssertEqual(older.count, ChatStore.boundedWindowSize)
        XCTAssertEqual(older.first?.id, "message-021")
        XCTAssertEqual(older.last?.id, "message-070")
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.open.local-first-coherent
    func testHasOlderMessagesStopsAtOldestBoundary() {
        let store = seededStore(messageCount: 120)

        XCTAssertTrue(store.hasOlderMessages(for: "unit-large-chat", before: "message-021"))
        XCTAssertFalse(store.hasOlderMessages(for: "unit-large-chat", before: "message-001"))
        XCTAssertFalse(store.hasOlderMessages(for: "unit-large-chat", before: nil))
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.open.local-first-coherent
    func testOpeningFallbackFetchesWhenSyncedChatHasMessagesButEmptyInitialWindow() {
        XCTAssertTrue(
            ChatOpeningFallbackPolicy.shouldFetchMissingSyncedMessages(
                messagesV: 2,
                lastMessageAt: nil
            )
        )
        XCTAssertTrue(
            ChatOpeningFallbackPolicy.shouldFetchMissingSyncedMessages(
                messagesV: nil,
                lastMessageAt: "2026-01-01T00:00:00Z"
            )
        )
        XCTAssertFalse(
            ChatOpeningFallbackPolicy.shouldFetchMissingSyncedMessages(
                messagesV: 0,
                lastMessageAt: nil
            )
        )
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.open.local-first-coherent
    func testBatchUpsertMergesChatsWithoutRepeatedLookupSideEffects() {
        let store = ChatStore()
        store.performWithoutPersistence {
            store.upsertChats([
                makeChat(id: "chat-a", title: "A", updatedAt: "2026-01-01T00:00:00Z", messagesV: 1),
                makeChat(id: "chat-b", title: "B", updatedAt: "2026-01-02T00:00:00Z", messagesV: 1)
            ])
            store.upsertChats([
                makeChat(id: "chat-a", title: "A updated", updatedAt: "2026-01-03T00:00:00Z", messagesV: 2),
                makeChat(id: "chat-c", title: "C", updatedAt: "2026-01-04T00:00:00Z", messagesV: 1)
            ], serverSortOrder: ["chat-c", "chat-a", "chat-b"])
        }

        XCTAssertEqual(store.chats.map(\.id), ["chat-c", "chat-a", "chat-b"])
        XCTAssertEqual(store.chat(for: "chat-a")?.title, "A updated")
        XCTAssertEqual(store.chat(for: "chat-a")?.messagesV, 2)
        XCTAssertEqual(store.chats.count, 3)
    }

    private func assertSupersededOlderPageIsDiscarded(usesStore: Bool, reloadsSameChat: Bool) async throws {
        let gate = OlderMessageDecryptionGate()
        let model = ChatViewModel(messageDecryptor: { await gate.decrypt($0, chatId: $1) })
        let store = usesStore ? ChatStore() : nil
        model.configure(wsManager: nil, chatStore: store)
        let firstChat = makeChat(id: "paging-a", title: "A", updatedAt: "2026-01-01T00:01:00Z", messagesV: 1)
        let nextChat = makeChat(id: reloadsSameChat ? firstChat.id : "paging-b", title: "B",
                                updatedAt: "2026-01-01T00:01:00Z", messagesV: 2)
        let firstRows = makePagingMessages(chatId: firstChat.id, prefix: "first-load")
        let nextRows = makePagingMessages(chatId: nextChat.id, prefix: "next-load")
        store?.performWithoutPersistence { store?.setMessages(for: firstChat.id, messages: firstRows) }
        await model.loadChat(id: firstChat.id, initialChat: firstChat, initialMessages: firstRows)
        let firstPage = try XCTUnwrap(model.loadOlderMessages())
        await gate.waitUntilStarted(0)
        XCTAssertTrue(model.isLoadingOlder)

        store?.performWithoutPersistence { store?.setMessages(for: nextChat.id, messages: nextRows) }
        await model.loadChat(id: nextChat.id, initialChat: nextChat, initialMessages: nextRows)
        XCTAssertFalse(model.isLoadingOlder, "A new load must release the previous pagination lock")
        let expectedVisibleIDs = Array(nextRows.suffix(50)).map(\.id)
        XCTAssertEqual(model.messages.map(\.id), expectedVisibleIDs)
        let nextPage = try XCTUnwrap(model.loadOlderMessages())
        await gate.waitUntilStarted(1)

        // The cancelled decryptor still returns its original page, reproducing
        // a non-cancellable cryptographic operation completing after navigation.
        gate.release(0)
        await firstPage.value
        XCTAssertEqual(model.chat?.id, nextChat.id)
        XCTAssertEqual(model.messages.map(\.id), expectedVisibleIDs)
        XCTAssertNil(model.embedRecords["first-load-embed"])
        XCTAssertTrue(model.embedRecords.isEmpty)
        XCTAssertTrue(model.hasOlderMessages)
        XCTAssertTrue(model.isLoadingOlder, "The stale page must not complete the next page's loading state")

        gate.release(1)
        await nextPage.value
        XCTAssertEqual(model.messages.map(\.id), nextRows.prefix(50).map(\.id))
        XCTAssertEqual(model.messages.count, 50)
        XCTAssertEqual(Set(model.embedRecords.keys), ["next-load-embed"])
        XCTAssertFalse(model.hasOlderMessages)
        XCTAssertTrue(model.hasNewerMessages)
        XCTAssertFalse(model.isLoadingOlder)
    }

    private func makePagingMessages(chatId: String, prefix: String) -> [Message] {
        (1...60).map { index in
            let content = index == 1
                ? "```json\n{\"type\":\"audio-recording\",\"embed_id\":\"\(prefix)-embed\"}\n```"
                : "Synthetic message \(index)"
            return Message(id: "\(prefix)-\(String(format: "%03d", index))", chatId: chatId, role: .user,
                           content: content, encryptedContent: nil,
                           createdAt: String(format: "2026-01-01T00:%02d:%02dZ", index / 60, index % 60),
                           updatedAt: nil, appId: nil, isStreaming: false, embedRefs: nil)
        }
    }

    private func seededStore(messageCount: Int) -> ChatStore {
        let store = ChatStore()
        store.performWithoutPersistence {
            store.setMessages(for: "unit-large-chat", messages: makeMessages(count: messageCount))
        }
        return store
    }

    private func makeMessages(count: Int) -> [Message] {
        (1...count).map { index in
            let id = String(format: "message-%03d", index)
            return Message(
                id: id,
                chatId: "unit-large-chat",
                role: index.isMultiple(of: 2) ? .assistant : .user,
                content: "Synthetic message \(index)",
                encryptedContent: nil,
                createdAt: String(format: "2026-01-01T00:%02d:%02dZ", index / 60, index % 60),
                updatedAt: nil,
                appId: nil,
                isStreaming: false,
                embedRefs: nil
            )
        }
    }

    private func makeChat(id: String, title: String, updatedAt: String, messagesV: Int,
                          lastVisibleMessageId: String? = nil) -> Chat {
        Chat(
            id: id,
            title: title,
            lastMessageAt: updatedAt,
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: updatedAt,
            isArchived: false,
            isPinned: false,
            appId: "ai",
            encryptedTitle: nil,
            encryptedChatKey: nil,
            messagesV: messagesV,
            titleV: messagesV,
            lastVisibleMessageId: lastVisibleMessageId
        )
    }
}

/// Holds only older ten-message pages, leaving initial fifty-message loads
/// immediate. Continuations make the interleaving deterministic without sleeps.
@MainActor
private final class OlderMessageDecryptionGate {
    private var nextPage = 0
    private var pending: [Int: ([Message], CheckedContinuation<[Message], Never>)] = [:]
    private var startWaiters: [Int: CheckedContinuation<Void, Never>] = [:]

    func decrypt(_ messages: [Message], chatId: String) async -> [Message] {
        guard messages.count == 10 else { return messages }
        let page = nextPage
        nextPage += 1
        return await withCheckedContinuation { continuation in
            pending[page] = (messages, continuation)
            startWaiters.removeValue(forKey: page)?.resume()
        }
    }

    func waitUntilStarted(_ page: Int) async {
        guard pending[page] == nil else { return }
        await withCheckedContinuation { startWaiters[page] = $0 }
    }

    func release(_ page: Int) {
        guard let (messages, continuation) = pending.removeValue(forKey: page) else {
            XCTFail("Expected a suspended older-message page")
            return
        }
        continuation.resume(returning: messages)
    }
}

/// Pauses one chosen history load without sleeping or using account/network data.
@MainActor
private final class SuspendedHistoryLoad {
    private var armed = false
    private var pending: ([Message], CheckedContinuation<[Message], Never>)?
    private var started: CheckedContinuation<Void, Never>?

    func arm() { armed = true }

    func decrypt(_ messages: [Message]) async -> [Message] {
        guard armed else { return messages }
        armed = false
        return await withCheckedContinuation { continuation in
            pending = (messages, continuation)
            started?.resume()
            started = nil
        }
    }

    func waitUntilStarted() async {
        guard pending == nil else { return }
        await withCheckedContinuation { started = $0 }
    }

    func release() {
        guard let (messages, continuation) = pending else {
            XCTFail("Expected a suspended history load")
            return
        }
        pending = nil
        continuation.resume(returning: messages)
    }
}
