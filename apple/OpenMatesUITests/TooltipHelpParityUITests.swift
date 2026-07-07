// Tooltip/help parity coverage for native Apple app chrome.
// macOS exposes SwiftUI `.help(Text(...))` as a native help tag/tooltip;
// this UI test hovers an icon-only workspace tab and verifies the tooltip text
// appears instead of relying only on VoiceOver labels.

import XCTest

#if os(macOS)
@MainActor
final class TooltipHelpParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testWorkspaceTabHelpAppearsAsNativeTooltipOnHover() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "--ui-test-disable-auth-cache",
            "--ui-test-show-workspace-tabs"
        ]
        app.launch()

        let projectsTab = element(in: app, identifier: "projects-nav-link")
        XCTAssertTrue(
            projectsTab.waitForExistence(timeout: 12),
            "Expected workspace projects tab. Visible UI: \(app.debugDescription)"
        )
        XCTAssertEqual(projectsTab.label, "Projects")

        projectsTab.hover()

        XCTAssertTrue(
            waitForTooltip(named: "Projects", in: app, timeout: 4),
            "Expected native tooltip text for the Projects tab after hover. Visible UI: \(app.debugDescription)"
        )
    }

    private func element(in app: XCUIApplication, identifier: String) -> XCUIElement {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier == %@", identifier))
            .firstMatch
    }

    private func waitForTooltip(named label: String, in app: XCUIApplication, timeout: TimeInterval) -> Bool {
        let appTooltip = app.staticTexts.matching(NSPredicate(format: "label == %@", label)).firstMatch
        let accessibilityTooltip = XCUIApplication(bundleIdentifier: "com.apple.AccessibilityUIServer")
            .staticTexts
            .matching(NSPredicate(format: "label == %@", label))
            .firstMatch
        let deadline = Date().addingTimeInterval(timeout)

        while Date() < deadline {
            if appTooltip.exists || accessibilityTooltip.exists {
                return true
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        return false
    }
}
#endif
