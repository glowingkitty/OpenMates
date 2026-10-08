// Detached production intent controls and coordinator, with disposable typed memories.
// Does not request real ActivityKit activities, load accounts, or call inference.
// Specification: specifications/features/apple-live-activities/specification.yml
// Assertions: apple-live-activities.memories.upcoming, apple-live-activities.lifecycle.isolation
#if DEBUG && os(iOS)
import SwiftUI
import ActivityKit

@MainActor
private final class UpcomingMemoryFixtureDriver: ObservableObject, UpcomingMemoryNavigationDriving {
    @Published var current: OpenMatesLiveActivityAttributes.ContentState?
    @Published var route = "none"
    var owner: String?
    let identity: String
    private let suite: String
    private let defaults: UserDefaults
    private var coordinator: UpcomingMemoryLiveActivityCoordinator!
    private var entries: [SettingsMemoryEntry] = []
    private let now = Date()
    init() {
        suite = "DevUpcomingMemoryFixture-" + UUID().uuidString
        defaults = UserDefaults(suiteName: suite)!
        let owner = UpcomingMemoryLiveActivityCoordinator.opaque(suite)
        self.owner = owner
        identity = UpcomingMemoryLiveActivityCoordinator.opaque(owner + ":upcoming")
        defaults.set(owner, forKey: "openmates.upcoming-live.owner")
        coordinator = UpcomingMemoryLiveActivityCoordinator(defaults: defaults, navigationDriver: self)
        entries = (1...3).map { entry($0) }
        refresh()
        NavigateUpcomingMemoryIntent.fixtureActions[identity] = { [weak self] step in
            guard let self else { return }
            await self.coordinator.navigate(activityIdentity: self.identity, step: step, now: self.now)
        }
    }
    private func entry(_ index: Int) -> SettingsMemoryEntry {
        let formatter = ISO8601DateFormatter()
        let app = index == 1 ? "health" : index == 2 ? "events" : "travel"
        let category = index == 1 ? "appointments" : index == 2 ? "saved_events" : "saved_connections"
        let field = index == 1 ? "appointment_time" : index == 2 ? "date_start" : "departure"
        return .init(id: "fixture-\(index)", appId: app, categoryId: category, key: "Private fixture medical title",
            value: "Private fixture memory body", createdAt: 0, updatedAt: 0, version: 1, isExample: false,
            fields: ["embed_id": .string("fixture-embed-\(index)"), "title": .string("Private fixture medical title"),
                     "notes": .string("Private fixture medical notes"),
                     field: .string(formatter.string(from: now.addingTimeInterval(Double(index) * 60)))])
    }
    private func refresh() {
        guard let owner else { current = nil; return }
        let sanitized = UpcomingMemorySnapshotBindingPolicy.sanitizedEntries(entries)
        let candidates = UpcomingMemoryActivityPolicy.candidates(from: sanitized, now: now).filter { $0.activityStartsAt <= now }
        guard !candidates.isEmpty else { current = nil; return }
        var state = OpenMatesLiveActivityAttributes.ContentState(title: "Upcoming event", detail: "Open your saved memories",
            phase: "upcoming", progress: 0, completedBytes: 0, totalBytes: 0, itemCount: candidates.count,
            startsAt: candidates.first?.startsAt, expiresAt: candidates.first?.startsAt)
        state.upcomingPages = candidates.map { UpcomingMemoryActivityPolicy.page($0, owner: owner) }
        state.selectedUpcomingIdentity = current?.selectedUpcomingIdentity
        current = UpcomingMemoryActivityNavigation.bounded(state,
            attributes: .init(identity: identity, kind: "upcoming"))
    }
    func removeFirst() { entries.removeAll { $0.id == "fixture-1" }; refresh() }
    func overflow() { entries = (1...30).map { entry($0) }; refresh() }
    func switchOwner() { owner = UpcomingMemoryLiveActivityCoordinator.opaque("another-disposable-owner") }
    func authorizedOwner() async -> String? { owner }
    func state(for identity: String) -> OpenMatesLiveActivityAttributes.ContentState? { identity == self.identity ? current : nil }
    func update(_ state: OpenMatesLiveActivityAttributes.ContentState, identity: String) async {
        if identity == self.identity { current = state }
    }
    func end(identity: String) async { if identity == self.identity { current = nil } }
    func cleanup() {
        NavigateUpcomingMemoryIntent.fixtureActions.removeValue(forKey: identity)
        defaults.removePersistentDomain(forName: suite)
    }
}

struct DevUpcomingMemoryLiveActivityFixture: View {
    @StateObject private var driver = UpcomingMemoryFixtureDriver()
    var body: some View {
        VStack(spacing: .spacing4) {
            if let state = driver.current {
                UpcomingMemorySmallActivityView(state: state, kind: "upcoming", isStale: false)
                    .padding(8).frame(width: 176, height: 140).background(Color.grey0)
                    .accessibilityIdentifier("upcoming-small-fixture-container")
                VStack(alignment: .leading, spacing: .spacing2) {
                    Text(state.title)
                    Text(state.detail)
                    if let start = state.startsAt { Text(start, style: .time) }
                    UpcomingMemoryActivityNavigationControls(state: state, identity: driver.identity,
                        labels: .init(previous: "Previous", next: "Next", position: "{number} of {count}",
                                      total: "{count} upcoming", viewAll: "View all"))
                }
                .padding(.spacing4).frame(width: 360).background(Color.grey0)
                .environment(\.openURL, OpenURLAction { url in
                    driver.route = url.absoluteString == "openmates://settings/settings_memories" ? "memories" : "other"
                    return .handled
                })
            }
            Text(driver.route).accessibilityIdentifier("upcoming-live-fixture-route")
            Button { driver.removeFirst() } label: { Text("Remove first").frame(minHeight: 44).contentShape(Rectangle()) }
                .buttonStyle(.plain).accessibilityIdentifier("upcoming-live-fixture-remove")
            Button { driver.overflow() } label: { Text("Overflow").frame(minHeight: 44).contentShape(Rectangle()) }
                .buttonStyle(.plain).accessibilityIdentifier("upcoming-live-fixture-overflow")
            Button { driver.switchOwner() } label: { Text("Switch owner").frame(minHeight: 44).contentShape(Rectangle()) }
                .buttonStyle(.plain).accessibilityIdentifier("upcoming-live-fixture-switch-owner")
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("upcoming-live-activity-fixture")
        .onDisappear { driver.cleanup() }
    }
}
#endif
