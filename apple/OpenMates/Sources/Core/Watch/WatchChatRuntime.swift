// Watch chat runtime and offline cache.
// Provides the portable data layer for the standalone watchOS chat shell while
// staying small enough to unit test from the existing Apple unit-test target.
// The runtime fetches recent chats/messages directly from the backend and keeps
// a Watch-local JSON snapshot for offline startup. Encryption-aware display is
// completed by later Watch sync slices; this layer never logs plaintext.

import Foundation
import SwiftUI

struct WatchChatSummary: Codable, Equatable, Identifiable, Sendable {
    let id: String
    var title: String?
    var lastMessageAt: String?
    var preview: String?
    var isPinned: Bool
}

struct WatchChatMessage: Codable, Equatable, Identifiable, Sendable {
    enum Role: String, Codable, Sendable {
        case user
        case assistant
        case system
    }

    let id: String
    let chatId: String
    let role: Role
    var content: String?
    let createdAt: String
    var isPending: Bool
}

struct WatchChatSnapshot: Codable, Equatable, Sendable {
    var chats: [WatchChatSummary]
    var messagesByChatId: [String: [WatchChatMessage]]
    var savedAt: Date

    static let empty = WatchChatSnapshot(chats: [], messagesByChatId: [:], savedAt: .distantPast)
}

protocol WatchChatAPI: Sendable {
    func fetchRecentChats(limit: Int) async throws -> [WatchChatSummary]
    func fetchMessages(chatId: String) async throws -> [WatchChatMessage]
}

actor WatchChatOfflineCache {
    private let fileURL: URL
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    init(directory: URL = Self.defaultDirectory()) {
        self.fileURL = directory.appendingPathComponent("watch-chat-snapshot.json")
        self.encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        self.decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
    }

    func loadSnapshot() -> WatchChatSnapshot {
        guard let data = try? Data(contentsOf: fileURL),
              let snapshot = try? decoder.decode(WatchChatSnapshot.self, from: data) else {
            return .empty
        }
        return snapshot
    }

    func saveSnapshot(_ snapshot: WatchChatSnapshot) throws {
        try FileManager.default.createDirectory(
            at: fileURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        let data = try encoder.encode(snapshot)
        try data.write(to: fileURL, options: [.atomic])
    }

    func removeSnapshot() throws {
        guard FileManager.default.fileExists(atPath: fileURL.path) else { return }
        try FileManager.default.removeItem(at: fileURL)
    }

    static func defaultDirectory() -> URL {
        FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("OpenMatesWatch", isDirectory: true)
    }
}

@MainActor
final class WatchChatRuntime: ObservableObject {
    @Published private(set) var chats: [WatchChatSummary] = []
    @Published private(set) var messagesByChatId: [String: [WatchChatMessage]] = [:]
    @Published var selectedChatId: String?
    @Published private(set) var isSyncing = false
    @Published private(set) var isOffline = false
    @Published private(set) var errorMessage: String?

    private let api: any WatchChatAPI
    private let cache: WatchChatOfflineCache

    init(api: any WatchChatAPI = APIClient.shared, cache: WatchChatOfflineCache = WatchChatOfflineCache()) {
        self.api = api
        self.cache = cache
    }

    var selectedChat: WatchChatSummary? {
        guard let selectedChatId else { return nil }
        return chats.first { $0.id == selectedChatId }
    }

    var selectedMessages: [WatchChatMessage] {
        guard let selectedChatId else { return [] }
        return messagesByChatId[selectedChatId] ?? []
    }

    func loadCachedSnapshot() async {
        apply(await cache.loadSnapshot())
    }

    func refresh() async {
        isSyncing = true
        errorMessage = nil
        if chats.isEmpty {
            await loadCachedSnapshot()
        }

        do {
            let fetchedChats = try await api.fetchRecentChats(limit: 20)
            chats = Self.sortedChats(fetchedChats)
            if selectedChatId == nil {
                selectedChatId = chats.first?.id
            }
            isOffline = false
            try await persistSnapshot()
        } catch {
            isOffline = true
            errorMessage = error.localizedDescription
            if chats.isEmpty {
                await loadCachedSnapshot()
            }
        }
        isSyncing = false
    }

    func openChat(_ chat: WatchChatSummary) async {
        selectedChatId = chat.id
        if messagesByChatId[chat.id] == nil {
            await loadCachedSnapshot()
        }

        do {
            let messages = try await api.fetchMessages(chatId: chat.id)
            messagesByChatId[chat.id] = Self.sortedMessages(messages)
            isOffline = false
            errorMessage = nil
            try await persistSnapshot()
        } catch {
            isOffline = true
            errorMessage = error.localizedDescription
        }
    }

    func queueLocalText(_ content: String) async {
        let trimmed = content.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, let selectedChatId else { return }
        let pending = WatchChatMessage(
            id: "pending-\(UUID().uuidString)",
            chatId: selectedChatId,
            role: .user,
            content: trimmed,
            createdAt: ISO8601DateFormatter().string(from: Date()),
            isPending: true
        )
        var messages = messagesByChatId[selectedChatId] ?? []
        messages.append(pending)
        messagesByChatId[selectedChatId] = Self.sortedMessages(messages)
        try? await persistSnapshot()
    }

    private func apply(_ snapshot: WatchChatSnapshot) {
        chats = Self.sortedChats(snapshot.chats)
        messagesByChatId = snapshot.messagesByChatId.mapValues(Self.sortedMessages)
        if selectedChatId == nil {
            selectedChatId = chats.first?.id
        }
    }

    private func persistSnapshot() async throws {
        try await cache.saveSnapshot(
            WatchChatSnapshot(chats: chats, messagesByChatId: messagesByChatId, savedAt: Date())
        )
    }

    private static func sortedChats(_ chats: [WatchChatSummary]) -> [WatchChatSummary] {
        chats.sorted { lhs, rhs in
            if lhs.isPinned != rhs.isPinned { return lhs.isPinned && !rhs.isPinned }
            return (lhs.lastMessageAt ?? "") > (rhs.lastMessageAt ?? "")
        }
    }

    private static func sortedMessages(_ messages: [WatchChatMessage]) -> [WatchChatMessage] {
        messages.sorted { $0.createdAt < $1.createdAt }
    }
}

extension APIClient: WatchChatAPI {
    func fetchRecentChats(limit: Int) async throws -> [WatchChatSummary] {
        let response: WatchChatListEnvelope = try await request(.get, path: "/v1/chats?limit=\(limit)")
        return response.chats.map(WatchChatSummary.init(dto:))
    }

    func fetchMessages(chatId: String) async throws -> [WatchChatMessage] {
        let response: [WatchChatMessageDTO] = try await request(.get, path: "/v1/chats/\(chatId)/messages")
        return response.map(WatchChatMessage.init(dto:))
    }
}

private struct WatchChatListEnvelope: Decodable {
    let chats: [WatchChatDTO]
}

private struct WatchChatDTO: Decodable {
    let id: String
    let title: String?
    let lastMessageAt: String?
    let updatedAt: String?
    let chatSummary: String?
    let isPinned: Bool?

    private enum CodingKeys: String, CodingKey {
        case id
        case chatId = "chat_id"
        case title
        case lastMessageAt
        case lastMessageAtSnake = "last_message_at"
        case updatedAt
        case updatedAtSnake = "updated_at"
        case chatSummary
        case chatSummarySnake = "chat_summary"
        case isPinned
        case isPinnedSnake = "is_pinned"
        case pinned
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decodeIfPresent(String.self, forKey: .id)
            ?? container.decode(String.self, forKey: .chatId)
        title = try container.decodeIfPresent(String.self, forKey: .title)
        lastMessageAt = try container.decodeIfPresent(String.self, forKey: .lastMessageAt)
            ?? container.decodeIfPresent(String.self, forKey: .lastMessageAtSnake)
        updatedAt = try container.decodeIfPresent(String.self, forKey: .updatedAt)
            ?? container.decodeIfPresent(String.self, forKey: .updatedAtSnake)
        chatSummary = try container.decodeIfPresent(String.self, forKey: .chatSummary)
            ?? container.decodeIfPresent(String.self, forKey: .chatSummarySnake)
        isPinned = try container.decodeIfPresent(Bool.self, forKey: .isPinned)
            ?? container.decodeIfPresent(Bool.self, forKey: .isPinnedSnake)
            ?? container.decodeIfPresent(Bool.self, forKey: .pinned)
    }
}

private struct WatchChatMessageDTO: Decodable {
    let id: String
    let chatId: String
    let role: WatchChatMessage.Role
    let content: String?
    let createdAt: String

    private enum CodingKeys: String, CodingKey {
        case id
        case messageId = "message_id"
        case chatId
        case chatIdSnake = "chat_id"
        case role
        case content
        case createdAt
        case createdAtSnake = "created_at"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decodeIfPresent(String.self, forKey: .id)
            ?? container.decode(String.self, forKey: .messageId)
        chatId = try container.decodeIfPresent(String.self, forKey: .chatId)
            ?? container.decode(String.self, forKey: .chatIdSnake)
        role = try container.decode(WatchChatMessage.Role.self, forKey: .role)
        content = try container.decodeIfPresent(String.self, forKey: .content)
        createdAt = try container.decodeIfPresent(String.self, forKey: .createdAt)
            ?? container.decodeIfPresent(String.self, forKey: .createdAtSnake)
            ?? ""
    }
}

private extension WatchChatSummary {
    init(dto: WatchChatDTO) {
        self.init(
            id: dto.id,
            title: dto.title,
            lastMessageAt: dto.lastMessageAt ?? dto.updatedAt,
            preview: dto.chatSummary,
            isPinned: dto.isPinned == true
        )
    }
}

private extension WatchChatMessage {
    init(dto: WatchChatMessageDTO) {
        self.init(
            id: dto.id,
            chatId: dto.chatId,
            role: dto.role,
            content: dto.content,
            createdAt: dto.createdAt,
            isPending: false
        )
    }
}
