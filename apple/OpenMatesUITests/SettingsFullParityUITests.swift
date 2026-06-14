// Guest-safe settings submenu parity smoke for the native settings shell.
// Exercises public top-level settings destinations without credentials,
// account data, billing data, admin access, or provider network assertions.
// Verifies stable page identifiers, native back navigation, and no default
// table chrome for the static/public submenu flow.

import XCTest

@MainActor
final class SettingsFullParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testGuestPublicSettingsSubmenusOpenAndReturn() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache"]
        app.launch()

        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15))
        app.buttons["settings-button"].tap()
        XCTAssertTrue(waitForElement("settings-menu", in: app, timeout: 10))

        for destination in guestDestinations {
            openDestination(destination, in: app)
            XCTAssertFalse(app.tables.firstMatch.exists, "Settings destination must not render default List/table chrome")
            app.descendants(matching: .any)["settings-destination-back"].tap()
            XCTAssertTrue(waitForElement("settings-menu", in: app, timeout: 5))
        }

        attachScreenshot(name: "Guest settings submenu smoke")
    }

    private var guestDestinations: [(row: String, page: String)] {
        [
            ("settings-pricing-row", "settings-pricing-page"),
            ("settings-ai-row", "settings-ai-page"),
            ("settings-apps-row", "settings-apps-page"),
            ("settings-interface-row", "settings-interface-page"),
            ("settings-server-connection-row", "settings-server-connection-page"),
            ("settings-newsletter-row", "settings-newsletter-page"),
            ("settings-support-row", "settings-support-page"),
            ("settings-report-issue-row", "settings-report-issue-page"),
        ]
    }

    private func openDestination(_ destination: (row: String, page: String), in app: XCUIApplication) {
        XCTAssertTrue(waitForElement(destination.row, in: app, timeout: 5), "Expected row \(destination.row)")
        app.descendants(matching: .any)[destination.row].tap()
        XCTAssertTrue(waitForElement(destination.page, in: app, timeout: 8), "Expected page \(destination.page)")
        XCTAssertTrue(waitForElement("settings-destination-back", in: app, timeout: 3))
    }

    private func waitForElement(_ identifier: String, in app: XCUIApplication, timeout: TimeInterval) -> Bool {
        let element = app.descendants(matching: .any)[identifier]
        if element.waitForExistence(timeout: timeout) { return true }

        let scrollView = app.scrollViews.firstMatch
        for _ in 0..<6 where scrollView.exists {
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
