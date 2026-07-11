// macOS settings shell UI coverage for the native desktop app.
// Launches without cached authentication or private account data and verifies
// that Settings remains visible, clickable, navigable, and free of default
// table chrome. Narrow/fullscreen coverage can extend this real macOS target.
// Screenshots are XCTest attachments and contain only the guest-safe shell.

import XCTest

@MainActor
final class SettingsMacShellParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testGuestSettingsShellOpensAndNavigatesOnMacOS() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache"]
        app.launch()
        app.activate()

        let settingsButton = app.buttons["settings-button"]
        XCTAssertTrue(settingsButton.waitForExistence(timeout: 15))
        XCTAssertTrue(settingsButton.isHittable)
        settingsButton.click()

        XCTAssertTrue(element("settings-menu", in: app).waitForExistence(timeout: 10))
        XCTAssertFalse(app.tables.firstMatch.exists, "macOS Settings must not render default table chrome")

        let pricingRow = element("settings-pricing-row", in: app)
        XCTAssertTrue(pricingRow.waitForExistence(timeout: 5))
        XCTAssertTrue(pricingRow.isHittable)
        pricingRow.click()

        XCTAssertTrue(element("settings-pricing-page", in: app).waitForExistence(timeout: 8))
        let backButton = element("settings-destination-back", in: app)
        XCTAssertTrue(backButton.waitForExistence(timeout: 3))
        XCTAssertTrue(backButton.isHittable)
        backButton.click()
        XCTAssertTrue(element("settings-menu", in: app).waitForExistence(timeout: 5))

        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = "Guest macOS settings shell"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func element(_ identifier: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier == %@", identifier))
            .firstMatch
    }
}
