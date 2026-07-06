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
                Self.chat(id: "older", title: "Older", lastMessageAt: "2026-07-05T10:00:00Z"),
                Self.chat(id: "pinned", title: "Pinned", lastMessageAt: "2026-07-01T10:00:00Z", isPinned: true),
            ]
        )
        let runtime = WatchChatRuntime(api: api, cache: cache)

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
                savedAt: Date()
            )
        )
        let runtime = WatchChatRuntime(api: FakeWatchChatAPI(shouldThrow: true), cache: cache)

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
            chats: [chat],
            messagesByChatId: [
                "chat-a": [Self.message(id: "msg-a", chatId: "chat-a", content: "Remote")]
            ]
        )
        let runtime = WatchChatRuntime(api: api, cache: cache)

        await runtime.refresh()
        await runtime.openChat(chat)
        await runtime.queueLocalText("  Pending reply  ")

        XCTAssertEqual(runtime.selectedMessages.map(\.content), ["Remote", "Pending reply"])
        XCTAssertEqual(runtime.selectedMessages.last?.isPending, true)
        let cached = await cache.loadSnapshot()
        XCTAssertEqual(cached.messagesByChatId["chat-a"]?.last?.content, "Pending reply")
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
            isPinned: isPinned
        )
    }

    private static func message(id: String, chatId: String, content: String) -> WatchChatMessage {
        WatchChatMessage(
            id: id,
            chatId: chatId,
            role: .assistant,
            content: content,
            createdAt: "2026-07-06T10:00:00Z",
            isPending: false
        )
    }
}

private final class FakeWatchChatAPI: WatchChatAPI, @unchecked Sendable {
    private let shouldThrow: Bool
    private let chats: [WatchChatSummary]
    private let messagesByChatId: [String: [WatchChatMessage]]

    init(
        chats: [WatchChatSummary] = [],
        messagesByChatId: [String: [WatchChatMessage]] = [:],
        shouldThrow: Bool = false
    ) {
        self.chats = chats
        self.messagesByChatId = messagesByChatId
        self.shouldThrow = shouldThrow
    }

    func fetchRecentChats(limit: Int) async throws -> [WatchChatSummary] {
        if shouldThrow { throw URLError(.notConnectedToInternet) }
        return Array(chats.prefix(limit))
    }

    func fetchMessages(chatId: String) async throws -> [WatchChatMessage] {
        if shouldThrow { throw URLError(.notConnectedToInternet) }
        return messagesByChatId[chatId] ?? []
    }
}
