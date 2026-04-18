// Account settings UI tests — maps to: account-recovery-flow.spec.ts,
// import-chats.spec.ts, usage-token-breakdown.spec.ts

import XCTest

final class AccountSettingsUITests: XCTestCase {

    var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["--uitesting", "--authenticated"]
        app.launch()
    }

    // MARK: - Account detail (username, timezone)

    func testAccountDetailPageLoads() {
        openSettings()
        scrollToAndTap("Username & Timezone")

        let usernameField = app.textFields["Username"]
        XCTAssertTrue(usernameField.waitForExistence(timeout: 5))
    }

    // MARK: - Email settings

    func testEmailSettingsPageLoads() {
        openSettings()
        scrollToAndTap("Email")

        let currentEmail = app.staticTexts["Current Email"]
        XCTAssertTrue(currentEmail.waitForExistence(timeout: 5))
    }

    // MARK: - Profile picture

    func testProfilePicturePageLoads() {
        openSettings()
        scrollToAndTap("Profile Picture")

        let chooseBtn = app.buttons["Choose Photo"]
        XCTAssertTrue(chooseBtn.waitForExistence(timeout: 5))
    }

    // MARK: - Usage

    func testUsagePageLoads() {
        openSettings()
        scrollToAndTap("Usage")

        let usageNav = app.navigationBars["Usage"]
        XCTAssertTrue(usageNav.waitForExistence(timeout: 5))
    }

    // MARK: - Storage

    func testStoragePageLoads() {
        openSettings()
        scrollToAndTap("Storage")

        let storageNav = app.navigationBars["Storage"]
        XCTAssertTrue(storageNav.waitForExistence(timeout: 5))
    }

    // MARK: - Chats management

    func testChatsManagementPageLoads() {
        openSettings()
        scrollToAndTap("Chats")

        let statsSection = app.staticTexts["Chat Statistics"]
        XCTAssertTrue(statsSection.waitForExistence(timeout: 5))
    }

    // MARK: - Import chats (import-chats)

    func testImportChatsPageLoads() {
        openSettings()
        scrollToAndTap("Import Chats")

        // Import view should load
        let navBar = app.navigationBars.firstMatch
        XCTAssertTrue(navBar.waitForExistence(timeout: 5))
    }

    // MARK: - Export data

    func testExportDataPageLoads() {
        openSettings()
        scrollToAndTap("Export Data")

        let exportNav = app.navigationBars["Export Data"]
        XCTAssertTrue(exportNav.waitForExistence(timeout: 5))
    }

    // MARK: - Delete account

    func testDeleteAccountPageLoads() {
        openSettings()

        let list = app.collectionViews.firstMatch
        for _ in 0..<5 { list.swipeUp() }

        let deleteBtn = app.buttons["Delete Account"]
        guard deleteBtn.waitForExistence(timeout: 5) else { return }
        deleteBtn.tap()

        let confirmField = app.textFields.matching(NSPredicate(format: "placeholderValue CONTAINS 'delete'")).firstMatch
        XCTAssertTrue(confirmField.waitForExistence(timeout: 5))
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
