// OS-owned ActivityKit navigation: supported intent buttons replace custom gestures.
// Web source: none — Live Activities are an Apple platform capability.
// Specification: specifications/features/apple-live-activities/specification.yml
// Assertions: apple-live-activities.memories.upcoming, apple-live-activities.lifecycle.isolation
import Foundation

/// Only an opaque item identity and its time cross into the OS presentation.
struct UpcomingMemoryActivityPage: Codable, Hashable, Sendable {
    let identity: String
    let startsAt: Date
}

enum UpcomingMemoryActivityNavigation {
    // ActivityKit's entire dynamic + static payload has a 4 KB limit. Keep the
    // navigation snapshot bounded; the full memory snapshot stays in the app.
    static let maximumPages = 24

    static func pages(_ pages: [UpcomingMemoryActivityPage], now: Date) -> [UpcomingMemoryActivityPage] {
        Array(pages.filter { $0.startsAt > now && $0.startsAt <= now.addingTimeInterval(4 * 3_600) }
            .prefix(maximumPages))
    }

    static func selectedIndex(in pages: [UpcomingMemoryActivityPage], identity: String?, step: Int = 0) -> Int? {
        guard !pages.isEmpty, (-1...1).contains(step) else { return nil }
        guard let index = identity.flatMap({ id in pages.firstIndex { $0.identity == id } }) else { return 0 }
        return (index + step + pages.count) % pages.count
    }

    static func accepts(activityIdentity: String, expectedIdentity: String, kind: String,
                        ownerMatches: Bool, authenticated: Bool, notificationsAllowed: Bool,
                        activitiesEnabled: Bool) -> Bool {
        kind == "upcoming" && activityIdentity == expectedIdentity && ownerMatches
            && authenticated && notificationsAllowed && activitiesEnabled
    }
}

#if os(iOS) && canImport(ActivityKit)
import AppIntents
import ActivityKit
import SwiftUI

struct UpcomingMemoryActivityNavigationLabels {
    let previous: String
    let next: String
    let position: String
    let total: String
    let viewAll: String
}

/// The exact controls are shared with the detached Debug GUI fixture.
@available(iOS 17.0, *)
struct UpcomingMemoryActivityNavigationControls: View {
    let state: OpenMatesLiveActivityAttributes.ContentState
    let identity: String
    let labels: UpcomingMemoryActivityNavigationLabels
    var body: some View {
        if let pages = state.upcomingPages,
           let index = UpcomingMemoryActivityNavigation.selectedIndex(in: pages, identity: state.selectedUpcomingIdentity) {
            HStack {
                if pages.count > 1 {
                    Button(intent: NavigateUpcomingMemoryIntent(activityIdentity: identity, step: -1)) {
                        Label(labels.previous, systemImage: "chevron.left").labelStyle(.iconOnly).padding(8)
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("upcoming-live-activity-previous")
                }
                Text(labels.position.replacingOccurrences(of: "{number}", with: String(index + 1))
                    .replacingOccurrences(of: "{count}", with: String(pages.count)))
                    .monospacedDigit()
                    .accessibilityIdentifier("upcoming-live-activity-position")
                if pages.count > 1 {
                    Button(intent: NavigateUpcomingMemoryIntent(activityIdentity: identity, step: 1)) {
                        Label(labels.next, systemImage: "chevron.right").labelStyle(.iconOnly).padding(8)
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("upcoming-live-activity-next")
                }
                Spacer()
                if state.itemCount > pages.count {
                    Text(labels.total.replacingOccurrences(of: "{count}", with: String(state.itemCount)))
                    Link(labels.viewAll, destination: URL(string: "openmates://settings/settings_memories")!)
                        .accessibilityIdentifier("upcoming-live-activity-view-all")
                }
            }
            .font(.caption)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("upcoming-live-activity-navigation")
            .accessibilityValue("total=\(state.itemCount);pages=\(pages.count);selected=\(index + 1)")
        }
    }
}

@available(iOS 16.2, *)
extension UpcomingMemoryActivityNavigation {
    /// Leave at least 1 KB for ActivityKit envelope/encoding differences.
    static let payloadBudget = 3_072

    static func payloadBytes(_ state: OpenMatesLiveActivityAttributes.ContentState,
                             attributes: OpenMatesLiveActivityAttributes) -> Int? {
        guard let stateData = try? JSONEncoder().encode(state),
              let attributesData = try? JSONEncoder().encode(attributes) else { return nil }
        return stateData.count + attributesData.count
    }

    static func bounded(_ input: OpenMatesLiveActivityAttributes.ContentState,
                        attributes: OpenMatesLiveActivityAttributes) -> OpenMatesLiveActivityAttributes.ContentState? {
        var state = input
        var pages = Array((state.upcomingPages ?? []).prefix(maximumPages))
        while !pages.isEmpty {
            state.upcomingPages = pages
            guard let index = selectedIndex(in: pages, identity: state.selectedUpcomingIdentity) else { return nil }
            state.selectedUpcomingIdentity = pages[index].identity
            state.startsAt = pages[index].startsAt
            state.expiresAt = pages[index].startsAt
            if let count = payloadBytes(state, attributes: attributes), count <= payloadBudget { return state }
            pages.removeLast()
        }
        return nil
    }

    static func moved(_ input: OpenMatesLiveActivityAttributes.ContentState, step: Int,
                      now: Date) -> OpenMatesLiveActivityAttributes.ContentState? {
        guard (-1...1).contains(step), let source = input.upcomingPages else { return nil }
        let eligible = pages(source, now: now)
        guard let index = selectedIndex(in: eligible, identity: input.selectedUpcomingIdentity, step: step) else { return nil }
        var state = input
        state.upcomingPages = eligible
        state.selectedUpcomingIdentity = eligible[index].identity
        state.startsAt = eligible[index].startsAt
        state.expiresAt = eligible[index].startsAt
        // Overflow cannot be refreshed from OS state; retain its known total,
        // subtracting only the expired pages visible in this bounded snapshot.
        state.itemCount = max(eligible.count, input.itemCount - (source.count - eligible.count))
        return state
    }
}

@available(iOS 17.0, *)
struct NavigateUpcomingMemoryIntent: LiveActivityIntent {
    static let title: LocalizedStringResource = "live_activities.upcoming_next"
    static let openAppWhenRun = false
    static let isDiscoverable = false
    #if DEBUG && !OPENMATES_WIDGET_EXTENSION
    /// Detached fixtures register only their random synthetic identity; no real
    /// owner or ActivityKit activity can use this account-independent seam.
    @MainActor static var fixtureActions: [String: @MainActor (Int) async -> Void] = [:]
    #endif

    @Parameter(title: "Activity") var activityIdentity: String
    @Parameter(title: "Direction") var step: Int

    init() {}
    init(activityIdentity: String, step: Int) {
        self.activityIdentity = activityIdentity
        self.step = step
    }

    func perform() async throws -> some IntentResult {
        // LiveActivityIntent executes in the containing app. Both targets must
        // include the type so WidgetKit can archive the button action.
        #if !OPENMATES_WIDGET_EXTENSION
        #if DEBUG
        if let action = await Self.fixtureActions[activityIdentity] {
            await action(step)
            return .result()
        }
        #endif
        await UpcomingMemoryLiveActivityCoordinator.shared.navigate(activityIdentity: activityIdentity, step: step)
        #endif
        return .result()
    }
}
#endif
