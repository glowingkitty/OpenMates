// Native iOS Privacy settings UI coverage using deterministic synthetic state.
// Verifies privacy policy, connected accounts, location, retention, diagnostics,
// and temporary debug-session controls are rendered and clickable.
// The fixture never uses account credentials, private content, or live APIs.
// macOS interaction coverage lives in SettingsMacPrivacyParityUITests.

import XCTest

@MainActor
final class SettingsPrivacyParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.navigation.parent-return,settings-ui.composition.canonical-and-accessible,settings-ui.parity.web-apple-shell
    func testPrivacyHubAndNestedFlowsAreVisibleAndClickable() {
        let app = launchPrivacyFixture()

        assertHittable("settings-privacy-policy-link", in: app)
        assertHittable("settings-privacy-connected-accounts-row", in: app)
        assertHittable("settings-privacy-location-toggle", in: app)

        let hideToggle = app.switches["settings-hide-personal-data-row-toggle"]
        XCTAssertTrue(hideToggle.waitForExistence(timeout: 5), "Hide personal data must expose its real toggle")
        XCTAssertTrue(hideToggle.isHittable)
        hideToggle.tap()
        assertHittable("settings-hide-personal-data-toggle", in: app)
        returnToPrivacyHub(in: app)

        element("settings-privacy-connected-accounts-row", in: app).tap()
        XCTAssertTrue(element("privacy-connected-account-row", in: app).waitForExistence(timeout: 5))
        returnToPrivacyHub(in: app)

        scrollTo("settings-privacy-auto-delete-chats-row", in: app)
        scrollUntilExists("settings-privacy-files-retention-row", in: app)
        scrollUntilExists("settings-privacy-usage-retention-row", in: app)
        scrollUntilExists("settings-privacy-compliance-retention-row", in: app)
        scrollUntilExists("settings-privacy-invoices-retention-row", in: app)
        scrollTo("settings-privacy-stability-toggle", in: app)
        scrollTo("settings-privacy-debug-toggle", in: app)

        scrollTo("settings-privacy-auto-delete-chats-row", in: app)
        element("settings-privacy-auto-delete-chats-row", in: app).tap()
        assertHittable("privacy-auto-deletion-period-90d", in: app)
        returnToPrivacyHub(in: app)

        scrollTo("settings-privacy-share-debug-logs-row", in: app)
        element("settings-privacy-share-debug-logs-row", in: app).tap()
        assertHittable("privacy-debug-session-duration", in: app)
        assertHittable("privacy-debug-session-start", in: app)
    }

    // contract-test: direct surface=gui.apple assertions=pii.apple.enhanced-local-detection
    func testEnhancedDetectionIsOptionalAndDownloadCanBeCancelledInPrivacy() {
        let app = launchPrivacyFixture(extraArguments: ["--ui-test-local-lab-progress-fixture", "--ui-test-local-lab-hold-download"])
        element("settings-hide-personal-data-row", in: app).tap()
        scrollTo("settings-enhanced-pii-model-action", in: app)
        let action = app.buttons["settings-enhanced-pii-model-action"]
        // The deterministic store fixture starts with an installed privacy model.
        let installed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@ AND enabled == true", "Remove model"), object: action)
        XCTAssertEqual(XCTWaiter.wait(for: [installed], timeout: 5), .completed)
        XCTAssertTrue(action.isEnabled && action.isHittable)
        XCTAssertFalse(element("settings-enhanced-pii-model-progress", in: app).exists,
                       "Opening Privacy must not start a download")
        action.tap()
        let offered = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "Download model"), object: action)
        XCTAssertEqual(XCTWaiter.wait(for: [offered], timeout: 5), .completed)
        action.tap()
        let cancel = app.buttons["settings-enhanced-pii-model-cancel-download"]
        XCTAssertTrue(cancel.waitForExistence(timeout: 5))
        XCTAssertTrue(cancel.isEnabled && cancel.isHittable)
        XCTAssertTrue(element("settings-enhanced-pii-model-progress", in: app).exists)
        cancel.tap()
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: cancel)], timeout: 5), .completed)
        XCTAssertTrue(action.isEnabled)
        XCTAssertTrue(element("settings-enhanced-pii-model-regex-fallback", in: app).exists)
        scrollTo("settings-hide-personal-data-toggle", in: app)
        XCTAssertTrue(app.switches["settings-hide-personal-data-toggle"].isHittable)
        scrollTo("settings-pii-category-email_addresses", in: app)
        XCTAssertTrue(app.switches["settings-pii-category-email_addresses"].isHittable)
        scrollTo("settings-add-personal-data-custom", in: app)
        XCTAssertTrue(element("settings-add-personal-data-custom", in: app).isHittable)
    }

    // contract-test: direct surface=gui.apple assertions=settings-ui.navigation.contextual-availability,settings-ui.parity.web-apple-shell
    func testGuestPrivacyAccountActionsOpenAuthentication() {
        for identifier in [
            "settings-hide-personal-data-row",
            "settings-hide-personal-data-row-toggle",
            "settings-privacy-connected-accounts-row",
            "settings-privacy-auto-delete-chats-row",
            "settings-privacy-share-debug-logs-row",
            "settings-privacy-location-toggle",
            "settings-privacy-stability-toggle",
            "settings-privacy-debug-toggle",
        ] {
            let app = launchGuestPrivacy()
            scrollTo(identifier, in: app)
            let target = app.switches[identifier].firstMatch.exists
                ? app.switches[identifier].firstMatch : element(identifier, in: app)
            XCTAssertTrue(target.isHittable, identifier)
            target.tap()
            let signupTab = app.buttons["auth-signup-tab"]
            XCTAssertTrue(signupTab.waitForExistence(timeout: 8), "Guest account action \(identifier) must open authentication")
            XCTAssertTrue(signupTab.isHittable)
            XCTAssertFalse(app.descendants(matching: .any)["privacy-connected-account-row"].exists)
            XCTAssertFalse(app.descendants(matching: .any)["privacy-debug-session-start"].exists)
            app.terminate()
        }
    }

    // contract-test: direct surface=gui.apple assertions=settings-ui.shell.lifecycle-and-routing,settings-ui.navigation.contextual-availability
    func testGuestPrivatePrivacyLinksOpenAuthenticationBeforeDestination() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-app-link-fixture"]
        for path in ["privacy/connected-accounts", "privacy/hide-personal-data",
                     "privacy/auto-deletion/chats", "privacy/share-debug-logs"] {
            app.launchEnvironment["UI_TEST_SETTINGS_LINK_PATH"] = path
            app.launch()
            let link = app.descendants(matching: .any)["ui-test-settings-link"]
            XCTAssertTrue(link.waitForExistence(timeout: 15))
            XCTAssertTrue(link.isHittable)
            link.tap()
            let signup = app.buttons["auth-signup-tab"]
            XCTAssertTrue(signup.waitForExistence(timeout: 8), path)
            XCTAssertTrue(signup.isHittable)
            XCTAssertFalse(app.descendants(matching: .any)["settings-privacy-subpage-back"].exists)
            XCTAssertFalse(app.descendants(matching: .any)["privacy-connected-account-row"].exists)
            app.terminate()
        }
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.navigation.contextual-availability,settings-ui.navigation.parent-return
    func testGuestPrivacyPolicyRemainsPublicAndReturnsToOverview() {
        let app = launchGuestPrivacy()
        attachScreenshot("Privacy guest hub subtitle order", app: app)
        let policy = app.buttons["settings-privacy-policy-link"]
        XCTAssertTrue(policy.waitForExistence(timeout: 5))
        XCTAssertTrue(policy.isHittable)
        XCTAssertEqual(policy.images.count, 0, "The public policy entry is a text link without an icon")
        XCTAssertEqual(policy.frame.height, 40, accuracy: 1, "The text link uses web10pt vertical padding")
        let hideToggle = app.switches["settings-hide-personal-data-row-toggle"]
        XCTAssertTrue(hideToggle.waitForExistence(timeout: 5))
        XCTAssertTrue(hideToggle.isHittable)
        XCTAssertTrue(app.switches["settings-privacy-location-toggle"].isHittable)
        let connected = app.buttons["settings-privacy-connected-accounts-row"]
        XCTAssertEqual(connected.frame.height, 44, accuracy: 1, "Compact rows retain the web44pt icon slot")
        policy.tap()
        let back = app.buttons["settings-privacy-subpage-back"]
        XCTAssertTrue(back.waitForExistence(timeout: 5))
        XCTAssertTrue(back.isHittable)
        XCTAssertFalse(app.buttons["auth-signup-tab"].exists)
        attachScreenshot("Privacy public policy", app: app)
        back.tap()
        XCTAssertTrue(app.buttons["settings-privacy-connected-accounts-row"].waitForExistence(timeout: 5))
    }

    private func attachScreenshot(_ name: String, app: XCUIApplication) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func launchGuestPrivacy() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache"]
        app.launch()
        let settings = app.buttons["settings-button"]
        XCTAssertTrue(settings.waitForExistence(timeout: 15))
        XCTAssertTrue(settings.isHittable)
        settings.tap()
        let privacy = app.buttons["settings-privacy-row"]
        XCTAssertTrue(privacy.waitForExistence(timeout: 8))
        XCTAssertTrue(privacy.isHittable)
        privacy.tap()
        XCTAssertTrue(element("settings-privacy-hub", in: app).waitForExistence(timeout: 8))
        XCTAssertTrue(app.scrollViews["settings-privacy-page"].waitForExistence(timeout: 5))
        return app
    }

    private func launchPrivacyFixture(extraArguments: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = [
            "--ui-test-disable-auth-cache",
            "--ui-test-account-settings-fixture",
            "--ui-test-authenticated-chat-navigation",
            "--ui-test-privacy-settings-fixture",
            "-AppleLanguages", "(en)", "-AppleLocale", "en_US", "-app_language", "en",
        ] + extraArguments
        app.launch()
        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15))
        app.buttons["settings-button"].tap()
        let privacyRow = element("settings-privacy-row", in: app)
        XCTAssertTrue(privacyRow.waitForExistence(timeout: 8))
        privacyRow.tap()
        XCTAssertTrue(element("settings-privacy-page", in: app).waitForExistence(timeout: 8))
        XCTAssertTrue(app.scrollViews["settings-privacy-page"].exists, "The page identity must belong to the actual scrolling Privacy surface")
        XCTAssertTrue(element("settings-privacy-hub", in: app).exists)
        return app
    }

    private func assertHittable(_ identifier: String, in app: XCUIApplication) {
        let target = element(identifier, in: app)
        XCTAssertTrue(target.waitForExistence(timeout: 5), "Missing \(identifier)")
        XCTAssertTrue(target.isHittable, "Not hittable: \(identifier)")
    }

    private func returnToPrivacyHub(in app: XCUIApplication) {
        let explicitBack = app.buttons["settings-privacy-subpage-back"].firstMatch
        if explicitBack.exists {
            explicitBack.tap()
        } else {
            app.buttons["settings-privacy-page"].firstMatch.tap()
        }
        XCTAssertTrue(element("settings-privacy-connected-accounts-row", in: app).waitForExistence(timeout: 5))
    }

    private func scrollTo(_ identifier: String, in app: XCUIApplication) {
        let target = element(identifier, in: app)
        for _ in 0..<8 where !target.isHittable {
            app.swipeUp()
        }
        for _ in 0..<8 where !target.isHittable {
            app.swipeDown()
        }
        XCTAssertTrue(target.exists, "Missing \(identifier)")
        XCTAssertTrue(target.isHittable, "Not hittable after scrolling: \(identifier)")
    }

    private func scrollUntilExists(_ identifier: String, in app: XCUIApplication) {
        let target = element(identifier, in: app)
        for _ in 0..<8 where !target.exists {
            app.swipeUp()
        }
        XCTAssertTrue(target.exists, "Missing \(identifier)")
    }

    private func element(_ identifier: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier == %@", identifier))
            .firstMatch
    }
}
