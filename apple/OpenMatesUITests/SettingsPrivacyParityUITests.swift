// Native iOS Privacy settings UI coverage using deterministic synthetic state.
// Verifies privacy policy, connected accounts, location, retention, diagnostics,
// and temporary debug-session controls are rendered and clickable.
// The fixture never uses account credentials, private content, or live APIs.
// macOS interaction coverage lives in SettingsMacPrivacyParityUITests.

import XCTest

@MainActor
final class SettingsPrivacyParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testPrivacyHubAndNestedFlowsAreVisibleAndClickable() {
        let app = launchPrivacyFixture()

        assertHittable("settings-privacy-policy-link", in: app)
        assertHittable("settings-privacy-connected-accounts-row", in: app)
        assertHittable("settings-privacy-location-toggle", in: app)

        element("settings-privacy-connected-accounts-row", in: app).tap()
        XCTAssertTrue(element("privacy-connected-account-row", in: app).waitForExistence(timeout: 5))
        returnToPrivacyHub(in: app)

        scrollTo("settings-privacy-auto-delete-chats-row", in: app)
        scrollUntilExists("settings-privacy-files-retention-row", in: app)
        scrollUntilExists("settings-privacy-usage-retention-row", in: app)
        scrollUntilExists("settings-privacy-compliance-retention-row", in: app)
        scrollUntilExists("settings-privacy-invoices-retention-row", in: app)
        scrollTo("settings-privacy-stability-toggle", in: app)
        scrollTo("settings-privacy-debug-toggle", in: app)

        scrollTo("settings-privacy-auto-delete-chats-row", in: app)
        element("settings-privacy-auto-delete-chats-row", in: app).tap()
        assertHittable("privacy-auto-deletion-period-90d", in: app)
        returnToPrivacyHub(in: app)

        scrollTo("settings-privacy-share-debug-logs-row", in: app)
        element("settings-privacy-share-debug-logs-row", in: app).tap()
        assertHittable("privacy-debug-session-duration", in: app)
        assertHittable("privacy-debug-session-start", in: app)
    }

    private func launchPrivacyFixture() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = [
            "--ui-test-disable-auth-cache",
            "--ui-test-account-settings-fixture",
            "--ui-test-privacy-settings-fixture",
        ]
        app.launch()
        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15))
        app.buttons["settings-button"].tap()
        let privacyRow = element("settings-privacy-row", in: app)
        XCTAssertTrue(privacyRow.waitForExistence(timeout: 8))
        privacyRow.tap()
        XCTAssertTrue(element("settings-privacy-page", in: app).waitForExistence(timeout: 8))
        return app
    }

    private func assertHittable(_ identifier: String, in app: XCUIApplication) {
        let target = element(identifier, in: app)
        XCTAssertTrue(target.waitForExistence(timeout: 5), "Missing \(identifier)")
        XCTAssertTrue(target.isHittable, "Not hittable: \(identifier)")
    }

    private func returnToPrivacyHub(in app: XCUIApplication) {
        let explicitBack = app.buttons["settings-privacy-subpage-back"].firstMatch
        if explicitBack.exists {
            explicitBack.tap()
        } else {
            app.buttons["settings-privacy-page"].firstMatch.tap()
        }
        XCTAssertTrue(element("settings-privacy-connected-accounts-row", in: app).waitForExistence(timeout: 5))
    }

    private func scrollTo(_ identifier: String, in app: XCUIApplication) {
        let target = element(identifier, in: app)
        for _ in 0..<8 where !target.isHittable {
            app.swipeUp()
        }
        for _ in 0..<8 where !target.isHittable {
            app.swipeDown()
        }
        XCTAssertTrue(target.exists, "Missing \(identifier)")
        XCTAssertTrue(target.isHittable, "Not hittable after scrolling: \(identifier)")
    }

    private func scrollUntilExists(_ identifier: String, in app: XCUIApplication) {
        let target = element(identifier, in: app)
        for _ in 0..<8 where !target.exists {
            app.swipeUp()
        }
        XCTAssertTrue(target.exists, "Missing \(identifier)")
    }

    private func element(_ identifier: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier == %@", identifier))
            .firstMatch
    }
}
