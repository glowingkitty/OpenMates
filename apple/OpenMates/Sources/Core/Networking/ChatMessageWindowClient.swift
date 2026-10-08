// Published v1 foreground viewing windows. These pages are not complete sync
// snapshots and must never advance offline-cohort completeness receipts.
// Reference: backend/core/api/app/routes/chats.py; openmates-cli/src/client.ts.
// Specification: specifications/architecture/storage-lifecycle/specification.yml
// Assertions: storage.surface.semantic-parity, storage.privacy.ciphertext-boundary, storage.cold.independent-message-pages, storage.compression.incremental-archive
import Foundation

struct ChatMessageWindowCursor: Codable, Equatable, Sendable {
    let createdAt: Int
    let messageId: String
}

struct ChatMessageWindowQuery: Equatable, Sendable {
    enum Direction: String, Sendable { case latest, before, after, around }
    var direction: Direction = .latest
    var limit = 20
    var before: ChatMessageWindowCursor?
    var after: ChatMessageWindowCursor?
    var anchorMessageId: String?
    var respectCompressionBoundary = true
    // Published v1 permits an after-timestamp without an ID for the first page.
    var afterBeginning = false

    func path(chatId: String, teamId: String?) throws -> String {
        guard !chatId.isEmpty, !chatId.contains("/"), (1...100).contains(limit),
              direction != .before || before != nil,
              direction != .after || after != nil || afterBeginning,
              direction != .around || !(anchorMessageId?.isEmpty ?? true),
              before.map({ !$0.messageId.isEmpty && $0.createdAt >= 0 }) ?? true,
              after.map({ !$0.messageId.isEmpty && $0.createdAt >= 0 }) ?? true else {
            throw ChatMessageWindowError.invalidRequest
        }
        var components = URLComponents()
        components.path = "/v1/chats/\(chatId)/messages/window"
        var items = [URLQueryItem(name: "direction", value: direction.rawValue),
                     URLQueryItem(name: "limit", value: String(limit)),
                     URLQueryItem(name: "respect_compression_boundary", value: String(respectCompressionBoundary))]
        if let before {
            items += [.init(name: "before_timestamp", value: String(before.createdAt)),
                      .init(name: "before_message_id", value: before.messageId)]
        }
        if let after {
            items += [.init(name: "after_timestamp", value: String(after.createdAt)),
                      .init(name: "after_message_id", value: after.messageId)]
        } else if afterBeginning { items.append(.init(name: "after_timestamp", value: "0")) }
        if let anchorMessageId { items.append(.init(name: "anchor_message_id", value: anchorMessageId)) }
        if let teamId { items.append(.init(name: "team_id", value: teamId)) }
        components.queryItems = items
        guard let path = components.string else { throw ChatMessageWindowError.invalidRequest }
        return path
    }
}

struct ChatMessageWindowCheckpoint: Decodable, Sendable {
    let id: String
    let chatId: String
    let encryptedSummary: String?
    let compressedUpToTimestamp: Int?
    let compressedUpToMessageId: String?
    let coveredMessageIds: [String]?
    let compressedMessageCount: Int?
    let summaryTokenEstimate: Int?
    let keyVersion: Int?
}

struct ChatMessageWindowPage: Decodable, Sendable {
    let chatId: String
    var messages: [Message]
    let hasMoreBefore: Bool
    let hasMoreAfter: Bool
    var startCursor: ChatMessageWindowCursor?
    var endCursor: ChatMessageWindowCursor?
    let anchorFound: Bool
    let serverMessageCount: Int?
    let messagesV: Int?
    let compressionBoundaryTimestamp: Int?
    let compressionCheckpoints: [ChatMessageWindowCheckpoint]
    let respectCompressionBoundary: Bool

    let oversizedMessage: Bool?
    let oversizedMessageCursor: ChatMessageWindowCursor?
    let payloadBytes: Int?
    // Local proof that the separately addressed row passed exact-read validation.
    var resolvedOversizedMessage = false
    var decryptedProjection: [Message] = []
    private enum CodingKeys: String, CodingKey {
        case chatId, messages, hasMoreBefore, hasMoreAfter, startCursor, endCursor, anchorFound
        case serverMessageCount, messagesV, compressionBoundaryTimestamp, compressionCheckpoints
        case respectCompressionBoundary, oversizedMessage, oversizedMessageCursor, payloadBytes
    }

    static func timestamp(_ value: String) -> TimeInterval? {
        if let seconds = Double(value) { return seconds }
        let date = (try? Date.ISO8601FormatStyle().parse(value))
            ?? (try? Date.ISO8601FormatStyle(includingFractionalSeconds: true).parse(value))
        return date?.timeIntervalSince1970
    }

    static func cursor(for message: Message) throws -> ChatMessageWindowCursor {
        let seconds = Self.timestamp(message.createdAt)
        guard let seconds, seconds.isFinite, seconds >= 0, seconds < Double(Int.max) else {
            throw ChatMessageWindowError.invalidResponse
        }
        return .init(createdAt: Int(seconds), messageId: message.id)
    }

    static func precedes(_ lhs: ChatMessageWindowCursor, _ rhs: ChatMessageWindowCursor) -> Bool {
        lhs.createdAt == rhs.createdAt ? lhs.messageId < rhs.messageId : lhs.createdAt < rhs.createdAt
    }

    func validated(chatId expectedChatId: String, query: ChatMessageWindowQuery) throws -> Self {
        guard chatId == expectedChatId, messages.count <= min(query.limit, 20),
              payloadBytes.map({ (0...256 * 1024).contains($0) }) ?? true,
              messages.reduce(0, { $0 + ($1.encryptedContent?.utf8.count ?? 0) }) <= (resolvedOversizedMessage ? 2 * 1024 * 1024 : 256 * 1024),
              messagesV.map({ $0 >= 0 }) ?? true,
              serverMessageCount.map({ $0 >= 0 }) ?? true,
              respectCompressionBoundary == query.respectCompressionBoundary,
              Set(messages.map(\.id)).count == messages.count,
              messages.allSatisfy({ $0.chatId == chatId && !$0.id.isEmpty && !$0.createdAt.isEmpty
                  && $0.content == nil && !($0.encryptedContent?.isEmpty ?? true) }),
              compressionCheckpoints.allSatisfy({ $0.chatId == chatId && !$0.id.isEmpty
                  && ($0.coveredMessageIds.map { !$0.isEmpty && Set($0).count == $0.count && $0.allSatisfy { !$0.isEmpty } } ?? true) }) else {
            throw ChatMessageWindowError.invalidResponse
        }
        let cursors = try messages.map(Self.cursor)
        guard zip(cursors, cursors.dropFirst()).allSatisfy({ Self.precedes($0.0, $0.1) }) else {
            throw ChatMessageWindowError.invalidResponse
        }
        if let oversizedMessageCursor {
            guard oversizedMessage == true, oversizedMessageCursor.createdAt >= 0,
                  !oversizedMessageCursor.messageId.isEmpty,
                  messages.isEmpty || resolvedOversizedMessage else { throw ChatMessageWindowError.invalidResponse }
            if query.direction == .before, let before = query.before,
               !Self.precedes(oversizedMessageCursor, before) { throw ChatMessageWindowError.invalidResponse }
            if query.direction == .after, let after = query.after,
               !Self.precedes(after, oversizedMessageCursor) { throw ChatMessageWindowError.invalidResponse }
            if query.direction == .around && anchorFound,
               oversizedMessageCursor.messageId != query.anchorMessageId { throw ChatMessageWindowError.invalidResponse }
        } else if oversizedMessage == true { throw ChatMessageWindowError.invalidResponse }
        if messages.isEmpty {
            guard startCursor == nil, endCursor == nil,
                  oversizedMessageCursor != nil || !(query.direction == .before ? hasMoreBefore : query.direction == .after ? hasMoreAfter : hasMoreBefore || hasMoreAfter)
            else { throw ChatMessageWindowError.invalidResponse }
        } else {
            guard let startCursor, let endCursor, startCursor.createdAt >= 0, endCursor.createdAt >= startCursor.createdAt,
                  startCursor == cursors.first, endCursor == cursors.last else {
                throw ChatMessageWindowError.invalidResponse
            }
            if query.direction == .before, let before = query.before, !Self.precedes(endCursor, before) {
                throw ChatMessageWindowError.invalidResponse
            }
            if query.direction == .after, let after = query.after, !Self.precedes(after, startCursor) {
                throw ChatMessageWindowError.invalidResponse
            }
            if query.direction == .around && anchorFound,
               !messages.contains(where: { $0.id == query.anchorMessageId }) { throw ChatMessageWindowError.invalidResponse }
        }
        return self
    }

    static func decode(_ data: Data, chatId: String, query: ChatMessageWindowQuery) throws -> Self {
        guard data.count <= 512 * 1024 else { throw ChatMessageWindowError.invalidResponse }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(Self.self, from: data).validated(chatId: chatId, query: query)
    }

    /// Foreground eviction never changes the durable offline store or pending writes.
    /// Stop at the first budget limit so retained saved rows remain contiguous.
    @MainActor static func retainedForeground(_ source: [Message], newest: Bool, pendingIds: Set<String>,
        maximumCount: Int = 200, maximumBytes: Int = 8 * 1024 * 1024) -> [Message] {
        func protected(_ row: Message) -> Bool {
            row.isStreaming == true || pendingIds.contains(row.id)
                || (row.encryptedContent == nil && row.content != nil)
        }
        let ordered = merge([], preserving: source)
        let ordinary = ordered.filter { !protected($0) }
        var selected: [Message] = [], bytes = 0
        for row in newest ? Array(ordinary.reversed()) : ordinary {
            let size = [row.encryptedContent, row.content, row.encryptedThinkingContent,
                        row.thinkingContent, row.encryptedPIIMappings].compactMap { $0 }.reduce(0) { $0 + $1.utf8.count }
            guard selected.count < maximumCount, size <= maximumBytes - bytes else { break }
            selected.append(row); bytes += size
        }
        return merge(selected, preserving: ordered.filter(protected))
    }

    /// A partial page updates only its stable identities. Absence says nothing
    /// about other rows or pending local work; active streams keep their body.
    @MainActor static func merge(_ page: [Message], preserving current: [Message], pendingIds: Set<String> = []) -> [Message] {
        var byId = Dictionary(current.map { ($0.id, $0) }, uniquingKeysWith: { _, last in last })
        for incoming in page {
            let alias = incoming.serverMessageId.flatMap { byId[$0] }
            let local = byId[incoming.id] ?? alias
            if let local, local.isStreaming == true || pendingIds.contains(local.id) { continue }
            if let alias, alias.id != incoming.id, alias.chatId == incoming.chatId, alias.role == incoming.role {
                byId.removeValue(forKey: alias.id)
            }
            byId[incoming.id] = ChatCompletionRecoveryCoordinator.mergingRecoveredMessage(incoming, preserving: local)
        }
        return byId.values.sorted { $0.createdAt == $1.createdAt ? $0.id < $1.id : $0.createdAt < $1.createdAt }
    }
}

enum ChatMessageWindowError: Error {
    case invalidRequest, invalidResponse, staleContext, missingAccount, decryptionFailed
}


struct ChatWrapperWindowPage: Decodable, Sendable {
    let wrappers: [ChatKeyWrapperRecord]
    let hasMoreBefore: Bool
    let startCursor: String?
    let oversizedWrapperId: String?
    let payloadBytes: Int?

    func validated(chatId: String, beforeId: String?, exactWrapperId: String?) throws -> Self {
        let ids = wrappers.compactMap(\.id)
        guard wrappers.count <= (exactWrapperId == nil ? 20 : 1), ids.count == wrappers.count,
              Set(ids).count == ids.count,
              wrappers.allSatisfy({ $0.hashedChatId == ChatKeyWrapperRecord.hashedChatId(for: chatId)
                  && !$0.encryptedChatKey.isEmpty && $0.id?.isEmpty == false }),
              payloadBytes.map({ $0 >= 0 && $0 <= 64 * 1024 }) ?? true else { throw ChatMessageWindowError.invalidResponse }
        if let exactWrapperId {
            guard ids == [exactWrapperId], !hasMoreBefore, startCursor == nil, oversizedWrapperId == nil else { throw ChatMessageWindowError.invalidResponse }
        } else {
            guard zip(ids, ids.dropFirst()).allSatisfy({ $0.0 > $0.1 }),
                  beforeId.map({ before in ids.allSatisfy { $0 < before } }) ?? true,
                  startCursor == ids.last,
                  !hasMoreBefore || startCursor != nil || oversizedWrapperId != nil else { throw ChatMessageWindowError.invalidResponse }
            if let oversizedWrapperId {
                guard wrappers.isEmpty, !oversizedWrapperId.isEmpty, hasMoreBefore,
                      beforeId.map({ oversizedWrapperId < $0 }) ?? true else { throw ChatMessageWindowError.invalidResponse }
            }
        }
        return self
    }
}

struct ChatWindowMessageDeletion: Decodable { let chatId: String; let messageId: String }

extension APIClient {
    /// Context parameters use the existing authenticated request fence. Nil
    /// context remains useful for isolated URLProtocol contract fixtures.
    func chatMessageWindow(chatId: String, teamId: String?, query: ChatMessageWindowQuery,
        serverProfile: ServerProfile, expectedAccountId: String? = nil, expectedScope: UUID? = nil,
        expectedTeamContext: APIRequestTeamContext? = nil) async throws -> ChatMessageWindowPage {
        let data: Data = try await request(.get, path: query.path(chatId: chatId, teamId: teamId),
            serverProfile: serverProfile, expectedAccountID: expectedAccountId,
            expectedScope: expectedScope, expectedTeamContext: expectedTeamContext)
        var page = try ChatMessageWindowPage.decode(data, chatId: chatId, query: query)
        if let cursor = page.oversizedMessageCursor {
            let message = try await exactChatMessage(chatId: chatId, messageId: cursor.messageId, teamId: teamId,
                serverProfile: serverProfile, expectedAccountId: expectedAccountId, expectedScope: expectedScope,
                expectedTeamContext: expectedTeamContext)
            guard try ChatMessageWindowPage.cursor(for: message) == cursor else { throw ChatMessageWindowError.invalidResponse }
            page.messages = [message]; page.startCursor = cursor; page.endCursor = cursor
            page.resolvedOversizedMessage = true
        }
        return try page.validated(chatId: chatId, query: query)
    }

    func chatWrapperWindow(chatId: String, teamId: String?, beforeId: String? = nil, exactWrapperId: String? = nil,
        serverProfile: ServerProfile, expectedAccountId: String? = nil, expectedScope: UUID? = nil,
        expectedTeamContext: APIRequestTeamContext? = nil) async throws -> ChatWrapperWindowPage {
        guard !chatId.isEmpty, !chatId.contains("/"), beforeId == nil || exactWrapperId == nil else { throw ChatMessageWindowError.invalidRequest }
        var url = URLComponents(); url.path = "/v1/chats/\(chatId)/wrappers/window"
        var items: [URLQueryItem] = []
        if let teamId { items.append(.init(name: "team_id", value: teamId)) }
        if let beforeId { items.append(.init(name: "before_id", value: beforeId)) }
        if let exactWrapperId { items.append(.init(name: "wrapper_id", value: exactWrapperId)) }
        url.queryItems = items
        guard let path = url.string else { throw ChatMessageWindowError.invalidRequest }
        let data: Data = try await request(.get, path: path, serverProfile: serverProfile,
            expectedAccountID: expectedAccountId, expectedScope: expectedScope, expectedTeamContext: expectedTeamContext)
        guard data.count <= (exactWrapperId == nil ? 128 * 1024 : 2 * 1024 * 1024) else { throw ChatMessageWindowError.invalidResponse }
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(ChatWrapperWindowPage.self, from: data).validated(chatId: chatId, beforeId: beforeId, exactWrapperId: exactWrapperId)
    }

    func exactChatMessage(chatId: String, messageId: String, teamId: String?, serverProfile: ServerProfile,
        expectedAccountId: String? = nil, expectedScope: UUID? = nil,
        expectedTeamContext: APIRequestTeamContext? = nil) async throws -> Message {
        guard !chatId.isEmpty, !chatId.contains("/"), !messageId.isEmpty, !messageId.contains("/") else {
            throw ChatMessageWindowError.invalidRequest
        }
        var url = URLComponents(); url.path = "/v1/chats/\(chatId)/messages/\(messageId)"
        if let teamId { url.queryItems = [.init(name: "team_id", value: teamId)] }
        guard let path = url.string else { throw ChatMessageWindowError.invalidRequest }
        let data: Data = try await request(.get, path: path, serverProfile: serverProfile,
            expectedAccountID: expectedAccountId, expectedScope: expectedScope, expectedTeamContext: expectedTeamContext)
        // Reject over-budget legacy content. A 413 propagates as a visible retryable read failure.
        guard data.count <= 2 * 1024 * 1024 + 4096 else { throw ChatMessageWindowError.invalidResponse }
        struct Envelope: Decodable { let message: Message }
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        let message = try decoder.decode(Envelope.self, from: data).message
        guard message.id == messageId, message.chatId == chatId, message.content == nil,
              message.encryptedContent?.isEmpty == false,
              (message.encryptedContent?.utf8.count ?? 0) <= 2 * 1024 * 1024 else { throw ChatMessageWindowError.invalidResponse }
        return message
    }
}

@MainActor
enum ChatMessageWindowClient {
    static func fetchWrappers(chatId: String, teamId: String?, beforeId: String? = nil,
                              exactWrapperId: String? = nil, expectedOwnerId: String? = nil) async throws -> ChatWrapperWindowPage {
        let profile = ServerProfile.current(), scope = OfflineStore.shared.scopeGeneration
        let team = TeamWorkspaceContext.shared.snapshot
        let deletion = OfflineStore.shared.chatDeletionVersion(chatId)
        guard team.teamID == teamId, let owner = await AuthManager.currentUserId(),
              expectedOwnerId == nil || expectedOwnerId == owner else { throw ChatMessageWindowError.missingAccount }
        func validate() throws {
            guard !Task.isCancelled, profile == ServerProfile.current(), scope == OfflineStore.shared.scopeGeneration,
                  TeamWorkspaceContext.shared.isCurrent(team), OfflineStore.shared.chatDeletionVersion(chatId) == deletion else { throw ChatMessageWindowError.staleContext }
        }
        try validate()
        let page = try await APIClient.shared.chatWrapperWindow(chatId: chatId, teamId: teamId, beforeId: beforeId,
            exactWrapperId: exactWrapperId, serverProfile: profile, expectedAccountId: owner, expectedScope: scope,
            expectedTeamContext: .init(epoch: team.epoch, teamID: teamId))
        try validate()
        guard await AuthManager.currentUserId() == owner else { throw ChatMessageWindowError.staleContext }
        try validate()
        return page
    }

    static func fetch(chatId: String, teamId: String?, query: ChatMessageWindowQuery,
                      expectedOwnerId: String? = nil) async throws -> ChatMessageWindowPage {
        let profile = ServerProfile.current(), scope = OfflineStore.shared.scopeGeneration
        let team = TeamWorkspaceContext.shared.snapshot
        let deletion = OfflineStore.shared.chatDeletionVersion(chatId)
        guard team.teamID == teamId, let owner = await AuthManager.currentUserId(),
              expectedOwnerId == nil || expectedOwnerId == owner else { throw ChatMessageWindowError.missingAccount }
        func validate() throws {
            guard !Task.isCancelled, profile == ServerProfile.current(), scope == OfflineStore.shared.scopeGeneration,
                  TeamWorkspaceContext.shared.isCurrent(team),
                  OfflineStore.shared.chatDeletionVersion(chatId) == deletion else { throw ChatMessageWindowError.staleContext }
        }
        try validate()
        let page = try await APIClient.shared.chatMessageWindow(chatId: chatId, teamId: teamId, query: query,
            serverProfile: profile, expectedAccountId: owner, expectedScope: scope,
            expectedTeamContext: .init(epoch: team.epoch, teamID: teamId))
        try validate()
        guard await AuthManager.currentUserId() == owner else { throw ChatMessageWindowError.staleContext }
        try validate()
        return page
    }
}
