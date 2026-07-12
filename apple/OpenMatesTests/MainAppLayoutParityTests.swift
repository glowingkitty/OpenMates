// Deterministic coverage for responsive shell calculations shared by iPhone and iPad.
// Verifies live settings-drag width and chat-only inspiration growth without
// depending on simulator gesture timing, credentials, or private user data.
// Rendered shell behavior remains covered by ChatShellResponsiveParityUITests.
//
// Web source: frontend/apps/web_app/src/routes/+page.svelte
//             frontend/packages/ui/src/components/ActiveChat.svelte

import XCTest
@testable import OpenMates

final class MainAppLayoutParityTests: XCTestCase {
    func testSideBySideSettingsWidthTracksLiveOpenAndCloseDrag() {
        XCTAssertEqual(MainAppLayoutParity.sideBySideSettingsWidth(isOpen: false, dragOffset: 0), 0)
        XCTAssertEqual(MainAppLayoutParity.sideBySideSettingsWidth(isOpen: false, dragOffset: -120), 120)
        XCTAssertEqual(MainAppLayoutParity.sideBySideSettingsWidth(isOpen: false, dragOffset: -500), 323)

        XCTAssertEqual(MainAppLayoutParity.sideBySideSettingsWidth(isOpen: true, dragOffset: 0), 323)
        XCTAssertEqual(MainAppLayoutParity.sideBySideSettingsWidth(isOpen: true, dragOffset: 120), 203)
        XCTAssertEqual(MainAppLayoutParity.sideBySideSettingsWidth(isOpen: true, dragOffset: 500), 0)
    }

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
