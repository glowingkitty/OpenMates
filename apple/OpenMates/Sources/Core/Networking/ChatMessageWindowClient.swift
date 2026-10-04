// Published v1 foreground viewing windows. These pages are not complete sync
// snapshots and must never advance offline-cohort completeness receipts.
// Reference: backend/core/api/app/routes/chats.py; openmates-cli/src/client.ts.
// Specification: specifications/architecture/storage-lifecycle/specification.yml
// Assertions: storage.surface.semantic-parity, storage.privacy.ciphertext-boundary
import Foundation

struct ChatMessageWindowCursor: Codable, Equatable, Sendable {
    let createdAt: Int
    let messageId: String
}

struct ChatMessageWindowQuery: Equatable, Sendable {
    enum Direction: String, Sendable { case latest, before, after, around }
    var direction: Direction = .latest
    var limit = 30
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
    let compressedMessageCount: Int?
    let summaryTokenEstimate: Int?
    let keyVersion: Int?
}

struct ChatMessageWindowPage: Decodable, Sendable {
    let chatId: String
    let messages: [Message]
    let hasMoreBefore: Bool
    let hasMoreAfter: Bool
    let startCursor: ChatMessageWindowCursor?
    let endCursor: ChatMessageWindowCursor?
    let anchorFound: Bool
    let serverMessageCount: Int?
    let messagesV: Int?
    let compressionBoundaryTimestamp: Int?
    let compressionCheckpoints: [ChatMessageWindowCheckpoint]
    let respectCompressionBoundary: Bool

    func validated(chatId expectedChatId: String, query: ChatMessageWindowQuery) throws -> Self {
        guard chatId == expectedChatId, messages.count <= query.limit,
              messagesV.map({ $0 >= 0 }) ?? true,
              serverMessageCount.map({ $0 >= 0 }) ?? true,
              respectCompressionBoundary == query.respectCompressionBoundary,
              Set(messages.map(\.id)).count == messages.count,
              messages.allSatisfy({ $0.chatId == chatId && !$0.id.isEmpty && !$0.createdAt.isEmpty
                  && $0.content == nil && !($0.encryptedContent?.isEmpty ?? true) }),
              compressionCheckpoints.allSatisfy({ $0.chatId == chatId }) else {
            throw ChatMessageWindowError.invalidResponse
        }
        if messages.isEmpty {
            guard startCursor == nil, endCursor == nil,
                  !(query.direction == .before ? hasMoreBefore : query.direction == .after ? hasMoreAfter : hasMoreBefore || hasMoreAfter)
            else { throw ChatMessageWindowError.invalidResponse }
        } else {
            guard let startCursor, let endCursor, startCursor.createdAt >= 0, endCursor.createdAt >= startCursor.createdAt,
                  startCursor.messageId == messages.first?.id, endCursor.messageId == messages.last?.id else {
                throw ChatMessageWindowError.invalidResponse
            }
            func precedes(_ lhs: ChatMessageWindowCursor, _ rhs: ChatMessageWindowCursor) -> Bool {
                lhs.createdAt == rhs.createdAt ? lhs.messageId < rhs.messageId : lhs.createdAt < rhs.createdAt
            }
            if query.direction == .before, let before = query.before, !precedes(endCursor, before) {
                throw ChatMessageWindowError.invalidResponse
            }
            if query.direction == .after, let after = query.after, !precedes(after, startCursor) {
                throw ChatMessageWindowError.invalidResponse
            }
            if query.direction == .around && anchorFound,
               !messages.contains(where: { $0.id == query.anchorMessageId }) { throw ChatMessageWindowError.invalidResponse }
        }
        return self
    }

    static func decode(_ data: Data, chatId: String, query: ChatMessageWindowQuery) throws -> Self {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(Self.self, from: data).validated(chatId: chatId, query: query)
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
    case invalidRequest, invalidResponse, staleContext, missingAccount
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
        return try ChatMessageWindowPage.decode(data, chatId: chatId, query: query)
    }
}

@MainActor
enum ChatMessageWindowClient {
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
