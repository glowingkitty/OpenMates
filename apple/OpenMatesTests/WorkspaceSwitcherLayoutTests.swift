import XCTest
@testable import OpenMates

final class WorkspaceSwitcherLayoutTests: XCTestCase {
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
}
