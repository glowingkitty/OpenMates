// Deterministic coverage for responsive shell calculations and gesture policy
// shared by iPhone and iPad. Verifies live pane resizing, threshold settlement,
// bottom-corner system gesture exclusion, and chat-only inspiration growth without
// depending on simulator gesture timing, credentials, or private user data.
// Rendered shell behavior remains covered by ChatShellResponsiveParityUITests.
//
// Web source: frontend/apps/web_app/src/routes/+page.svelte
//             frontend/packages/ui/src/components/ActiveChat.svelte

import XCTest
@testable import OpenMates

final class MainAppLayoutParityTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.layout.responsive-history
    func testRegularSidebarDragResizesActiveChatContinuously() {
        XCTAssertEqual(WorkspaceSidebarLayoutPolicy.leadingInset(width: 1024, isOpen: false, dragOffset: 0), 10)
        XCTAssertEqual(WorkspaceSidebarLayoutPolicy.leadingInset(width: 1024, isOpen: false, dragOffset: 100), 110)
        XCTAssertEqual(WorkspaceSidebarLayoutPolicy.leadingInset(width: 1024, isOpen: false, dragOffset: 500), 335)

        XCTAssertEqual(WorkspaceSidebarLayoutPolicy.leadingInset(width: 1024, isOpen: true, dragOffset: 0), 335)
        XCTAssertEqual(WorkspaceSidebarLayoutPolicy.leadingInset(width: 1024, isOpen: true, dragOffset: -100), 235)
        XCTAssertEqual(WorkspaceSidebarLayoutPolicy.leadingInset(width: 1024, isOpen: true, dragOffset: -500), 10)
        XCTAssertEqual(WorkspaceSidebarLayoutPolicy.leadingInset(width: 390, isOpen: true, dragOffset: -100), 0)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.layout.responsive-history
    func testSettingsDragDoesNotResizeAnAlreadyOpenSidebar() {
        let offsets = MainAppLayoutParity.paneDragOffsets(target: .openSettings, dragOffset: -160)

        XCTAssertEqual(offsets, .init(chats: 0, settings: -160))
        XCTAssertEqual(
            WorkspaceSidebarLayoutPolicy.leadingInset(
                width: 1024,
                isOpen: true,
                dragOffset: offsets.chats
            ),
            335
        )
        XCTAssertEqual(
            MainAppLayoutParity.sideBySideSettingsWidth(
                isOpen: false,
                dragOffset: offsets.settings
            ),
            160
        )
        XCTAssertEqual(ShellSwipePolicy.target(
            startLocation: CGPoint(x: 1023, y: 300),
            translation: CGSize(width: -160, height: 0),
            viewportSize: CGSize(width: 1024, height: 768),
            chatsOpen: true,
            settingsOpen: false,
            settingsSideBySide: true
        ), .openSettings)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.layout.responsive-history
    func testChatDragDoesNotResizeSettingsPane() {
        XCTAssertEqual(
            MainAppLayoutParity.paneDragOffsets(target: .closeChats, dragOffset: -160),
            .init(chats: -160, settings: 0)
        )
        XCTAssertEqual(
            MainAppLayoutParity.paneDragOffsets(target: nil, dragOffset: -160),
            .init(chats: 0, settings: 0)
        )
    }

    // contract-test: supporting surface=gui.apple assertions=chats.layout.responsive-history
    func testShellSwipeUsesWebProgressThresholdToSettleEachPane() {
        XCTAssertFalse(ShellSwipePolicy.shouldSettleOpen(
            target: .openChats,
            translation: CGSize(width: 100, height: 0),
            viewportWidth: 1024
        ))
        XCTAssertTrue(ShellSwipePolicy.shouldSettleOpen(
            target: .openChats,
            translation: CGSize(width: 114, height: 0),
            viewportWidth: 1024
        ))
        XCTAssertTrue(ShellSwipePolicy.shouldSettleOpen(
            target: .closeChats,
            translation: CGSize(width: -100, height: 0),
            viewportWidth: 1024
        ))
        XCTAssertFalse(ShellSwipePolicy.shouldSettleOpen(
            target: .closeChats,
            translation: CGSize(width: -220, height: 0),
            viewportWidth: 1024
        ))

        XCTAssertFalse(ShellSwipePolicy.shouldSettleOpen(
            target: .openSettings,
            translation: CGSize(width: -100, height: 0),
            viewportWidth: 1024
        ))
        XCTAssertTrue(ShellSwipePolicy.shouldSettleOpen(
            target: .openSettings,
            translation: CGSize(width: -114, height: 0),
            viewportWidth: 1024
        ))
        XCTAssertTrue(ShellSwipePolicy.shouldSettleOpen(
            target: .closeSettings,
            translation: CGSize(width: 100, height: 0),
            viewportWidth: 1024
        ))
        XCTAssertFalse(ShellSwipePolicy.shouldSettleOpen(
            target: .closeSettings,
            translation: CGSize(width: 220, height: 0),
            viewportWidth: 1024
        ))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.layout.responsive-history
    func testBottomCornerSystemGestureCannotOpenSettings() {
        let viewport = CGSize(width: 1024, height: 768)
        XCTAssertNil(ShellSwipePolicy.target(
            startLocation: CGPoint(x: 1023, y: 767),
            translation: CGSize(width: -180, height: -180),
            viewportSize: viewport,
            chatsOpen: false,
            settingsOpen: false,
            settingsSideBySide: false
        ))
        XCTAssertEqual(ShellSwipePolicy.target(
            startLocation: CGPoint(x: 1023, y: 300),
            translation: CGSize(width: -180, height: 0),
            viewportSize: viewport,
            chatsOpen: false,
            settingsOpen: false,
            settingsSideBySide: false
        ), .openSettings)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.layout.responsive-history
    func testVerticalMovementCancelsPaneGesture() {
        XCTAssertTrue(ShellSwipePolicy.isCancelledByVerticalMovement(CGSize(width: -50, height: -100)))
        XCTAssertFalse(ShellSwipePolicy.isCancelledByVerticalMovement(CGSize(width: -130, height: -100)))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.layout.responsive-history
    func testSideBySideSettingsWidthTracksLiveOpenAndCloseDrag() {
        XCTAssertEqual(MainAppLayoutParity.sideBySideSettingsWidth(isOpen: false, dragOffset: 0), 0)
        XCTAssertEqual(MainAppLayoutParity.sideBySideSettingsWidth(isOpen: false, dragOffset: -120), 120)
        XCTAssertEqual(MainAppLayoutParity.sideBySideSettingsWidth(isOpen: false, dragOffset: -500), 323)

        XCTAssertEqual(MainAppLayoutParity.sideBySideSettingsWidth(isOpen: true, dragOffset: 0), 323)
        XCTAssertEqual(MainAppLayoutParity.sideBySideSettingsWidth(isOpen: true, dragOffset: 120), 203)
        XCTAssertEqual(MainAppLayoutParity.sideBySideSettingsWidth(isOpen: true, dragOffset: 500), 0)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.layout.responsive-history
    func testInspirationHeightExpandsOnlyWithoutSettings() {
        let iPadChatSize = CGSize(width: 1024, height: 1000)

        XCTAssertEqual(MainAppLayoutParity.inspirationHeight(for: iPadChatSize, isSettingsOpen: false), 350)
        XCTAssertEqual(MainAppLayoutParity.inspirationHeight(for: iPadChatSize, isSettingsOpen: true), 240)
        XCTAssertEqual(
            MainAppLayoutParity.inspirationHeight(
                for: CGSize(width: 390, height: 600),
                isSettingsOpen: false
            ),
            190
        )
    }
}
