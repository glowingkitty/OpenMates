// Fixture-backed billing UI parity smoke for native StoreKit and web-only paths.
// Runs without credentials, real StoreKit purchases, invoices, customer IDs,
// payment methods, or private screenshots. The billing fixture exposes the
// authenticated-only billing row and static product tiers for safe verification.

import XCTest

@MainActor
final class SettingsBillingStoreKitParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testBillingStoreKitAndWebOnlyFallbackSurfaces() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-billing-fixture"]
        app.launch()

        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15))
        app.buttons["settings-button"].tap()
        XCTAssertTrue(waitForElement("settings-menu", in: app, timeout: 10))
        XCTAssertTrue(waitForElement("settings-billing-row", in: app, timeout: 5))
        app.descendants(matching: .any)["settings-billing-row"].tap()

        XCTAssertTrue(waitForElement("settings-billing-page", in: app, timeout: 8))
        XCTAssertTrue(waitForElement("settings-billing-hub", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-billing-buy-credits-row", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-billing-auto-topup-row", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-billing-invoices-row", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-billing-gift-cards-row", in: app, timeout: 3))
        XCTAssertFalse(app.tables.firstMatch.exists, "Billing hub must not render default List/table chrome")

        app.descendants(matching: .any)["settings-billing-buy-credits-row"].tap()
        XCTAssertTrue(waitForElement("settings-billing-buy-credits-page", in: app, timeout: 5))
        XCTAssertTrue(waitForElement("settings-billing-product-1000", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-billing-product-10000", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-billing-product-21000", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-billing-product-54000", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-billing-best-value-badge", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-billing-bank-transfer-web-only", in: app, timeout: 3))
        XCTAssertFalse(app.tables.firstMatch.exists, "Buy credits must not render default List/table chrome")
        app.descendants(matching: .any)["settings-billing-subview-back"].tap()

        XCTAssertTrue(waitForElement("settings-billing-auto-topup-row", in: app, timeout: 5))
        app.descendants(matching: .any)["settings-billing-auto-topup-row"].tap()
        XCTAssertTrue(waitForElement("settings-billing-auto-topup-page", in: app, timeout: 5))
        XCTAssertTrue(waitForElement("settings-billing-low-balance-toggle", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-billing-low-balance-package", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-billing-monthly-toggle", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-billing-monthly-package", in: app, timeout: 3))
        XCTAssertFalse(app.tables.firstMatch.exists, "Auto top-up must not render default List/table chrome")
        app.descendants(matching: .any)["settings-billing-subview-back"].tap()

        XCTAssertTrue(waitForElement("settings-billing-invoices-row", in: app, timeout: 5))
        app.descendants(matching: .any)["settings-billing-invoices-row"].tap()
        XCTAssertTrue(waitForElement("settings-billing-invoices-page", in: app, timeout: 5))
        XCTAssertTrue(waitForElement("settings-billing-no-invoices", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-billing-invoices-web-only-fallback", in: app, timeout: 3))
        XCTAssertFalse(app.tables.firstMatch.exists, "Invoices must not render default List/table chrome")

        attachScreenshot(name: "Billing StoreKit fixture surfaces")
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
