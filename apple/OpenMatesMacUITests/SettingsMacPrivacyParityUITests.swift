// Native macOS Privacy settings UI coverage using deterministic synthetic state.
// Verifies the privacy hub and temporary debug-session flow are visible and
// clickable without stock table chrome or private account credentials.
// The test fixture performs no live network requests and stores no user data.
// iOS interaction coverage lives in SettingsPrivacyParityUITests.

import XCTest

@MainActor
final class SettingsMacPrivacyParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testPrivacyHubAndDebugSessionAreUsableOnMacOS() {
        let app = XCUIApplication()
        app.launchArguments = [
            "--ui-test-disable-auth-cache",
            "--ui-test-account-settings-fixture",
            "--ui-test-privacy-settings-fixture",
        ]
        app.launch()
        app.activate()

        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15))
        app.buttons["settings-button"].click()
        let privacyRow = element("settings-privacy-row", in: app)
        XCTAssertTrue(privacyRow.waitForExistence(timeout: 8))
        privacyRow.click()

        XCTAssertTrue(element("settings-privacy-page", in: app).waitForExistence(timeout: 8))
        XCTAssertFalse(app.tables.firstMatch.exists)
        XCTAssertTrue(element("settings-privacy-policy-link", in: app).isHittable)
        XCTAssertTrue(element("settings-privacy-location-toggle", in: app).isHittable)
        for _ in 0..<8 where !element("settings-privacy-share-debug-logs-row", in: app).isHittable {
            app.scrollViews.firstMatch.scroll(byDeltaX: 0, deltaY: -6)
        }
        element("settings-privacy-share-debug-logs-row", in: app).click()
        XCTAssertTrue(element("privacy-debug-session-page", in: app).waitForExistence(timeout: 5))
        XCTAssertTrue(element("privacy-debug-session-start", in: app).isHittable)
    }

    private func element(_ identifier: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier == %@", identifier))
            .firstMatch
    }
}
