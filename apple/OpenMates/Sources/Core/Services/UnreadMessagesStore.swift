// Unread messages store — tracks unread message counts per chat for badge display.
// Mirrors the web app's unreadMessagesStore.ts: increments on background AI responses,
// clears when user opens a chat, syncs total count to app badge.
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity
// Specification: specifications/features/apple-notifications/specification.yml
// Assertions: apple-notifications.action.routing-coherent

import Foundation
import SwiftUI
#if os(iOS)
import UIKit
#endif

/// Metadata-only state. Account/server scope is the existing offline scope hash;
/// Team selection filters presentation and never transfers another scope's counts.
struct NativeUnreadState {
    struct Entry { var count: Int; let teamID: String? }
    private(set) var scopeID: String?
    private(set) var activeTeamID: String?
    private(set) var activeChatID: String?
    private var entries: [String: Entry] = [:]
    private var completions: [String] = []

    mutating func configure(scopeID: String?, teamID: String?) {
        if self.scopeID != scopeID { entries = [:]; completions = []; activeChatID = nil }
        if activeTeamID != teamID { activeChatID = nil }
        self.scopeID = scopeID; activeTeamID = teamID
    }
    mutating func setActiveChat(_ id: String?) {
        activeChatID = id
        if let id { set(id: id, count: 0, teamID: activeTeamID, expectedScope: scopeID) }
    }
    func normalizedCount(id: String, count: Int, teamID: String?) -> Int {
        id == activeChatID && teamID == activeTeamID ? 0 : max(0, count)
    }
    func wouldSet(id: String, count: Int, teamID: String?, expectedScope: String?) -> Bool {
        guard let scopeID, expectedScope == scopeID else { return false }
        let normalized = normalizedCount(id: id, count: count, teamID: teamID)
        guard let entry = entries[id] else { return normalized != 0 }
        return entry.count != normalized || entry.teamID != teamID
    }
    func hasCompletion(id: String, messageID: String?) -> Bool {
        guard let messageID else { return false }
        return completions.contains(id + ":" + messageID)
    }
    mutating func set(id: String, count: Int, teamID: String?, expectedScope: String?) {
        guard let scopeID, expectedScope == scopeID else { return }
        entries[id] = Entry(count: normalizedCount(id: id, count: count, teamID: teamID), teamID: teamID)
    }
    mutating func complete(id: String, messageID: String?, teamID: String?) -> Int? {
        guard scopeID != nil else { return nil }
        if let messageID {
            let key = id + ":" + messageID
            guard !completions.contains(key) else { return nil }
            completions.append(key)
            if completions.count > 512 { completions.removeFirst(completions.count - 512) }
        }
        set(id: id, count: count(id: id, teamID: teamID) + 1, teamID: teamID, expectedScope: scopeID)
        return count(id: id, teamID: teamID)
    }
    func isActivelyViewing(chatID: String, teamID: String?) -> Bool {
        scopeID != nil && activeChatID == chatID && activeTeamID == teamID
    }
    func count(id: String, teamID: String?) -> Int { entries[id]?.teamID == teamID ? entries[id]?.count ?? 0 : 0 }
    var total: Int { entries.values.filter { $0.teamID == activeTeamID }.reduce(0) { $0 + $1.count } }
}

@MainActor
final class UnreadMessagesStore: ObservableObject {
    static let shared = UnreadMessagesStore()
    @Published private var state = NativeUnreadState()
    @Published private(set) var totalUnread: Int = 0
    var isConfigured: Bool { state.scopeID != nil }
    func isActivelyViewing(chatID: String, teamID: String?) -> Bool { state.isActivelyViewing(chatID: chatID, teamID: teamID) }
    private let badgeUpdater: (@MainActor (Int) -> Void)?
    private var didSynchronizeBadge = false
    private var badgeRevision = 0

    /// Tests use an independent store and synchronous badge recorder.
    init(badgeUpdater: (@MainActor (Int) -> Void)? = nil) {
        self.badgeUpdater = badgeUpdater
    }

    func configure(scopeID: String?, teamID: String?) {
        guard state.scopeID != scopeID || state.activeTeamID != teamID else {
            if !didSynchronizeBadge { recalculateTotal() } // Clear an initial stale OS badge once.
            return
        }
        state.configure(scopeID: scopeID, teamID: teamID); recalculateTotal()
    }
    func setActiveTeam(_ teamID: String?) { configure(scopeID: state.scopeID, teamID: teamID) }
    func setActiveChat(_ id: String?) {
        guard state.activeChatID != id else { return }
        state.setActiveChat(id); recalculateTotal()
    }
    @discardableResult
    func incrementUnread(chatId: String, messageID: String? = nil, teamID: String? = nil) -> Int? {
        guard state.scopeID != nil, !state.hasCompletion(id: chatId, messageID: messageID) else { return nil }
        let count = state.complete(id: chatId, messageID: messageID, teamID: teamID)
        recalculateTotal(); return count
    }
    func setUnread(chatId: String, count: Int, teamID: String? = nil) {
        // Guard before invoking a mutating method on @Published state: even a
        // rejected inout mutation otherwise writes the property back.
        guard state.wouldSet(id: chatId, count: count, teamID: teamID, expectedScope: state.scopeID) else { return }
        state.set(id: chatId, count: count, teamID: teamID, expectedScope: state.scopeID); recalculateTotal()
    }
    func clearUnread(chatId: String) { setUnread(chatId: chatId, count: 0, teamID: state.activeTeamID) }
    func getUnreadCount(chatId: String) -> Int { state.count(id: chatId, teamID: state.activeTeamID) }
    func getUnreadCount(chatId: String, teamID: String?) -> Int { state.count(id: chatId, teamID: teamID) }
    func hasUnread(chatId: String) -> Bool { getUnreadCount(chatId: chatId) > 0 }
    func clearAll() { configure(scopeID: nil, teamID: nil) }
    /// Reconcile external/stale OS state without changing logical unread state.
    /// Explicit activation/actions may need a write even when metadata is equal.
    func resynchronizeBadge() { recalculateTotal(forceBadge: true) }

    private func recalculateTotal(forceBadge: Bool = false) {
        let nextTotal = state.total
        let changed = nextTotal != totalUnread
        if changed { totalUnread = nextTotal }
        guard forceBadge || changed || !didSynchronizeBadge else { return }
        didSynchronizeBadge = true
        badgeRevision += 1
        if let badgeUpdater { badgeUpdater(nextTotal); return }
        #if os(iOS)
        let revision = badgeRevision
        Task {
            let center = UNUserNotificationCenter.current()
            let settings = await center.notificationSettings()
            guard revision == badgeRevision else { return }
            if settings.badgeSetting == .enabled { try? await center.setBadgeCount(nextTotal) }
        }
        #endif
    }
}

/// Receipt transport replay is separate from foreground active-chat publication.
/// The scoped bridge checks its owner again for each queued action.
@MainActor
enum NativeUnreadReadReplay {
    @discardableResult
    static func schedule(isCurrent: @escaping @MainActor () -> Bool,
                         replay: @escaping @MainActor () async -> Void) -> Task<Void, Never> {
        Task { @MainActor in
            guard !Task.isCancelled, isCurrent() else { return }
            await replay()
        }
    }
}
