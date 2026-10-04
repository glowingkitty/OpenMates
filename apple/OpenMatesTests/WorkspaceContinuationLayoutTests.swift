import XCTest
@testable import OpenMates

final class WorkspaceContinuationLayoutTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,projects.surface.semantic-parity
    func testTallPhoneUsesActualBannerComposerGapAndCentersInsideIt() {
        let placement = WorkspaceContinuationLayoutPolicy.resolve(width: 390, height: 744, bannerBottom: 190, composerTop: 644)
        XCTAssertTrue(placement.expanded)
        XCTAssertEqual(placement.availableHeight, 454)
        XCTAssertEqual(placement.centerY, 417)
        XCTAssertGreaterThanOrEqual(placement.centerY - 210, placement.top)
        XCTAssertLessThanOrEqual(placement.centerY + 210, placement.bottom)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,projects.surface.semantic-parity
    func testExactGapBoundaryAndWideShortWorkspace() {
        XCTAssertTrue(WorkspaceContinuationLayoutPolicy.resolve(width: 300, height: 700, bannerBottom: 190, composerTop: 610).expanded)
        XCTAssertFalse(WorkspaceContinuationLayoutPolicy.resolve(width: 390, height: 700, bannerBottom: 190, composerTop: 609).expanded)
        XCTAssertFalse(WorkspaceContinuationLayoutPolicy.resolve(width: 1024, height: 800, bannerBottom: 420, composerTop: 720).expanded,
                       "A wide viewport cannot substitute for space below its taller banner")
        XCTAssertFalse(WorkspaceContinuationLayoutPolicy.resolve(width: 299, height: 900, bannerBottom: 190, composerTop: 800).expanded,
                       "A complete 300-point card must fit the actual content lane")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,projects.surface.semantic-parity
    func testKeyboardAndOverlappingBoundsCannotPlaceCardsUnderComposer() {
        let keyboard = WorkspaceContinuationLayoutPolicy.resolve(width: 390, height: 500, bannerBottom: 190, composerTop: 410)
        XCTAssertFalse(keyboard.expanded)
        XCTAssertEqual(keyboard.centerY, 300)
        let overlap = WorkspaceContinuationLayoutPolicy.resolve(width: 390, height: 300, bannerBottom: 190, composerTop: 150)
        XCTAssertFalse(overlap.expanded)
        XCTAssertEqual(overlap.availableHeight, 0)
        XCTAssertEqual(overlap.centerY, 190)
        let invalid = WorkspaceContinuationLayoutPolicy.resolve(width: .infinity, height: .nan, bannerBottom: .nan, composerTop: .infinity)
        XCTAssertFalse(invalid.expanded)
        XCTAssertEqual(invalid.availableHeight, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=projects.surface.semantic-parity
    func testProjectBrowseMatchesOnlyCurrentProjectMetadata() {
        XCTAssertTrue(WorkspaceProjectBrowsePolicy.matches(query: "  LAUNCH\n", name: "Launch plan", description: "Engineering work"))
        XCTAssertTrue(WorkspaceProjectBrowsePolicy.matches(query: "research", name: "Plan", description: "Customer research"))
        XCTAssertTrue(WorkspaceProjectBrowsePolicy.matches(query: " \n", name: "Plan", description: ""))
        XCTAssertFalse(WorkspaceProjectBrowsePolicy.matches(query: "chat-only phrase", name: "Launch plan", description: "Engineering work"))
    }
}
