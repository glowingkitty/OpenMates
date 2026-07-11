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
            if destination.page == "settings-report-issue-page" {
                XCTAssertTrue(app.descendants(matching: .any)["settings-report-issue-form"].waitForExistence(timeout: 5))
                XCTAssertTrue(app.descendants(matching: .any)["report-issue-title"].exists)
                XCTAssertTrue(app.descendants(matching: .any)["report-issue-submit"].exists)
            }
            app.descendants(matching: .any)["settings-destination-back"].tap()
            XCTAssertTrue(waitForElement("settings-menu", in: app, timeout: 5))
        }

        attachScreenshot(name: "Guest settings submenu smoke")
    }

    func testAuthenticatedSettingsSubmenusOpenAndReturn() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "--ui-test-disable-auth-cache",
            "--ui-test-account-settings-fixture",
        ]
        app.launch()

        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15))
        app.buttons["settings-button"].tap()
        XCTAssertTrue(waitForElement("settings-menu", in: app, timeout: 10))

        for destination in authenticatedDestinations {
            openDestination(destination, in: app)
            XCTAssertFalse(app.tables.firstMatch.exists, "Settings destination must not render default List/table chrome")
            app.descendants(matching: .any)["settings-destination-back"].tap()
            XCTAssertTrue(waitForElement("settings-menu", in: app, timeout: 5))
        }
    }

    func testReportIssueSubmissionSucceedsAndUploadsSimulatorLogs() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "--ui-test-disable-auth-cache",
            "--ui-test-report-issue-success",
            "--ui-test-seed-report-logs",
        ]
        app.launch()

        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15))
        app.buttons["settings-button"].tap()
        XCTAssertTrue(waitForElement("settings-menu", in: app, timeout: 10))

        openDestination((row: "settings-report-issue-row", page: "settings-report-issue-page"), in: app)
        enterText("Report issue UI test submission", into: "report-issue-title", in: app)
        enterText("Opened Settings, Report issue, and submitted from the simulator.", into: "report-issue-user-flow", in: app)
        enterText("A success reference appears and logs are uploaded.", into: "report-issue-expected", in: app)
        enterText("The UI test verifies the native issue-log payload.", into: "report-issue-actual", in: app)

        app.descendants(matching: .any)["report-issue-submit"].tap()
        XCTAssertTrue(waitForElement("report-issue-reference", in: app, timeout: 10))
        XCTAssertTrue(app.staticTexts["report-issue-reference"].label.contains("OPE-IOS-UI-TEST"))

        let logPayload = app.staticTexts["report-issue-debug-log-payload"]
        XCTAssertTrue(logPayload.waitForExistence(timeout: 5))
        XCTAssertTrue(logPayload.label.contains("issue-ios-ui-test"))
        XCTAssertTrue(logPayload.label.contains("apple://settings/report_issue"))
        XCTAssertTrue(logPayload.label.contains("OpenMates-Apple"))
        XCTAssertTrue(logPayload.label.contains("ui_test_simulator"))
        XCTAssertTrue(logPayload.label.contains("Report issue simulator diagnostic"))
        XCTAssertTrue(logPayload.label.contains("Submitting native issue report"))
        XCTAssertTrue(logPayload.label.contains("<email>"))
        XCTAssertTrue(logPayload.label.contains("token=<redacted>"))
        XCTAssertFalse(logPayload.label.contains("tester@example.org"))
        XCTAssertFalse(logPayload.label.contains("token=secret"))

        attachScreenshot(name: "Report issue submission success with simulator logs")
    }

    func testSettingsShellProducesLightAndDarkReviewArtifacts() {
        for appearance in ["Light", "Dark"] {
            let app = XCUIApplication()
            app.launchArguments = [
                "--ui-test-disable-auth-cache",
                "-AppleInterfaceStyle",
                appearance,
            ]
            app.launch()

            XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15))
            app.buttons["settings-button"].tap()
            XCTAssertTrue(waitForElement("settings-menu", in: app, timeout: 10))
            XCTAssertTrue(waitForElement("settings-ai-row", in: app, timeout: 5))
            XCTAssertTrue(app.descendants(matching: .any)["settings-ai-row"].isHittable)
            XCTAssertFalse(app.tables.firstMatch.exists)
            attachScreenshot(name: "iPhone Settings shell \(appearance.lowercased())")

            app.terminate()
        }
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

    private var authenticatedDestinations: [(row: String, page: String)] {
        [
            ("settings-memories-row", "settings-memories-page"),
            ("settings-privacy-row", "settings-privacy-page"),
            ("settings-projects-row", "settings-projects-page"),
            ("settings-billing-row", "settings-billing-page"),
            ("settings-notifications-row", "settings-notifications-page"),
            ("settings-shared-row", "settings-shared-page"),
            ("settings-account-row", "settings-account-page"),
            ("settings-developers-row", "settings-developers-page"),
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
        for _ in 0..<6 where scrollView.exists {
            scrollView.swipeDown()
            if element.waitForExistence(timeout: 1) { return true }
        }
        return false
    }

    private func enterText(_ text: String, into identifier: String, in app: XCUIApplication) {
        let textView = app.textViews[identifier]
        let element = textView.exists ? textView : app.descendants(matching: .any)[identifier]
        XCTAssertTrue(element.waitForExistence(timeout: 5), "Expected text input \(identifier)")
        element.tap()
        element.typeText(text)
    }

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
