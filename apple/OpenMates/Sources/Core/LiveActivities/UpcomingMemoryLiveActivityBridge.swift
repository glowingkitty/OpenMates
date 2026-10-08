// Binds complete, decrypted saved-memory snapshots to generic Live Activity state.
// Private titles, notes and memory values never enter the retained bridge snapshot.
// Specification: specifications/features/apple-live-activities/specification.yml
// Assertions: apple-live-activities.memories.upcoming, apple-live-activities.lifecycle.isolation

import Foundation

struct UpcomingMemorySnapshotScope: Equatable {
    let accountID: String
    let server: ServerProfile
    let scope: UUID
    let teamID: String?
    let teamEpoch: UInt64

    init(accountID: String, server: ServerProfile, scope: UUID, team: APIRequestTeamContext) {
        self.accountID = accountID; self.server = server; self.scope = scope
        teamID = team.teamID; teamEpoch = team.epoch
    }

    init?(_ context: SettingsMemoryContext) {
        guard let accountID = context.accountID else { return nil }
        self.init(accountID: accountID, server: context.server, scope: context.scope, team: context.team)
    }

    /// Runtime fences change on relaunch; the persisted owner identity must not.
    var ownerIdentity: String {
        String(decoding: (try? JSONEncoder().encode([accountID, server.apiBaseURL.absoluteString, teamID ?? ""])) ?? Data(), as: UTF8.self)
    }
}

struct SettingsMemoryLiveActivitySnapshot {
    enum Change { case full, upsert(SettingsMemoryEntry), removed(String) }
    let scope: UpcomingMemorySnapshotScope
    let entries: [SettingsMemoryEntry]
    let revision: UInt64
    var change: Change = .full
    @MainActor private static var revisionCounter: UInt64 = 0
    /// Issue before a full read, and after a successful mutation. A slow earlier
    /// read cannot resurrect an entry removed by a newer acknowledged mutation.
    @MainActor static func nextRevision() -> UInt64 { revisionCounter &+= 1; return revisionCounter }
}

enum UpcomingMemorySnapshotBindingPolicy {
    static func accepts(_ snapshot: SettingsMemoryLiveActivitySnapshot,
                        currentScope: UpcomingMemorySnapshotScope?, after revision: UInt64) -> Bool {
        snapshot.scope == currentScope && snapshot.revision > revision
    }

    static func sanitizedEntries(_ entries: [SettingsMemoryEntry]) -> [SettingsMemoryEntry] {
        let fields: Set<String> = ["embed_id", "date_start", "date_end", "appointment_time", "departure", "arrival",
                                   "status", "deleted", "completed", "cancelled", "canceled"]
        return entries.filter { !$0.isExample }.map {
            SettingsMemoryEntry(id: $0.id, appId: $0.appId, categoryId: $0.categoryId, key: "", value: "",
                createdAt: 0, updatedAt: 0, version: $0.version, isExample: false,
                fields: $0.fields.filter { fields.contains($0.key) })
        }
    }

    static func applying(_ snapshot: SettingsMemoryLiveActivitySnapshot, to entries: [SettingsMemoryEntry]) -> [SettingsMemoryEntry] {
        switch snapshot.change {
        case .full: return sanitizedEntries(snapshot.entries)
        case .upsert(let entry):
            // A receipt affects only its entry; the source service may hold older siblings.
            return entries.filter { $0.id != entry.id } + sanitizedEntries([entry])
        case .removed(let id): return entries.filter { $0.id != id }
        }
    }
}

@MainActor
final class UpcomingMemoryLiveActivityBridge {
    static let shared = UpcomingMemoryLiveActivityBridge()
    private var currentScope: UpcomingMemorySnapshotScope?
    private var entries: [SettingsMemoryEntry] = []
    private var acceptedRevision: UInt64 = 0
    private var notificationsEnabled = false
    private var configured = false
    private var isForeground = false

    /// Root calls this on authentication, account, server, team and opt-in changes.
    /// Authorization is checked again by the ActivityKit coordinator before use.
    func configure(accountID: String?, server: ServerProfile, scope: UUID, team: APIRequestTeamContext,
                   authenticated: Bool, notificationsEnabled: Bool) {
        let next = authenticated ? accountID.map {
            UpcomingMemorySnapshotScope(accountID: $0, server: server, scope: scope, team: team)
        } : nil
        // The first logged-out launch must also clear OS activities retained from
        // an earlier session, even though the bridge's default state is empty.
        let changed = !configured || next != currentScope || self.notificationsEnabled != notificationsEnabled
        guard changed else { return }
        configured = true
        entries = []; acceptedRevision = 0
        currentScope = next
        self.notificationsEnabled = notificationsEnabled
        UpcomingMemoryLiveActivityCoordinator.shared.prepareOwner(ownerScope: next?.ownerIdentity,
            ownerAccountID: next?.accountID, notificationsEnabled: notificationsEnabled)
        if next == nil || !notificationsEnabled { reconcile() }
        if isForeground { startLoading() }
    }

    /// Re-evaluate dates and OS authorization whenever the app becomes active.
    func foreground() async {
        isForeground = true
        if currentScope != nil && notificationsEnabled && acceptedRevision > 0 { reconcile() }
        startLoading()
    }

    func background() {
        isForeground = false
    }

    func accept(_ snapshot: SettingsMemoryLiveActivitySnapshot) {
        guard notificationsEnabled,
              UpcomingMemorySnapshotBindingPolicy.accepts(snapshot, currentScope: currentScope, after: acceptedRevision) else { return }
        acceptedRevision = snapshot.revision
        entries = UpcomingMemorySnapshotBindingPolicy.applying(snapshot, to: entries)
        reconcile()
    }

    private func startLoading() {
        #if os(iOS)
        guard isForeground, currentScope != nil, notificationsEnabled else { return }
        // Shared scoped inventory publishes unsanitized data only to Continue's
        // RAM cache and sanitized timing-only data to this bridge.
        WelcomeContinueService.shared.becameActive()
        #endif
    }

    func reevaluateDates() { if isForeground { reconcile() } }

    private func reconcile() {
        UpcomingMemoryLiveActivityCoordinator.shared.reconcile(entries: entries,
            ownerScope: currentScope?.ownerIdentity, ownerAccountID: currentScope?.accountID,
            notificationsEnabled: notificationsEnabled)
    }
}
