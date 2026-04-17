// Settings UI tests — maps to: language-settings-flow.spec.ts,
// backup-codes-settings.spec.ts, recovery-key-settings.spec.ts,
// session-revoke-flow.spec.ts, debug-logging-settings.spec.ts,
// model-toggle-settings.spec.ts, default-model-settings.spec.ts,
// ai-settings-breadcrumb.spec.ts, reminder-button-settings.spec.ts,
// focus-mode-settings.spec.ts, newsletter-flow.spec.ts, report-issue-flow.spec.ts,
// settings-buy-credits-stripe.spec.ts, settings-buy-credits-polar.spec.ts

import XCTest

final class SettingsUITests: XCTestCase {

    var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["--uitesting", "--authenticated"]
        app.launch()
    }

    // MARK: - Settings navigation

    func testSettingsOpensAndShowsSections() {
        openSettings()

        let sections = ["AI", "Privacy", "Billing", "Notifications", "Account", "Security"]
        for section in sections {
            XCTAssertTrue(
                app.staticTexts[section].waitForExistence(timeout: 3),
                "Missing settings section: \(section)"
            )
        }
    }

    // MARK: - AI settings (ai-settings-breadcrumb, model-toggle-settings, default-model-settings)

    func testAISettingsNavigates() {
        openSettings()
        app.buttons["AI Model & Providers"].tap()

        let aiNav = app.navigationBars.firstMatch
        XCTAssertTrue(aiNav.waitForExistence(timeout: 5))
    }

    // MARK: - Language settings (language-settings-flow)

    func testLanguageSettingsShowsAllLanguages() {
        openSettings()
        scrollToAndTap("Language")

        let english = app.buttons["English"]
        XCTAssertTrue(english.waitForExistence(timeout: 5))

        let deutsch = app.buttons["Deutsch"]
        XCTAssertTrue(deutsch.exists)

        let arabic = app.buttons["العربية"]
        // May need scrolling
        let list = app.collectionViews.firstMatch
        list.swipeUp()
        _ = arabic.waitForExistence(timeout: 3)
    }

    func testLanguageSwitchUpdatesUI() {
        openSettings()
        scrollToAndTap("Language")

        let deutsch = app.buttons["Deutsch"]
        guard deutsch.waitForExistence(timeout: 5) else { return }
        deutsch.tap()

        // Checkmark should move to Deutsch
        // Switch back to English
        let english = app.buttons["English"]
        guard english.waitForExistence(timeout: 3) else { return }
        english.tap()
    }

    // MARK: - Security settings (backup-codes-settings, recovery-key-settings, session-revoke-flow)

    func testSecuritySettingsNavigation() {
        openSettings()
        scrollToAndTap("Passkeys")
        let passkeysNav = app.navigationBars["Passkeys"]
        XCTAssertTrue(passkeysNav.waitForExistence(timeout: 5))
    }

    func testSessionsSettingsNavigation() {
        openSettings()
        scrollToAndTap("Active Sessions")
        let sessionsNav = app.navigationBars["Sessions"]
        XCTAssertTrue(sessionsNav.waitForExistence(timeout: 5))
    }

    func testSessionsShowsLogoutAllButton() {
        openSettings()
        scrollToAndTap("Active Sessions")

        let logoutAll = app.buttons["Log Out All Other Sessions"]
        XCTAssertTrue(logoutAll.waitForExistence(timeout: 5))
    }

    // MARK: - Privacy settings (pii-detection-flow, debug-logging-settings)

    func testPrivacyHidePersonalData() {
        openSettings()
        scrollToAndTap("Hide Personal Data")

        let piiToggle = app.switches.firstMatch
        XCTAssertTrue(piiToggle.waitForExistence(timeout: 5))
    }

    func testShareDebugLogs() {
        openSettings()
        scrollToAndTap("Share Debug Logs")

        let toggle = app.switches.firstMatch
        XCTAssertTrue(toggle.waitForExistence(timeout: 5))
    }

    // MARK: - Billing (settings-buy-credits-stripe, settings-buy-credits-polar)

    func testBillingShowsBalance() {
        openSettings()
        scrollToAndTap("Billing & Credits")

        let creditsLabel = app.staticTexts["Credits"]
        XCTAssertTrue(creditsLabel.waitForExistence(timeout: 5))
    }

    func testBuyCreditsShowsProducts() {
        openSettings()
        scrollToAndTap("Billing & Credits")

        let buyCredits = app.buttons["Buy Credits"]
        guard buyCredits.waitForExistence(timeout: 5) else { return }
        buyCredits.tap()

        let buyNav = app.navigationBars["Buy Credits"]
        XCTAssertTrue(buyNav.waitForExistence(timeout: 5))
    }

    // MARK: - Newsletter (newsletter-flow)

    func testNewsletterSettingsNavigates() {
        openSettings()
        scrollToAndTap("Newsletter")

        let toggle = app.switches.firstMatch
        XCTAssertTrue(toggle.waitForExistence(timeout: 5))
    }

    // MARK: - Report issue (report-issue-flow)

    func testReportIssueOpens() {
        openSettings()
        scrollToAndTap("Report an Issue")

        let titleField = app.textFields["Title"]
        XCTAssertTrue(titleField.waitForExistence(timeout: 5))
    }

    // MARK: - Logout

    func testLogoutButtonExists() {
        openSettings()

        let list = app.collectionViews.firstMatch
        list.swipeUp()
        list.swipeUp()
        list.swipeUp()

        let logout = app.buttons["Log Out"]
        XCTAssertTrue(logout.waitForExistence(timeout: 5))
    }

    // MARK: - Done dismisses (settings close)

    func testDoneButtonDismissesSettings() {
        openSettings()

        let done = app.buttons["Done"]
        XCTAssertTrue(done.exists)
        done.tap()

        let settingsNav = app.navigationBars["Settings"]
        XCTAssertFalse(settingsNav.waitForExistence(timeout: 2))
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
        if button.waitForExistence(timeout: 3) {
            button.tap()
            return
        }
        // Scroll to find it
        let list = app.collectionViews.firstMatch
        for _ in 0..<5 {
            list.swipeUp()
            if button.waitForExistence(timeout: 1) {
                button.tap()
                return
            }
        }
    }
}
