// Upcoming saved embeds use schema fields, never title/notes scraping. The
// ActivityKit payload is generic and stores only an opaque identity and dates.
// Specification: specifications/features/apple-live-activities/specification.yml
// Assertions: apple-live-activities.memories.upcoming, apple-live-activities.lifecycle.isolation
import Foundation
import CryptoKit
#if os(iOS)
// This SDK leaves Activity and its async update/end APIs without Sendable
// annotations. Keep framework interoperability local: all app-side handles
// remain owned by this MainActor coordinator and its ordered effect queue.
@preconcurrency import ActivityKit
import UIKit
import UserNotifications

@available(iOS 17.0, *)
@MainActor
protocol UpcomingMemoryNavigationDriving: AnyObject {
    func authorizedOwner() async -> String?
    func state(for identity: String) -> OpenMatesLiveActivityAttributes.ContentState?
    func update(_ state: OpenMatesLiveActivityAttributes.ContentState, identity: String) async
    func end(identity: String) async
}

@available(iOS 17.0, *)
@MainActor
private final class ActivityKitUpcomingMemoryNavigationDriver: UpcomingMemoryNavigationDriving {
    func authorizedOwner() async -> String? {
        let settings = await UNUserNotificationCenter.current().notificationSettings()
        let auth = AuthManager.notificationSession
        guard auth.state == .authenticated, let accountID = auth.currentUser?.id,
              auth.currentUser?.pushNotificationEnabled == true,
              settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional,
              ActivityAuthorizationInfo().areActivitiesEnabled else { return nil }
        let team = TeamWorkspaceContext.shared
        let scope = UpcomingMemorySnapshotScope(accountID: accountID, server: ServerProfile.current(), scope: UUID(),
            team: .init(epoch: team.contextEpoch, teamID: team.teamID))
        return UpcomingMemoryLiveActivityCoordinator.opaque(scope.ownerIdentity)
    }
    private func activity(_ identity: String) -> Activity<OpenMatesLiveActivityAttributes>? {
        Activity.activities.first { $0.attributes.kind == "upcoming" && $0.attributes.identity == identity }
    }
    func state(for identity: String) -> OpenMatesLiveActivityAttributes.ContentState? { activity(identity)?.content.state }
    func update(_ state: OpenMatesLiveActivityAttributes.ContentState, identity: String) async {
        await activity(identity)?.update(ActivityContent(state: state, staleDate: state.startsAt))
    }
    func end(identity: String) async { await activity(identity)?.end(nil, dismissalPolicy: .immediate) }
}
#endif

struct UpcomingMemoryActivityCandidate: Equatable, Sendable {
    let memoryID: String
    let embedID: String
    let startsAt: Date
    let endsAt: Date?
    var activityStartsAt: Date { startsAt.addingTimeInterval(-4 * 3_600) }
}

enum UpcomingMemoryActivityPolicy {
    static func page(_ candidate: UpcomingMemoryActivityCandidate, owner: String) -> UpcomingMemoryActivityPage {
        .init(identity: String(UpcomingMemoryLiveActivityCoordinator.opaque(owner + ":" + candidate.memoryID + ":" + String(candidate.startsAt.timeIntervalSince1970)).prefix(32)),
              startsAt: candidate.startsAt)
    }

    static func candidates(from entries: [SettingsMemoryEntry], now: Date) -> [UpcomingMemoryActivityCandidate] {
        entries.compactMap { entry in
            guard !entry.isExample, let embed = entry.fields["embed_id"]?.string, !embed.isEmpty else { return nil }
            let excludedStatus: Set<String> = ["cancelled", "canceled", "completed", "deleted"]
            if let status = entry.fields["status"]?.string, excludedStatus.contains(status.lowercased()) { return nil }
            if ["deleted", "completed", "cancelled", "canceled"].contains(where: { entry.fields[$0] == .bool(true) }) { return nil }
            let startField: String
            let endField: String?
            switch (entry.appId, entry.categoryId) {
            case ("events", "saved_events"): startField = "date_start"; endField = "date_end"
            case ("health", "appointments"): startField = "appointment_time"; endField = nil
            case ("travel", "saved_connections"): startField = "departure"; endField = "arrival"
            default: return nil
            }
            guard let value = entry.fields[startField]?.string, let start = parseTimestamp(value), start > now else { return nil }
            let end = endField.flatMap { entry.fields[$0]?.string }.flatMap(parseTimestamp)
            guard end == nil || end! > start else { return nil }
            return .init(memoryID: entry.id, embedID: embed, startsAt: start, endsAt: end)
        }.sorted { $0.startsAt == $1.startsAt ? $0.memoryID < $1.memoryID : $0.startsAt < $1.startsAt }
    }

    static func parseTimestamp(_ value: String) -> Date? {
        // A date or local civil time cannot define the four-hour threshold safely.
        // Explicit offsets account for time-zone/DST changes without guessing.
        guard value.range(of: #"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"#,
                          options: .regularExpression) != nil else { return nil }
        let civil = String(value.prefix(19))
        let validator = DateFormatter()
        validator.locale = Locale(identifier: "en_US_POSIX")
        validator.timeZone = TimeZone(secondsFromGMT: 0)
        validator.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        validator.isLenient = false
        guard let date = validator.date(from: civil), validator.string(from: date) == civil else { return nil }
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return fractional.date(from: value) ?? ISO8601DateFormatter().date(from: value)
    }
}

@MainActor
final class UpcomingMemoryLiveActivityCoordinator {
    static let shared = UpcomingMemoryLiveActivityCoordinator()
    private var generation = UUID()
    private var tail: Task<Void, Never>?
    private var lastIdentity: String?
    private var currentOwner: String?
    private let defaults: UserDefaults
    #if os(iOS)
    private let navigationDriver: (any UpcomingMemoryNavigationDriving)?
    init(defaults: UserDefaults = .standard, navigationDriver: (any UpcomingMemoryNavigationDriving)? = nil) {
        self.navigationDriver = navigationDriver
        self.defaults = defaults
        lastIdentity = defaults.string(forKey: "openmates.upcoming-live.identity")
        currentOwner = defaults.string(forKey: "openmates.upcoming-live.owner")
    }
    #else
    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        lastIdentity = defaults.string(forKey: "openmates.upcoming-live.identity")
        currentOwner = defaults.string(forKey: "openmates.upcoming-live.owner")
    }
    #endif

    /// Prepare account ownership before loading the authoritative snapshot. A
    /// failed same-owner load must not erase a persisted user dismissal.
    func prepareOwner(ownerScope: String?, ownerAccountID: String?, notificationsEnabled: Bool) {
        #if os(iOS)
        generation = UUID()
        let expected = generation
        let predecessor = tail
        let owner = ownerScope.map(Self.opaque)
        tail = Task { [weak self] in
            await predecessor?.value
            guard let self, self.generation == expected, !Task.isCancelled else { return }
            let settings = await UNUserNotificationCenter.current().notificationSettings()
            guard self.generation == expected, !Task.isCancelled else { return }
            let auth = AuthManager.notificationSession
            let allowed = notificationsEnabled && owner != nil && ownerAccountID != nil
                && auth.state == .authenticated && auth.currentUser?.id == ownerAccountID
                && auth.currentUser?.pushNotificationEnabled == true
                && (settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional)
            if self.currentOwner != owner || !allowed {
                if #available(iOS 16.2, *) { await self.endAll() }
                guard self.generation == expected, !Task.isCancelled else { return }
                self.lastIdentity = nil
                self.defaults.removeObject(forKey: "openmates.upcoming-live.identity")
            }
            self.currentOwner = allowed ? owner : nil
            self.defaults.set(self.currentOwner, forKey: "openmates.upcoming-live.owner")
        }
        #endif
    }

    /// Root binds full decrypted saved-memory snapshots after account/scope checks.
    /// An empty snapshot ends removed/cancelled entries; an owner change ends old activities.
    func reconcile(entries: [SettingsMemoryEntry], ownerScope: String?, ownerAccountID: String?, notificationsEnabled: Bool, now: Date = Date()) {
        #if os(iOS)
        generation = UUID()
        let expected = generation
        let predecessor = tail
        let candidates = notificationsEnabled && ownerScope != nil && ownerAccountID != nil ? UpcomingMemoryActivityPolicy.candidates(from: entries, now: now) : []
        let owner = ownerScope.map(Self.opaque)
        tail = Task { [weak self] in
            await predecessor?.value
            guard let self, self.generation == expected, !Task.isCancelled else { return }
            if self.currentOwner != owner {
                self.lastIdentity = nil
                if #available(iOS 16.2, *) { await self.endAll() }
                self.currentOwner = owner
                self.defaults.set(owner, forKey: "openmates.upcoming-live.owner")
            }
            guard self.generation == expected, !Task.isCancelled else { return }
            if #available(iOS 16.2, *) { await self.publish(candidates, owner: owner, ownerAccountID: ownerAccountID, expected: expected, now: now) }
        }
        #endif
    }

    nonisolated static func opaque(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    #if os(iOS)
    /// Intents adopt the OS's generic snapshot after a process restart, without
    /// loading private memories. Live authentication and scope must still match.
    @available(iOS 17.0, *)
    func navigate(activityIdentity: String, step: Int, now: Date = Date()) async {
        guard (-1...1).contains(step), step != 0 else { return }
        let expected = generation
        let predecessor = tail
        let effect = Task { [weak self] in
            await predecessor?.value
            guard let self else { return }
            await self.performNavigation(activityIdentity: activityIdentity, step: step, now: now, expected: expected)
        }
        tail = effect
        await effect.value
    }

    @available(iOS 17.0, *)
    private func performNavigation(activityIdentity: String, step: Int, now: Date, expected: UUID) async {
        guard generation == expected, !Task.isCancelled else { return }
        let driver = navigationDriver ?? ActivityKitUpcomingMemoryNavigationDriver()
        let owner = await driver.authorizedOwner()
        guard generation == expected, !Task.isCancelled else { return }
        guard let owner else { return }
        guard UpcomingMemoryActivityNavigation.accepts(activityIdentity: activityIdentity,
                  expectedIdentity: Self.opaque(owner + ":upcoming"), kind: "upcoming", ownerMatches: currentOwner == owner,
                  authenticated: true, notificationsAllowed: true, activitiesEnabled: true),
              let original = driver.state(for: activityIdentity) else { return }
        guard var state = UpcomingMemoryActivityNavigation.moved(original, step: step, now: now) else {
            await driver.end(identity: activityIdentity)
            return
        }
        // Do not fabricate a fresh full snapshot: only this chosen date changes.
        state.expiresAt = state.startsAt
        await driver.update(state, identity: activityIdentity)
    }

    @available(iOS 16.2, *)
    private func endAll() async {
        for activity in Activity<OpenMatesLiveActivityAttributes>.activities where activity.attributes.kind == "upcoming" {
            await activity.end(nil, dismissalPolicy: .immediate)
        }
    }

    @available(iOS 16.2, *)
    private func publish(_ candidates: [UpcomingMemoryActivityCandidate], owner: String?, ownerAccountID: String?, expected: UUID, now: Date) async {
        let settings = await UNUserNotificationCenter.current().notificationSettings()
        guard generation == expected, !Task.isCancelled else { return }
        let auth = AuthManager.notificationSession
        let allowed = auth.state == .authenticated && auth.currentUser?.id == ownerAccountID && ownerAccountID != nil
            && auth.currentUser?.pushNotificationEnabled == true
            && (settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional)
            && ActivityAuthorizationInfo().areActivitiesEnabled
        guard allowed, let candidate = candidates.first, let owner else {
            await endAll()
            lastIdentity = nil
            defaults.removeObject(forKey: "openmates.upcoming-live.identity")
            return
        }
        let identity = Self.opaque(owner + ":upcoming")
        let windowIdentity = Self.opaque(owner + ":" + candidate.memoryID + ":" + String(candidate.startsAt.timeIntervalSince1970))
        let existing = Activity<OpenMatesLiveActivityAttributes>.activities.filter { $0.attributes.kind == "upcoming" }
        let retained = existing.first { $0.attributes.identity == identity }
        for activity in existing where activity.id != retained?.id { await activity.end(nil, dismissalPolicy: .immediate) }
        guard generation == expected, !Task.isCancelled else { return }
        let eligible = candidates.filter { $0.activityStartsAt <= now }
        // Scheduled activities contain only the first future item until an
        // authoritative reconcile (or an intent) evaluates the active window.
        let visible = eligible.isEmpty ? [candidate] : eligible
        let pages = visible.prefix(UpcomingMemoryActivityNavigation.maximumPages).map { UpcomingMemoryActivityPolicy.page($0, owner: owner) }
        var state = OpenMatesLiveActivityAttributes.ContentState(title: AppStrings.liveActivityUpcomingTitle,
            detail: AppStrings.liveActivityUpcomingDetail, phase: "upcoming", progress: 0, completedBytes: 0,
            totalBytes: 0, itemCount: visible.count, startsAt: candidate.startsAt, expiresAt: candidate.startsAt)
        state.upcomingPages = pages
        state.selectedUpcomingIdentity = retained?.content.state.selectedUpcomingIdentity
        let attributes = OpenMatesLiveActivityAttributes(identity: identity, kind: "upcoming")
        guard let bounded = UpcomingMemoryActivityNavigation.bounded(state, attributes: attributes) else { return }
        state = bounded
        let content = ActivityContent(state: state, staleDate: state.startsAt)
        if let retained {
            lastIdentity = windowIdentity
            defaults.set(windowIdentity, forKey: "openmates.upcoming-live.identity")
            await retained.update(content)
            return
        }
        // A user dismissal suppresses re-creation for this same selected item.
        guard lastIdentity != windowIdentity, UIApplication.shared.applicationState == .active else { return }
        do {
            if candidate.activityStartsAt <= now {
                _ = try Activity.request(attributes: attributes, content: content, pushType: nil)
            } else if #available(iOS 26.0, *) {
                _ = try Activity.request(attributes: attributes, content: content, pushType: nil, style: .standard,
                    alertConfiguration: .init(title: LocalizedStringResource("\(AppStrings.openMatesName)"),
                                              body: LocalizedStringResource("\(AppStrings.liveActivityUpcomingTitle)"), sound: .default),
                    start: candidate.activityStartsAt)
            } else {
                // Older OS versions reconcile again on foreground/save/sync. A
                // local notification or suspended timer cannot start an activity.
                return
            }
            lastIdentity = windowIdentity
            defaults.set(windowIdentity, forKey: "openmates.upcoming-live.identity")
        } catch {
            NativeDiagnostics.event("upcoming_live_activity_unavailable", category: "live_activities", level: .warning)
        }
    }
    #endif
}
