// Fixture-backed billing UI parity smoke for native StoreKit and backend contract paths.
// Runs without credentials, real StoreKit purchases, invoices, customer IDs,
// payment methods, or private screenshots. The billing fixture exposes the
// authenticated-only billing row and static product tiers for safe verification.

import XCTest

@MainActor
final class SettingsBillingStoreKitParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // contract-test: supporting surface=gui.apple assertions=billing.surface.semantic-parity,billing.usage.landing-complete
    func testBillingStoreKitAndNativeContractSurfaces() throws {
        RealAccountUITestSupport.installNotificationPermissionHandler(on: self)
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
        XCTAssertFalse(app.buttons["settings-billing-usage-row"].exists, "Usage is embedded directly in Billing")
        XCTAssertTrue(waitForElement("settings-billing-support-row", in: app, timeout: 3))
        XCTAssertFalse(app.tables.firstMatch.exists, "Billing hub must not render default List/table chrome")

        app.descendants(matching: .any)["settings-billing-buy-credits-row"].tap()
        XCTAssertTrue(waitForElement("settings-billing-buy-credits-page", in: app, timeout: 5))
        XCTAssertTrue(waitForElement("settings-billing-product-1000", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-billing-product-10000", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-billing-product-21000", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-billing-product-54000", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-billing-restore-purchases-row", in: app, timeout: 3))
        XCTAssertFalse(app.tables.firstMatch.exists, "Buy credits must not render default List/table chrome")
        returnToBillingHub(in: app)

        XCTAssertTrue(waitForElement("settings-billing-auto-topup-row", in: app, timeout: 5))
        app.descendants(matching: .any)["settings-billing-auto-topup-row"].tap()
        XCTAssertTrue(waitForElement("settings-billing-auto-topup-page", in: app, timeout: 5))
        XCTAssertTrue(waitForElement("settings-billing-low-balance-toggle", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("settings-billing-low-balance-package", in: app, timeout: 3))
        XCTAssertFalse(app.tables.firstMatch.exists, "Auto top-up must not render default List/table chrome")
        returnToBillingHub(in: app)

        XCTAssertTrue(waitForElement("settings-billing-invoices-row", in: app, timeout: 5))
        app.descendants(matching: .any)["settings-billing-invoices-row"].tap()
        XCTAssertTrue(waitForElement("settings-billing-invoices-page", in: app, timeout: 5))
        XCTAssertTrue(waitForElement("settings-billing-invoice-row", in: app, timeout: 3))
        XCTAssertFalse(app.tables.firstMatch.exists, "Invoices must not render default List/table chrome")

        returnToBillingHub(in: app)
        XCTAssertTrue(waitForElement("settings-billing-usage-page", in: app, timeout: 5))
        XCTAssertTrue(waitForElement("settings-billing-usage-tabs", in: app, timeout: 3))
        XCTAssertTrue(waitForElement("usage-export-button", in: app, timeout: 3))
        app.descendants(matching: .any)["settings-billing-gift-cards-row"].tap()
        XCTAssertTrue(waitForElement("settings-billing-gift-cards-page", in: app, timeout: 5))
        XCTAssertTrue(waitForElement("settings-billing-gift-card-purchase", in: app, timeout: 3))

        returnToBillingHub(in: app)
        app.descendants(matching: .any)["settings-billing-support-row"].tap()
        XCTAssertTrue(waitForElement("settings-billing-support-page", in: app, timeout: 5))

        attachScreenshot(name: "Billing StoreKit fixture surfaces")
    }

    // contract-test: supporting surface=gui.apple assertions=billing.usage.landing-complete,billing.usage.receipt-token-breakdown,billing.surface.semantic-parity
    func testInlineUsageShowsChargedContextsAndOpensRealEntryReceipt() throws {
        RealAccountUITestSupport.installNotificationPermissionHandler(on: self)
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-billing-fixture"]
        app.launch()
        let settings = app.buttons["settings-button"]
        XCTAssertTrue(settings.waitForExistence(timeout: 15))
        XCTAssertTrue(settings.isHittable); settings.tap()
        XCTAssertTrue(RealAccountUITestSupport.waitForVisibleSettingsHome(in: app),
                      "The opened settings pane and home ScrollView must be enabled and visible")
        let billing = app.buttons["settings-billing-row"]
        XCTAssertTrue(billing.waitForExistence(timeout: 10))
        XCTAssertTrue(billing.isEnabled && billing.isHittable); billing.tap()
        XCTAssertTrue(waitForElement("settings-billing-hub", in: app, timeout: 8))
        XCTAssertFalse(app.buttons["settings-billing-usage-row"].exists)
        XCTAssertTrue(waitForVisibleElement("usage-export-button", in: app))
        XCTAssertTrue(waitForVisibleElement("settings-billing-usage-tabs", in: app))
        let export = app.buttons["usage-export-button"]
        let tabs = app.descendants(matching: .any)["settings-billing-usage-tabs"].firstMatch
        XCTAssertTrue(export.isHittable)
        XCTAssertLessThanOrEqual(export.frame.maxY, tabs.frame.minY + 1,
            "Product Billing stacks export above tabs; chrome=0 preview flex layout is not the product parent")
        attachScreenshot(name: "Usage product header and canonical row appearance")
        for identifier in ["usage-overview-day-heading", "usage-overview-chat-row", "usage-overview-app-row",
                           "usage-overview-api-device-row", "usage-overview-workflow-row", "usage-overview-other-row"] {
            XCTAssertTrue(waitForVisibleElement(identifier, in: app), "Usage must visibly render \(identifier)")
        }
        XCTAssertTrue(waitForVisibleElement("usage-chat-lucide-rocket", in: app),
            "Usage must render a real supplied Lucide icon outside the 18 category fallback assets")
        let loadMore = app.buttons["usage-load-more-days-button"]
        XCTAssertTrue(waitForVisibleElement("usage-load-more-days-button", in: app)); loadMore.tap()
        XCTAssertTrue(waitForVisibleElement("usage-overview-day-heading", in: app))
        XCTAssertFalse(app.buttons["usage-load-more-days-button"].exists)
        let chat = app.buttons.matching(identifier: "usage-overview-chat-row").firstMatch
        XCTAssertTrue(waitForVisibleElement("usage-overview-chat-row", in: app)); chat.tap()
        let entry = app.buttons["usage-chat-entry"].firstMatch
        XCTAssertTrue(waitForVisibleElement("usage-detail-header", in: app))
        XCTAssertTrue(waitForVisibleElement("usage-chat-entry", in: app)); entry.tap()
        XCTAssertTrue(waitForVisibleElement("usage-detail-header", in: app))
        for identifier in ["usage-system-prompt-tokens", "usage-user-input-tokens", "usage-app-skill-tokens",
                           "usage-input-tokens", "usage-output-tokens"] {
            XCTAssertTrue(waitForVisibleElement(identifier, in: app), "Expected visible receipt field \(identifier)")
        }
        let systemPrompt = app.descendants(matching: .any)["usage-system-prompt-tokens"].firstMatch
        let userInput = app.descendants(matching: .any)["usage-user-input-tokens"].firstMatch
        XCTAssertTrue(systemPrompt.isHittable && userInput.isHittable)
        // Contained AX groups omit blank top padding from their frames. Adjacent
        // row origins measure the actual web spacing without relying on that union.
        XCTAssertGreaterThanOrEqual(userInput.frame.minY - systemPrompt.frame.minY, 42,
            "Receipt row pitch retains web 14px vertical padding around 14px type")
        XCTAssertFalse(app.buttons["usage-open-target-button"].exists, "No message exists in this account-free fixture")
        attachScreenshot(name: "Inline usage entry receipt")
        XCTAssertTrue(waitForVisibleElement("usage-entry-detail-back-button", in: app))
        app.buttons["usage-entry-detail-back-button"].tap()
        XCTAssertTrue(waitForVisibleElement("usage-chat-entry", in: app))
        XCTAssertTrue(waitForVisibleElement("usage-chat-detail-back-button", in: app))
        app.buttons["usage-chat-detail-back-button"].tap()
        XCTAssertTrue(waitForVisibleElement("settings-tab-chats", in: app))
        app.buttons["settings-tab-chats"].tap()
        XCTAssertTrue(waitForVisibleElement("usage-chat-lucide-help-circle", in: app),
            "Unsupported supplied Lucide names use the web help-circle fallback")
        attachScreenshot(name: "Usage category icon and unsupported-name fallback")
        XCTAssertTrue(waitForVisibleElement("settings-tab-apps", in: app))
        app.buttons["settings-tab-apps"].tap()
        XCTAssertTrue(waitForVisibleElement("usage-apps-summary-row", in: app))
        app.buttons["usage-apps-summary-row"].tap()
        XCTAssertTrue(waitForVisibleElement("usage-detail-entry-row", in: app))
        XCTAssertFalse(app.tables.firstMatch.exists)
    }

    private func waitForVisibleElement(_ identifier: String, in app: XCUIApplication) -> Bool {
        let element = app.descendants(matching: .any).matching(identifier: identifier).firstMatch
        if element.waitForExistence(timeout: 3), element.isHittable { return true }
        let scroll = app.otherElements["workspace-settings"].scrollViews.firstMatch
        for _ in 0..<7 where scroll.exists {
            scroll.swipeUp()
            if element.exists && element.isHittable { return true }
        }
        for _ in 0..<10 where scroll.exists {
            scroll.swipeDown()
            if element.exists && element.isHittable { return true }
        }
        return false
    }

    private func returnToBillingHub(in app: XCUIApplication) {
        let explicitBack = app.buttons["settings-billing-subview-back"].firstMatch
        if explicitBack.exists {
            explicitBack.tap()
        } else {
            app.buttons["settings-billing-page"].firstMatch.tap()
        }
        XCTAssertTrue(waitForElement("settings-billing-hub", in: app, timeout: 5))
    }

    private func waitForElement(_ identifier: String, in app: XCUIApplication, timeout: TimeInterval) -> Bool {
        let element = app.descendants(matching: .any)[identifier]
        if element.waitForExistence(timeout: timeout) { return true }

        let scrollView = app.otherElements["workspace-settings"].scrollViews.firstMatch
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
