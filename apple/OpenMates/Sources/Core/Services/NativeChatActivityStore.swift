// Specification: specifications/features/chat-navigation/specification.yml
// Assertions: chat-navigation.projects.nested-readable, chat-navigation.activity.global-running, chat-navigation.projects.organize
// Web source: services/chatSyncService.ts, stores/chatActivityStore.ts
// Specification: specifications/features/projects/specification.yml
// Assertions: projects.surface.semantic-parity, projects.access.explicit-context
import Foundation
import Combine

/// Activity is a workspace concern; notification preferences never gate sidebar state.
@MainActor
final class NativeChatActivityStore: ObservableObject {
    static let shared = NativeChatActivityStore()
    @Published private(set) var processingIDs: Set<String> = []
    @Published private(set) var ancestry: [String: String] = [:]
    private(set) var policy = ActiveChatsPolicy()
    private var accountID: String?
    private var scope: UUID?
    private var server: ServerProfile?
    private var teamID: String?
    private var teamEpoch: UInt64 = 0
    private var revision = 0
    private var refreshRequest: UUID?

    func configure(accountID: String?, scope: UUID, server: ServerProfile, teamID: String?, teamEpoch: UInt64 = 0) {
        guard self.accountID != accountID || self.scope != scope || self.server != server || self.teamID != teamID || self.teamEpoch != teamEpoch else { return }
        self.accountID = accountID; self.scope = scope; self.server = server; self.teamID = teamID; self.teamEpoch = teamEpoch
        revision += 1; refreshRequest = nil; policy = .init(); processingIDs = []; ancestry = [:]
    }
    func consume(type: String, fields: [String: Any], scope: UUID) {
        guard accountID != nil, self.scope == scope, server?.apiBaseURL == ServerConfiguration.current.apiBaseURL,
              (fields["team_id"] as? String) == teamID, let id = fields["chat_id"] as? String, !id.isEmpty else { return }
        let task = fields["ai_task_id"] as? String ?? fields["task_id"] as? String
        let message = fields["message_id"] as? String
        let user = fields["user_message_id"] as? String
        switch type {
        case "ai_task_initiated":
            if let task, !task.isEmpty {
                let provisional = user?.isEmpty == false ? user! : task
                policy.start(.init(chatID: id, turnID: provisional), now: Date())
                policy.adopt(chatID: id, provisional: provisional, server: task, now: Date())
            }
        case "ai_typing_started":
            if let message, !message.isEmpty {
                if let user, policy.items[id]?.aliases.contains(user) == true {
                    policy.adopt(chatID: id, provisional: user, server: message, now: Date())
                } else if let turn = policy.items[id]?.turnID {
                    policy.adopt(chatID: id, provisional: turn, server: message, now: Date())
                } else { policy.start(.init(chatID: id, turnID: message), now: Date()) }
            }
        case "ai_typing_ended":
            if let message { policy.finish(chatID: id, turnID: message) }
        case "post_processing_completed":
            if let task { policy.finish(chatID: id, turnID: task) }
        case "ai_background_response_completed", "ai_response_storage_confirmed":
            if let message { policy.finish(chatID: id, turnID: message) }
            else if let task { policy.finish(chatID: id, turnID: task) }
        case "chat_deleted":
            if let turn = policy.items[id]?.turnID { policy.finish(chatID: id, turnID: turn) }
        default: return
        }
        revision += 1
        processingIDs = Set(policy.items.keys)
    }
    func refresh() async {
        guard refreshRequest == nil, let accountID, let scope, let server else { return }
        let refreshID = UUID(); refreshRequest = refreshID
        let request = revision, expectedTeam = teamID
        struct Snapshot: Decodable {
            struct Run: Decodable { let chatId: String; let taskId: String }
            struct Parent: Decodable { let chatId: String; let parentId: String? }
            let activeTasks: [Run]; let chats: [Parent]
        }
        defer { if refreshRequest == refreshID { refreshRequest = nil } }
        do {
            let suffix = expectedTeam.map { "?team_id=" + ($0.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? "") } ?? ""
            let snapshot: Snapshot = try await APIClient.shared.request(.get, path: "/v1/chats/activity" + suffix,
                serverProfile: server, expectedAccountID: accountID, expectedScope: scope, expectedTeamContext: .init(epoch: teamEpoch, teamID: expectedTeam))
            guard request == revision, self.accountID == accountID, self.scope == scope, teamID == expectedTeam else { return }
            let runs = snapshot.activeTasks.map { ActiveChatsRun(chatID: $0.chatId, turnID: $0.taskId) }
            policy.reconcile(runs, now: Date())
            if let liveScope = ActiveChatsCoordinator.shared.currentScope,
               liveScope.accountID == accountID, liveScope.scope == scope,
               liveScope.server == server, liveScope.teamID == expectedTeam {
                ActiveChatsCoordinator.shared.reconcileActiveChats(runs, scope: liveScope)
            }
            ancestry = Dictionary(snapshot.chats.compactMap { parent in parent.parentId.map { (parent.chatId, $0) } }, uniquingKeysWith: { first, _ in first })
            processingIDs = Set(policy.items.keys)
        } catch {}
    }
    func processingAncestorIDs(chats: [Chat]) -> Set<String> {
        let rows = Dictionary(chats.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
        var result = processingIDs
        for id in processingIDs {
            var current = id, visited: Set<String> = []
            while visited.insert(current).inserted, let parent = rows[current]?.parentId ?? ancestry[current] {
                result.insert(parent); current = parent
            }
        }
        return result
    }
    func activeSubChatCounts(chats: [Chat]) -> [String: Int] {
        let rows = Dictionary(chats.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
        var counts: [String: Int] = [:]
        for id in processingIDs {
            var root = id, visited: Set<String> = []
            while visited.insert(root).inserted, let parent = rows[root]?.parentId ?? ancestry[root] { root = parent }
            if root != id { counts[root, default: 0] += 1 }
        }
        return counts
    }
    /// The accepted activity policy retains the first-observed task sequence;
    /// never rebuild display order from processingIDs, which is an unordered set.
    func orderedRootIDs(chats: [Chat]) -> [String] {
        Self.orderedRootIDs(processingChatIDs: policy.orderedItems.map(\.chatID), chats: chats, ancestry: ancestry)
    }

    static func orderedRootIDs(processingChatIDs: [String], chats: [Chat], ancestry: [String: String] = [:]) -> [String] {
        let rows = Dictionary(chats.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
        var seen: Set<String> = [], result: [String] = []
        for id in processingChatIDs {
            var root = id, visited: Set<String> = []
            while visited.insert(root).inserted, let parent = rows[root]?.parentId ?? ancestry[root] { root = parent }
            if seen.insert(root).inserted { result.append(root) }
        }
        return result
    }

    func rootIDs(chats: [Chat]) -> Set<String> {
        let rows = Dictionary(chats.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
        return Set(processingIDs.map { id in
            var root = id, visited: Set<String> = []
            while visited.insert(root).inserted, let parent = rows[root]?.parentId ?? ancestry[root] { root = parent }
            return root
        })
    }
}
