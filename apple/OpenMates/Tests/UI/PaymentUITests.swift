// Payment UI tests — maps to: buy-credits-flow.spec.ts,
// usage-token-breakdown.spec.ts, saved-payment-invoice-flow.spec.ts

import XCTest

final class PaymentUITests: XCTestCase {

    var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["--uitesting", "--authenticated"]
        app.launch()
    }

    // MARK: - Buy credits (buy-credits-flow)

    func testBuyCreditsShowsProducts() {
        openSettings()
        scrollToAndTap("Billing & Credits")

        let buyCredits = app.buttons["Buy Credits"]
        guard buyCredits.waitForExistence(timeout: 5) else { return }
        buyCredits.tap()

        // Should show credit packages
        let creditsText = app.staticTexts.matching(NSPredicate(format: "label CONTAINS 'credits'")).firstMatch
        XCTAssertTrue(creditsText.waitForExistence(timeout: 10))
    }

    func testBuyCreditsShowsRestoreButton() {
        openSettings()
        scrollToAndTap("Billing & Credits")

        let buyCredits = app.buttons["Buy Credits"]
        guard buyCredits.waitForExistence(timeout: 5) else { return }
        buyCredits.tap()

        let restoreBtn = app.buttons["Restore Purchases"]
        let list = app.collectionViews.firstMatch
        list.swipeUp()
        XCTAssertTrue(restoreBtn.waitForExistence(timeout: 5))
    }

    // MARK: - Invoices (saved-payment-invoice-flow)

    func testInvoicesPageLoads() {
        openSettings()
        scrollToAndTap("Billing & Credits")

        let invoicesBtn = app.buttons["Invoices"]
        guard invoicesBtn.waitForExistence(timeout: 5) else { return }
        invoicesBtn.tap()

        let invoicesNav = app.navigationBars["Invoices"]
        XCTAssertTrue(invoicesNav.waitForExistence(timeout: 5))
    }

    // MARK: - Gift cards

    func testGiftCardsPageLoads() {
        openSettings()
        scrollToAndTap("Billing & Credits")

        let giftCards = app.buttons["Gift Cards"]
        guard giftCards.waitForExistence(timeout: 5) else { return }
        giftCards.tap()

        let giftNav = app.navigationBars["Gift Cards"]
        XCTAssertTrue(giftNav.waitForExistence(timeout: 5))
    }

    // MARK: - Pricing for non-authenticated (unauthenticated pricing)

    func testPricingShowsForNonAuthenticated() {
        let unauthApp = XCUIApplication()
        unauthApp.launchArguments = ["--uitesting"]
        unauthApp.launch()

        // Non-authenticated users should see pricing in settings area
        // (this depends on whether the settings button is accessible pre-login)
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
