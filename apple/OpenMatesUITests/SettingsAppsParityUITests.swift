// The user retired legacy Apps settings navigation while retaining app capabilities.
// Verify the menu exclusion and unavailable legacy routes through real internal links.
// The fixture contains no credentials, private account data, or provider calls.

import XCTest

@MainActor
final class SettingsAppsParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.navigation.contextual-availability,settings-ui.shell.lifecycle-and-routing
    func testLegacyAppsSettingsAreExcludedFromMenuAndInternalRoutes() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-app-link-fixture"]
        app.launch()
        let settingsButton = app.buttons["settings-button"]
        XCTAssertTrue(settingsButton.waitForExistence(timeout: 15))
        XCTAssertTrue(settingsButton.isHittable)
        settingsButton.tap()
        XCTAssertTrue(app.scrollViews["settings-menu"].waitForExistence(timeout: 8))
        XCTAssertFalse(app.descendants(matching: .any)["settings-apps-row"].exists)
        XCTAssertTrue(app.buttons["settings-ai-row"].exists)
        XCTAssertTrue(app.buttons["settings-memories-row"].exists)
        XCTAssertTrue(app.buttons["settings-privacy-row"].exists)
        app.terminate()

        for path in ["apps", "apps/all", "apps/weather", "apps/weather/skills/forecast"] {
            app.launchEnvironment["UI_TEST_SETTINGS_LINK_PATH"] = path
            app.launch()
            let link = app.descendants(matching: .any)["ui-test-settings-link"]
            XCTAssertTrue(link.waitForExistence(timeout: 15))
            XCTAssertTrue(link.isHittable)
            link.tap()
            XCTAssertTrue(app.descendants(matching: .any)["settings-deep-link-unavailable"].waitForExistence(timeout: 8), path)
            XCTAssertFalse(app.descendants(matching: .any)["settings-app-store-page"].exists)
            XCTAssertFalse(app.descendants(matching: .any)["settings-app-detail-page"].exists)
            XCTAssertFalse(app.webViews.firstMatch.exists)
            XCTAssertFalse(app.tables.firstMatch.exists)
            app.terminate()
        }
    }
}
