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
        let fullCiphertext = String(repeating: "synthetic-ciphertext", count: 8_000)
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
            "compressed_message_count": 95, "summary_token_estimate": 10, "key_version": 1,
            "compressed_up_to_message_id": "m095", "covered_message_ids": ["m090", "m091"]]]
        let page = try ChatMessageWindowPage.decode(JSONSerialization.data(withJSONObject: payload), chatId: "synthetic-window", query: query)
        XCTAssertEqual(page.messages.count, 10)
        XCTAssertEqual(page.messages.last?.encryptedContent, "complete-ciphertext-99")
        XCTAssertEqual(page.startCursor, .init(createdAt: 1090, messageId: "m090"))
        XCTAssertEqual(page.compressionCheckpoints.first?.encryptedSummary, "complete-encrypted-summary")
        XCTAssertEqual(page.compressionBoundaryTimestamp, 1095)
        XCTAssertEqual(page.compressionCheckpoints.first?.compressedUpToMessageId, "m095")
        XCTAssertEqual(page.compressionCheckpoints.first?.coveredMessageIds, ["m090", "m091"])
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
        let model = ChatViewModel(messageDecryptor: { rows, _ in rows.map { row in var value = row; value.content = "Synthetic decrypted body"; return value } }, accountScopeGeneration: { offline.scopeGeneration },
            contentBatchFetcher: { _ in fullBatches += 1; throw CancellationError() }, offlineStore: offline,
            messageWindowFetcher: { id, team, query in
                XCTAssertEqual(id, chat.id); XCTAssertNil(team)
                queries.append(query)
                return try Self.page(query.direction == .latest ? 130..<150 : 110..<130,
                    query: query, older: true, newer: query.direction != .latest)
            })
        model.configure(wsManager: nil, chatStore: store)
        await model.loadChat(id: chat.id)
        XCTAssertNil(model.error)
        XCTAssertEqual(model.messages.count, 20)
        XCTAssertTrue(model.hasOlderMessages)
        try await XCTUnwrap(model.loadOlderMessages()).value
        XCTAssertEqual(queries.count, 2)
        XCTAssertEqual(queries[1].before, .init(createdAt: 1130, messageId: "m130"))
        XCTAssertEqual(queries[1].direction, .before)
        XCTAssertTrue(queries.allSatisfy { $0.limit <= 20 && !$0.respectCompressionBoundary })
        XCTAssertEqual(model.messages.first?.id, "m110")
        XCTAssertEqual(Set(model.messages.map(\.id)).count, 40)
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
        let model = ChatViewModel(messageDecryptor: { rows, _ in rows.map { row in var value = row; value.content = "Synthetic decrypted body"; return value } }, accountScopeGeneration: { offline.scopeGeneration },
            offlineStore: offline, messageWindowFetcher: { _, _, query in
                if query.direction == .before && failOlder { throw URLError(.timedOut) }
                return try Self.page(query.direction == .latest ? 130..<150 : 110..<130,
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
        XCTAssertEqual(model.messages.first?.id, "m110")
    }

    // contract-test: direct surface=gui.apple assertions=auth.session.isolation,storage.surface.semantic-parity
    func testScopeChangeAndDeletionDropLateRemotePage() async throws {
        for deletion in [false, true] {
            let offline = try makeOffline(), store = ChatStore(), chat = makeChat()
            store.performWithoutPersistence { store.upsertChat(chat) }
            var scope = offline.scopeGeneration
            let gate = MessageWindowReadGate()
            let model = ChatViewModel(messageDecryptor: { rows, _ in rows.map { row in var value = row; value.content = "Synthetic decrypted body"; return value } }, accountScopeGeneration: { scope },
                offlineStore: offline, messageWindowFetcher: { _, _, query in
                    await gate.wait()
                    return try Self.page(130..<150, query: query, older: true, newer: false)
                })
            model.configure(wsManager: nil, chatStore: store)
            let opening = Task { @MainActor in await model.loadChat(id: chat.id) }
            await gate.waitUntilEntered()
            if deletion { model.consumeForegroundMessageDeletion(chatId: chat.id, messageId: "m130") }
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
            appId: "ai", encryptedTitle: nil, encryptedChatKey: nil, messagesV: 150, lastVisibleMessageId: "m010")
        store.performWithoutPersistence { store.upsertChat(chat) }
        var latestReads = 0, failLatest = true
        let model = ChatViewModel(messageDecryptor: { rows, _ in rows.map { row in var value = row; value.content = "Synthetic decrypted body"; return value } }, accountScopeGeneration: { offline.scopeGeneration },
            offlineStore: offline, messageWindowFetcher: { _, _, query in
                if query.direction == .around { return try Self.page(0..<20, query: query, older: false, newer: true) }
                latestReads += 1
                if failLatest && latestReads == 1 { throw URLError(.timedOut) }
                // A broken retry loop terminates, then fails the assertions,
                // instead of hanging the unit runner indefinitely.
                return try Self.page(130..<150, query: query, older: true, newer: false)
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
        XCTAssertEqual(model.messages.first?.id, "m130")
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

    // contract-test: supporting surface=gui.apple assertions=storage.cold.independent-message-pages,storage.privacy.ciphertext-boundary
    func testOversizedCursorIsAcceptedAndCannotSkipOrRepeatRequestedBoundary() throws {
        let query = ChatMessageWindowQuery(direction: .before, before: .init(createdAt: 1100, messageId: "m100"), respectCompressionBoundary: false)
        var payload = Self.payload(0..<0, query: query, older: true, newer: true)
        payload["oversized_message"] = true
        payload["oversized_message_cursor"] = ["created_at": 1099, "message_id": "m099"]
        payload["payload_bytes"] = 0
        let page = try ChatMessageWindowPage.decode(JSONSerialization.data(withJSONObject: payload), chatId: "synthetic-window", query: query)
        XCTAssertTrue(page.messages.isEmpty)
        XCTAssertEqual(page.oversizedMessageCursor?.messageId, "m099")
        payload["oversized_message_cursor"] = ["created_at": 1100, "message_id": "m100"]
        XCTAssertThrowsError(try ChatMessageWindowPage.decode(JSONSerialization.data(withJSONObject: payload), chatId: "synthetic-window", query: query))
    }

    // contract-test: supporting surface=gui.apple assertions=storage.cold.independent-message-pages,storage.integrity.observable-reconcilable
    func testByteBudgetAndInternalOutOfOrderRowsFailClosed() throws {
        let query = ChatMessageWindowQuery(respectCompressionBoundary: false)
        for mutation in 0..<3 {
            var payload = Self.payload(0..<3, query: query, older: false, newer: false)
            var rows = try XCTUnwrap(payload["messages"] as? [[String: Any]])
            if mutation == 0 { payload["payload_bytes"] = 256 * 1024 + 1 }
            else if mutation == 1 { rows[1]["created_at"] = 999 }
            else { rows[1]["encrypted_content"] = String(repeating: "x", count: 256 * 1024 + 1) }
            payload["messages"] = rows
            XCTAssertThrowsError(try ChatMessageWindowPage.decode(JSONSerialization.data(withJSONObject: payload), chatId: "synthetic-window", query: query))
        }
    }

    // contract-test: supporting surface=gui.apple assertions=storage.cold.independent-message-pages,storage.surface.semantic-parity
    func testDecryptionFailureRetainsHistoryAndCursorForExplicitRetry() async throws {
        let offline = try makeOffline(), store = ChatStore(), chat = makeChat()
        store.performWithoutPersistence { store.upsertChat(chat) }
        var fail = false
        let model = ChatViewModel(messageDecryptor: { rows, _ in
            rows.map { row in var value = row; if !fail { value.content = "Synthetic body" }; return value }
        }, accountScopeGeneration: { offline.scopeGeneration }, offlineStore: offline,
            messageWindowFetcher: { _, _, query in try Self.page(query.direction == .latest ? 130..<150 : 110..<130, query: query, older: true, newer: query.direction != .latest) })
        model.configure(wsManager: nil, chatStore: store)
        await model.loadChat(id: chat.id)
        let ids = model.messages.map(\.id)
        fail = true
        try await XCTUnwrap(model.loadOlderMessages()).value
        XCTAssertNotNil(model.error)
        XCTAssertEqual(model.messages.map(\.id), ids)
        XCTAssertTrue(model.hasOlderMessages)
        fail = false
        try await XCTUnwrap(model.loadOlderMessages()).value
        XCTAssertNil(model.error)
        XCTAssertEqual(model.messages.first?.id, "m110")
    }

    // contract-test: supporting surface=gui.apple assertions=storage.cold.shared-team-authorized,storage.cold.independent-message-pages
    func testWrapperCursorExactIdentityAndForeignChatFailClosed() throws {
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        let hash = ChatKeyWrapperRecord.hashedChatId(for: "synthetic-window")
        let wire: [String: Any] = ["wrappers": [["id": "b", "hashed_chat_id": hash, "key_type": "master", "encrypted_chat_key": "ciphertext"]],
            "has_more_before": true, "start_cursor": "b", "oversized_wrapper_id": NSNull(), "payload_bytes": 200]
        let page = try decoder.decode(ChatWrapperWindowPage.self, from: JSONSerialization.data(withJSONObject: wire))
        XCTAssertNoThrow(try page.validated(chatId: "synthetic-window", beforeId: "c", exactWrapperId: nil))
        XCTAssertThrowsError(try page.validated(chatId: "synthetic-window", beforeId: "b", exactWrapperId: nil))
        XCTAssertThrowsError(try page.validated(chatId: "another-chat", beforeId: nil, exactWrapperId: nil))
        XCTAssertThrowsError(try page.validated(chatId: "synthetic-window", beforeId: nil, exactWrapperId: "wrong"))
    }

    // contract-test: supporting surface=gui.apple assertions=storage.cold.independent-message-pages,storage.privacy.ciphertext-boundary
    func testExactOversizedContinuationKeepsFullBodyAnd413FailsWithoutSkipping() async throws {
        let query = ChatMessageWindowQuery(direction: .before, before: .init(createdAt: 1100, messageId: "m100"), respectCompressionBoundary: false)
        var payload = Self.payload(0..<0, query: query, older: true, newer: true)
        payload["oversized_message"] = true
        payload["oversized_message_cursor"] = ["created_at": 1099, "message_id": "m099"]
        payload["payload_bytes"] = 0
        WindowFixtureURLProtocol.configure(try JSONSerialization.data(withJSONObject: payload))
        let ciphertext = String(repeating: "synthetic", count: 40_000)
        let exact: [String: Any] = ["message": ["id": "different-database-row", "message_id": "m099", "chat_id": "synthetic-window", "role": "assistant", "created_at": 1099, "encrypted_content": ciphertext], "storage_tier": "archive"]
        let exactPath = "/v1/chats/synthetic-window/messages/m099"
        WindowFixtureURLProtocol.configureResponse(path: exactPath, body: try JSONSerialization.data(withJSONObject: exact))
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [WindowFixtureURLProtocol.self]
        configuration.httpCookieStorage = HTTPCookieStorage.sharedCookieStorage(forGroupContainerIdentifier: "exact-window-\(UUID().uuidString)")
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel() }
        let api = APIClient(session: session, cookieStorage: try XCTUnwrap(configuration.httpCookieStorage))
        let page = try await api.chatMessageWindow(chatId: "synthetic-window", teamId: nil, query: query, serverProfile: .custom(domain: "message-window-fixture.invalid"))
        XCTAssertEqual(page.messages.first?.encryptedContent, ciphertext)
        XCTAssertEqual(page.startCursor, page.oversizedMessageCursor)
        XCTAssertTrue(page.resolvedOversizedMessage)
        XCTAssertEqual(WindowFixtureURLProtocol.lastRequest()?.url?.path, exactPath)
        WindowFixtureURLProtocol.configureResponse(path: exactPath, body: Data(#"{"detail":"MESSAGE_REQUIRES_BOUNDED_READER"}"#.utf8), status: 413)
        do {
            _ = try await api.chatMessageWindow(chatId: "synthetic-window", teamId: nil, query: query, serverProfile: .custom(domain: "message-window-fixture.invalid"))
            XCTFail("Over-budget legacy body must stay unresolved")
        } catch let APIError.httpError(status, _) { XCTAssertEqual(status, 413) }
    }

    // contract-test: supporting surface=gui.apple assertions=storage.compression.incremental-archive,storage.subchats.durable-before-archive,storage.cold.independent-message-pages
    func testHotColdCoveredMainAndChildPagesMergeWithStableClientIDs() throws {
        for chatId in ["synthetic-main", "synthetic-child"] {
            let query = ChatMessageWindowQuery(respectCompressionBoundary: false)
            var hot = Self.payload(10..<20, query: query, older: true, newer: false)
            var cold = Self.payload(0..<15, query: query, older: false, newer: true)
            for value in [true, false] {
                var wire = value ? hot : cold
                wire["chat_id"] = chatId
                var rows = try XCTUnwrap(wire["messages"] as? [[String: Any]])
                for index in rows.indices { rows[index]["chat_id"] = chatId }
                wire["messages"] = rows
                wire["storage_tier"] = value ? "hot" : "archive"
                wire["compression_boundary_timestamp"] = 1010
                if value { hot = wire } else { cold = wire }
            }
            let hotPage = try ChatMessageWindowPage.decode(JSONSerialization.data(withJSONObject: hot), chatId: chatId, query: query)
            let coldPage = try ChatMessageWindowPage.decode(JSONSerialization.data(withJSONObject: cold), chatId: chatId, query: query)
            let merged = ChatMessageWindowPage.merge(coldPage.messages, preserving: hotPage.messages)
            XCTAssertEqual(merged.count, 20)
            XCTAssertEqual(merged.first?.id, "m000")
            XCTAssertEqual(merged.last?.id, "m019")
            XCTAssertEqual(Set(merged.map(\.id)).count, 20)
            XCTAssertTrue(merged.allSatisfy { $0.chatId == chatId && $0.content == nil })
        }
    }

    // contract-test: supporting surface=gui.apple assertions=storage.cold.independent-message-pages,storage.warm.bounded-chat-tail
    func testForegroundCacheCountAndByteEvictionProtectPendingAndStreamingBodies() throws {
        let query = ChatMessageWindowQuery(respectCompressionBoundary: false)
        let source = try Self.page(0..<10, query: query, older: false, newer: false).messages
        var pending = source[8]; pending.content = "Pending local body"
        let stream = Message(id: source[9].id, chatId: source[9].chatId, role: source[9].role, content: "Live body",
            encryptedContent: source[9].encryptedContent, createdAt: source[9].createdAt,
            updatedAt: source[9].updatedAt, appId: source[9].appId, isStreaming: true, embedRefs: source[9].embedRefs)
        let input = Array(source.prefix(8)) + [pending, stream]
        let older = ChatMessageWindowPage.retainedForeground(input, newest: false, pendingIds: [pending.id], maximumCount: 3)
        XCTAssertEqual(older.map(\.id), ["m000", "m001", "m002", "m008", "m009"])
        let newer = ChatMessageWindowPage.retainedForeground(input, newest: true, pendingIds: [pending.id], maximumCount: 3)
        XCTAssertEqual(newer.map(\.id), ["m005", "m006", "m007", "m008", "m009"])
        let size = try XCTUnwrap(source[0].encryptedContent).utf8.count
        let bytes = ChatMessageWindowPage.retainedForeground(input, newest: false, pendingIds: [pending.id], maximumBytes: size * 2)
        XCTAssertEqual(bytes.map(\.id), ["m000", "m001", "m008", "m009"])
        XCTAssertEqual(bytes.first { $0.id == pending.id }?.content, "Pending local body")
        XCTAssertEqual(input.count, 10, "Foreground retention never edits the originating snapshot")
    }

    // contract-test: supporting surface=gui.apple assertions=storage.cold.independent-message-pages,storage.compression.incremental-archive
    func testEvictedNewerHistoryCanBeReadAgainAndPageDecryptionIsNotRepeated() async throws {
        let offline = try makeOffline(), store = ChatStore(), chat = makeChat()
        store.performWithoutPersistence { store.upsertChat(chat) }
        var decryptCount = 0
        let model = ChatViewModel(messageDecryptor: { rows, _ in
            decryptCount += rows.count
            return rows.map { row in var value = row; value.content = "Synthetic plaintext"; return value }
        }, accountScopeGeneration: { offline.scopeGeneration }, offlineStore: offline,
            messageWindowFetcher: { _, _, query in
                let end = query.before?.createdAt ?? 1500
                let last = end - 1000
                return try Self.page((last - 20)..<last, query: query, older: last > 20, newer: query.direction == .before)
            })
        model.configure(wsManager: nil, chatStore: store)
        await model.loadChat(id: chat.id)
        XCTAssertEqual(decryptCount, 20, "A validated decrypted projection is reused for initial commit")
        for _ in 0..<11 { try await XCTUnwrap(model.loadOlderMessages()).value }
        XCTAssertTrue(model.hasNewerMessages, "Evicting newer saved rows keeps their read continuation")
        XCTAssertTrue(model.hasOlderMessages)
        try await XCTUnwrap(model.loadMessageWindow(.latest)).value
        XCTAssertEqual(model.messages.first?.id, "m480")
        XCTAssertFalse(model.hasNewerMessages)
        XCTAssertTrue(offline.loadLatestMessageWindow(chatId: chat.id).isEmpty)
        XCTAssertTrue(store.messages(for: chat.id).isEmpty)
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
    private nonisolated(unsafe) static var responses: [String: (Data, Int)] = [:]
    static func configureResponse(path: String, body: Data, status: Int = 200) {
        lock.lock(); defer { lock.unlock() }; responses[path] = (body, status)
    }
    static func configure(_ value: Data) { lock.lock(); defer { lock.unlock() }; data = value; recordedRequest = nil; responses = [:] }
    static func lastRequest() -> URLRequest? { lock.lock(); defer { lock.unlock() }; return recordedRequest }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        Self.lock.lock(); let fixture = Self.responses[request.url?.path ?? ""]
        let body = fixture?.0 ?? Self.data; let status = fixture?.1 ?? 200
        Self.recordedRequest = request; Self.lock.unlock()
        guard let url = request.url,
              let response = HTTPURLResponse(url: url, statusCode: status, httpVersion: nil, headerFields: ["Content-Type": "application/json"]) else {
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
