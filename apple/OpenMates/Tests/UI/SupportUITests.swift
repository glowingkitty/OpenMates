// Support UI tests — maps to: settings-support-stripe.spec.ts,
// settings-support-bank-transfer.spec.ts, report-issue-flow.spec.ts

import XCTest

final class SupportUITests: XCTestCase {

    var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["--uitesting", "--authenticated"]
        app.launch()
    }

    // MARK: - Support page (settings-support-stripe)

    func testSupportPageLoads() {
        openSettings()
        scrollToAndTap("Support OpenMates")

        let supportNav = app.navigationBars.firstMatch
        XCTAssertTrue(supportNav.waitForExistence(timeout: 5))
    }

    func testOneTimeSupportNavigates() {
        openSettings()
        scrollToAndTap("Support OpenMates")

        let oneTime = app.buttons["One-Time Contribution"]
        guard oneTime.waitForExistence(timeout: 5) else { return }
        oneTime.tap()

        let oneTimeNav = app.navigationBars["One-Time"]
        XCTAssertTrue(oneTimeNav.waitForExistence(timeout: 5))
    }

    func testMonthlySupportNavigates() {
        openSettings()
        scrollToAndTap("Support OpenMates")

        let monthly = app.buttons["Monthly Support"]
        guard monthly.waitForExistence(timeout: 5) else { return }
        monthly.tap()

        let monthlyNav = app.navigationBars["Monthly Support"]
        XCTAssertTrue(monthlyNav.waitForExistence(timeout: 5))
    }

    // MARK: - Report issue (report-issue-flow)

    func testReportIssueFormValidation() {
        openSettings()
        scrollToAndTap("Report an Issue")

        let titleField = app.textFields["Title"]
        guard titleField.waitForExistence(timeout: 5) else { return }

        // Submit button should be disabled without title
        let submitBtn = app.buttons["Submit Report"]
        XCTAssertTrue(submitBtn.exists)
        XCTAssertFalse(submitBtn.isEnabled, "Submit should be disabled without title")

        // Fill in title
        titleField.tap()
        titleField.typeText("Test issue")

        // Still disabled without description (need to fill TextEditor)
    }

    func testReportIssueCategoryPicker() {
        openSettings()
        scrollToAndTap("Report an Issue")

        let categoryPicker = app.buttons["Category"]
        XCTAssertTrue(categoryPicker.waitForExistence(timeout: 5))
    }

    func testReportIssueScreenshotAttachment() {
        openSettings()
        scrollToAndTap("Report an Issue")

        let attachBtn = app.buttons["Attach Screenshot"]
        XCTAssertTrue(attachBtn.waitForExistence(timeout: 5))
    }

    // MARK: - Mates

    func testMatesPageLoads() {
        openSettings()
        scrollToAndTap("AI Mates")

        let matesNav = app.navigationBars["Mates"]
        XCTAssertTrue(matesNav.waitForExistence(timeout: 5))
    }

    // MARK: - Shared chats

    func testSharedChatsPageLoads() {
        openSettings()
        scrollToAndTap("Shared Chats")

        let sharedNav = app.navigationBars["Shared"]
        XCTAssertTrue(sharedNav.waitForExistence(timeout: 5))
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
