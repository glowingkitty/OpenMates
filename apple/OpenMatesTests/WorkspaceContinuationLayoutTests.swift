import XCTest
@testable import OpenMates

final class WorkspaceContinuationLayoutTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=message-input.layout.responsive-parity
    func testShortKeyboardAdaptationAppliesOnlyToLandscapePhoneKeyboard() {
        XCTAssertTrue(MessageComposerMetric.compactKeyboardLayout(isPhone: true, compactHeight: true, keyboardVisible: true))
        XCTAssertFalse(MessageComposerMetric.compactKeyboardLayout(isPhone: false, compactHeight: true, keyboardVisible: true))
        XCTAssertFalse(MessageComposerMetric.compactKeyboardLayout(isPhone: true, compactHeight: false, keyboardVisible: true))
        XCTAssertFalse(MessageComposerMetric.compactKeyboardLayout(isPhone: true, compactHeight: true, keyboardVisible: false))
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.layout.responsive-parity
    func testZeroHeightRegressionRequiresReclaimedPhysicalChromeAndBoundedCollapse() {
        let originalAvailable: CGFloat = 116
        let originalCap = MessageComposerMetric.welcomeMaximumFieldHeight(availableHeight: originalAvailable, compactKeyboardLayout: false)
        XCTAssertEqual(originalCap, 56)
        XCTAssertEqual(max(0, originalCap - MessageComposerMetric.expandedBottomReservedHeight), 0)
        // Reclaimed measured chrome is an input, never a minimum-size clamp.
        let reclaimedAvailable = originalAvailable + 66
        let cap = MessageComposerMetric.welcomeMaximumFieldHeight(availableHeight: reclaimedAvailable, compactKeyboardLayout: true)
        XCTAssertEqual(cap, 142)
        let collapsed = MessageComposerMetric.boundedFieldHeight(intrinsicHeight: MessageComposerMetric.collapsedTextFieldMaxHeight,
            maximumHeight: cap, compact: false, fullscreen: false, containsEmbed: false, topReservedHeight: 0)
        let expanded = MessageComposerMetric.boundedFieldHeight(intrinsicHeight: cap,
            maximumHeight: cap, compact: false, fullscreen: true, containsEmbed: false, topReservedHeight: 0)
        XCTAssertEqual(collapsed, MessageComposerMetric.focusedEmptyHeight)
        XCTAssertLessThan(collapsed, expanded)
        XCTAssertGreaterThan(collapsed - MessageComposerMetric.expandedBottomReservedHeight,
            MessageComposerMetric.editorVerticalInset * 2 + MessageComposerMetric.editorLineHeight)
        XCTAssertEqual(expanded + 40, reclaimedAvailable, "Field and dismissal reserve fit the physical viewport")
        XCTAssertEqual(MessageComposerMetric.boundedFieldHeight(intrinsicHeight: 165, maximumHeight: cap,
            compact: false, fullscreen: false, containsEmbed: true, topReservedHeight: 0), cap)
        XCTAssertEqual(MessageComposerMetric.boundedFieldHeight(intrinsicHeight: 165, maximumHeight: cap,
            compact: false, fullscreen: false, containsEmbed: false, topReservedHeight: 0, hasInlineContent: true), cap)
        XCTAssertEqual(MessageComposerMetric.boundedFieldHeight(intrinsicHeight: 165, maximumHeight: 56,
            compact: false, fullscreen: false, containsEmbed: false, topReservedHeight: 0), 56,
            "An impossible physical cap must never be exceeded")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,projects.surface.semantic-parity
    func testTallPhoneUsesActualBannerComposerGapAndCentersInsideIt() {
        let placement = WorkspaceContinuationLayoutPolicy.resolve(width: 390, height: 744, bannerBottom: 190, composerTop: 644)
        XCTAssertTrue(placement.expanded)
        XCTAssertEqual(placement.availableHeight, 454)
        XCTAssertEqual(placement.centerY, 417)
        XCTAssertGreaterThanOrEqual(placement.centerY - 180, placement.top)
        XCTAssertLessThanOrEqual(placement.centerY + 180, placement.bottom)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,projects.surface.semantic-parity
    func testExactGapBoundaryAndWideShortWorkspace() {
        XCTAssertTrue(WorkspaceContinuationLayoutPolicy.resolve(width: 300, height: 700, bannerBottom: 190, composerTop: 550).expanded)
        XCTAssertFalse(WorkspaceContinuationLayoutPolicy.resolve(width: 390, height: 700, bannerBottom: 190, composerTop: 549).expanded)
        XCTAssertFalse(WorkspaceContinuationLayoutPolicy.resolve(width: 1024, height: 800, bannerBottom: 420, composerTop: 720).expanded,
                       "A wide viewport cannot substitute for space below its taller banner")
        XCTAssertFalse(WorkspaceContinuationLayoutPolicy.resolve(width: 299, height: 900, bannerBottom: 190, composerTop: 800).expanded,
                       "A complete 300-point card must fit the actual content lane")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,projects.surface.semantic-parity
    func testOrdinaryTallPhoneExpandsWithinMeasuredGapAndWorkflowBadgeReserve() {
        let ordinary = WorkspaceContinuationLayoutPolicy.resolve(width: 390, height: 744,
            bannerBottom: 190, composerTop: 594)
        XCTAssertTrue(ordinary.expanded, "A 404pt content gap fits the complete tall-phone stack")
        XCTAssertTrue(WorkspaceContinuationLayoutPolicy.resolve(width: 390, height: 744,
            bannerBottom: 190, composerTop: 594, requiredExpandedHeight: 400).expanded)
        XCTAssertFalse(WorkspaceContinuationLayoutPolicy.resolve(width: 390, height: 744,
            bannerBottom: 190, composerTop: 580, requiredExpandedHeight: 400).expanded,
            "A workflow badge must fit along with its greeting, card and links")
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
