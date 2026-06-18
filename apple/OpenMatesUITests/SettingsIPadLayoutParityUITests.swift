// iPad settings layout parity smoke for the native Apps settings path.
// Uses the deterministic app-store fixture to avoid provider calls,
// credentials, private account data, billing state, and private screenshots.
// Verifies that key iPad controls remain visible, tappable, and free of
// default table chrome while exercising Apps drilldown back navigation.

import XCTest

@MainActor
final class SettingsIPadLayoutParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testIPadAppsSettingsLayoutKeepsControlsVisibleAndUsable() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-app-store-fixture"]
        app.launch()

        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15))
        app.buttons["settings-button"].tap()

        XCTAssertTrue(waitForElement("settings-menu", in: app, timeout: 10))
        XCTAssertTrue(waitForElement("settings-apps-row", in: app, timeout: 5))
        assertElementInsideWindow(app.descendants(matching: .any)["settings-apps-row"], in: app)
        app.descendants(matching: .any)["settings-apps-row"].tap()

        XCTAssertTrue(waitForElement("settings-app-store-page", in: app, timeout: 10))
        XCTAssertTrue(waitForElement("settings-show-all-apps-row", in: app, timeout: 5))
        XCTAssertTrue(waitForElement("app-card-weather", in: app, timeout: 5))
        assertElementInsideWindow(app.descendants(matching: .any)["settings-show-all-apps-row"], in: app)
        assertElementInsideWindow(app.descendants(matching: .any)["app-card-weather"], in: app)

        app.descendants(matching: .any)["settings-show-all-apps-row"].tap()
        XCTAssertTrue(waitForElement("settings-all-apps-page", in: app, timeout: 8))
        XCTAssertTrue(waitForElement("settings-all-apps-filter-focus-modes", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-all-app-row-weather", in: app, timeout: 5))
        assertElementInsideWindow(app.descendants(matching: .any)["settings-all-app-row-weather"], in: app)

        app.descendants(matching: .any)["settings-all-app-row-weather"].tap()
        XCTAssertTrue(waitForElement("settings-app-detail-page", in: app, timeout: 8))
        XCTAssertTrue(waitForElement("settings-app-skill-row-forecast", in: app, timeout: 5))
        assertElementInsideWindow(app.descendants(matching: .any)["settings-app-skill-row-forecast"], in: app)
        XCTAssertTrue(waitForElement("settings-app-focus-row-travel_weather", in: app, timeout: 5))

        app.descendants(matching: .any)["settings-app-skill-row-forecast"].tap()
        XCTAssertTrue(waitForElement("settings-skill-detail-page", in: app, timeout: 5))
        XCTAssertTrue(waitForElement("settings-skill-detail-back", in: app, timeout: 3))
        assertElementInsideWindow(app.descendants(matching: .any)["settings-skill-detail-back"], in: app)
        app.descendants(matching: .any)["settings-skill-detail-back"].tap()

        XCTAssertTrue(waitForElement("settings-app-focus-row-travel_weather", in: app, timeout: 5))
        app.descendants(matching: .any)["settings-app-focus-row-travel_weather"].tap()
        XCTAssertTrue(waitForElement("settings-focus-detail-page", in: app, timeout: 5))
        XCTAssertTrue(waitForElement("settings-focus-instructions-toggle", in: app, timeout: 3))
        assertElementInsideWindow(app.descendants(matching: .any)["settings-focus-instructions-toggle"], in: app)
        XCTAssertFalse(app.tables.firstMatch.exists, "iPad Apps settings must not render default List/table chrome")

        attachScreenshot(name: "iPad Apps settings layout smoke")
    }

    private func waitForElement(_ identifier: String, in app: XCUIApplication, timeout: TimeInterval) -> Bool {
        let element = app.descendants(matching: .any)[identifier]
        if element.waitForExistence(timeout: timeout), isElementInsideWindow(element, in: app) { return true }

        let scrollView = app.scrollViews.firstMatch
        for _ in 0..<6 where scrollView.exists {
            scrollView.swipeUp()
            if element.waitForExistence(timeout: 1), isElementInsideWindow(element, in: app) { return true }
        }
        return element.exists
    }

    private func assertElementInsideWindow(_ element: XCUIElement, in app: XCUIApplication) {
        XCTAssertTrue(element.exists, "Expected element to exist before checking its frame")
        XCTAssertTrue(
            isElementInsideWindow(element, in: app),
            "Expected element frame \(element.frame) to fit within window frame \(app.windows.firstMatch.frame.insetBy(dx: -1, dy: -1))"
        )
    }

    private func isElementInsideWindow(_ element: XCUIElement, in app: XCUIApplication) -> Bool {
        guard element.exists else { return false }
        let windowFrame = app.windows.firstMatch.frame.insetBy(dx: -1, dy: -1)
        return windowFrame.contains(element.frame)
    }

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
