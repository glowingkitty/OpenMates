// Publishes the accepted processing census, without another network or timer loop.
// Specification: specifications/features/chat-navigation/specification.yml
// Assertions: chat-navigation.activity.global-running, apple-live-activities.processing.widget
// Specification: specifications/features/apple-live-activities/specification.yml
// Assertions: apple-live-activities.lifecycle.isolation
import Foundation
import WidgetKit

@MainActor
final class ActiveChatsWidgetBridge {
    static let shared = ActiveChatsWidgetBridge()
    private let storage: WidgetActiveChatsStorage
    private let reload: @MainActor () -> Void
    private let currentScope: @MainActor () -> ActiveChatsScope?
    private var chatLookup: @MainActor (String) -> Chat? = { _ in nil }
    private var context: ActiveChatsScope?
    private var configured = false
    private var lastSnapshot: WidgetActiveChatsSnapshot?
    private var lastTurns: [String: String] = [:]

    init(storage: WidgetActiveChatsStorage = .shared,
         reload: @escaping @MainActor () -> Void = { WidgetCenter.shared.reloadTimelines(ofKind: WidgetActiveChatsStorage.kind) },
         currentScope: @escaping @MainActor () -> ActiveChatsScope? = { ActiveChatsCoordinator.shared.currentScope }) {
        self.storage = storage; self.reload = reload; self.currentScope = currentScope
    }
    func setChatLookup(_ lookup: @escaping @MainActor (String) -> Chat?) { chatLookup = lookup }

    func publish(_ policy: ActiveChatsPolicy, scope: ActiveChatsScope?, authoritative: Bool, now: Date = Date()) {
        guard scope == currentScope() else { return }
        if !configured || context != scope {
            configured = true; context = scope; lastSnapshot = nil; lastTurns = [:]
            // Even a same-owner runtime/team-epoch replacement discards an old
            // census. Restore needs the existing authoritative activity refresh.
            storage.clear()
            storage.activate(owner: scope.map(owner))
            reload()
        }
        guard let scope, authoritative else { return }
        let summaries = policy.orderedItems.filter { $0.lastEvidence.addingTimeInterval(ActiveChatsPolicy.expiryInterval) > now }
            .compactMap { item -> WidgetActiveChatSummary? in
                guard WidgetActiveChatsLinks.safeID(item.chatID) else { return nil }
                // Hidden chats retain a generic row and link, never their title.
                let chat = chatLookup(item.chatID).flatMap { $0.teamId == scope.teamID ? $0 : nil }
                let title = chat.flatMap { $0.isHiddenFromNormalSurfaces ? nil : ActiveChatsPolicy.safeLabel($0.title) }
                    ?? AppStrings.activeChatsWidgetChat(number: item.ordinal)
                return WidgetActiveChatSummary(id: item.chatID, title: title,
                    expiresAt: item.lastEvidence.addingTimeInterval(ActiveChatsPolicy.expiryInterval))
            }
        let snapshot = WidgetActiveChatsSnapshot(owner: owner(scope), teamID: scope.teamID, updatedAt: now, chats: summaries)
        let turns = Dictionary(uniqueKeysWithValues: policy.orderedItems.map { ($0.chatID, $0.turnID) })
        if let lastSnapshot, lastSnapshot.owner == snapshot.owner, lastSnapshot.teamID == snapshot.teamID,
           lastTurns == turns, lastSnapshot.chats.map(\.id) == summaries.map(\.id),
           lastSnapshot.chats.map(\.title) == summaries.map(\.title) {
            // Token/progress callbacks renew evidence often. Request at most one
            // refresh per 30 seconds for an unchanged inventory and titles.
            guard lastSnapshot.chats != summaries, now.timeIntervalSince(lastSnapshot.updatedAt) >= 30 else { return }
        }
        do {
            try storage.save(snapshot)
            lastSnapshot = snapshot; lastTurns = turns
            storage.setLanguage(LocalizationManager.shared.currentLanguage.code)
            // Requests refresh; WidgetKit schedules actual rendering.
            reload()
        } catch { NativeDiagnostics.warning("Active chats widget snapshot unavailable", category: "widgets") }
    }
    func metadataChanged() {
        let coordinator = ActiveChatsCoordinator.shared
        publish(coordinator.policy, scope: coordinator.currentScope, authoritative: coordinator.hasProcessingEvidence)
    }
    private func owner(_ scope: ActiveChatsScope) -> String {
        WidgetActiveChatsOwner.identity(accountID: scope.accountID, apiBaseURL: scope.server.apiBaseURL, teamID: scope.teamID)
    }
}
