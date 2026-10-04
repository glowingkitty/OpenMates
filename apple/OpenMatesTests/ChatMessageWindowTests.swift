// Synthetic published-v1 window contracts. No inference or account mutations.
import XCTest
import SwiftData
import Foundation
@testable import OpenMates

@MainActor
final class ChatMessageWindowTests: XCTestCase {
    // contract-test: direct surface=gui.apple assertions=storage.surface.semantic-parity,storage.privacy.ciphertext-boundary
    func testAPIEndpointPreservesFullCiphertextAndEncodesPairedCursorWithoutNetwork() async throws {
        let query = ChatMessageWindowQuery(direction: .before, before: .init(createdAt: 1100, messageId: "m100"),
                                           respectCompressionBoundary: false)
        var payload = Self.payload(90..<100, query: query, older: true, newer: true)
        var rows = try XCTUnwrap(payload["messages"] as? [[String: Any]])
        let fullCiphertext = String(repeating: "synthetic-ciphertext", count: 16_000)
        rows[0]["encrypted_content"] = fullCiphertext; payload["messages"] = rows
        WindowFixtureURLProtocol.configure(try JSONSerialization.data(withJSONObject: payload))
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [WindowFixtureURLProtocol.self]
        configuration.httpCookieStorage = HTTPCookieStorage.sharedCookieStorage(forGroupContainerIdentifier: "window-fixture-\(UUID().uuidString)")
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel() }
        let api = APIClient(session: session, cookieStorage: try XCTUnwrap(configuration.httpCookieStorage))
        let page = try await api.chatMessageWindow(chatId: "synthetic-window", teamId: "synthetic-team", query: query,
            serverProfile: .custom(domain: "message-window-fixture.invalid"))
        XCTAssertEqual(page.messages.first?.encryptedContent, fullCiphertext)
        let request = try XCTUnwrap(WindowFixtureURLProtocol.lastRequest())
        XCTAssertEqual(request.httpMethod, "GET")
        XCTAssertEqual(request.url?.path, "/v1/chats/synthetic-window/messages/window")
        let items = try XCTUnwrap(URLComponents(url: try XCTUnwrap(request.url), resolvingAgainstBaseURL: false)?.queryItems)
        let byName = Dictionary(items.map { ($0.name, $0.value ?? "") }, uniquingKeysWith: { _, last in last })
        XCTAssertEqual(byName["before_timestamp"], "1100")
        XCTAssertEqual(byName["before_message_id"], "m100")
        XCTAssertEqual(byName["team_id"], "synthetic-team")
    }

    // contract-test: direct surface=gui.apple assertions=storage.surface.semantic-parity,storage.privacy.ciphertext-boundary
    func testPublishedWindowDecodesCompleteCiphertextAndCompoundCursorWithCompressionMetadata() throws {
        let query = ChatMessageWindowQuery(direction: .before, before: .init(createdAt: 1100, messageId: "m100"),
                                           respectCompressionBoundary: false)
        var payload = Self.payload(90..<100, query: query, older: true, newer: true)
        payload["compression_boundary_timestamp"] = 1095
        payload["compression_checkpoints"] = [["id": "checkpoint", "chat_id": "synthetic-window",
            "encrypted_summary": "complete-encrypted-summary", "compressed_up_to_timestamp": 1095,
            "compressed_message_count": 95, "summary_token_estimate": 10, "key_version": 1]]
        let page = try ChatMessageWindowPage.decode(JSONSerialization.data(withJSONObject: payload), chatId: "synthetic-window", query: query)
        XCTAssertEqual(page.messages.count, 10)
        XCTAssertEqual(page.messages.last?.encryptedContent, "complete-ciphertext-99")
        XCTAssertEqual(page.startCursor, .init(createdAt: 1090, messageId: "m090"))
        XCTAssertEqual(page.compressionCheckpoints.first?.encryptedSummary, "complete-encrypted-summary")
        XCTAssertEqual(page.compressionBoundaryTimestamp, 1095)
        let path = try query.path(chatId: "synthetic-window", teamId: "synthetic-team")
        let items = try XCTUnwrap(URLComponents(string: path)?.queryItems)
        let byName = Dictionary(items.map { ($0.name, $0.value ?? "") }, uniquingKeysWith: { _, last in last })
        XCTAssertEqual(byName["before_timestamp"], "1100")
        XCTAssertEqual(byName["before_message_id"], "m100")
        XCTAssertEqual(byName["team_id"], "synthetic-team")
        XCTAssertEqual(byName["respect_compression_boundary"], "false")
    }

    // contract-test: direct surface=gui.apple assertions=storage.privacy.ciphertext-boundary,storage.surface.semantic-parity
    func testMalformedForeignPlaintextDuplicateAndOversizedPagesFailClosed() throws {
        let query = ChatMessageWindowQuery(limit: 2, respectCompressionBoundary: false)
        let original = Self.payload(0..<2, query: query, older: false, newer: false)
        for mutation in 0..<7 {
            var payload = original
            var rows = try XCTUnwrap(payload["messages"] as? [[String: Any]])
            switch mutation {
            case 0: payload["chat_id"] = "another-chat"
            case 1: rows[0]["chat_id"] = "another-chat"
            case 2: rows[0]["content"] = "Unexpected plaintext"
            case 3: rows[0].removeValue(forKey: "encrypted_content")
            case 4: rows[1]["client_message_id"] = rows[0]["client_message_id"]
            case 5: rows.append(rows[0])
            default: payload["start_cursor"] = ["created_at": 1000, "message_id": "wrong-id"]
            }
            payload["messages"] = rows
            XCTAssertThrowsError(try ChatMessageWindowPage.decode(JSONSerialization.data(withJSONObject: payload),
                chatId: "synthetic-window", query: query), "Mutation \(mutation) must not be accepted")
        }
        XCTAssertThrowsError(try ChatMessageWindowQuery(direction: .before).path(chatId: "synthetic-window", teamId: nil))
    }

    // contract-test: direct surface=gui.apple assertions=chats.message.identity-idempotent,chats.persistence.client-encrypted
    func testPartialMergeDeduplicatesStableIDsAndPreservesAbsentRowsAndActiveStream() throws {
        let query = ChatMessageWindowQuery(respectCompressionBoundary: false)
        let page = try Self.page(0..<3, query: query, older: false, newer: false)
        let pending = Message(id: "pending-user", chatId: page.chatId, role: .user, content: "Pending local work",
            encryptedContent: nil, createdAt: "2026-01-01T00:00:00Z", updatedAt: nil, appId: nil, isStreaming: false, embedRefs: nil)
        let streaming = Message(id: "m001", chatId: page.chatId, role: .assistant, content: "Current stream",
            encryptedContent: nil, createdAt: page.messages[1].createdAt, updatedAt: nil, appId: nil, isStreaming: true, embedRefs: nil)
        let merged = ChatMessageWindowPage.merge(page.messages, preserving: [pending, streaming, page.messages[0]])
        XCTAssertEqual(merged.count, 4)
        XCTAssertEqual(merged.first { $0.id == "m001" }?.content, "Current stream")
        XCTAssertNotNil(merged.first { $0.id == "pending-user" })
        XCTAssertEqual(Set(merged.map(\.id)).count, merged.count)
        let pendingEncrypted = Message(id: "m000", chatId: page.chatId, role: .user, content: "Queued local user body",
            encryptedContent: "retained-original-encryption", createdAt: page.messages[0].createdAt,
            updatedAt: nil, appId: nil, isStreaming: false, embedRefs: nil)
        let protected = ChatMessageWindowPage.merge(page.messages, preserving: [pendingEncrypted], pendingIds: ["m000"])
        XCTAssertEqual(protected.first { $0.id == "m000" }?.encryptedContent, "retained-original-encryption")
    }

    // contract-test: direct surface=gui.apple assertions=storage.surface.semantic-parity,apple-offline.snapshot-integrity
    func testMissingForegroundHistoryUsesBoundedPagesAndNeverPublishesPartialSyncSnapshot() async throws {
        let offline = try makeOffline()
        let store = ChatStore()
        let chat = makeChat()
        store.performWithoutPersistence { store.upsertChat(chat) }
        var queries: [ChatMessageWindowQuery] = []
        var fullBatches = 0
        let model = ChatViewModel(messageDecryptor: { rows, _ in rows }, accountScopeGeneration: { offline.scopeGeneration },
            contentBatchFetcher: { _ in fullBatches += 1; throw CancellationError() }, offlineStore: offline,
            messageWindowFetcher: { id, team, query in
                XCTAssertEqual(id, chat.id); XCTAssertNil(team)
                queries.append(query)
                return try Self.page(query.direction == .latest ? 100..<150 : 50..<100,
                    query: query, older: true, newer: query.direction != .latest)
            })
        model.configure(wsManager: nil, chatStore: store)
        await model.loadChat(id: chat.id)
        XCTAssertNil(model.error)
        XCTAssertEqual(model.messages.count, 50)
        XCTAssertTrue(model.hasOlderMessages)
        try await XCTUnwrap(model.loadOlderMessages()).value
        XCTAssertEqual(queries.count, 2)
        XCTAssertEqual(queries[1].before, .init(createdAt: 1100, messageId: "m100"))
        XCTAssertEqual(queries[1].direction, .before)
        XCTAssertTrue(queries.allSatisfy { $0.limit <= 50 && !$0.respectCompressionBoundary })
        XCTAssertEqual(model.messages.first?.id, "m060")
        XCTAssertEqual(Set(model.messages.map(\.id)).count, 50)
        XCTAssertTrue(store.messages(for: chat.id).isEmpty)
        XCTAssertTrue(offline.loadLatestMessageWindow(chatId: chat.id).isEmpty)
        XCTAssertFalse(offline.hasCompleteOfflineSnapshot(for: chat))
        XCTAssertEqual(fullBatches, 0)
    }

    // contract-test: direct surface=gui.apple assertions=storage.surface.semantic-parity
    func testFailedOlderPageKeepsViewportAndCanRetryWithoutFullTranscriptFallback() async throws {
        let offline = try makeOffline(), store = ChatStore(), chat = makeChat()
        store.performWithoutPersistence { store.upsertChat(chat) }
        var failOlder = true
        let model = ChatViewModel(messageDecryptor: { rows, _ in rows }, accountScopeGeneration: { offline.scopeGeneration },
            offlineStore: offline, messageWindowFetcher: { _, _, query in
                if query.direction == .before && failOlder { throw URLError(.timedOut) }
                return try Self.page(query.direction == .latest ? 100..<150 : 50..<100,
                    query: query, older: true, newer: query.direction != .latest)
            })
        model.configure(wsManager: nil, chatStore: store)
        await model.loadChat(id: chat.id)
        let original = model.messages.map(\.id)
        try await XCTUnwrap(model.loadOlderMessages()).value
        XCTAssertNotNil(model.error)
        XCTAssertEqual(model.messages.map(\.id), original)
        XCTAssertTrue(model.hasOlderMessages)
        XCTAssertFalse(model.isLoadingOlder)
        failOlder = false
        try await XCTUnwrap(model.loadOlderMessages()).value
        XCTAssertNil(model.error)
        XCTAssertEqual(model.messages.first?.id, "m060")
    }

    // contract-test: direct surface=gui.apple assertions=auth.session.isolation,storage.surface.semantic-parity
    func testScopeChangeAndDeletionDropLateRemotePage() async throws {
        for deletion in [false, true] {
            let offline = try makeOffline(), store = ChatStore(), chat = makeChat()
            store.performWithoutPersistence { store.upsertChat(chat) }
            var scope = offline.scopeGeneration
            let gate = MessageWindowReadGate()
            let model = ChatViewModel(messageDecryptor: { rows, _ in rows }, accountScopeGeneration: { scope },
                offlineStore: offline, messageWindowFetcher: { _, _, query in
                    await gate.wait()
                    return try Self.page(100..<150, query: query, older: true, newer: false)
                })
            model.configure(wsManager: nil, chatStore: store)
            let opening = Task { @MainActor in await model.loadChat(id: chat.id) }
            await gate.waitUntilEntered()
            if deletion { model.consumeForegroundMessageDeletion(chatId: chat.id, messageId: "m100") }
            else { scope = UUID() }
            gate.release()
            await opening.value
            XCTAssertTrue(model.messages.isEmpty)
            XCTAssertTrue(store.messages(for: chat.id).isEmpty)
        }
    }

    // contract-test: direct surface=gui.apple assertions=storage.surface.semantic-parity,message-input.embeds.gated-send
    func testFailedLatestReadStopsSendAndRemainsExplicitlyRetryable() async throws {
        let offline = try makeOffline(), store = ChatStore()
        let chat = Chat(id: "synthetic-window", title: "Synthetic window", lastMessageAt: nil,
            createdAt: "2026-01-01T00:00:00Z", updatedAt: nil, isArchived: false, isPinned: false,
            appId: "ai", encryptedTitle: nil, encryptedChatKey: nil, messagesV: 150, lastVisibleMessageId: "m025")
        store.performWithoutPersistence { store.upsertChat(chat) }
        var latestReads = 0, failLatest = true
        let model = ChatViewModel(messageDecryptor: { rows, _ in rows }, accountScopeGeneration: { offline.scopeGeneration },
            offlineStore: offline, messageWindowFetcher: { _, _, query in
                if query.direction == .around { return try Self.page(0..<50, query: query, older: false, newer: true) }
                latestReads += 1
                if failLatest && latestReads == 1 { throw URLError(.timedOut) }
                // A broken retry loop terminates, then fails the assertions,
                // instead of hanging the unit runner indefinitely.
                return try Self.page(100..<150, query: query, older: true, newer: false)
            })
        model.configure(wsManager: nil, chatStore: store)
        await model.loadChat(id: chat.id)
        XCTAssertTrue(model.hasNewerMessages)
        let previous = model.messages.map(\.id)
        await model.sendMessage("Synthetic unsent body")
        XCTAssertEqual(latestReads, 1, "Failed history must not cause an automatic read/send loop")
        XCTAssertNotNil(model.error)
        XCTAssertTrue(model.hasNewerMessages)
        XCTAssertEqual(model.messages.map(\.id), previous)
        XCTAssertTrue(offline.loadPendingActions().isEmpty, "Failed history must not enqueue a turn")
        failLatest = false
        try await XCTUnwrap(model.loadMessageWindow(.latest)).value
        XCTAssertEqual(latestReads, 2)
        XCTAssertNil(model.error)
        XCTAssertFalse(model.hasNewerMessages)
        XCTAssertEqual(model.messages.first?.id, "m100")
    }

    // contract-test: direct surface=gui.apple assertions=storage.surface.semantic-parity
    func testEmptyBoundaryPageAndSameTimestampCompoundCursorRemainValid() throws {
        let query = ChatMessageWindowQuery(direction: .before, limit: 2,
            before: .init(createdAt: 1000, messageId: "m002"), respectCompressionBoundary: false)
        XCTAssertNoThrow(try Self.page(0..<0, query: query, older: false, newer: true))
        var payload = Self.payload(0..<2, query: query, older: false, newer: true)
        var rows = try XCTUnwrap(payload["messages"] as? [[String: Any]])
        rows[1]["created_at"] = 1000; payload["messages"] = rows
        payload["end_cursor"] = ["created_at": 1000, "message_id": "m001"]
        let page = try ChatMessageWindowPage.decode(JSONSerialization.data(withJSONObject: payload), chatId: "synthetic-window", query: query)
        XCTAssertEqual(page.messages.map(\.id), ["m000", "m001"])
        let merged = ChatMessageWindowPage.merge(Array(page.messages.reversed()), preserving: [])
        XCTAssertEqual(merged.map(\.id), ["m000", "m001"])
    }

    private func makeChat() -> Chat {
        Chat(id: "synthetic-window", title: "Synthetic window", lastMessageAt: nil,
            createdAt: "2026-01-01T00:00:00Z", updatedAt: nil, isArchived: false, isPinned: false,
            appId: "ai", encryptedTitle: nil, encryptedChatKey: nil, messagesV: 150)
    }
    private func makeOffline() throws -> OfflineStore {
        let schema = Schema([PersistedChat.self, PersistedMessage.self, PersistedEmbed.self,
            PersistedEmbedKey.self, PersistedCodeRunOutput.self, PendingOfflineAction.self])
        return OfflineStore(modelContainer: try ModelContainer(for: schema,
            configurations: [ModelConfiguration("RemoteWindow-\(UUID().uuidString)", schema: schema, isStoredInMemoryOnly: true)]))
    }
    private static func page(_ range: Range<Int>, query: ChatMessageWindowQuery, older: Bool, newer: Bool) throws -> ChatMessageWindowPage {
        try ChatMessageWindowPage.decode(JSONSerialization.data(withJSONObject: payload(range, query: query, older: older, newer: newer)),
            chatId: "synthetic-window", query: query)
    }
    private static func payload(_ range: Range<Int>, query: ChatMessageWindowQuery, older: Bool, newer: Bool) -> [String: Any] {
        let rows: [[String: Any]] = range.map { index in
            ["id": "database-\(index)", "client_message_id": String(format: "m%03d", index),
             "chat_id": "synthetic-window", "role": "assistant", "created_at": 1000 + index,
             "encrypted_content": "complete-ciphertext-\(index)"]
        }
        func cursor(_ index: Int) -> [String: Any] { ["created_at": 1000 + index, "message_id": String(format: "m%03d", index)] }
        return ["chat_id": "synthetic-window", "messages": rows, "has_more_before": older, "has_more_after": newer,
                "start_cursor": range.isEmpty ? NSNull() as Any : cursor(range.lowerBound) as Any,
                "end_cursor": range.isEmpty ? NSNull() as Any : cursor(range.upperBound - 1) as Any,
                "anchor_found": true, "server_message_count": 150, "messages_v": 150,
                "compression_boundary_timestamp": NSNull(), "compression_checkpoints": [],
                "respect_compression_boundary": query.respectCompressionBoundary]
    }
}

private final class WindowFixtureURLProtocol: URLProtocol, @unchecked Sendable {
    private static let lock = NSLock()
    private nonisolated(unsafe) static var data = Data()
    private nonisolated(unsafe) static var recordedRequest: URLRequest?
    static func configure(_ value: Data) { lock.lock(); defer { lock.unlock() }; data = value; recordedRequest = nil }
    static func lastRequest() -> URLRequest? { lock.lock(); defer { lock.unlock() }; return recordedRequest }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        Self.lock.lock(); let body = Self.data; Self.recordedRequest = request; Self.lock.unlock()
        guard let url = request.url,
              let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: nil, headerFields: ["Content-Type": "application/json"]) else {
            client?.urlProtocol(self, didFailWithError: URLError(.badURL)); return
        }
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: body)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

@MainActor
private final class MessageWindowReadGate {
    private var entered = false
    private var entry: CheckedContinuation<Void, Never>?
    private var releaseContinuation: CheckedContinuation<Void, Never>?
    func wait() async {
        entered = true; entry?.resume(); entry = nil
        await withCheckedContinuation { releaseContinuation = $0 }
    }
    func waitUntilEntered() async {
        if !entered { await withCheckedContinuation { entry = $0 } }
    }
    func release() { releaseContinuation?.resume(); releaseContinuation = nil }
}
