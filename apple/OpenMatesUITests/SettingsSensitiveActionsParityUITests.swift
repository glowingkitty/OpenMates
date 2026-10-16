// Fixture-backed sensitive settings parity UI tests.
// Verifies native account-security entry points and destructive-action previews
// without live account mutation. Tests must avoid logging or attaching secrets,
// backup codes, recovery keys, OTP seeds, API keys, or private email values.

import XCTest

@MainActor
final class SettingsSensitiveActionsParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.navigation.contextual-availability,settings-ui.composition.canonical-and-accessible
    func testSensitiveEntrypointsAndDeletePreview() throws {
        let app = launchAccountSettingsFixture()
        openSettingsAccountPage(in: app)

        for identifier in sensitiveAccountRows {
            XCTAssertTrue(waitForButton(identifier, in: app, timeout: 5), "Expected sensitive row \(identifier)")
        }
        XCTAssertFalse(app.tables.firstMatch.exists, "Account settings must not render default List/table chrome")
        app.terminate()

        let deletePreviewApp = launchAccountSettingsFixture(extraArguments: ["--ui-test-account-delete-preview"])
        openSettingsAccountEntry(in: deletePreviewApp)
        XCTAssertTrue(waitForElement("delete-account-password-input", in: deletePreviewApp, timeout: 5))
        XCTAssertTrue(waitForElement("delete-account-confirm-input", in: deletePreviewApp, timeout: 5))
        let finalDeleteButton = deletePreviewApp.buttons["delete-account-final-button"]
        XCTAssertTrue(finalDeleteButton.waitForExistence(timeout: 5))
        XCTAssertFalse(finalDeleteButton.isEnabled, "Final account deletion must stay disabled without explicit confirmation")
        XCTAssertFalse(deletePreviewApp.tables.firstMatch.exists, "Delete account preview must not render default List/table chrome")

        attachScreenshot(name: "Sensitive settings fixture preview")
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.authoritative-enforcement
    func testExpiredPasswordCommitClearsFormAndRequiresFreshVerification() {
        for status in [401, 428] {
            let app = launchPasswordCommitFixture(status: status)
            let fields = passwordFields(in: app)
            let emptyValues = fields.map { $0.value as? String ?? "" }
            preparePasswordCommit(in: app, fields: fields)
            app.buttons["settings-password-submit"].tap()
            let submit = app.buttons["settings-password-submit"]
            XCTAssertTrue(app.staticTexts["settings-password-result"].waitForExistence(timeout: 5))
            XCTAssertEqual(submit.value as? String, "request-verification")
            XCTAssertFalse(submit.isEnabled, "A fresh draft and verification are required")
            XCTAssertFalse(app.textFields["settings-password-email-code"].exists)
            XCTAssertEqual(fields.map { $0.value as? String ?? "" }, emptyValues)

            // Re-entering a draft must request a new proof instead of committing.
            enterPasswordDraft(fields)
            XCTAssertTrue(submit.isEnabled)
            submit.tap()
            let code = app.textFields["settings-password-email-code"]
            XCTAssertTrue(code.waitForExistence(timeout: 5))
            XCTAssertEqual(submit.value as? String, "commit-password")
            XCTAssertFalse(submit.isEnabled, "The replacement challenge requires a fresh code")
            app.terminate()
        }
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible
    func testUnavailablePasswordCommitPreservesDraftAndVerificationCode() {
        let app = launchPasswordCommitFixture(status: 503)
        let fields = passwordFields(in: app)
        preparePasswordCommit(in: app, fields: fields)
        let valuesBeforeFailure = fields.map { $0.value as? String ?? "" }
        app.buttons["settings-password-submit"].tap()
        XCTAssertTrue(app.staticTexts["settings-password-result"].waitForExistence(timeout: 5))
        let submit = app.buttons["settings-password-submit"]
        XCTAssertEqual(submit.value as? String, "commit-password")
        XCTAssertTrue(submit.isEnabled)
        XCTAssertEqual(fields.map { $0.value as? String ?? "" }, valuesBeforeFailure)
        XCTAssertEqual(app.textFields["settings-password-email-code"].value as? String, "123456")
        app.terminate()
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible,settings-ui.parity.web-apple-shell
    func testLandscapePasswordFormRemainsScrollableAndInteractive() {
        XCUIDevice.shared.orientation = .landscapeLeft
        defer { XCUIDevice.shared.orientation = .portrait }
        let app = launchAccountSettingsFixture(extraArguments: ["--ui-test-password-commit-status", "428"])
        let landscape = XCTNSPredicateExpectation(
            predicate: NSPredicate { _, _ in app.frame.width > app.frame.height }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [landscape], timeout: 5), .completed)
        openSettingsAccountPage(in: app)
        XCTAssertTrue(waitForButton("settings-account-password-row", in: app, timeout: 5))
        app.buttons["settings-account-password-row"].tap()
        let scroll = app.scrollViews["settings-password-form-scroll"]
        XCTAssertTrue(scroll.waitForExistence(timeout: 5))
        XCTAssertGreaterThan(scroll.frame.height, 100, "Landscape must retain room for settings controls")
        XCTAssertTrue(app.frame.intersects(scroll.frame))
        let current = app.secureTextFields["settings-password-current-input"]
        XCTAssertTrue(current.waitForExistence(timeout: 5))
        for _ in 0..<4 where !current.isHittable { scroll.swipeUp() }
        XCTAssertTrue(current.isHittable)
        let emptyValue = current.value as? String
        current.tap()
        current.typeText("SyntheticOld9!\n")
        XCTAssertNotEqual(current.value as? String, emptyValue, "The visible field must accept typing")
        XCTAssertTrue(app.buttons["settings-account-subpage-back"].isHittable)
        app.terminate()
    }

    private func launchPasswordCommitFixture(status: Int) -> XCUIApplication {
        // Wide embed cases share this simulator and leave it in landscape.
        // These password-form regressions own their portrait viewport explicitly.
        XCUIDevice.shared.orientation = .portrait
        let app = launchAccountSettingsFixture(extraArguments: ["--ui-test-password-commit-status", String(status)])
        let portrait = XCTNSPredicateExpectation(
            predicate: NSPredicate { _, _ in app.frame.height > app.frame.width }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [portrait], timeout: 5), .completed,
                       "The password fixture requires its own portrait viewport")
        openSettingsAccountPage(in: app)
        XCTAssertTrue(waitForButton("settings-account-password-row", in: app, timeout: 5))
        app.buttons["settings-account-password-row"].tap()
        XCTAssertTrue(app.secureTextFields["settings-password-current-input"].waitForExistence(timeout: 5))
        return app
    }

    private func passwordFields(in app: XCUIApplication) -> [XCUIElement] {
        ["current", "new", "confirm"].map { app.secureTextFields["settings-password-\($0)-input"] }
    }

    private func enterPasswordDraft(_ fields: [XCUIElement]) {
        for (field, value) in zip(fields, ["SyntheticOld9!", "SyntheticNew9!", "SyntheticNew9!"]) {
            field.tap()
            field.typeText(value + "\n")
        }
    }

    private func preparePasswordCommit(in app: XCUIApplication, fields: [XCUIElement]) {
        enterPasswordDraft(fields)
        let submit = app.buttons["settings-password-submit"]
        XCTAssertTrue(submit.isEnabled)
        XCTAssertEqual(submit.value as? String, "request-verification")
        submit.tap()
        let code = app.textFields["settings-password-email-code"]
        XCTAssertTrue(code.waitForExistence(timeout: 5))
        code.tap()
        code.typeText("123456")
        // Bring the actual submit control above the number pad if necessary.
        let formScroll = app.scrollViews["settings-password-form-scroll"]
        XCTAssertTrue(formScroll.waitForExistence(timeout: 5))
        for _ in 0..<4 where !submit.isHittable {
            formScroll.swipeUp()
        }
        XCTAssertTrue(submit.isHittable)
        XCTAssertTrue(submit.isEnabled)
        XCTAssertEqual(submit.value as? String, "commit-password")
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.parity.web-apple-shell,settings-ui.navigation.parent-return
    func testReservedAccountSecurityInventoryIsReadOnly() throws {
        let credentials = try RealAccountTestCredentials.fromReservedSlot(14)
        let app = RealAccountUITestSupport.launchApp(disableAuthCache: true)
        RealAccountUITestSupport.logIn(app: app, credentials: credentials)
        openSettingsAccountPage(in: app)

        XCTAssertTrue(waitForButton("settings-account-passkeys-row", in: app, timeout: 8))
        app.buttons["settings-account-passkeys-row"].tap()
        XCTAssertTrue(waitForElement("settings-account-passkeys-page", in: app, timeout: 8))
        XCTAssertFalse(app.tables.firstMatch.exists)
        XCTAssertFalse(app.alerts.firstMatch.exists)

        app.buttons["settings-account-subpage-back"].tap()
        XCTAssertTrue(waitForButton("settings-account-sessions-row", in: app, timeout: 8))
        app.buttons["settings-account-sessions-row"].tap()
        XCTAssertTrue(waitForElement("settings-account-sessions-page", in: app, timeout: 8))
        XCTAssertFalse(app.tables.firstMatch.exists)
        XCTAssertFalse(app.alerts.firstMatch.exists)
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.navigation.contextual-availability
    func testAdminRoutesAreFailClosedWithoutAdminFixture() {
        let accountApp = launchAccountSettingsFixture()
        openSettingsMenu(in: accountApp)
        XCTAssertFalse(waitForButton("settings-server-row", in: accountApp, timeout: 1))
        XCTAssertFalse(waitForButton("settings-logs-row", in: accountApp, timeout: 1))
        accountApp.terminate()

        let adminApp = launchAccountSettingsFixture(extraArguments: ["--ui-test-admin-settings-fixture"])
        openSettingsMenu(in: adminApp)
        XCTAssertTrue(waitForButton("settings-server-row", in: adminApp, timeout: 5))
        XCTAssertTrue(waitForButton("settings-logs-row", in: adminApp, timeout: 5))
        XCTAssertFalse(adminApp.tables.firstMatch.exists)
    }

    private var sensitiveAccountRows: [String] {
        [
            "settings-account-passkeys-row",
            "settings-account-password-row",
            "settings-account-2fa-row",
            "settings-account-recovery-key-row",
            "settings-account-sessions-row",
            "settings-account-delete-row",
        ]
    }

    private func launchAccountSettingsFixture(extraArguments: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-account-settings-fixture"] + extraArguments
        app.launch()
        return app
    }

    private func openSettingsAccountEntry(in app: XCUIApplication) {
        openSettingsMenu(in: app)
        XCTAssertTrue(waitForButton("settings-account-row", in: app, timeout: 8))
        app.buttons["settings-account-row"].tap()
    }

    private func openSettingsMenu(in app: XCUIApplication) {
        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15))
        app.buttons["settings-button"].tap()
        XCTAssertTrue(waitForElement("settings-menu", in: app, timeout: 10))
    }

    private func openSettingsAccountPage(in app: XCUIApplication) {
        openSettingsAccountEntry(in: app)
        let account = app.otherElements["workspace-settings"]
        XCTAssertTrue(account.waitForExistence(timeout: 8))
        XCTAssertTrue(account.buttons["settings-account-username-row"].waitForExistence(timeout: 8),
                      "The rendered account form must be active before opening security")
    }

    private func waitForButton(_ identifier: String, in app: XCUIApplication, timeout: TimeInterval) -> Bool {
        let button = app.buttons[identifier]
        if button.waitForExistence(timeout: timeout) { return true }

        let scrollView = app.otherElements["workspace-settings"].scrollViews.firstMatch
        for _ in 0..<8 where scrollView.exists {
            scrollView.swipeUp()
            if button.waitForExistence(timeout: 1) { return true }
        }
        return false
    }

    private func waitForElement(_ identifier: String, in app: XCUIApplication, timeout: TimeInterval) -> Bool {
        let element = app.descendants(matching: .any)[identifier]
        if element.waitForExistence(timeout: timeout) { return true }

        let scrollView = app.otherElements["workspace-settings"].scrollViews.firstMatch
        for _ in 0..<8 where scrollView.exists {
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
