// Fixture-backed sensitive settings parity UI tests.
// Verifies native account-security entry points and destructive-action previews
// without live account mutation. Tests must avoid logging or attaching secrets,
// backup codes, recovery keys, OTP seeds, API keys, or private email values.

import XCTest

@MainActor
final class SettingsSensitiveActionsParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testSensitiveEntrypointsAndDeletePreview() throws {
        let app = launchAccountSettingsFixture()
        openSettingsAccountPage(in: app)

        for identifier in sensitiveAccountRows {
            XCTAssertTrue(waitForButton(identifier, in: app, timeout: 5), "Expected sensitive row \(identifier)")
        }
        XCTAssertFalse(app.tables.firstMatch.exists, "Account settings must not render default List/table chrome")
        app.terminate()

        let deletePreviewApp = launchAccountSettingsFixture(extraArguments: ["--ui-test-account-delete-preview"])
        openSettingsAccountEntry(in: deletePreviewApp)
        XCTAssertTrue(waitForElement("delete-account-password-input", in: deletePreviewApp, timeout: 5))
        XCTAssertTrue(waitForElement("delete-account-confirm-input", in: deletePreviewApp, timeout: 5))
        let finalDeleteButton = deletePreviewApp.buttons["delete-account-final-button"]
        XCTAssertTrue(finalDeleteButton.waitForExistence(timeout: 5))
        XCTAssertFalse(finalDeleteButton.isEnabled, "Final account deletion must stay disabled without explicit confirmation")
        XCTAssertFalse(deletePreviewApp.tables.firstMatch.exists, "Delete account preview must not render default List/table chrome")

        attachScreenshot(name: "Sensitive settings fixture preview")
    }

    private var sensitiveAccountRows: [String] {
        [
            "settings-account-passkeys-row",
            "settings-account-password-row",
            "settings-account-2fa-row",
            "settings-account-recovery-key-row",
            "settings-account-sessions-row",
            "settings-account-delete-row",
        ]
    }

    private func launchAccountSettingsFixture(extraArguments: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-account-settings-fixture"] + extraArguments
        app.launch()
        return app
    }

    private func openSettingsAccountEntry(in app: XCUIApplication) {
        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15))
        app.buttons["settings-button"].tap()
        XCTAssertTrue(waitForElement("settings-menu", in: app, timeout: 10))
        XCTAssertTrue(waitForButton("settings-account-row", in: app, timeout: 8))
        app.buttons["settings-account-row"].tap()
    }

    private func openSettingsAccountPage(in app: XCUIApplication) {
        openSettingsAccountEntry(in: app)
        XCTAssertTrue(waitForElement("settings-account-page", in: app, timeout: 8))
    }

    private func waitForButton(_ identifier: String, in app: XCUIApplication, timeout: TimeInterval) -> Bool {
        let button = app.buttons[identifier]
        if button.waitForExistence(timeout: timeout) { return true }

        let scrollView = app.scrollViews.firstMatch
        for _ in 0..<8 where scrollView.exists {
            scrollView.swipeUp()
            if button.waitForExistence(timeout: 1) { return true }
        }
        return false
    }

    private func waitForElement(_ identifier: String, in app: XCUIApplication, timeout: TimeInterval) -> Bool {
        let element = app.descendants(matching: .any)[identifier]
        if element.waitForExistence(timeout: timeout) { return true }

        let scrollView = app.scrollViews.firstMatch
        for _ in 0..<8 where scrollView.exists {
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
