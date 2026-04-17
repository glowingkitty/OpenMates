// Encryption UI tests — maps to: multi-tab-encryption.spec.ts,
// multi-session-encryption.spec.ts, location-security-flow.spec.ts

import XCTest

final class EncryptionUITests: XCTestCase {

    var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["--uitesting", "--authenticated"]
        app.launch()
    }

    // MARK: - Session management (multi-session-encryption)

    func testActiveSessionsShowCurrentDevice() {
        openSettings()
        scrollToAndTap("Active Sessions")

        let sessionsNav = app.navigationBars["Sessions"]
        XCTAssertTrue(sessionsNav.waitForExistence(timeout: 5))

        // Should show at least the current session
        let currentBadge = app.staticTexts["Current"]
        XCTAssertTrue(currentBadge.waitForExistence(timeout: 5))
    }

    func testLogoutAllOtherSessions() {
        openSettings()
        scrollToAndTap("Active Sessions")

        let logoutAll = app.buttons["Log Out All Other Sessions"]
        XCTAssertTrue(logoutAll.waitForExistence(timeout: 5))
    }

    // MARK: - Device pairing (pair-initiate)

    func testPairDevicePageLoads() {
        openSettings()
        scrollToAndTap("Pair New Device")

        let generateBtn = app.buttons["Generate Pairing Code"]
        XCTAssertTrue(generateBtn.waitForExistence(timeout: 5))
    }

    // MARK: - Password change

    func testPasswordChangePageLoads() {
        openSettings()
        scrollToAndTap("Password")

        let currentPwField = app.secureTextFields["Current Password"]
        XCTAssertTrue(currentPwField.waitForExistence(timeout: 5))
    }

    // MARK: - 2FA settings

    func test2FAPageLoads() {
        openSettings()
        scrollToAndTap("Two-Factor Authentication")

        let statusText = app.staticTexts["Status"]
        XCTAssertTrue(statusText.waitForExistence(timeout: 5))
    }

    // MARK: - Recovery key

    func testRecoveryKeyPageLoads() {
        openSettings()
        scrollToAndTap("Recovery Key")

        let verifySection = app.staticTexts["Verify Identity"]
        XCTAssertTrue(verifySection.waitForExistence(timeout: 5))
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
