// UI smoke coverage for the native Apps/App Store settings path.
// Runs with a deterministic local fixture and unauthenticated settings only,
// avoiding provider calls, private accounts, billing state, and private data.

import XCTest

@MainActor
final class SettingsAppsParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testAppsRootAllAppsAndDetailExposeStableIdentifiers() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-app-store-fixture"]
        app.launch()

        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15))
        app.buttons["settings-button"].tap()

        XCTAssertTrue(waitForElement("settings-menu", in: app, timeout: 10))
        XCTAssertTrue(waitForElement("settings-apps-row", in: app, timeout: 5))
        app.descendants(matching: .any)["settings-apps-row"].tap()

        XCTAssertTrue(waitForElement("settings-app-store-page", in: app, timeout: 10))
        XCTAssertTrue(waitForElement("settings-show-all-apps-row", in: app, timeout: 5))
        XCTAssertTrue(waitForElement("settings-app-category-for_everyday_life-scroll", in: app, timeout: 5))
        XCTAssertTrue(waitForElement("app-card-weather", in: app, timeout: 5))

        app.descendants(matching: .any)["settings-show-all-apps-row"].tap()
        XCTAssertTrue(waitForElement("settings-all-apps-page", in: app, timeout: 8))
        XCTAssertTrue(waitForElement("settings-all-apps-search", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-all-apps-filter-skills", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-all-apps-filter-focus-modes", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-all-apps-filter-settings-memories", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-all-apps-sort-newest", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-all-apps-sort-name", in: app, timeout: 3))

        app.descendants(matching: .any)["settings-all-apps-filter-focus-modes"].tap()
        XCTAssertTrue(waitForElement("settings-all-app-row-weather", in: app, timeout: 5))
        XCTAssertFalse(app.descendants(matching: .any)["settings-all-app-row-docs"].exists)

        app.descendants(matching: .any)["settings-all-app-row-weather"].tap()
        XCTAssertTrue(waitForElement("settings-app-detail-page", in: app, timeout: 8))
        XCTAssertTrue(waitForElement("settings-app-detail-back", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-app-skill-row-forecast", in: app, timeout: 5))
        XCTAssertTrue(waitForElement("settings-app-memory-row-home_location", in: app, timeout: 5))
        XCTAssertTrue(waitForElement("settings-app-focus-row-travel_weather", in: app, timeout: 5))

        app.descendants(matching: .any)["settings-app-skill-row-forecast"].tap()
        XCTAssertTrue(waitForElement("settings-skill-detail-page", in: app, timeout: 5))
        XCTAssertTrue(waitForElement("settings-skill-pricing-section", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-skill-example-card-0", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-skill-how-to-use-card-0", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-skill-provider-item", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-skill-model-item", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-skill-mention-button", in: app, timeout: 3))
        app.descendants(matching: .any)["settings-skill-mention-button"].tap()
        XCTAssertTrue(waitForElement("settings-skill-mention-inserted", in: app, timeout: 3))
        app.descendants(matching: .any)["settings-skill-detail-back"].tap()
        XCTAssertTrue(waitForElement("settings-app-detail-page", in: app, timeout: 5))

        app.descendants(matching: .any)["settings-app-focus-row-travel_weather"].tap()
        XCTAssertTrue(waitForElement("settings-focus-detail-page", in: app, timeout: 5))
        XCTAssertTrue(waitForElement("settings-focus-example-card-0", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-focus-how-to-use-card-0", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-focus-process-bullet", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-focus-instructions-toggle", in: app, timeout: 3))
        app.descendants(matching: .any)["settings-focus-instructions-toggle"].tap()
        XCTAssertTrue(waitForElement("settings-focus-instructions-text", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-focus-mention-button", in: app, timeout: 3))
        app.descendants(matching: .any)["settings-focus-mention-button"].tap()
        XCTAssertTrue(waitForElement("settings-focus-mention-inserted", in: app, timeout: 3))
        XCTAssertFalse(app.tables.firstMatch.exists, "Apps settings must not render default List/table chrome")

        attachScreenshot(name: "Apps settings fixture path")
    }

    private func waitForElement(_ identifier: String, in app: XCUIApplication, timeout: TimeInterval) -> Bool {
        let element = app.descendants(matching: .any)[identifier]
        if element.waitForExistence(timeout: timeout) { return true }

        let scrollView = app.scrollViews.firstMatch
        for _ in 0..<5 where scrollView.exists {
            scrollView.swipeUp()
            if element.waitForExistence(timeout: 1) { return true }
        }
        return false
    }

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
