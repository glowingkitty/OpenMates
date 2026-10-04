// Accepted native running-chat census used by the Active chats widget.
// Exact turn aliases and account/server/runtime/Team scope fence every update.
// Specification: specifications/features/apple-live-activities/specification.yml
// Assertions: apple-live-activities.processing.widget, apple-live-activities.lifecycle.isolation
import Foundation
typealias ActiveChatsScope = UpcomingMemorySnapshotScope

struct ActiveChatsRun: Equatable {
    let chatID: String
    let turnID: String
}

struct ActiveChatsPolicy {
    struct Item: Equatable {
        let chatID: String
        var turnID: String
        var aliases: Set<String>
        let ordinal: Int
        var lastEvidence: Date
    }
    static let expiryInterval: TimeInterval = 15 * 60
    private(set) var items: [String: Item] = [:]
    private var completed: [String] = []
    private var nextOrdinal = 0
    var orderedItems: [Item] { items.values.sorted { $0.ordinal < $1.ordinal } }

    @discardableResult mutating func start(_ run: ActiveChatsRun, now: Date) -> Bool {
        guard !run.chatID.isEmpty, !run.turnID.isEmpty, !completed.contains(key(run.chatID, run.turnID)) else { return false }
        if let existing = items[run.chatID], existing.aliases.contains(run.turnID) {
            return false
        }
        if let previous = items[run.chatID] { remember(previous) }
        nextOrdinal += 1
        items[run.chatID] = Item(chatID: run.chatID, turnID: run.turnID, aliases: [run.turnID], ordinal: nextOrdinal, lastEvidence: now)
        return true
    }

    @discardableResult mutating func adopt(chatID: String, provisional: String, server: String, now: Date) -> Bool {
        guard !server.isEmpty, !completed.contains(key(chatID, server)),
              var item = items[chatID], item.aliases.contains(provisional) else { return false }
        guard !item.aliases.contains(server) else { return false }
        item.turnID = server; item.aliases.insert(server); item.lastEvidence = now
        items[chatID] = item
        return true
    }

    @discardableResult mutating func progress(chatID: String, turnID: String, now: Date) -> Bool {
        guard var item = items[chatID], item.aliases.contains(turnID) else { return false }
        item.lastEvidence = now; items[chatID] = item
        return true
    }

    @discardableResult mutating func finish(chatID: String, turnID: String) -> Bool {
        guard !chatID.isEmpty, !turnID.isEmpty else { return false }
        // A finish may precede a replayed start after reconnect. Keep that receipt
        // even when it cannot remove the currently active, newer turn.
        rememberKey(key(chatID, turnID))
        guard let item = items[chatID], item.aliases.contains(turnID) else { return false }
        remember(item); items.removeValue(forKey: chatID)
        return true
    }

    mutating func reconcile(_ runs: [ActiveChatsRun], now: Date) {
        let wanted = Set(runs.map { key($0.chatID, $0.turnID) })
        for item in Array(items.values) where !item.aliases.contains(where: { wanted.contains(key(item.chatID, $0)) }) {
            remember(item); items.removeValue(forKey: item.chatID)
        }
        for run in runs {
            if !progress(chatID: run.chatID, turnID: run.turnID, now: now) { start(run, now: now) }
        }
        expire(now: now)
    }

    mutating func expire(now: Date) {
        for item in Array(items.values) where item.lastEvidence.addingTimeInterval(Self.expiryInterval) <= now {
            remember(item); items.removeValue(forKey: item.chatID)
        }
    }

    func hasCompleted(chatID: String, turnID: String) -> Bool { completed.contains(key(chatID, turnID)) }
    static func safeLabel(_ label: String?) -> String? {
        guard let label else { return nil }
        let oneLine = label.components(separatedBy: .whitespacesAndNewlines).filter { !$0.isEmpty }.joined(separator: " ")
        let filtered = String(oneLine.unicodeScalars.filter { !CharacterSet.controlCharacters.contains($0) })
        return filtered.isEmpty ? nil : String(filtered.prefix(80))
    }

    private func key(_ chat: String, _ turn: String) -> String {
        String(decoding: (try? JSONEncoder().encode([chat, turn])) ?? Data(), as: UTF8.self)
    }
    private mutating func remember(_ item: Item) { for alias in item.aliases { rememberKey(key(item.chatID, alias)) } }
    private mutating func rememberKey(_ value: String) {
        if !completed.contains(value) { completed.append(value) }
        if completed.count > 256 { completed.removeFirst(completed.count - 256) }
    }
}

@MainActor
final class ActiveChatsCoordinator {
    static let shared = ActiveChatsCoordinator()
    private(set) var currentScope: ActiveChatsScope?
    private(set) var policy = ActiveChatsPolicy()
    private var authenticated = false
    private let publishWidgetSnapshot: @MainActor (ActiveChatsPolicy, ActiveChatsScope?, Bool) -> Void
    private var lastProgressPublication: Date?
    private var hasAuthoritativeProcessingEvidence = false
    init(publishWidgetSnapshot: (@MainActor (ActiveChatsPolicy, ActiveChatsScope?, Bool) -> Void)? = nil) {
        self.publishWidgetSnapshot = publishWidgetSnapshot ?? { policy, scope, evidence in
            ActiveChatsWidgetBridge.shared.publish(policy, scope: scope, authoritative: evidence)
        }
    }

    func configure(accountID: String?, server: ServerProfile, scope: UUID, team: APIRequestTeamContext,
                   authenticated: Bool) {
        let next = authenticated ? accountID.map { ActiveChatsScope(accountID: $0, server: server, scope: scope, team: team) } : nil
        if next != currentScope || self.authenticated != authenticated {
            policy = ActiveChatsPolicy()
            lastProgressPublication = nil
            hasAuthoritativeProcessingEvidence = false
            currentScope = next
            self.authenticated = authenticated
        }
        publish()
    }

    func started(chatID: String, turnID: String, scope: ActiveChatsScope, now: Date = Date()) {
        guard accepts(scope), policy.start(.init(chatID: chatID, turnID: turnID), now: now) else { return }
        hasAuthoritativeProcessingEvidence = true
        policy.expire(now: now); publish()
    }
    func adoptServerTurn(chatID: String, provisionalTurnID: String, serverTurnID: String, scope: ActiveChatsScope, now: Date = Date()) {
        guard accepts(scope), policy.adopt(chatID: chatID, provisional: provisionalTurnID, server: serverTurnID, now: now) else { return }
        policy.expire(now: now)
        publish()
    }
    func progressed(chatID: String, turnID: String, scope: ActiveChatsScope, now: Date = Date()) {
        guard accepts(scope), policy.progress(chatID: chatID, turnID: turnID, now: now) else { return }
        policy.expire(now: now)
        // Streaming may emit one callback per token. Bound widget publications;
        // starts, terminal events and ownership changes still publish immediately.
        guard lastProgressPublication.map({ now.timeIntervalSince($0) >= 5 }) ?? true else { return }
        lastProgressPublication = now; publish()
    }
    func finished(chatID: String, turnID: String, scope: ActiveChatsScope) {
        guard accepts(scope) else { return }
        if policy.finish(chatID: chatID, turnID: turnID) {
            hasAuthoritativeProcessingEvidence = true
            publish()
        }
    }
    /// Only use a complete, authoritative active-run snapshot; partial sync pages
    /// must not remove other in-flight chats. A reconnect by itself is no evidence.
    func reconcileActiveChats(_ runs: [ActiveChatsRun], scope: ActiveChatsScope, now: Date = Date()) {
        guard accepts(scope) else { return }
        hasAuthoritativeProcessingEvidence = true
        policy.reconcile(runs, now: now); publish()
    }
    func foreground() { policy.expire(now: Date()); publish() }
    func reset() { currentScope = nil; authenticated = false; hasAuthoritativeProcessingEvidence = true; policy = ActiveChatsPolicy(); publish() }
    private func accepts(_ scope: ActiveChatsScope) -> Bool { authenticated && currentScope == scope }

    /// Called by ordered live transport dispatch, never by subscriber replay.
    /// User/task IDs explicitly alias the accepted client turn to the server ID.
    func consume(_ event: StreamingClient.StreamEvent, chatID: String, scope: ActiveChatsScope) {
        guard accepts(scope) else { return }
        switch event {
        case .taskInitiated(_, let taskID, let userID):
            guard !userID.isEmpty, !policy.hasCompleted(chatID: chatID, turnID: userID) else { return }
            started(chatID: chatID, turnID: userID, scope: scope)
            adoptServerTurn(chatID: chatID, provisionalTurnID: userID, serverTurnID: taskID, scope: scope)
        case .typingStarted(_, let messageID, let metadata):
            if let userID = metadata?.userMessageId, !userID.isEmpty {
                guard !policy.hasCompleted(chatID: chatID, turnID: userID) else { return }
                if policy.items[chatID]?.aliases.contains(userID) == true {
                    adoptServerTurn(chatID: chatID, provisionalTurnID: userID, serverTurnID: messageID, scope: scope)
                } else {
                    started(chatID: chatID, turnID: userID, scope: scope)
                    adoptServerTurn(chatID: chatID, provisionalTurnID: userID, serverTurnID: messageID, scope: scope)
                }
            } else if policy.items[chatID] == nil { started(chatID: chatID, turnID: messageID, scope: scope) }
            progressed(chatID: chatID, turnID: messageID, scope: scope)
        case .chunk(_, let messageID, _, _, let isFinal, let userID, _, _, _):
            if let userID, policy.items[chatID]?.aliases.contains(userID) == true {
                adoptServerTurn(chatID: chatID, provisionalTurnID: userID, serverTurnID: messageID, scope: scope)
            } else if !isFinal && policy.items[chatID] == nil && !(userID.map { policy.hasCompleted(chatID: chatID, turnID: $0) } ?? false) {
                started(chatID: chatID, turnID: messageID, scope: scope)
            }
            if isFinal { finished(chatID: chatID, turnID: messageID, scope: scope) }
            else { progressed(chatID: chatID, turnID: messageID, scope: scope) }
        case .thinkingChunk(_, let messageID, _), .thinkingComplete(_, let messageID):
            if policy.items[chatID] == nil { started(chatID: chatID, turnID: messageID, scope: scope) }
            progressed(chatID: chatID, turnID: messageID, scope: scope)
        case .messageReady(_, let messageID): finished(chatID: chatID, turnID: messageID, scope: scope)
        case .typingEnded(_, let messageID):
            if let messageID { finished(chatID: chatID, turnID: messageID, scope: scope) }
        case .postProcessingCompleted(_, let taskID, _, _, _, _, _, _, _):
            finished(chatID: chatID, turnID: taskID, scope: scope)
        case .preprocessingStep, .messageQueued, .cancelRequested, .error:
            // These events lack an exact terminal assistant ID. A cancellation
            // request/transport failure does not prove inference has stopped.
            break
        }
    }

    var hasProcessingEvidence: Bool { hasAuthoritativeProcessingEvidence }

    private func publish() {
        publishWidgetSnapshot(policy, currentScope, hasAuthoritativeProcessingEvidence)
    }
}
