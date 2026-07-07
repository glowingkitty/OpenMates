// Unit coverage for the portable Watch chat runtime and offline cache.
// These tests avoid network, credentials, and message plaintext from real users.
// They lock down deterministic cache persistence, offline fallback behavior, and
// local pending message snapshots before watchOS UI tests exercise the shell.

import XCTest
@testable import OpenMates

@MainActor
final class WatchChatRuntimeTests: XCTestCase {
    func testOfflineCacheRoundTripsSnapshot() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let snapshot = WatchChatSnapshot(
            chats: [Self.chat(id: "chat-a", title: "Alpha", lastMessageAt: "2026-07-06T10:00:00Z")],
            messagesByChatId: ["chat-a": [Self.message(id: "msg-a", chatId: "chat-a", content: "Cached")]],
            pendingTextSends: [],
            savedAt: Date(timeIntervalSince1970: 1_783_337_600)
        )

        try await cache.saveSnapshot(snapshot)
        let loaded = await cache.loadSnapshot()

        XCTAssertEqual(loaded, snapshot)
    }

    func testRefreshFetchesChatsAndPersistsSortedSnapshot() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let api = FakeWatchChatAPI(
            chats: [
                Self.remoteChat(id: "older", title: "Older", lastMessageAt: "2026-07-05T10:00:00Z"),
                Self.remoteChat(id: "pinned", title: "Pinned", lastMessageAt: "2026-07-01T10:00:00Z", isPinned: true),
            ]
        )
        let runtime = WatchChatRuntime(api: api, cache: cache, crypto: FakeWatchChatCrypto())

        await runtime.refresh()

        XCTAssertEqual(runtime.chats.map(\.id), ["pinned", "older"])
        XCTAssertEqual(runtime.selectedChatId, "pinned")
        let cached = await cache.loadSnapshot()
        XCTAssertEqual(cached.chats.map(\.id), ["pinned", "older"])
    }

    func testRefreshFallsBackToCachedChatsWhenAPIThrows() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        try await cache.saveSnapshot(
            WatchChatSnapshot(
                chats: [Self.chat(id: "cached", title: "Cached", lastMessageAt: "2026-07-06T10:00:00Z")],
                messagesByChatId: [:],
                pendingTextSends: [],
                savedAt: Date()
            )
        )
        let runtime = WatchChatRuntime(api: FakeWatchChatAPI(shouldThrow: true), cache: cache, crypto: FakeWatchChatCrypto())

        await runtime.refresh()

        XCTAssertTrue(runtime.isOffline)
        XCTAssertEqual(runtime.chats.map(\.id), ["cached"])
    }

    func testOpenChatLoadsMessagesAndQueuedLocalTextPersists() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let chat = Self.chat(id: "chat-a", title: "Alpha", lastMessageAt: "2026-07-06T10:00:00Z")
        let api = FakeWatchChatAPI(
            chats: [Self.remoteChat(id: "chat-a", title: "Alpha", lastMessageAt: "2026-07-06T10:00:00Z")],
            messagesByChatId: [
                "chat-a": [Self.remoteMessage(id: "msg-a", chatId: "chat-a", content: "Remote")]
            ],
            shouldThrowOnSend: true
        )
        let runtime = WatchChatRuntime(api: api, cache: cache, crypto: FakeWatchChatCrypto())

        await runtime.refresh()
        await runtime.openChat(chat)
        await runtime.queueLocalText("  Pending reply  ")

        XCTAssertEqual(runtime.selectedMessages.map(\.content), ["Remote", "Pending reply"])
        XCTAssertEqual(runtime.selectedMessages.last?.isPending, true)
        let cached = await cache.loadSnapshot()
        XCTAssertEqual(cached.messagesByChatId["chat-a"]?.last?.content, "Pending reply")
        XCTAssertEqual(cached.pendingTextSends.count, 1)
    }

    func testQueuedLocalTextReplaysAndClearsPendingSnapshotWhenOnline() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let chat = Self.chat(id: "chat-a", title: "Alpha", lastMessageAt: "2026-07-06T10:00:00Z")
        let api = FakeWatchChatAPI(
            chats: [Self.remoteChat(id: "chat-a", title: "Alpha", lastMessageAt: "2026-07-06T10:00:00Z")],
            messagesByChatId: ["chat-a": []]
        )
        let runtime = WatchChatRuntime(api: api, cache: cache, crypto: FakeWatchChatCrypto())

        await runtime.refresh()
        await runtime.openChat(chat)
        await runtime.queueLocalText("Replay me")

        XCTAssertEqual(api.sentMessages.count, 1)
        XCTAssertEqual(runtime.selectedMessages.last?.isPending, false)
        let cached = await cache.loadSnapshot()
        XCTAssertEqual(cached.pendingTextSends.count, 0)
    }

    func testEncryptedRemoteFieldsAreDecryptedBeforeDisplay() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let api = FakeWatchChatAPI(
            chats: [
                Self.remoteChat(
                    id: "chat-a",
                    title: nil,
                    lastMessageAt: "2026-07-06T10:00:00Z",
                    encryptedTitle: "enc-title",
                    encryptedSummary: "enc-summary"
                )
            ],
            messagesByChatId: [
                "chat-a": [Self.remoteMessage(id: "msg-a", chatId: "chat-a", content: nil, encryptedContent: "enc-message")]
            ]
        )
        let crypto = FakeWatchChatCrypto(decryptedValues: [
            "enc-title": "Decrypted title",
            "enc-summary": "Decrypted summary",
            "enc-message": "Decrypted message",
        ])
        let runtime = WatchChatRuntime(api: api, cache: cache, crypto: crypto)

        await runtime.refresh()
        guard let chat = runtime.chats.first else {
            XCTFail("Expected decrypted chat")
            return
        }
        await runtime.openChat(chat)

        XCTAssertEqual(runtime.chats.first?.title, "Decrypted title")
        XCTAssertEqual(runtime.chats.first?.preview, "Decrypted summary")
        XCTAssertEqual(runtime.selectedMessages.first?.content, "Decrypted message")
    }

    func testRealtimeSyncUsesCachedWatchClientStateWithoutIncognitoChats() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let socket = FakeWatchChatSyncSocket()
        try await cache.saveSnapshot(
            WatchChatSnapshot(
                chats: [
                    Self.chat(id: "chat-a", title: "Alpha", lastMessageAt: "2026-07-06T10:00:00Z"),
                    Self.chat(id: "incognito-local", title: "Private", lastMessageAt: "2026-07-06T11:00:00Z"),
                ],
                messagesByChatId: [:],
                pendingTextSends: [],
                savedAt: Date()
            )
        )
        let runtime = WatchChatRuntime(
            api: FakeWatchChatAPI(),
            cache: cache,
            crypto: FakeWatchChatCrypto(),
            syncSocket: socket,
            syncSession: WatchSyncSession(sessionId: "watch-session", token: "watch-ws-token")
        )

        await runtime.loadCachedSnapshot()
        await runtime.startRealtimeSync()

        XCTAssertEqual(socket.connectedSession, WatchSyncSession(sessionId: "watch-session", token: "watch-ws-token"))
        XCTAssertEqual(socket.connectedSyncState?.clientChatIds, ["chat-a"])
        XCTAssertEqual(socket.connectedSyncState?.clientChatVersions, [:])
        XCTAssertEqual(socket.connectedSyncState?.clientEmbedIds, [])
    }

    private func temporaryDirectory() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("watch-chat-runtime-tests-\(UUID().uuidString)", isDirectory: true)
    }

    private static func chat(
        id: String,
        title: String,
        lastMessageAt: String,
        isPinned: Bool = false
    ) -> WatchChatSummary {
        WatchChatSummary(
            id: id,
            title: title,
            lastMessageAt: lastMessageAt,
            preview: nil,
            isPinned: isPinned,
            encryptedTitle: nil,
            encryptedPreview: nil,
            encryptedChatKey: "wrapped-chat-key"
        )
    }

    private static func message(id: String, chatId: String, content: String) -> WatchChatMessage {
        WatchChatMessage(
            id: id,
            chatId: chatId,
            role: .assistant,
            content: content,
            encryptedContent: nil,
            createdAt: "2026-07-06T10:00:00Z",
            isPending: false
        )
    }

    private static func remoteChat(
        id: String,
        title: String?,
        lastMessageAt: String,
        isPinned: Bool = false,
        encryptedTitle: String? = nil,
        encryptedSummary: String? = nil
    ) -> WatchRemoteChat {
        WatchRemoteChat(
            id: id,
            title: title,
            lastMessageAt: lastMessageAt,
            updatedAt: nil,
            chatSummary: nil,
            isPinned: isPinned,
            encryptedTitle: encryptedTitle,
            encryptedChatSummary: encryptedSummary,
            encryptedChatKey: "wrapped-chat-key"
        )
    }

    private static func remoteMessage(
        id: String,
        chatId: String,
        content: String?,
        encryptedContent: String? = nil
    ) -> WatchRemoteMessage {
        WatchRemoteMessage(
            id: id,
            chatId: chatId,
            role: .assistant,
            content: content,
            encryptedContent: encryptedContent,
            createdAt: "2026-07-06T10:00:00Z"
        )
    }
}

private final class FakeWatchChatAPI: WatchChatAPI, @unchecked Sendable {
    private let shouldThrow: Bool
    private let shouldThrowOnSend: Bool
    private let chats: [WatchRemoteChat]
    private let messagesByChatId: [String: [WatchRemoteMessage]]
    private(set) var sentMessages: [WatchPendingTextSend] = []

    init(
        chats: [WatchRemoteChat] = [],
        messagesByChatId: [String: [WatchRemoteMessage]] = [:],
        shouldThrow: Bool = false,
        shouldThrowOnSend: Bool = false
    ) {
        self.chats = chats
        self.messagesByChatId = messagesByChatId
        self.shouldThrow = shouldThrow
        self.shouldThrowOnSend = shouldThrowOnSend
    }

    func fetchRecentChats(limit: Int) async throws -> [WatchRemoteChat] {
        if shouldThrow { throw URLError(.notConnectedToInternet) }
        return Array(chats.prefix(limit))
    }

    func fetchMessages(chatId: String) async throws -> [WatchRemoteMessage] {
        if shouldThrow { throw URLError(.notConnectedToInternet) }
        return messagesByChatId[chatId] ?? []
    }

    func sendPendingText(_ pending: WatchPendingTextSend) async throws {
        if shouldThrow || shouldThrowOnSend { throw URLError(.notConnectedToInternet) }
        sentMessages.append(pending)
    }
}

@MainActor
private final class FakeWatchChatSyncSocket: WatchChatSyncSocket {
    private(set) var connectedSession: WatchSyncSession?
    private(set) var connectedSyncState: SyncClientState?
    private(set) var didDisconnect = false

    func connect(session: WatchSyncSession, syncState: SyncClientState) {
        connectedSession = session
        connectedSyncState = syncState
    }

    func disconnect() {
        didDisconnect = true
    }
}

@MainActor
private final class FakeWatchChatCrypto: WatchChatCrypto {
    private let decryptedValues: [String: String]

    init(decryptedValues: [String: String] = [:]) {
        self.decryptedValues = decryptedValues
    }

    func decryptChat(_ chat: WatchRemoteChat) async -> WatchChatSummary {
        WatchChatSummary(
            id: chat.id,
            title: chat.encryptedTitle.flatMap { decryptedValues[$0] } ?? chat.title,
            lastMessageAt: chat.lastMessageAt ?? chat.updatedAt,
            preview: chat.encryptedChatSummary.flatMap { decryptedValues[$0] } ?? chat.chatSummary,
            isPinned: chat.isPinned,
            encryptedTitle: chat.encryptedTitle,
            encryptedPreview: chat.encryptedChatSummary,
            encryptedChatKey: chat.encryptedChatKey
        )
    }

    func decryptMessage(_ message: WatchRemoteMessage) async -> WatchChatMessage {
        WatchChatMessage(
            id: message.id,
            chatId: message.chatId,
            role: message.role,
            content: message.encryptedContent.flatMap { decryptedValues[$0] } ?? message.content,
            encryptedContent: message.encryptedContent,
            createdAt: message.createdAt,
            isPending: false
        )
    }

    func encryptText(_ text: String, for chat: WatchChatSummary) async throws -> String {
        "encrypted:\(text)"
    }
}
