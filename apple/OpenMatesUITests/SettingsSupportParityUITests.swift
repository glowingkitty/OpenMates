// Support navigation and retired payment routes use isolated guest state.
import XCTest

@MainActor
final class SettingsSupportParityUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: direct surface=gui.apple assertions=settings-ui.navigation.parent-return,settings-ui.parity.web-apple-shell
    func testSupportContactHubReturnsToSettingsWithoutPaymentControls() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache"]
        app.launch()
        let settings = app.buttons["settings-button"]
        XCTAssertTrue(settings.waitForExistence(timeout: 15))
        XCTAssertTrue(settings.isHittable)
        settings.tap()
        let menu = app.scrollViews["settings-menu"]
        XCTAssertTrue(menu.waitForExistence(timeout: 8))
        let support = app.buttons["settings-support-row"]
        XCTAssertTrue(support.exists)
        for _ in 0..<5 where !support.isHittable { menu.swipeUp() }
        XCTAssertTrue(support.isHittable)
        support.tap()
        assertContactHub(app)
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = "support-contact-hub"
        attachment.lifetime = .keepAlways
        add(attachment)
        let back = app.buttons["settings-destination-back"]
        XCTAssertTrue(back.isHittable)
        back.tap()
        XCTAssertTrue(menu.waitForExistence(timeout: 8))
        XCTAssertTrue(support.exists)
    }

    // contract-test: direct surface=gui.apple assertions=settings-ui.navigation.parent-return,settings-ui.parity.web-apple-shell
    func testLegacyContributionDeepLinksResolveToContactWithoutPaymentControls() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-app-link-fixture"]
        for path in ["support", "support/one-time", "support/monthly"] {
            app.launchEnvironment["UI_TEST_SETTINGS_LINK_PATH"] = path
            app.launch()
            let link = app.descendants(matching: .any)["ui-test-settings-link"]
            XCTAssertTrue(link.waitForExistence(timeout: 15), path)
            XCTAssertTrue(link.isHittable, path)
            link.tap()
            assertContactHub(app)
            XCTAssertTrue(app.buttons["settings-destination-back"].isEnabled, path)
            app.terminate()
        }
    }

    private func assertContactHub(_ app: XCUIApplication) {
        let contact = app.buttons["settings-support-contact-row"]
        XCTAssertTrue(contact.waitForExistence(timeout: 8))
        XCTAssertTrue(contact.isHittable)
        XCTAssertTrue(contact.label.contains("support@openmates.org"))
        XCTAssertTrue(app.descendants(matching: .any)["settings-support-information"].exists)
        for id in ["settings-support-one-time-row", "settings-support-monthly-row", "settings-support-github-row",
            "support-one-time-pay", "support-monthly-pay", "support-one-time-payment-element", "support-monthly-payment-element",
            "support-one-time-switch-bank", "bank-transfer-details"] {
            XCTAssertFalse(app.descendants(matching: .any)[id].exists, id)
        }
        XCTAssertFalse(app.webViews.firstMatch.exists)
        XCTAssertFalse(app.textFields.firstMatch.exists)
    }
}
