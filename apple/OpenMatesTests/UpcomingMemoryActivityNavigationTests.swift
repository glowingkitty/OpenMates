import XCTest
@testable import OpenMates

final class UpcomingMemoryActivityNavigationTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_791_021_600)

    // contract-test: supporting surface=gui.apple assertions=apple-live-activities.memories.upcoming
    func testFourHourPagesExcludeExpiredAndFutureItemsAndWrapBothWays() throws {
        let first = page("first", seconds: 1), boundary = page("boundary", seconds: 14_400)
        let pages = UpcomingMemoryActivityNavigation.pages([
            page("expired", seconds: 0), first, boundary, page("later", seconds: 14_401)
        ], now: now)
        XCTAssertEqual(pages, [first, boundary])
        XCTAssertEqual(UpcomingMemoryActivityNavigation.selectedIndex(in: pages, identity: first.identity, step: -1), 1)
        XCTAssertEqual(UpcomingMemoryActivityNavigation.selectedIndex(in: pages, identity: boundary.identity, step: 1), 0)
        XCTAssertNil(UpcomingMemoryActivityNavigation.selectedIndex(in: pages, identity: first.identity, step: 2))
        XCTAssertNil(UpcomingMemoryActivityNavigation.selectedIndex(in: [], identity: nil))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-live-activities.memories.upcoming,apple-live-activities.lifecycle.isolation
    func testRemovedOrExpiredSelectionAdoptsEarliestRemainingInsteadOfSkippingIt() {
        let pages = [page("remaining", seconds: 10), page("last", seconds: 20)]
        XCTAssertEqual(UpcomingMemoryActivityNavigation.selectedIndex(in: pages, identity: "removed", step: 1), 0)
        XCTAssertEqual(UpcomingMemoryActivityNavigation.selectedIndex(in: pages, identity: "removed", step: -1), 0)
        XCTAssertEqual(UpcomingMemoryActivityNavigation.selectedIndex(in: pages, identity: "last"), 1)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-live-activities.lifecycle.isolation
    func testAuthorizationRejectsEveryMissingPermissionAndStaleScope() {
        func accepts(identity: String = "scope", expected: String = "scope", kind: String = "upcoming",
                     owner: Bool = true, authenticated: Bool = true, notifications: Bool = true, activities: Bool = true) -> Bool {
            UpcomingMemoryActivityNavigation.accepts(activityIdentity: identity, expectedIdentity: expected, kind: kind,
                ownerMatches: owner, authenticated: authenticated, notificationsAllowed: notifications, activitiesEnabled: activities)
        }
        XCTAssertTrue(accepts())
        XCTAssertFalse(accepts(identity: "previous-account-server-or-team"))
        XCTAssertFalse(accepts(kind: "download"))
        XCTAssertFalse(accepts(owner: false))
        XCTAssertFalse(accepts(authenticated: false))
        XCTAssertFalse(accepts(notifications: false))
        XCTAssertFalse(accepts(activities: false))
    }

    private func page(_ identity: String, seconds: TimeInterval) -> UpcomingMemoryActivityPage {
        .init(identity: identity, startsAt: now.addingTimeInterval(seconds))
    }
}

#if os(iOS)
import ActivityKit

@MainActor
final class UpcomingMemoryActivityNavigationEffectsTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_791_021_600)

    // contract-test: direct surface=gui.apple assertions=apple-live-activities.memories.upcoming,apple-live-activities.lifecycle.isolation
    func testColdCoordinatorAdoptsOSSnapshotAndPublishesNextPreviousAndExpiredRemoval() async throws {
        let suite = "UpcomingMemoryNavigationTests-" + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let owner = UpcomingMemoryLiveActivityCoordinator.opaque("disposable-account/server/team")
        defaults.set(owner, forKey: "openmates.upcoming-live.owner")
        let identity = UpcomingMemoryLiveActivityCoordinator.opaque(owner + ":upcoming")
        let pages = (1...3).map { UpcomingMemoryActivityPage(identity: String(repeating: String($0), count: 32),
            startsAt: now.addingTimeInterval(Double($0) * 60)) }
        let driver = UpcomingNavigationEffectProbe(owner: owner, identity: identity, state: state(pages: pages))
        // No full memory read/reconcile has occurred in this relaunched process.
        let coordinator = UpcomingMemoryLiveActivityCoordinator(defaults: defaults, navigationDriver: driver)
        await coordinator.navigate(activityIdentity: identity, step: 1, now: now)
        XCTAssertEqual(driver.current?.startsAt, pages[1].startsAt)
        XCTAssertEqual(driver.updates.count, 1)
        await coordinator.navigate(activityIdentity: identity, step: -1, now: now)
        XCTAssertEqual(driver.current?.startsAt, pages[0].startsAt)
        await coordinator.navigate(activityIdentity: identity, step: -1, now: now)
        XCTAssertEqual(driver.current?.startsAt, pages[2].startsAt, "Previous wraps to the last page")
        await coordinator.navigate(activityIdentity: identity, step: 1, now: pages[0].startsAt)
        XCTAssertEqual(driver.current?.startsAt, pages[1].startsAt)
        XCTAssertEqual(driver.current?.itemCount, 2)
        XCTAssertEqual(driver.current?.upcomingPages?.count, 2)
        XCTAssertEqual(driver.current?.expiresAt, pages[1].startsAt)
        await coordinator.navigate(activityIdentity: identity, step: 1, now: pages[2].startsAt)
        XCTAssertNil(driver.current)
        XCTAssertEqual(driver.ends, 1, "Expired bounded state ends instead of displaying a past appointment")
        XCTAssertEqual(driver.ownerChecks, 5, "Each intent revalidates the live account and OS permission")
    }

    // contract-test: direct surface=gui.apple assertions=apple-live-activities.lifecycle.isolation
    func testColdCoordinatorRejectsMissingAuthStaleOwnerAndForeignActivity() async throws {
        let suite = "UpcomingMemoryNavigationTests-" + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let owner = UpcomingMemoryLiveActivityCoordinator.opaque("disposable-owner")
        let identity = UpcomingMemoryLiveActivityCoordinator.opaque(owner + ":upcoming")
        defaults.set(owner, forKey: "openmates.upcoming-live.owner")
        let driver = UpcomingNavigationEffectProbe(owner: nil, identity: identity,
            state: state(pages: [.init(identity: "opaque-item", startsAt: now.addingTimeInterval(60))]))
        let coordinator = UpcomingMemoryLiveActivityCoordinator(defaults: defaults, navigationDriver: driver)
        await coordinator.navigate(activityIdentity: identity, step: 1, now: now)
        driver.owner = UpcomingMemoryLiveActivityCoordinator.opaque("other-owner")
        await coordinator.navigate(activityIdentity: identity, step: 1, now: now)
        driver.owner = owner
        await coordinator.navigate(activityIdentity: "foreign-activity", step: 1, now: now)
        XCTAssertTrue(driver.updates.isEmpty)
        XCTAssertEqual(driver.ends, 0)
        XCTAssertEqual(driver.stateReads, 0, "Unvalidated owner/identity cannot even adopt OS content")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-live-activities.memories.upcoming,apple-live-activities.lifecycle.isolation
    func testPayloadCapsPagesShrinksLongContentAndPreservesOverflowTotal() throws {
        let pages = (1...30).map { UpcomingMemoryActivityPage(identity: String(format: "%032x", $0),
            startsAt: now.addingTimeInterval(Double($0) * 60)) }
        let attributes = OpenMatesLiveActivityAttributes(identity: String(repeating: "a", count: 64), kind: "upcoming")
        var initial = state(pages: pages)
        initial.selectedUpcomingIdentity = pages[3].identity
        let bounded = try XCTUnwrap(UpcomingMemoryActivityNavigation.bounded(initial, attributes: attributes))
        XCTAssertLessThanOrEqual(try XCTUnwrap(bounded.upcomingPages?.count), 24)
        XCTAssertEqual(bounded.itemCount, 30)
        XCTAssertEqual(bounded.selectedUpcomingIdentity, pages[3].identity)
        XCTAssertLessThanOrEqual(try XCTUnwrap(UpcomingMemoryActivityNavigation.payloadBytes(bounded, attributes: attributes)), 3_072)
        var expanded = state(pages: pages, title: String(repeating: "多", count: 550))
        var fullPageBudgetProbe = expanded
        fullPageBudgetProbe.upcomingPages = bounded.upcomingPages
        XCTAssertGreaterThan(try XCTUnwrap(UpcomingMemoryActivityNavigation.payloadBytes(fullPageBudgetProbe, attributes: attributes)), 3_072,
                             "This fixture must exceed the byte budget even after applying the page-count cap")
        let shrunk = try XCTUnwrap(UpcomingMemoryActivityNavigation.bounded(expanded, attributes: attributes))
        XCTAssertLessThan(try XCTUnwrap(shrunk.upcomingPages?.count), try XCTUnwrap(bounded.upcomingPages?.count))
        XCTAssertEqual(shrunk.itemCount, 30)
        expanded = state(pages: pages, title: String(repeating: "多", count: 2_000))
        XCTAssertNil(UpcomingMemoryActivityNavigation.bounded(expanded, attributes: attributes), "Never publish an oversized ActivityKit payload")
        let encoded = String(decoding: try JSONEncoder().encode(bounded), as: UTF8.self)
        XCTAssertFalse(encoded.contains("embed_id"))
        XCTAssertFalse(encoded.contains("appointment_time"))
        XCTAssertFalse(encoded.contains("notes"))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-live-activities.memories.upcoming,apple-live-activities.lifecycle.isolation
    func testAuthoritativePageRemovalRetainsSelectionThenFallsBackWhenSelectedItemIsRemoved() throws {
        let pages = (1...3).map { UpcomingMemoryActivityPage(identity: "opaque-\($0)", startsAt: now.addingTimeInterval(Double($0) * 60)) }
        let attributes = OpenMatesLiveActivityAttributes(identity: "opaque-owner", kind: "upcoming")
        var updated = state(pages: pages)
        updated.selectedUpcomingIdentity = pages[1].identity
        updated.upcomingPages = [pages[1], pages[2]]
        updated.itemCount = 2
        let retained = try XCTUnwrap(UpcomingMemoryActivityNavigation.bounded(updated, attributes: attributes))
        XCTAssertEqual(retained.startsAt, pages[1].startsAt)
        updated.upcomingPages = [pages[2]]
        updated.itemCount = 1
        let replaced = try XCTUnwrap(UpcomingMemoryActivityNavigation.bounded(updated, attributes: attributes))
        XCTAssertEqual(replaced.startsAt, pages[2].startsAt)
        XCTAssertEqual(replaced.selectedUpcomingIdentity, pages[2].identity)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-live-activities.lifecycle.isolation,apple-live-activities.memories.upcoming
    func testExistingRemoteActivityPayloadDecodesWithoutNavigationFields() throws {
        let data = Data(#"{"title":"Processing","detail":"Active chats","phase":"processing","progress":0,"completedBytes":0,"totalBytes":0,"itemCount":2}"#.utf8)
        let decoded = try JSONDecoder().decode(OpenMatesLiveActivityAttributes.ContentState.self, from: data)
        XCTAssertEqual(decoded.itemCount, 2)
        XCTAssertNil(decoded.upcomingPages)
        XCTAssertNil(decoded.selectedUpcomingIdentity)
    }

    private func state(pages: [UpcomingMemoryActivityPage], title: String = "Upcoming event") -> OpenMatesLiveActivityAttributes.ContentState {
        var result = OpenMatesLiveActivityAttributes.ContentState(title: title, detail: "Open your saved memories",
            phase: "upcoming", progress: 0, completedBytes: 0, totalBytes: 0, itemCount: pages.count,
            startsAt: pages.first?.startsAt, expiresAt: pages.first?.startsAt)
        result.upcomingPages = pages
        result.selectedUpcomingIdentity = pages.first?.identity
        return result
    }
}

@MainActor
private final class UpcomingNavigationEffectProbe: UpcomingMemoryNavigationDriving {
    var owner: String?
    let identity: String
    var current: OpenMatesLiveActivityAttributes.ContentState?
    private(set) var updates: [OpenMatesLiveActivityAttributes.ContentState] = []
    private(set) var ends = 0
    private(set) var ownerChecks = 0
    private(set) var stateReads = 0
    init(owner: String?, identity: String, state: OpenMatesLiveActivityAttributes.ContentState) {
        self.owner = owner; self.identity = identity; current = state
    }
    func authorizedOwner() async -> String? { ownerChecks += 1; return owner }
    func state(for identity: String) -> OpenMatesLiveActivityAttributes.ContentState? {
        stateReads += 1
        return identity == self.identity ? current : nil
    }
    func update(_ state: OpenMatesLiveActivityAttributes.ContentState, identity: String) async {
        guard identity == self.identity else { return }
        updates.append(state); current = state
    }
    func end(identity: String) async { if identity == self.identity { ends += 1; current = nil } }
}
#endif
