// Unit coverage for bounded native chat-window loading helpers.
// These tests use deterministic in-memory chat data and never touch network,
// credentials, encryption keys, or private persisted chat content.
// They guard the Apple chat-opening path against accidentally materializing
// full large-chat histories before first render.

import XCTest
import Combine
import CryptoKit
import SwiftData
@testable import OpenMates

@MainActor
final class ChatWindowLoadingTests: XCTestCase {
    // contract-test: direct surface=gui.apple assertions=apple-offline.local-first
    func testOfflineChatBeyondStartupFiveOpensBoundedDiskWindowAndPagesWithEmbeds() async throws {
        let schema = Schema([PersistedChat.self, PersistedMessage.self, PersistedEmbed.self,
            PersistedEmbedKey.self, PersistedCodeRunOutput.self, PendingOfflineAction.self])
        let configuration = ModelConfiguration("OfflineWindow-\(UUID().uuidString)", schema: schema, isStoredInMemoryOnly: true)
        let container = try ModelContainer(for: schema, configurations: [configuration])
        let offline = OfflineStore(modelContainer: container)
        let store = ChatStore()
        let chatID = "offline-sixth-chat"
        let chat = makeChat(id: chatID, title: "Synthetic offline chat", updatedAt: "2026-01-02T00:00:00Z", messagesV: 250)
        let rows = (0..<250).map { index in
            Message(id: String(format: "offline-%03d", index), chatId: chatID, role: .user,
                content: (index == 0 || index == 249) ? "```json\n{\"type\":\"sheet\",\"embed_id\":\"offline-sheet\"}\n```" : "Synthetic row \(index)",
                encryptedContent: nil, createdAt: String(format: "2026-01-01T00:%02d:%02dZ", index / 60, index % 60),
                updatedAt: nil, appId: nil, isStreaming: false, embedRefs: nil)
        }
        let embed = EmbedRecord(id: "offline-sheet", type: "sheets-sheet", status: .finished,
            data: .raw(["table": AnyCodable("| Item | Count |\n|---|---|\n| Saved | 1 |")]),
            parentEmbedId: nil, appId: "sheets", skillId: "sheet", embedIds: nil,
            hashedChatId: ChatKeyWrapperRecord.hashedChatId(for: chatID), createdAt: nil)
        offline.persistChats([chat])
        offline.persistMessages(rows, chatId: chatID)
        offline.persistEmbeds([embed], chatId: chatID)
        store.performWithoutPersistence { store.upsertChat(chat) }
        var decryptedCounts: [Int] = []
        var networkRequests = 0
        let model = ChatViewModel(messageDecryptor: { messages, _ in
            decryptedCounts.append(messages.count)
            return messages
        }, accountScopeGeneration: { offline.scopeGeneration }, contentBatchFetcher: { _ in
            networkRequests += 1
            throw CancellationError()
        }, offlineStore: offline)
        model.configure(wsManager: nil, chatStore: store)
        await model.loadChat(id: chatID)
        await Task.yield()
        XCTAssertNil(model.error)
        XCTAssertEqual(model.messages.map(\.id), rows.suffix(50).map(\.id))
        XCTAssertEqual(decryptedCounts.first, 50)
        XCTAssertEqual(model.openingMetrics.initialMessagesReceived, 50)
        XCTAssertEqual(model.openingMetrics.initialEmbedsReceived, 1)
        XCTAssertEqual(model.embedRecords[embed.id]?.rawData?["table"]?.value as? String,
                       embed.rawData?["table"]?.value as? String,
                       "A decoded disk embed must be usable when the offline window finishes opening")
        XCTAssertTrue(model.hasOlderMessages)
        XCTAssertTrue(store.messages(for: chatID).isEmpty, "Opening one cached chat must not publish a full transcript")
        for _ in 0..<8 where model.hasOlderMessages {
            let task = try XCTUnwrap(model.loadOlderMessages())
            await task.value
            if model.messages.contains(where: { $0.id == rows[0].id }) {
                XCTAssertEqual(model.embedRecords[embed.id]?.rawData?["table"]?.value as? String,
                               embed.rawData?["table"]?.value as? String)
            } else {
                XCTAssertNil(model.embedRecords[embed.id], "Windows without the reference must not retain its payload")
            }
        }
        XCTAssertEqual(model.messages.map(\.id), rows.prefix(50).map(\.id))
        XCTAssertFalse(model.hasOlderMessages)
        XCTAssertTrue(model.hasNewerMessages)
        XCTAssertTrue(decryptedCounts.allSatisfy { $0 <= 50 })
        let latest = try XCTUnwrap(model.loadMessageWindow(.latest))
        await latest.value
        XCTAssertEqual(model.messages.map(\.id), rows.suffix(50).map(\.id))
        XCTAssertFalse(model.hasNewerMessages)
        XCTAssertEqual(model.embedRecords[embed.id]?.rawData?["table"]?.value as? String,
                       embed.rawData?["table"]?.value as? String)
        XCTAssertEqual(networkRequests, 0, "Disk rows and full embed records must not require a network hydration request")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-offline.local-first
    func testOfflinePagingDoesNotDropMessagesWithEqualTimestamps() throws {
        let schema = Schema([PersistedChat.self, PersistedMessage.self])
        let configuration = ModelConfiguration("OfflineTies-\(UUID().uuidString)", schema: schema, isStoredInMemoryOnly: true)
        let container = try ModelContainer(for: schema, configurations: [configuration])
        let offline = OfflineStore(modelContainer: container)
        let chat = makeChat(id: "offline-ties", title: "Synthetic", updatedAt: "2026-01-01T00:00:00Z", messagesV: 70)
        let rows = (0..<70).map { Message(id: String(format: "tie-%03d", $0), chatId: chat.id,
            role: .user, content: "Synthetic", encryptedContent: nil, createdAt: chat.createdAt,
            updatedAt: nil, appId: nil, isStreaming: false, embedRefs: nil) }
        offline.persistChats([chat])
        offline.persistMessages(rows, chatId: chat.id)
        let tail = offline.loadLatestMessageWindow(chatId: chat.id)
        let first = try XCTUnwrap(tail.first)
        XCTAssertTrue(offline.hasOlderMessages(chatId: chat.id, before: first))
        let older = offline.loadOlderMessageWindow(chatId: chat.id, before: first.id)
        XCTAssertEqual((older + tail).map(\.id), rows.map(\.id))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence,code-run.surface-parity
    func testCanonicalCodeReferenceHydratesEncryptedSourceWithoutInventingHTMLMetadata() async throws {
        try await assertCanonicalCodeRecordHydrates(includeMetadata: true, convertFromSnakeCase: false)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.rendering.assistant-document-convergence,code-run.surface-parity
    func testSavedCodeRecordHydratesCanonicalEmbedIDWithDistinctDatabaseUUID() async throws {
        for convertFromSnakeCase in [false, true] {
            try await assertCanonicalCodeRecordHydrates(includeMetadata: false, convertFromSnakeCase: convertFromSnakeCase)
        }
    }

    private func assertCanonicalCodeRecordHydrates(includeMetadata: Bool, convertFromSnakeCase: Bool) async throws {
        let chatId = UUID().uuidString.lowercased()
        let embedId = UUID().uuidString.lowercased()
        let databaseId = UUID().uuidString.lowercased()
        let reference = Message(id: "code-message", chatId: chatId, role: .assistant,
            content: "```json\n{\"type\":\"code\",\"embed_id\":\"\(embedId)\"}\n```",
            encryptedContent: nil, createdAt: "2026-01-01T00:00:00Z", updatedAt: nil,
            appId: "code", isStreaming: false, embedRefs: nil)
        let parsed = PublicChatContent.attachEmbeds(to: [reference])
        let shell = try XCTUnwrap(parsed.records[embedId])
        XCTAssertNil(shell.rawData?["filename"], "A reference cannot invent index.html")
        XCTAssertNil(shell.rawData?["language"], "A reference cannot invent HTML")
        XCTAssertTrue(ChatViewModel.embedRecordRequiresHydration(shell))
        let emptyFile = EmbedRecord(id: "empty-file", type: "code-code", status: .finished,
            data: .raw(["filename": AnyCodable("empty.js"), "code": AnyCodable("")]),
            parentEmbedId: nil, appId: "code", skillId: nil, embedIds: nil, createdAt: nil)
        XCTAssertFalse(ChatViewModel.embedRecordRequiresHydration(emptyFile), "A saved zero-byte file is complete")

        let chatKey = SymmetricKey(size: .bits256)
        let embedKey = SymmetricKey(size: .bits256)
        ChatKeyManager.shared.setKey(chatKey, for: chatId)
        defer {
            ChatKeyManager.shared.removeKey(for: chatId)
            EmbedKeyManager.shared.removeKeys(for: chatId)
        }
        let sealedKey = try AES.GCM.seal(embedKey.withUnsafeBytes { Data($0) }, using: chatKey)
        let wrappedKey = try XCTUnwrap(sealedKey.combined).base64EncodedString()
        let source = "export const ready = \"hello\";"
        XCTAssertEqual(source.utf8.count, 29)
        let content = String(decoding: try JSONSerialization.data(withJSONObject: [
            "type": "code", "filename": "greeting.js", "language": "javascript", "code": source,
            "status": "finished", "line_count": 1
        ]), as: UTF8.self)
        let encryptedContent = try await CryptoManager.shared.encryptContent(content, key: embedKey)
        // Metadata and ciphertext can arrive together without encrypted_type.
        // The metadata must not make decryptEmbeds skip the encrypted source.
        var wire: [String: Any] = [
            "id": databaseId, "embed_id": embedId, "status": "finished", "version_number": 8,
            "encrypted_content": encryptedContent, "hashed_chat_id": ChatKeyWrapperRecord.hashedChatId(for: chatId)
        ]
        if includeMetadata {
            wire["type"] = "code"
            wire["data"] = ["filename": "greeting.js", "language": "javascript"]
        } else {
            wire["encrypted_type"] = try await CryptoManager.shared.encryptContent("code", key: embedKey)
        }
        let decoder = JSONDecoder()
        if convertFromSnakeCase { decoder.keyDecodingStrategy = .convertFromSnakeCase }
        let stored = try decoder.decode(EmbedRecord.self, from: JSONSerialization.data(withJSONObject: wire))
        XCTAssertEqual(stored.id, embedId)
        XCTAssertNotEqual(stored.id, databaseId)
        XCTAssertEqual(EmbedRecord.relatedRecords(referencedIds: [embedId], from: [stored], context: "codeIdentityTest").map(\.id),
            [embedId], "The saved row must match its message reference before decryption")
        let key = EmbedKeyRecord(hashedEmbedId: ChatKeyWrapperRecord.hashedChatId(for: embedId),
            keyType: "chat", hashedChatId: ChatKeyWrapperRecord.hashedChatId(for: chatId), encryptedEmbedKey: wrappedKey)
        XCTAssertEqual(key.hashedEmbedId, ChatKeyWrapperRecord.hashedChatId(for: stored.id),
            "The record identity and wrapper lookup must hash the same canonical embed ID")
        XCTAssertNotEqual(key.hashedEmbedId, ChatKeyWrapperRecord.hashedChatId(for: databaseId))
        var requests = 0
        let model = ChatViewModel(contentBatchFetcher: { id in
            requests += 1
            return ChatContentBatchPayload(messagesByChatId: [id: []], versionsByChatId: [:], embeds: [stored],
                embedKeys: [key], chatKeyWrappers: [], codeRunOutputs: nil)
        })
        model.seedIsolatedHistory(chat: makeChat(id: chatId, title: "Code", updatedAt: reference.createdAt, messagesV: 1),
            messages: parsed.messages, embeds: [shell])
        await model.retryVisibleEmbedHydration()
        let hydrated = try XCTUnwrap(model.embedRecords[embedId])
        XCTAssertEqual(hydrated.type, "code-code", "The backend code alias must reach the native code renderer")
        let rendered = AppleCodeEmbedContent(data: hydrated.rawData)
        XCTAssertEqual(rendered.code, source)
        XCTAssertEqual(rendered.filename, "greeting.js")
        XCTAssertEqual(rendered.language, "javascript")
        XCTAssertEqual(rendered.lineCount, 1)
        XCTAssertEqual(hydrated.status, .finished)
        XCTAssertEqual(hydrated.versionNumber, 8)
        XCTAssertEqual(AppleCodeEmbedPreviewState(content: rendered, status: hydrated.status), .source)
        XCTAssertFalse(ChatViewModel.embedRecordRequiresHydration(hydrated))
        XCTAssertEqual(PublicChatContent.mergingHydratedRecords(existing: model.embedRecords, inline: parsed.records)[embedId]?.rawData,
            hydrated.rawData, "Reparsing a canonical reference must retain decrypted source")
        await model.retryVisibleEmbedHydration()
        XCTAssertEqual(requests, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence,code-run.surface-parity
    func testMissingCodeRecordDoesNotManufactureSourceOrHTMLFilename() async throws {
        let reference = Message(id: "missing-code-message", chatId: "missing-code-chat", role: .assistant,
            content: "```json\n{\"type\":\"code\",\"embed_id\":\"missing-code-ref\"}\n```",
            encryptedContent: nil, createdAt: "2026-01-01T00:00:00Z", updatedAt: nil,
            appId: "code", isStreaming: false, embedRefs: nil)
        let parsed = PublicChatContent.attachEmbeds(to: [reference])
        let model = ChatViewModel(contentBatchFetcher: { id in
            ChatContentBatchPayload(messagesByChatId: [id: []], versionsByChatId: [:], embeds: [],
                embedKeys: [], chatKeyWrappers: [], codeRunOutputs: nil)
        })
        model.seedIsolatedHistory(chat: makeChat(id: reference.chatId, title: "Code", updatedAt: reference.createdAt, messagesV: 1),
            messages: parsed.messages, embeds: Array(parsed.records.values))
        await model.retryVisibleEmbedHydration()
        let shell = try XCTUnwrap(model.embedRecords["missing-code-ref"])
        let content = AppleCodeEmbedContent(data: shell.rawData)
        XCTAssertTrue(content.code.isEmpty)
        XCTAssertNil(content.filename)
        XCTAssertEqual(content.language, "")
        XCTAssertEqual(AppleCodeEmbedPreviewState(content: content, status: shell.status), .empty)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testCanonicalSheetReferenceHydratesFullTableAndSurvivesReparse() async throws {
        let reference = Message(id: "sheet-message", chatId: "sheet-chat", role: .assistant,
            content: "```json\n{\"type\":\"sheet\",\"embed_id\":\"sheet-ref\",\"row_count\":2}\n```",
            encryptedContent: nil, createdAt: "2026-01-01T00:00:00Z", updatedAt: nil,
            appId: "sheets", isStreaming: false, embedRefs: nil)
        let parsed = PublicChatContent.attachEmbeds(to: [reference])
        let shell = try XCTUnwrap(parsed.records["sheet-ref"])
        XCTAssertNil(shell.rawData?["title"], "A reference cannot manufacture a table title")
        XCTAssertNil(shell.rawData?["rows"])
        XCTAssertEqual(shell.rawData?["row_count"]?.value as? Int, 2)
        XCTAssertTrue(ChatViewModel.embedRecordRequiresHydration(shell))
        let record = fullSheetRecord(chatId: reference.chatId)
        var requests = 0
        let model = ChatViewModel(contentBatchFetcher: { chatId in
            requests += 1
            return self.sheetBatch(chatId: chatId, record: record)
        })
        model.seedIsolatedHistory(chat: makeChat(id: reference.chatId, title: "Sheet", updatedAt: reference.createdAt, messagesV: 1),
                                  messages: parsed.messages, embeds: [shell])
        await model.retryVisibleEmbedHydration()
        let hydrated = try XCTUnwrap(model.embedRecords[record.id])
        let table = ParsedSheetTable(data: hydrated.rawData)
        XCTAssertEqual(table.headers, ["Item", "Count"])
        XCTAssertEqual(table.rows, [["First", "1"], ["Second", "2"]])
        XCTAssertNil(table.title, "A title is optional in a complete saved sheet")
        XCTAssertFalse(ChatViewModel.embedRecordRequiresHydration(hydrated))
        let reparsed = PublicChatContent.mergingHydratedRecords(existing: model.embedRecords, inline: parsed.records)
        XCTAssertEqual(ParsedSheetTable(data: reparsed[record.id]?.rawData).rows, table.rows)
        let legacy = EmbedRecord(id: record.id, type: "sheets-sheet", status: .finished,
            data: .raw(["title": AnyCodable("Table"), "rows": AnyCodable([String]())]),
            parentEmbedId: nil, appId: "sheets", skillId: "sheet", embedIds: nil, createdAt: nil)
        XCTAssertTrue(ChatViewModel.embedRecordRequiresHydration(legacy))
        XCTAssertEqual(PublicChatContent.mergingHydratedRecords(existing: reparsed, inline: [legacy.id: legacy])[record.id]?.rawData,
                       hydrated.rawData)
        await model.retryVisibleEmbedHydration()
        XCTAssertEqual(requests, 1, "A full table is not fetched again")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.local-state.precedence,chat-navigation.open.local-first-coherent
    func testSheetHydrationCoalescesAndRejectsStaleChatGenerationOrAccount() async throws {
        for invalidation in ["none", "chat", "generation", "account"] {
            let gate = SheetHydrationGate()
            var scope = UUID()
            let record = fullSheetRecord(chatId: "sheet-chat")
            let model = ChatViewModel(messageDecryptor: { rows, _ in rows }, accountScopeGeneration: { scope },
                contentBatchFetcher: { _ in try await gate.fetch() })
            let message = Message(id: "sheet-message", chatId: "sheet-chat", role: .assistant,
                content: "[[embed:sheet-ref]]", encryptedContent: nil, createdAt: "2026-01-01T00:00:00Z",
                updatedAt: nil, appId: "sheets", isStreaming: false,
                embedRefs: [EmbedRef(id: record.id, type: "sheet", status: "finished", data: nil)])
            let chat = makeChat(id: message.chatId, title: "Sheet", updatedAt: message.createdAt, messagesV: 1)
            model.seedIsolatedHistory(chat: chat, messages: [message], embeds: [])
            let first = Task { await model.loadEmbeds(for: [message.id]) }
            await gate.waitUntilStarted()
            let second = Task { await model.loadEmbeds(for: [message.id]) }
            await Task.yield()
            if invalidation == "account" { scope = UUID() }
            if invalidation == "chat" || invalidation == "generation" {
                let next = makeChat(id: invalidation == "chat" ? "other-chat" : chat.id,
                    title: "Replacement", updatedAt: message.createdAt, messagesV: 0)
                await model.loadChat(id: next.id, initialChat: next, initialMessages: [])
            }
            gate.release(sheetBatch(chatId: chat.id, record: record))
            await first.value
            await second.value
            XCTAssertEqual(gate.calls, 1, "Concurrent taps share one scoped request")
            if invalidation == "none" {
                XCTAssertEqual(ParsedSheetTable(data: model.embedRecords[record.id]?.rawData).rows.count, 2)
            } else {
                XCTAssertNil(model.embedRecords[record.id], "A superseded completion must not publish")
            }
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.local-state.precedence
    func testQueuedSheetHydrationDoesNotDispatchAfterAccountAuthorityChanges() async {
        let initialScope = UUID()
        let replacementScope = UUID()
        var armed = false
        var scopeReads = 0
        var requests = 0
        let model = ChatViewModel(accountScopeGeneration: {
            guard armed else { return initialScope }
            scopeReads += 1
            // The entry check captures the old authority. The queued fetch task
            // starts after that authority has been replaced.
            return scopeReads == 1 ? initialScope : replacementScope
        }, contentBatchFetcher: { _ in
            requests += 1
            throw URLError(.notConnectedToInternet)
        })
        let message = Message(id: "sheet-message", chatId: "sheet-chat", role: .assistant,
            content: "[[embed:sheet-ref]]", encryptedContent: nil, createdAt: "2026-01-01T00:00:00Z",
            updatedAt: nil, appId: "sheets", isStreaming: false,
            embedRefs: [EmbedRef(id: "sheet-ref", type: "sheet", status: "finished", data: nil)])
        model.seedIsolatedHistory(chat: makeChat(id: message.chatId, title: "Sheet", updatedAt: message.createdAt, messagesV: 1),
                                  messages: [message], embeds: [])
        armed = true
        await model.loadEmbeds(for: [message.id])
        XCTAssertGreaterThanOrEqual(scopeReads, 2)
        XCTAssertEqual(requests, 0, "A revoked queued request must never dispatch old chat IDs")
        XCTAssertNil(model.embedRecords["sheet-ref"])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testVisibleSheetReferenceRetriesAfterTransportRecovery() async throws {
        var attempts = 0
        let record = fullSheetRecord(chatId: "sheet-chat")
        let model = ChatViewModel(contentBatchFetcher: { chatId in
            attempts += 1
            if attempts == 1 { throw URLError(.notConnectedToInternet) }
            return self.sheetBatch(chatId: chatId, record: record)
        })
        let message = Message(id: "sheet-message", chatId: "sheet-chat", role: .assistant,
            content: "[[embed:sheet-ref]]", encryptedContent: nil, createdAt: "2026-01-01T00:00:00Z",
            updatedAt: nil, appId: "sheets", isStreaming: false,
            embedRefs: [EmbedRef(id: record.id, type: "sheet", status: "finished", data: nil)])
        model.seedIsolatedHistory(chat: makeChat(id: message.chatId, title: "Sheet", updatedAt: message.createdAt, messagesV: 1),
                                  messages: [message], embeds: [])
        await model.retryVisibleEmbedHydration()
        XCTAssertNil(model.embedRecords[record.id])
        await model.retryVisibleEmbedHydration()
        XCTAssertEqual(attempts, 2)
        XCTAssertEqual(ParsedSheetTable(data: model.embedRecords[record.id]?.rawData).rows.count, 2)
    }

    private func fullSheetRecord(chatId: String) -> EmbedRecord {
        EmbedRecord(id: "sheet-ref", type: "sheet", status: .finished,
            data: .raw(["table": AnyCodable("| Item | Count |\n|---|---|\n| First | 1 |\n| Second | 2 |"),
                        "row_count": AnyCodable(2), "col_count": AnyCodable(2)]),
            parentEmbedId: nil, appId: "sheets", skillId: "sheet", embedIds: nil,
            hashedChatId: ChatKeyWrapperRecord.hashedChatId(for: chatId), createdAt: nil)
    }

    private func sheetBatch(chatId: String, record: EmbedRecord) -> ChatContentBatchPayload {
        ChatContentBatchPayload(messagesByChatId: [chatId: []], versionsByChatId: [:], embeds: [record],
                                embedKeys: [], chatKeyWrappers: [], codeRunOutputs: nil)
    }

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

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testCanonicalHistoryKeepsArrayStorageAndEqualTimestampOrder() {
        var rows = makeMessages(count: 600)
        rows[1] = makeHistoryMessage(id: rows[1].id, createdAt: rows[0].createdAt, content: "Equal timestamp")
        let ordered = ChatHistoryWindowPolicy.orderedUnique(rows)
        XCTAssertEqual(ordered.map(\.id), rows.map(\.id))
        XCTAssertEqual(ordered.map(\.content), rows.map(\.content))
        assertSameMessageStorage(rows, ordered)
        XCTAssertTrue(ChatHistoryWindowPolicy.orderedUnique([]).isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testDuplicateHistoryKeepsLastValueAndFirstPositionForTimestampTies() {
        let date = "2026-01-01T00:01:00Z"
        let rows = [
            makeHistoryMessage(id: "duplicate", createdAt: date, content: "Old"),
            makeHistoryMessage(id: "peer", createdAt: date, content: "Peer"),
            makeHistoryMessage(id: "duplicate", createdAt: date, content: "Accepted replacement")
        ]
        let ordered = ChatHistoryWindowPolicy.orderedUnique(rows)
        XCTAssertEqual(ordered.map(\.id), ["duplicate", "peer"])
        XCTAssertEqual(ordered.map(\.content), ["Accepted replacement", "Peer"])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testUnorderedHistorySortsReplacementTimestampAndPreservesTiePositions() {
        let early = "2026-01-01T00:01:00Z"
        let late = "2026-01-01T00:02:00Z"
        let rows = [
            makeHistoryMessage(id: "later", createdAt: late, content: "Later"),
            makeHistoryMessage(id: "first-tie", createdAt: early, content: "First"),
            makeHistoryMessage(id: "second-tie", createdAt: early, content: "Second"),
            makeHistoryMessage(id: "later", createdAt: early, content: "Earlier replacement")
        ]
        let ordered = ChatHistoryWindowPolicy.orderedUnique(rows)
        XCTAssertEqual(ordered.map(\.id), ["later", "first-tie", "second-tie"])
        XCTAssertEqual(ordered.first?.content, "Earlier replacement")
        let withoutDuplicate = ChatHistoryWindowPolicy.orderedUnique(Array(rows.prefix(3)))
        XCTAssertEqual(withoutDuplicate.map(\.id), ["first-tie", "second-tie", "later"])
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.open.local-first-coherent,chats.local-state.precedence
    func testLargeChatBatchPublishesOneFinalSnapshotAndMergesRepeatedIDs() {
        let store = ChatStore()
        let date = "2026-01-01T00:00:00Z"
        store.performWithoutPersistence {
            store.upsertChats([makeChat(id: "batch-0", title: "Accepted title", updatedAt: date,
                messagesV: 4, encryptedChatKey: "wrapped-key-fixture")])
        }
        var snapshots: [[String]] = []
        let subscription = store.$chats.dropFirst().sink { snapshots.append($0.map(\.id)) }
        defer { subscription.cancel() }
        var incoming = (0..<600).map { index in
            makeChat(id: "batch-\(index)", title: "Incoming \(index)", updatedAt: date, messagesV: 1)
        }
        incoming.append(makeChat(id: "batch-1", title: "Newer duplicate", updatedAt: date, messagesV: 2))
        let serverOrder = (0..<600).reversed().map { "batch-\($0)" }
        store.performWithoutPersistence {
            store.upsertChats(incoming, serverSortOrder: serverOrder, serverSortOffset: 50)
        }
        XCTAssertEqual(snapshots.count, 1, "A batch must publish only its final merged and sorted list")
        XCTAssertEqual(snapshots.first, serverOrder)
        XCTAssertEqual(store.chats.map(\.id), serverOrder)
        XCTAssertEqual(store.chat(for: "batch-0")?.title, "Accepted title")
        XCTAssertEqual(store.chat(for: "batch-0")?.messagesV, 4)
        XCTAssertEqual(store.chat(for: "batch-0")?.encryptedChatKey, "wrapped-key-fixture")
        XCTAssertEqual(store.chat(for: "batch-1")?.title, "Newer duplicate")
        XCTAssertEqual(store.chat(for: "batch-1")?.messagesV, 2)
        let state = store.makeSyncClientState(clientSuggestionsCount: 0)
        XCTAssertEqual(state.clientChatIds, serverOrder)
        XCTAssertEqual(state.clientChatVersions["batch-0"]?["messages_v"], 4)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testModernEmbedsWithoutLegacyHashesKeepHistoryStorage() {
        let rows = makeMessages(count: 600)
        let embed = EmbedRecord(id: "modern-embed", type: "web-website", status: .finished,
            data: .raw([:]), parentEmbedId: nil, appId: "web", skillId: nil,
            embedIds: nil, createdAt: nil)
        let result = ChatLegacyEmbedLinkPolicy.applying(to: rows, embeds: [embed])
        XCTAssertEqual(result.map(\.id), rows.map(\.id))
        XCTAssertEqual(result.map(\.content), rows.map(\.content))
        assertSameMessageStorage(rows, result)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testLegacyHashStillLinksOnlyMatchingUserAndPreservesRawEmptyContent() throws {
        let linked = makeHistoryMessage(id: "legacy-audio-message", createdAt: "2026-01-01T00:01:00Z", content: "")
        let unmatched = makeHistoryMessage(id: "unmatched", createdAt: linked.createdAt, content: "")
        let embed = EmbedRecord(id: "legacy-audio", type: "audio-recording", status: .finished,
            data: .raw([:]), parentEmbedId: nil, appId: "audio", skillId: nil,
            embedIds: nil,
            hashedMessageId: "b01c731376d38838b752117a8df680216c9fedf304994c2968eef09e4d6dc7f9",
            createdAt: nil)
        let assistant = Message(id: linked.id, chatId: linked.chatId, role: .assistant, content: "",
            encryptedContent: nil, createdAt: linked.createdAt, updatedAt: nil,
            appId: nil, isStreaming: false, embedRefs: nil)
        let result = ChatLegacyEmbedLinkPolicy.applying(to: [linked, unmatched, assistant], embeds: [embed])
        XCTAssertEqual(result[0].embedRefs?.map(\.id), [embed.id])
        XCTAssertTrue(result[0].content?.contains(embed.id) == true)
        XCTAssertNil(result[1].embedRefs)
        XCTAssertEqual(result[1].content, "")
        XCTAssertNil(result[2].embedRefs, "Legacy links apply only to user messages")
        XCTAssertEqual(result[2].content, "")
        let raw = try XCTUnwrap(ChatLegacyEmbedLinkPolicy.applying(
            to: [linked], embeds: [embed], synthesizeMissingContent: false).first)
        XCTAssertEqual(raw.content, "")
        XCTAssertEqual(raw.embedRefs?.map(\.id), [embed.id])
    }

    private func assertSameMessageStorage(_ original: [Message], _ result: [Message],
                                         file: StaticString = #filePath, line: UInt = #line) {
        original.withUnsafeBufferPointer { originalBuffer in
            result.withUnsafeBufferPointer { resultBuffer in
                XCTAssertEqual(originalBuffer.baseAddress, resultBuffer.baseAddress,
                    "Canonical history should reuse its existing array", file: file, line: line)
            }
        }
    }

    private func makeHistoryMessage(id: String, createdAt: String, content: String) -> Message {
        Message(id: id, chatId: "unit-large-chat", role: .user, content: content,
            encryptedContent: nil, createdAt: createdAt, updatedAt: nil,
            appId: nil, isStreaming: false, embedRefs: nil)
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
                          lastVisibleMessageId: String? = nil, encryptedChatKey: String? = nil) -> Chat {
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
            encryptedChatKey: encryptedChatKey,
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

@MainActor
private final class SheetHydrationGate {
    private var pending: CheckedContinuation<ChatContentBatchPayload, Error>?
    private var started: CheckedContinuation<Void, Never>?
    private(set) var calls = 0
    func fetch() async throws -> ChatContentBatchPayload {
        calls += 1
        return try await withCheckedThrowingContinuation { continuation in
            pending = continuation
            started?.resume()
            started = nil
        }
    }
    func waitUntilStarted() async {
        if pending != nil { return }
        await withCheckedContinuation { started = $0 }
    }
    func release(_ batch: ChatContentBatchPayload) {
        pending?.resume(returning: batch)
        pending = nil
    }
}
