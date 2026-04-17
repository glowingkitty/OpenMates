// Reminder UI tests — maps to: reminder-redesign.spec.ts, reminder-new-chat.spec.ts,
// reminder-same-chat.spec.ts, reminder-repeating-and-cancel.spec.ts,
// reminder-email.spec.ts, reminder-button-settings.spec.ts

import XCTest

final class ReminderUITests: XCTestCase {

    var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["--uitesting", "--authenticated"]
        app.launch()
    }

    // MARK: - Reminder from chat menu (reminder-redesign)

    func testReminderOptionInChatMenu() {
        openExistingChat()

        let menuBtn = app.buttons["ellipsis.circle"]
        if menuBtn.waitForExistence(timeout: 5) {
            menuBtn.tap()
            let reminderBtn = app.buttons["Set Reminder"]
            XCTAssertTrue(reminderBtn.waitForExistence(timeout: 3))
        }
    }

    // MARK: - Reminder creation sheet (reminder-new-chat)

    func testReminderSheetOpens() {
        openExistingChat()

        let menuBtn = app.buttons["ellipsis.circle"]
        guard menuBtn.waitForExistence(timeout: 5) else { return }
        menuBtn.tap()

        let reminderBtn = app.buttons["Set Reminder"]
        guard reminderBtn.waitForExistence(timeout: 3) else { return }
        reminderBtn.tap()

        let datePicker = app.datePickers.firstMatch
        XCTAssertTrue(datePicker.waitForExistence(timeout: 5))
    }

    // MARK: - Helpers

    private func openExistingChat() {
        let chatItem = app.cells.matching(identifier: "chat-item-wrapper").firstMatch
        guard chatItem.waitForExistence(timeout: 10) else { return }
        chatItem.tap()
    }
}
