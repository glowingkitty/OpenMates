// Specification: specifications/architecture/sync/specification.yml
// Assertions: sync.surface.semantic-parity, sync.startup.bounded-phases, sync.access.first-party-authenticated
import XCTest
@testable import OpenMates

final class WorkspaceSwitcherLayoutTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,workflows-ui.responsive-accessible-reachable,projects.surface.semantic-parity,apps.presentation.shared-detail-and-recency
    func testCardHoverOnlyScalesEnabledCardAndReducedMotionDisablesAnimation() {
        XCTAssertEqual(OMCardHoverPolicy.scale(hovered: false, enabled: true), 1)
        XCTAssertEqual(OMCardHoverPolicy.scale(hovered: true, enabled: false), 1)
        XCTAssertEqual(OMCardHoverPolicy.scale(hovered: true, enabled: true), 1.05, accuracy: 0.001)
        XCTAssertNil(OMCardHoverPolicy.animationDuration(reduceMotion: true))
        XCTAssertEqual(OMCardHoverPolicy.animationDuration(reduceMotion: false), 0.15)
    }

    // contract-test: supporting surface=gui.apple assertions=workspace-shell.nav.released-surfaces-visible
    func testTabsFitTheMeasuredCenterLaneAtTheExactBoundary() {
        let inset = 2 * (CGFloat(90) + .spacing10 + .spacing4)
        XCTAssertFalse(WorkspaceSwitcherLayoutPolicy.isCompact(headerWidth: 360 + inset, leadingWidth: 90, trailingWidth: 80))
        XCTAssertTrue(WorkspaceSwitcherLayoutPolicy.isCompact(headerWidth: 359 + inset, leadingWidth: 90, trailingWidth: 80))
    }

    // contract-test: supporting surface=gui.apple assertions=workspace-shell.nav.released-surfaces-visible
    func testSidebarAndLongHeaderControlsUseRemainingSpaceOnEveryPlatform() {
        XCTAssertFalse(WorkspaceSwitcherLayoutPolicy.isCompact(headerWidth: 730, leadingWidth: 90, trailingWidth: 84))
        XCTAssertTrue(WorkspaceSwitcherLayoutPolicy.isCompact(headerWidth: 730, leadingWidth: 90, trailingWidth: 190))
        XCTAssertTrue(WorkspaceSwitcherLayoutPolicy.isCompact(headerWidth: 390, leadingWidth: 90, trailingWidth: 84))
        XCTAssertTrue(WorkspaceSwitcherLayoutPolicy.isCompact(headerWidth: .nan, leadingWidth: 0, trailingWidth: 0))
    }
    // contract-test: supporting surface=gui.apple assertions=workspace-shell.nav.released-surfaces-visible
    func testShortViewportClampsPanelAndKeepsRoomForScrollableRows() {
        let short = WorkspaceSwitcherLayoutPolicy.panelHeight(viewportHeight: 320)
        XCTAssertLessThanOrEqual(short + CGFloat.spacing5 + CGFloat.spacing4, 320)
        XCTAssertGreaterThanOrEqual(short - WorkspaceSwitcherLayoutPolicy.triggerHeight, 60)
        XCTAssertEqual(WorkspaceSwitcherLayoutPolicy.panelHeight(viewportHeight: 844), 376)
        XCTAssertEqual(WorkspaceSwitcherLayoutPolicy.panelHeight(viewportHeight: .nan), 44)
        XCTAssertEqual(WorkspaceSwitcherLayoutPolicy.panelHeight(viewportHeight: 0), 44)
    }
    // contract-test: supporting surface=gui.apple assertions=workspace-shell.nav.released-surfaces-visible
    func testCompactTriggerFitsBetweenMeasuredControlsAt320And390() {
        for (width, expected) in [(CGFloat(320), CGFloat(84)), (CGFloat(390), CGFloat(120))] {
            let lane = WorkspaceSwitcherLayoutPolicy.availableWidth(headerWidth: width, leadingWidth: 90, trailingWidth: 84)
            let trigger = WorkspaceSwitcherLayoutPolicy.compactTriggerWidth(availableCenterWidth: lane)
            XCTAssertEqual(trigger, expected)
            let start = (width - trigger) / 2
            let end = start + trigger
            XCTAssertGreaterThanOrEqual(start, CGFloat.spacing10 + 90 + .spacing4)
            XCTAssertLessThanOrEqual(end, width - .spacing10 - 84 - .spacing4)
        }
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testSyncIndicatorReflectsOnlyAuthenticatedActiveWork() {
        XCTAssertFalse(NativeHeaderSyncActivityPolicy.isActive(authenticated: false,
            initialSyncComplete: false, prefetching: true, flushing: true))
        XCTAssertFalse(NativeHeaderSyncActivityPolicy.isActive(authenticated: true,
            initialSyncComplete: true, prefetching: false, flushing: false))
        for phase in 0..<3 {
            XCTAssertTrue(NativeHeaderSyncActivityPolicy.isActive(authenticated: true,
                initialSyncComplete: phase != 0, prefetching: phase == 1, flushing: phase == 2))
        }
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity,chats.surface.semantic-parity
    func testHeaderConnectionFeedbackPrioritizesOfflineAndReconnectWithWebDelays() {
        var policy = NativeConnectionFeedbackPolicy()
        var input = NativeConnectionFeedbackInputs(online: false, authenticated: false,
            checkingAuth: false, connected: false, syncing: false)
        policy.update(input, now: 0)
        XCTAssertEqual(policy.state, .offline, "Guests also see airplane while offline")
        input.online = true
        policy.update(input, now: 1)
        XCTAssertEqual(policy.state, .idle)
        input.authenticated = true
        policy.update(input, now: 2)
        policy.update(input, now: 4.99)
        XCTAssertEqual(policy.state, .idle)
        policy.update(input, now: 5)
        XCTAssertEqual(policy.state, .reconnecting, "Connecting/disconnected/exhausted states retain feedback")
        input.connected = true; input.syncing = true
        policy.update(input, now: 6)
        policy.update(input, now: 6.59)
        XCTAssertEqual(policy.state, .idle)
        policy.update(input, now: 6.61)
        XCTAssertEqual(policy.state, .syncing)
        input.online = false
        policy.update(input, now: 7)
        XCTAssertEqual(policy.state, .offline, "Reconnect and sync must not hide offline")
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity,chats.surface.semantic-parity
    func testBriefSyncAndDisconnectedChurnDoNotCreateTimerDrivenSyncActivity() {
        var policy = NativeConnectionFeedbackPolicy()
        var input = NativeConnectionFeedbackInputs(online: true, authenticated: true,
            checkingAuth: false, connected: true, syncing: true)
        policy.update(input, now: 0)
        input.syncing = false
        policy.update(input, now: 0.5)
        policy.update(input, now: 100)
        XCTAssertEqual(policy.state, .idle)
        XCTAssertNil(policy.nextUpdateDelay(now: 100))
        input.connected = false
        policy.update(input, now: 101)
        policy.update(input, now: 102)
        policy.update(input, now: 104)
        XCTAssertEqual(policy.state, .reconnecting, "Transport substates cannot restart the presentation debounce")
        input.authenticated = false
        policy.update(input, now: 105)
        XCTAssertEqual(policy.state, .idle, "Logout clears authenticated connection feedback")
    }

    // contract-test: supporting surface=gui.apple assertions=sync.startup.bounded-phases,sync.access.first-party-authenticated
    @MainActor func testSyncActivityCompletionRequiresCurrentFullPersonalScope() {
        XCTAssertTrue(WebSocketManager.completesPersonalPhasedSync(["phase": "all", "context_epoch": 0]))
        XCTAssertFalse(WebSocketManager.completesPersonalPhasedSync(["phase": "metadata", "context_epoch": 0]))
        XCTAssertFalse(WebSocketManager.completesPersonalPhasedSync(["phase": "all", "context_epoch": 1]))
        XCTAssertFalse(WebSocketManager.completesPersonalPhasedSync(["phase": "all"]))
        XCTAssertFalse(WebSocketManager.completesPersonalPhasedSync(["phase": "all", "context_epoch": 0, "team_id": "other-team"]))
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testForegroundGraceSuppressesOnlyPresentationAndExpiresAfterTenSeconds() {
        var policy = NativeConnectionFeedbackPolicy()
        let input = NativeConnectionFeedbackInputs(online: true, authenticated: true,
            checkingAuth: false, connected: false, syncing: false)
        policy.update(input, now: 0); policy.update(input, now: 3)
        XCTAssertEqual(policy.state, .reconnecting)
        policy.resume(now: 4); policy.update(input, now: 4)
        XCTAssertEqual(policy.state, .idle)
        policy.update(input, now: 13.9)
        XCTAssertEqual(policy.state, .idle)
        policy.update(input, now: 14)
        XCTAssertEqual(policy.state, .reconnecting, "Grace must not hide a persistently broken connection")
    }

}
