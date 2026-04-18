// Notification UI tests — maps to: background-chat-notification.spec.ts,
// newsletter-categories.spec.ts

import XCTest

final class NotificationUITests: XCTestCase {

    var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["--uitesting", "--authenticated"]
        app.launch()
    }

    // MARK: - Notification settings (background-chat-notification)

    func testNotificationSettingsExist() {
        openSettings()
        scrollToAndTap("Chat Notifications")

        let toggle = app.switches.firstMatch
        XCTAssertTrue(toggle.waitForExistence(timeout: 5))
    }

    func testBackupRemindersSettingsExist() {
        openSettings()
        scrollToAndTap("Backup Reminders")

        let toggle = app.switches.firstMatch
        XCTAssertTrue(toggle.waitForExistence(timeout: 5))
    }

    // MARK: - Newsletter categories (newsletter-categories)

    func testNewsletterSettingsShowsCategories() {
        openSettings()
        scrollToAndTap("Newsletter")

        let toggle = app.switches.firstMatch
        XCTAssertTrue(toggle.waitForExistence(timeout: 5))
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
        if button.waitForExistence(timeout: 3) { button.tap(); return }
        let list = app.collectionViews.firstMatch
        for _ in 0..<8 {
            list.swipeUp()
            if button.waitForExistence(timeout: 1) { button.tap(); return }
        }
    }
}
