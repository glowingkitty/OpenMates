// UI smoke coverage for native settings and billing parity entry points.
// Runs unauthenticated against public settings only, avoiding credentials,
// invoices, customer IDs, payment data, and private account screenshots.

import XCTest

@MainActor
final class SettingsBillingParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // contract-test: direct surface=gui.apple assertions=billing.access.authenticated-first-party
    func testPublicSettingsMenuExposesStablePreferenceIdentifiers() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache"]
        app.launch()

        let settingsButton = app.buttons["settings-button"]
        XCTAssertTrue(settingsButton.waitForExistence(timeout: 15))
        settingsButton.tap()

        XCTAssertTrue(
            app.descendants(matching: .any)["settings-menu"].waitForExistence(timeout: 10),
            "Expected settings menu. Visible UI: \(visibleStateLabels(in: app))"
        )

        for identifier in [
            "settings-pricing-row",
            "settings-ai-row",
            "settings-interface-row",
            "settings-newsletter-row",
            "settings-support-row",
            "settings-report-issue-row",
        ] {
            XCTAssertTrue(
                app.descendants(matching: .any)[identifier].waitForExistence(timeout: 5),
                "Expected \(identifier). Visible UI: \(visibleStateLabels(in: app))"
            )
        }

        XCTAssertFalse(
            app.descendants(matching: .any)["settings-billing-row"].exists,
            "Unauthenticated settings must not expose billing account actions"
        )
        XCTAssertFalse(app.tables.firstMatch.exists, "Settings home must not render default List/table chrome")

        app.descendants(matching: .any)["settings-interface-row"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-interface-page"].waitForExistence(timeout: 10))

        attachScreenshot(name: "Public settings identifiers")
    }

    // contract-test: direct surface=gui.apple assertions=billing.access.authenticated-first-party
    func testGuestBillingDeepLinkRequestsAuthenticationWithoutShowingUsage() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-app-link-fixture"]
        app.launchEnvironment["UI_TEST_SETTINGS_LINK_PATH"] = "billing/usage"
        app.launch()

        let link = app.descendants(matching: .any)["ui-test-settings-link"]
        XCTAssertTrue(link.waitForExistence(timeout: 15))
        XCTAssertTrue(link.isHittable)
        link.tap()
        XCTAssertTrue(app.descendants(matching: .any)["auth-entry-header"].waitForExistence(timeout: 10),
                      "A real guest following a Billing link must authenticate")
        assertBillingHidden(in: app)
        attachScreenshot(name: "Guest Billing link requires authentication")
    }

    // contract-test: direct surface=gui.apple assertions=billing.access.authenticated-first-party
    func testGuestHeaderReferralPreselectionCannotExposeBilling() {
        let app = XCUIApplication()
        // The header-only fixture exposes the CTA without granting an account.
        // Deliberately omit the separate Billing fixture.
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-authenticated-header",
                               "--ui-test-show-workspace-tabs"]
        app.launch()
        let referralCTA = app.buttons["referral-cta"]
        XCTAssertTrue(referralCTA.waitForExistence(timeout: 15))
        XCTAssertTrue(referralCTA.isHittable)
        referralCTA.tap()
        XCTAssertTrue(app.descendants(matching: .any)["settings-menu"].waitForExistence(timeout: 10))
        assertBillingHidden(in: app)
        attachScreenshot(name: "Guest referral preselection keeps Billing private")
    }

    private func assertBillingHidden(in app: XCUIApplication) {
        for identifier in ["settings-billing-row", "settings-billing-hub", "settings-billing-usage-page",
                           "settings-billing-usage-tabs", "settings-billing-referral-code-page"] {
            XCTAssertFalse(app.descendants(matching: .any)[identifier].exists,
                           "Guest must not expose \(identifier)")
        }
    }

    // contract-test: direct surface=gui.apple assertions=billing.access.authenticated-first-party
    func testHeaderReferralCTAOpensReferralSettingsSubpage() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "--ui-test-disable-auth-cache",
            "--ui-test-authenticated-header",
            "--ui-test-billing-fixture",
            "--ui-test-show-workspace-tabs"
        ]
        app.launch()

        let referralCTA = app.buttons["referral-cta"]
        XCTAssertTrue(referralCTA.waitForExistence(timeout: 15), "Expected header referral CTA")
        referralCTA.tap()

        XCTAssertTrue(
            app.descendants(matching: .any)["settings-billing-referral-code-page"].waitForExistence(timeout: 10),
            "Expected referral code subpage after referral CTA. Visible UI: \(visibleStateLabels(in: app))"
        )
        XCTAssertEqual(app.state, .runningForeground, "Referral CTA must not crash the app")
        XCTAssertFalse(app.tables.firstMatch.exists, "Referral settings must not render default List/table chrome")

        attachScreenshot(name: "Header referral CTA opens referral settings")
    }

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func visibleStateLabels(in app: XCUIApplication) -> String {
        let buttons = elementSummaries(app.buttons.allElementsBoundByIndex, prefix: "button")
        let staticTexts = elementSummaries(app.staticTexts.allElementsBoundByIndex, prefix: "text")
        return (buttons + staticTexts).prefix(30).joined(separator: " | ")
    }

    private func elementSummaries(_ elements: [XCUIElement], prefix: String) -> [String] {
        elements.compactMap { element in
            let identifier = element.identifier.trimmingCharacters(in: .whitespacesAndNewlines)
            let label = element.label.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !identifier.isEmpty || !label.isEmpty else { return nil }
            if identifier.isEmpty { return "\(prefix):\(redact(label))" }
            if label.isEmpty || label == identifier { return "\(prefix)#\(identifier)" }
            return "\(prefix)#\(identifier)=\(redact(label))"
        }
    }

    private func redact(_ value: String) -> String {
        value.contains("@") ? "<email>" : value
    }
}
