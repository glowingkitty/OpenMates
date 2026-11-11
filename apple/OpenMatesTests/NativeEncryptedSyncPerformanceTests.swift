// Timings for the Apple sync/decrypt/persist path, measured with a seeded, fully
// synthetic ENCRYPTED fixture (random master key, 600 chats with wrapped chat
// keys and encrypted metadata, one chat with 1000 encrypted messages). Plan
// apple-client-core-migration A0 recorded the Swift baseline; from A3 on the same
// process measures the old per-field Swift sequence and the batched Rust core
// path side by side, because CI runner speed varies by about a factor of two.
// Each phase prints `APPLE_PERF name=<phase> ms=<median> min_ms=<min> n=<count>`
// and attaches the same line to the xcresult. Assertions only check correctness
// (decrypted values equal the fixture plaintext) plus a very generous ceiling.
//
// Old path (pre-A3 per-item/per-field call sequence, REPLAYED on the Swift
// functions that still exist; the production callers now use the core):
//   chat_key_bulk_load            CryptoManager.unwrapChatKey per key + setKey
//   chat_list_metadata_decrypt    ChatKeyManager.decryptChatField per field
//   chat_open_window_decrypt      OfflineStore.loadLatestMessageWindow +
//                                 ChatKeyManager.decryptMessageContent per field
//   chat_open_full_1000_decrypt   OfflineStore.loadMessages + the same per field
// Core path (production code, one batched UniFFI call off the main actor):
//   core_chat_key_bulk_load            ChatKeyManager.loadChatKeys
//   core_chat_list_metadata_decrypt    ChatKeyManager.decryptMetadata
//   core_chat_open_window_decrypt      OfflineStore.loadLatestMessageWindow +
//                                      ChatViewModel.decryptMessagesForDisplay
//   core_chat_open_full_1000_decrypt   OfflineStore.loadMessages + the same
// Storage (unchanged):
//   persist_chats                 OfflineStore.persistChats (direct)
//   persist_messages              OfflineStore.persistMessagesBatch (direct)
//   cold_load_from_disk           OfflineStore init + OfflineSyncBridge.loadFromDisk
//                                 + ChatStore (direct)
// No real account, Keychain or network: the master key is passed explicitly and
// every store lives in a temporary directory.

import CryptoKit
import Foundation
import XCTest
@testable import OpenMates

@MainActor
final class NativeEncryptedSyncPerformanceTests: XCTestCase {
    private static let chatCount = 600
    private static let messageCount = 1000
    private static let runsPerPhase = 3
    private static let ceilingMilliseconds = 120_000

    private struct ExpectedMessage {
        let content: String
        let senderName: String?
        let category: String?
        let modelName: String?
        let thinking: String?
        let piiOriginal: String?
    }

    private struct ExpectedChatMetadata {
        let title: String
        let category: String
        let icon: String
        let summary: String
    }

    private struct Fixture {
        let masterKey: SymmetricKey
        let chats: [Chat]
        let wrappedKeys: [(chatId: String, encryptedChatKey: String)]
        let expectedChats: [String: ExpectedChatMetadata]
        let busyChatId: String
        let messages: [Message]
        let expectedMessages: [String: ExpectedMessage]
    }

    private var temporaryDirectories: [URL] = []
    private var openedStores: [OfflineStore] = []
    private var perfLines: [String] = []

    override func tearDown() async throws {
        for store in openedStores { store.deactivate() }
        openedStores.removeAll()
        for directory in temporaryDirectories { try? FileManager.default.removeItem(at: directory) }
        temporaryDirectories.removeAll()
        ChatKeyManager.shared.clearAll()
        try await super.tearDown()
    }

    // contract-test: tooling
    func testSeededEncryptedSyncPerformanceOldAndCorePaths() async throws {
        let fixture = try await Self.makeFixture()
        let keyManager = ChatKeyManager.shared
        keyManager.clearAll()
        let master = fixture.masterKey
        let busyChatId = fixture.busyChatId

        // 1. Unwrap 600 chat keys: old per-key Swift sequence, then the core batch.
        try await measure("chat_key_bulk_load",
            prepare: { keyManager.clearAll() },
            body: {
                for entry in fixture.wrappedKeys {
                    let key = try await CryptoManager.shared.unwrapChatKey(
                        encryptedChatKeyBase64: entry.encryptedChatKey, masterKey: master)
                    keyManager.setKey(key, for: entry.chatId)
                }
                keyManager.markInitialSyncReady()
                return fixture.wrappedKeys.count
            },
            verify: { self.assertKeysLoaded(fixture, keyManager) })
        try await measure("core_chat_key_bulk_load",
            prepare: { keyManager.clearAll() },
            body: {
                await keyManager.loadChatKeys(from: fixture.wrappedKeys, masterKey: master)
                return fixture.wrappedKeys.count
            },
            verify: { self.assertKeysLoaded(fixture, keyManager) })

        // 2. Chat-list metadata: old per chat, per field sequence of the deleted
        // MainAppView.decryptChatMetadata (title, category, icon, summary), then
        // the production batched ChatKeyManager.decryptMetadata.
        var decryptedChats: [Chat] = []
        try await measure("chat_list_metadata_decrypt",
            prepare: {
                decryptedChats = []
                if !keyManager.hasKey(for: busyChatId) {
                    await keyManager.loadChatKeys(from: fixture.wrappedKeys, masterKey: master)
                }
            },
            body: {
                var result: [Chat] = []
                result.reserveCapacity(fixture.chats.count)
                for chat in fixture.chats {
                    var decrypted = chat
                    if decrypted.title?.isEmpty != false,
                       let encrypted = decrypted.encryptedTitle,
                       let value = await keyManager.decryptChatField(
                           chatId: decrypted.id, encryptedValue: encrypted, fieldName: "encrypted_title") {
                        decrypted.title = value
                    }
                    if decrypted.category == nil,
                       let encrypted = decrypted.encryptedCategory,
                       let value = await keyManager.decryptChatField(
                           chatId: decrypted.id, encryptedValue: encrypted, fieldName: "encrypted_category") {
                        decrypted.category = value
                    }
                    if decrypted.icon == nil,
                       let encrypted = decrypted.encryptedIcon,
                       let value = await keyManager.decryptChatField(
                           chatId: decrypted.id, encryptedValue: encrypted, fieldName: "encrypted_icon") {
                        decrypted.icon = value
                    }
                    if decrypted.chatSummary == nil,
                       let encrypted = decrypted.encryptedChatSummary,
                       let value = await keyManager.decryptChatField(
                           chatId: decrypted.id, encryptedValue: encrypted, fieldName: "encrypted_chat_summary") {
                        decrypted.chatSummary = value
                    }
                    result.append(decrypted)
                }
                decryptedChats = result
                return result.count
            },
            verify: { self.assertChats(decryptedChats, fixture) })
        try await measure("core_chat_list_metadata_decrypt",
            prepare: {
                decryptedChats = []
                if !keyManager.hasKey(for: busyChatId) {
                    await keyManager.loadChatKeys(from: fixture.wrappedKeys, masterKey: master)
                }
            },
            body: {
                decryptedChats = await keyManager.decryptMetadata(fixture.chats, replaceEmptyTitle: true)
                return decryptedChats.count
            },
            verify: { self.assertChats(decryptedChats, fixture) })

        // 3. Persist 600 chats into a fresh on-disk SwiftData store per run.
        var store: OfflineStore?
        try await measure("persist_chats",
            prepare: { store = try self.makeStore() },
            body: {
                store?.persistChats(fixture.chats)
                return fixture.chats.count
            },
            verify: {
                XCTAssertEqual(store?.loadChats().count, fixture.chats.count)
            })

        // 4. Persist the 1000 encrypted messages (chat rows exist, untimed).
        try await measure("persist_messages",
            prepare: {
                store = try self.makeStore()
                store?.persistChats(fixture.chats)
            },
            body: {
                store?.persistMessagesBatch([busyChatId: fixture.messages])
                return fixture.messages.count
            },
            verify: {
                XCTAssertEqual(store?.loadMessages(chatId: busyChatId).count, fixture.messages.count)
            })

        // 5. Cold load: new store instance on the same file, the production
        // OfflineSyncBridge.loadFromDisk fetch of startup chats into a fresh ChatStore.
        let coldDirectory = try makeTemporaryDirectory()
        let coldAccount = "perf-cold-account"
        let coldServer = URL(string: "https://synthetic.invalid")!
        do {
            let seeding = try OfflineStore(directory: coldDirectory, userId: coldAccount, apiBaseURL: coldServer)
            seeding.persistChats(fixture.chats)
            seeding.persistMessagesBatch([busyChatId: fixture.messages])
            seeding.deactivate()
        }
        var chatStore = ChatStore()
        try await measure("cold_load_from_disk",
            prepare: { chatStore = ChatStore() },
            body: {
                let reopened = try OfflineStore(directory: coldDirectory, userId: coldAccount, apiBaseURL: coldServer)
                self.openedStores.append(reopened)
                let bridge = OfflineSyncBridge(chatStore: chatStore, offlineStore: reopened)
                bridge.loadFromDisk(lastOpenedChatId: busyChatId)
                return chatStore.chats.count
            },
            verify: {
                XCTAssertFalse(chatStore.chats.isEmpty)
                XCTAssertNotNil(chatStore.chat(for: busyChatId))
                XCTAssertEqual(chatStore.messages(for: busyChatId).count, ChatStore.boundedWindowSize)
            })

        // 6 and 7. Chat open: load from the reopened store and decrypt for display,
        // old per-message per-field sequence first, then the production batch.
        let readStore = try OfflineStore(directory: coldDirectory, userId: coldAccount, apiBaseURL: coldServer)
        openedStores.append(readStore)
        var displayed: [Message] = []
        try await measure("chat_open_window_decrypt",
            prepare: { displayed = [] },
            body: {
                let window = readStore.loadLatestMessageWindow(chatId: busyChatId)
                displayed = await Self.perFieldDecrypt(window, chatId: busyChatId, keyManager: keyManager)
                return displayed.count
            },
            verify: {
                XCTAssertEqual(displayed.count, ChatStore.boundedWindowSize)
                self.assertDisplayed(displayed, expected: fixture.expectedMessages)
            })
        try await measure("core_chat_open_window_decrypt",
            prepare: { displayed = [] },
            body: {
                let window = readStore.loadLatestMessageWindow(chatId: busyChatId)
                displayed = await ChatViewModel.decryptMessagesForDisplay(window, chatId: busyChatId)
                return displayed.count
            },
            verify: {
                XCTAssertEqual(displayed.count, ChatStore.boundedWindowSize)
                self.assertDisplayed(displayed, expected: fixture.expectedMessages)
            })
        try await measure("chat_open_full_1000_decrypt",
            prepare: { displayed = [] },
            body: {
                let all = readStore.loadMessages(chatId: busyChatId)
                displayed = await Self.perFieldDecrypt(all, chatId: busyChatId, keyManager: keyManager)
                return displayed.count
            },
            verify: {
                XCTAssertEqual(displayed.count, Self.messageCount)
                self.assertDisplayed(displayed, expected: fixture.expectedMessages)
            })
        try await measure("core_chat_open_full_1000_decrypt",
            prepare: { displayed = [] },
            body: {
                let all = readStore.loadMessages(chatId: busyChatId)
                displayed = await ChatViewModel.decryptMessagesForDisplay(all, chatId: busyChatId)
                return displayed.count
            },
            verify: {
                XCTAssertEqual(displayed.count, Self.messageCount)
                self.assertDisplayed(displayed, expected: fixture.expectedMessages)
            })

        // 8. Chat open split: store load alone, then decrypt alone on messages loaded
        // untimed, so the decrypt cost is separate from the SwiftData fetch + mapping.
        var loaded: [Message] = []
        try await measure("chat_open_window_store_load",
            prepare: { loaded = [] },
            body: {
                loaded = readStore.loadLatestMessageWindow(chatId: busyChatId)
                return loaded.count
            },
            verify: {
                XCTAssertEqual(loaded.count, ChatStore.boundedWindowSize)
            })
        try await measure("chat_open_full_1000_store_load",
            prepare: { loaded = [] },
            body: {
                loaded = readStore.loadMessages(chatId: busyChatId)
                return loaded.count
            },
            verify: {
                XCTAssertEqual(loaded.count, Self.messageCount)
            })
        try await measure("chat_open_window_decrypt_only",
            prepare: {
                displayed = []
                loaded = readStore.loadLatestMessageWindow(chatId: busyChatId)
            },
            body: {
                displayed = await Self.perFieldDecrypt(loaded, chatId: busyChatId, keyManager: keyManager)
                return displayed.count
            },
            verify: {
                XCTAssertEqual(displayed.count, ChatStore.boundedWindowSize)
                self.assertDisplayed(displayed, expected: fixture.expectedMessages)
            })
        try await measure("core_chat_open_window_decrypt_only",
            prepare: {
                displayed = []
                loaded = readStore.loadLatestMessageWindow(chatId: busyChatId)
            },
            body: {
                displayed = await ChatViewModel.decryptMessagesForDisplay(loaded, chatId: busyChatId)
                return displayed.count
            },
            verify: {
                XCTAssertEqual(displayed.count, ChatStore.boundedWindowSize)
                self.assertDisplayed(displayed, expected: fixture.expectedMessages)
            })
        try await measure("chat_open_full_1000_decrypt_only",
            prepare: {
                displayed = []
                loaded = readStore.loadMessages(chatId: busyChatId)
            },
            body: {
                displayed = await Self.perFieldDecrypt(loaded, chatId: busyChatId, keyManager: keyManager)
                return displayed.count
            },
            verify: {
                XCTAssertEqual(displayed.count, Self.messageCount)
                self.assertDisplayed(displayed, expected: fixture.expectedMessages)
            })
        try await measure("core_chat_open_full_1000_decrypt_only",
            prepare: {
                displayed = []
                loaded = readStore.loadMessages(chatId: busyChatId)
            },
            body: {
                displayed = await ChatViewModel.decryptMessagesForDisplay(loaded, chatId: busyChatId)
                return displayed.count
            },
            verify: {
                XCTAssertEqual(displayed.count, Self.messageCount)
                self.assertDisplayed(displayed, expected: fixture.expectedMessages)
            })

        let attachment = XCTAttachment(string: perfLines.joined(separator: "\n"))
        attachment.name = "apple-perf-summary"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    // MARK: - Measurement

    /// Runs `body` `runsPerPhase` times, each after an untimed `prepare` and before an
    /// untimed `verify`, and reports the median and minimum wall time.
    private func measure(
        _ name: String,
        prepare: () async throws -> Void,
        body: () async throws -> Int,
        verify: () throws -> Void
    ) async throws {
        let clock = ContinuousClock()
        var samples: [Int] = []
        var count = 0
        for _ in 0..<Self.runsPerPhase {
            try await prepare()
            let started = clock.now
            count = try await body()
            let elapsed = Self.milliseconds(started.duration(to: clock.now))
            samples.append(elapsed)
            try verify()
            XCTAssertLessThan(elapsed, Self.ceilingMilliseconds, "\(name) exceeded the generous ceiling")
        }
        let sorted = samples.sorted()
        let median = sorted[sorted.count / 2]
        let line = "APPLE_PERF name=\(name) ms=\(median) min_ms=\(sorted[0]) n=\(count)"
        print(line)
        perfLines.append(line)
        let attachment = XCTAttachment(string: line)
        attachment.name = "apple-perf-\(name)"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private static func milliseconds(_ duration: Duration) -> Int {
        let parts = duration.components
        return Int(parts.seconds) * 1000 + Int(parts.attoseconds / 1_000_000_000_000_000)
    }

    private func assertKeysLoaded(_ fixture: Fixture, _ keyManager: ChatKeyManager) {
        for entry in fixture.wrappedKeys { XCTAssertTrue(keyManager.hasKey(for: entry.chatId)) }
        XCTAssertTrue(keyManager.isReady)
    }

    private func assertChats(_ decryptedChats: [Chat], _ fixture: Fixture) {
        XCTAssertEqual(decryptedChats.count, fixture.chats.count)
        for chat in decryptedChats {
            let expected = fixture.expectedChats[chat.id]
            XCTAssertEqual(chat.title, expected?.title)
            XCTAssertEqual(chat.category, expected?.category)
            XCTAssertEqual(chat.icon, expected?.icon)
            XCTAssertEqual(chat.chatSummary, expected?.summary)
        }
    }

    /// Replay of the pre-A3 `ChatViewModel.decryptMessagesForDisplay` body: one
    /// main-actor `decryptMessageContent` call per message field.
    private static func perFieldDecrypt(_ messages: [Message], chatId: String,
                                        keyManager: ChatKeyManager) async -> [Message] {
        var result: [Message] = []
        result.reserveCapacity(messages.count)
        for var message in messages {
            if message.content?.isEmpty != false, let encrypted = message.encryptedContent,
               let value = await keyManager.decryptMessageContent(chatId: chatId, encryptedContent: encrypted) {
                message.content = value
            }
            if message.piiMappings == nil, let encrypted = message.encryptedPIIMappings,
               let json = await keyManager.decryptMessageContent(chatId: chatId, encryptedContent: encrypted),
               let data = json.data(using: .utf8),
               let mappings = try? JSONDecoder().decode([PIIMapping].self, from: data) {
                message.piiMappings = mappings
            }
            if message.thinkingContent == nil, let encrypted = message.encryptedThinkingContent {
                message.thinkingContent = await keyManager.decryptMessageContent(chatId: chatId, encryptedContent: encrypted)
            }
            if message.senderName == nil, let encrypted = message.encryptedSenderName {
                message.senderName = await keyManager.decryptMessageContent(chatId: chatId, encryptedContent: encrypted)
            }
            if message.category == nil, let encrypted = message.encryptedCategory {
                message.category = await keyManager.decryptMessageContent(chatId: chatId, encryptedContent: encrypted)
            }
            if message.modelName == nil, let encrypted = message.encryptedModelName {
                message.modelName = await keyManager.decryptMessageContent(chatId: chatId, encryptedContent: encrypted)
            }
            result.append(message)
        }
        return result
    }

    private func assertDisplayed(_ displayed: [Message], expected: [String: ExpectedMessage]) {
        for message in displayed {
            guard let want = expected[message.id] else {
                XCTFail("Unexpected message \(message.id)")
                continue
            }
            XCTAssertEqual(message.content, want.content)
            XCTAssertEqual(message.senderName, want.senderName)
            XCTAssertEqual(message.category, want.category)
            XCTAssertEqual(message.modelName, want.modelName)
            XCTAssertEqual(message.thinkingContent, want.thinking)
            XCTAssertEqual(message.piiMappings?.first?.original, want.piiOriginal)
        }
    }

    // MARK: - Stores

    private func makeTemporaryDirectory() throws -> URL {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("apple-perf-" + UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        temporaryDirectories.append(directory)
        return directory
    }

    private func makeStore() throws -> OfflineStore {
        let store = try OfflineStore(
            directory: try makeTemporaryDirectory(),
            userId: "perf-account-" + UUID().uuidString,
            apiBaseURL: URL(string: "https://synthetic.invalid")!)
        openedStores.append(store)
        return store
    }

    // MARK: - Fixture (generated with the real Swift crypto; excluded from timings)

    private static func isoTimestamp(_ offsetSeconds: Int) -> String {
        ISO8601DateFormatter().string(
            from: Date(timeIntervalSince1970: 1_790_000_000 + TimeInterval(offsetSeconds)))
    }

    private static func makeFixture() async throws -> Fixture {
        let crypto = CryptoManager.shared
        let master = SymmetricKey(size: .bits256)
        var chats: [Chat] = []
        var wrapped: [(chatId: String, encryptedChatKey: String)] = []
        var expectedChats: [String: ExpectedChatMetadata] = [:]
        var busyKey: SymmetricKey?
        let busyChatId = "perf-chat-0000"

        for index in 0..<chatCount {
            let chatId = String(format: "perf-chat-%04d", index)
            let chatKey = await crypto.generateChatKey()
            if index == 0 { busyKey = chatKey }
            let wrapper = try await crypto.wrapChatKey(chatKey, masterKey: master)
            let expected = ExpectedChatMetadata(
                title: "Synthetic chat \(index) title",
                category: "general_knowledge",
                icon: "message-circle",
                summary: "Synthetic summary for chat \(index): a short deterministic description of the topic.")
            expectedChats[chatId] = expected
            wrapped.append((chatId: chatId, encryptedChatKey: wrapper))
            chats.append(Chat(
                id: chatId, title: nil,
                lastMessageAt: isoTimestamp(-index * 60),
                createdAt: isoTimestamp(-index * 60 - 3600),
                updatedAt: isoTimestamp(-index * 60),
                lastEditedOverallTimestamp: isoTimestamp(-index * 60),
                isArchived: false, isPinned: false, appId: nil,
                encryptedTitle: try await crypto.encryptContent(expected.title, key: chatKey),
                encryptedCategory: try await crypto.encryptContent(expected.category, key: chatKey),
                encryptedIcon: try await crypto.encryptContent(expected.icon, key: chatKey),
                encryptedChatSummary: try await crypto.encryptContent(expected.summary, key: chatKey),
                encryptedChatKey: wrapper,
                messagesV: index == 0 ? messageCount : 2, titleV: 1, metadataV: 1))
        }

        let key = try XCTUnwrap(busyKey)
        var messages: [Message] = []
        var expectedMessages: [String: ExpectedMessage] = [:]
        for index in 0..<messageCount {
            let id = String(format: "perf-msg-%04d", index)
            let isUser = index.isMultiple(of: 2)
            let expected = ExpectedMessage(
                content: "Synthetic message \(index). " + String(repeating: "Lorem ipsum dolor sit amet. ", count: 14),
                senderName: isUser ? nil : "Synthetic Mate",
                category: isUser ? nil : "general_knowledge",
                modelName: isUser ? nil : "synthetic-model",
                thinking: isUser ? nil : "Synthetic reasoning for message \(index).",
                piiOriginal: isUser ? "user\(index)@example.org" : nil)
            expectedMessages[id] = expected
            let pii = isUser
                ? "[{\"placeholder\":\"[EMAIL_1]\",\"original\":\"\(expected.piiOriginal ?? "")\",\"type\":\"EMAIL\"}]"
                : nil
            messages.append(Message(
                id: id, chatId: busyChatId,
                role: isUser ? .user : .assistant,
                content: nil,
                encryptedContent: try await crypto.encryptContent(expected.content, key: key),
                createdAt: isoTimestamp(index), updatedAt: nil, appId: nil,
                isStreaming: false, embedRefs: nil,
                encryptedSenderName: try await expected.senderName.asyncMap { try await crypto.encryptContent($0, key: key) },
                encryptedCategory: try await expected.category.asyncMap { try await crypto.encryptContent($0, key: key) },
                encryptedModelName: try await expected.modelName.asyncMap { try await crypto.encryptContent($0, key: key) },
                encryptedPIIMappings: try await pii.asyncMap { try await crypto.encryptContent($0, key: key) },
                encryptedThinkingContent: try await expected.thinking.asyncMap { try await crypto.encryptContent($0, key: key) }))
        }

        return Fixture(masterKey: master, chats: chats, wrappedKeys: wrapped, expectedChats: expectedChats,
                       busyChatId: busyChatId, messages: messages, expectedMessages: expectedMessages)
    }
}

private extension Optional where Wrapped == String {
    @MainActor
    func asyncMap(_ transform: @MainActor (String) async throws -> String) async rethrows -> String? {
        guard let self else { return nil }
        return try await transform(self)
    }
}
