// Developer settings UI tests — maps to: api-keys-flow.spec.ts,
// model-override.spec.ts, location-security-flow.spec.ts

import XCTest

final class DeveloperSettingsUITests: XCTestCase {

    var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["--uitesting", "--authenticated"]
        app.launch()
    }

    // MARK: - API Keys (api-keys-flow)

    func testAPIKeysPageLoads() {
        openSettings()
        scrollToAndTap("API Keys")

        let apiKeysNav = app.navigationBars["API Keys"]
        XCTAssertTrue(apiKeysNav.waitForExistence(timeout: 5))
    }

    func testCreateAPIKeyFormExists() {
        openSettings()
        scrollToAndTap("API Keys")

        let keyNameField = app.textFields["Key name"]
        XCTAssertTrue(keyNameField.waitForExistence(timeout: 5))

        let generateBtn = app.buttons["Generate API Key"]
        XCTAssertTrue(generateBtn.exists)
    }

    // MARK: - Devices page (developer devices)

    func testDevicesPageLoads() {
        openSettings()
        scrollToAndTap("Devices")

        let devicesNav = app.navigationBars["Devices"]
        XCTAssertTrue(devicesNav.waitForExistence(timeout: 5))
    }

    // MARK: - Webhooks page

    func testWebhooksPageLoads() {
        openSettings()
        scrollToAndTap("Webhooks")

        let webhooksNav = app.navigationBars["Webhooks"]
        XCTAssertTrue(webhooksNav.waitForExistence(timeout: 5))
    }

    // MARK: - Helpers

    private func openSettings() {
        let settingsBtn = app.buttons["settings-button"]
        guard settingsBtn.waitForExistence(timeout: 10) else { return }
        settingsBtn.tap()
        _ = app.navigationBars["Settings"].waitForExistence(timeout: 5)
    }

    private func scrollToAndTap(_ label: String) {
        let button = app.buttons[label]
        if button.waitForExistence(timeout: 3) {
            button.tap()
            return
        }
        let list = app.collectionViews.firstMatch
        for _ in 0..<8 {
            list.swipeUp()
            if button.waitForExistence(timeout: 1) { button.tap(); return }
        }
    }
}
