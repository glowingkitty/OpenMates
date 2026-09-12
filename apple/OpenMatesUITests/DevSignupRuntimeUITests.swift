// Uses production NativeSignupForm/SignupViewModel with local transport fixtures.
// Web contract: signup-skip-2fa-flow.spec.ts and signupFlow.test.ts. Completing a
// callback alone is insufficient: fields, error recovery, transitions and counts
// must match, and no extra recovery/backup/payment screen can appear.
import XCTest

@MainActor final class DevSignupRuntimeUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testConfirmationRejectsWrongCodeThenAutomaticallyAdvancesSixDigitsToSecurityChoice() {
        let app = launch("confirm-email")
        let code = app.textFields["signup-confirmation-code"]
        XCTAssertTrue(code.waitForExistence(timeout: 5))
        XCTAssertEqual(app.staticTexts["signup-requested-email"].label, "fixture@example.test")
        capture(app, name: "signup-confirm-email")
        code.tap(); code.typeText("111111")
        XCTAssertTrue(app.staticTexts["signup-runtime-error"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["signup-password-option"].exists)
        let clearedCode = code.value as? String ?? ""
        XCTAssertTrue(clearedCode.isEmpty || clearedCode == (code.placeholderValue ?? ""))
        tap(app.buttons["signup-open-mail"], in: app)
        XCTAssertTrue(app.staticTexts["fixture-auth-destination"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.staticTexts["fixture-auth-destination"].label, "mailto:")
        tap(app.buttons["fixture-auth-return"], in: app)
        XCTAssertTrue(code.waitForExistence(timeout: 5))
        code.tap(); code.typeText("123456")
        XCTAssertTrue(app.buttons["signup-password-option"].waitForExistence(timeout: 5))
        XCTAssertTrue(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: code)], timeout: 3) == .completed)
        XCTAssertFalse(app.staticTexts["signup-passkey-registration-boundary"].exists)
        XCTAssertTrue(app.buttons["signup-passkey-option"].isEnabled)
        XCTAssertEqual(app.staticTexts["fixture-signup-transport-counts"].label, "create=0;login=0")
    }

    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence,auth.surface.first-party-boundary
    func testPasswordStrengthConfirmationKeyboardAndCompletionFollowActualParentStateMachine() {
        let app = launch("password")
        let password = app.secureTextFields["signup-password"]
        XCTAssertTrue(password.waitForExistence(timeout: 5))
        password.tap(); password.typeText("short")
        XCTAssertTrue(app.staticTexts["signup-password-validation"].waitForExistence(timeout: 3))
        XCTAssertFalse(app.buttons["signup-create-password"].isEnabled)
        password.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: 5) + "OrchidMeadow1!\n")
        let confirmation = app.secureTextFields["signup-password-confirmation"]
        confirmation.typeText("OrchidMeadow1?")
        XCTAssertFalse(app.buttons["signup-create-password"].isEnabled)
        confirmation.typeText(XCUIKeyboardKey.delete.rawValue + "!\n")
        XCTAssertTrue(app.staticTexts["fixture-signup-complete"].waitForExistence(timeout: 10))
        XCTAssertTrue(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: password)], timeout: 3) == .completed)
        XCTAssertEqual(app.staticTexts["fixture-signup-transport-counts"].label, "create=1;login=1")
        XCTAssertEqual(app.staticTexts["signup-flow-state"].label, "complete")
        XCTAssertTrue(app.staticTexts["fixture-signup-boundary"].exists)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence,auth.surface.first-party-boundary
    func testUncertainAccountCreationShowsLoginRetryAndNeverSubmitsCreationTwice() {
        let app = launch("creation-uncertain")
        let password = app.secureTextFields["signup-password"]
        XCTAssertTrue(password.waitForExistence(timeout: 5))
        password.tap(); password.typeText("OrchidMeadow1!\n")
        app.secureTextFields["signup-password-confirmation"].typeText("OrchidMeadow1!\n")
        XCTAssertTrue(app.staticTexts["signup-runtime-error"].waitForExistence(timeout: 10))
        XCTAssertEqual(app.staticTexts["fixture-signup-transport-counts"].label, "create=1;login=0")
        XCTAssertFalse(password.isEnabled)
        XCTAssertFalse(app.staticTexts["fixture-signup-complete"].exists)
        tap(app.buttons["signup-create-password"], in: app)
        XCTAssertTrue(app.staticTexts["fixture-signup-complete"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.staticTexts["fixture-signup-transport-counts"].label, "create=1;login=1")
    }
    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testSecurityChoiceSettlesIntoMeasuredPasswordCardAndBothFieldsRemainInteractive() {
        let app = launch("secure-account")
        let option = app.buttons["signup-password-option"]
        XCTAssertTrue(option.waitForExistence(timeout: 5))
        let card = app.otherElements["signup-top-card"]
        XCTAssertTrue(card.waitForExistence(timeout: 5))
        XCTAssertEqual(card.frame.width, 326, accuracy: 1)
        XCTAssertEqual(card.frame.height, 600, accuracy: 1)
        capture(app, name: "signup-secure-account")
        XCTAssertTrue(app.buttons["signup-passkey-option"].isEnabled)
        tap(option, in: app)
        let password = app.secureTextFields["signup-password"]
        XCTAssertTrue(password.waitForExistence(timeout: 5))
        let settled = NSPredicate { _, _ in abs(card.frame.height - 380) < 1 && !option.exists }
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: settled, object: card)], timeout: 3), .completed)
        let field = app.otherElements["signup-password-field"]
        XCTAssertTrue(field.exists)
        XCTAssertEqual(field.frame.width, 278, accuracy: 1)
        XCTAssertEqual(field.frame.height, 48, accuracy: 1)
        capture(app, name: "signup-password-settled")
        XCTAssertTrue(app.staticTexts["signup-password-advice"].exists)
        tap(password, in: app)
        password.typeText("OrchidMeadow1!\n")
        app.secureTextFields["signup-password-confirmation"].typeText("OrchidMeadow1?")
        XCTAssertTrue(app.staticTexts["signup-password-confirmation-validation"].waitForExistence(timeout: 3))
        XCTAssertFalse(app.buttons["signup-create-password"].isEnabled)
        XCTAssertEqual(app.staticTexts["fixture-signup-transport-counts"].label, "create=0;login=0")
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary,auth.login.method-convergence
    func testPasswordManagerLinkReturnPreservesActualFormAndSubmitsOnce() {
        let app = launch("password")
        let password = app.secureTextFields["signup-password"]
        XCTAssertTrue(password.waitForExistence(timeout: 5))
        password.tap(); password.typeText("OrchidMeadow1!\n")
        app.secureTextFields["signup-password-confirmation"].typeText("OrchidMeadow1!")
        tap(app.buttons["signup-password-managers"], in: app)
        let destination = app.staticTexts["fixture-auth-destination"]
        XCTAssertTrue(destination.waitForExistence(timeout: 5))
        XCTAssertEqual(destination.label, "https://search.brave.com/search?q=best+password+manager")
        tap(app.buttons["fixture-auth-return"], in: app)
        XCTAssertTrue(password.waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["signup-create-password"].isEnabled)
        tap(app.buttons["signup-create-password"], in: app)
        XCTAssertTrue(app.staticTexts["fixture-signup-complete"].waitForExistence(timeout: 10))
        XCTAssertEqual(app.staticTexts["fixture-signup-transport-counts"].label, "create=1;login=1")
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary,auth.login.method-convergence
    func testPasskeyControlRegistersVerifiesAndCompletesUsingActualSignupRuntime() {
        let app = launch("passkey")
        tap(app.buttons["signup-passkey-option"], in: app)
        XCTAssertTrue(app.staticTexts["fixture-signup-complete"].waitForExistence(timeout: 10))
        XCTAssertEqual(app.staticTexts["fixture-signup-transport-counts"].label, "create=1;login=1")
        XCTAssertEqual(app.staticTexts["signup-flow-state"].label, "complete")
        XCTAssertFalse(app.secureTextFields["signup-password"].exists)
        XCTAssertEqual(app.staticTexts["fixture-signup-authorization-counts"].label, "register=1;assert=1")
        XCTAssertFalse(app.staticTexts["signup-runtime-error"].exists)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary,auth.login.method-convergence
    func testCancelledPasskeyAuthorizationKeepsChoiceUsableAndRetryCompletesOnce() {
        let app = launch("passkey-cancel")
        let passkey = app.buttons["signup-passkey-option"]
        tap(passkey, in: app)
        let authorizations = app.staticTexts["fixture-signup-authorization-counts"]
        let cancelled = NSPredicate(format: "label == %@", "register=1;assert=0")
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: cancelled, object: authorizations)], timeout: 5), .completed)
        let enabled = NSPredicate(format: "enabled == true")
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: enabled, object: passkey)], timeout: 5), .completed)
        XCTAssertEqual(app.staticTexts["fixture-signup-transport-counts"].label, "create=0;login=0")
        XCTAssertTrue(app.buttons["signup-password-option"].isEnabled)
        XCTAssertFalse(app.staticTexts["signup-runtime-error"].exists)
        tap(passkey, in: app)
        XCTAssertTrue(app.staticTexts["fixture-signup-complete"].waitForExistence(timeout: 10))
        XCTAssertEqual(app.staticTexts["fixture-signup-transport-counts"].label, "create=1;login=1")
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testPRFErrorContinueReturnsToSecurityAndPasswordFieldsWithoutCreatingAccount() {
        let app = launch("passkey-prf-error")
        let explanation = app.staticTexts["signup-passkey-prf-error"]
        XCTAssertTrue(explanation.waitForExistence(timeout: 5))
        XCTAssertTrue(explanation.label.contains("passkey encryption"))
        capture(app, name: "signup-passkey-prf-error")
        tap(app.buttons["signup-passkey-prf-continue"], in: app)
        let passwordChoice = app.buttons["signup-password-option"]
        XCTAssertTrue(passwordChoice.waitForExistence(timeout: 5))
        let settled = NSPredicate(format: "exists == false")
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: settled, object: explanation)], timeout: 3), .completed)
        tap(passwordChoice, in: app)
        let password = app.secureTextFields["signup-password"]
        XCTAssertTrue(password.waitForExistence(timeout: 5))
        tap(password, in: app); password.typeText("OrchidMeadow1!\n")
        app.secureTextFields["signup-password-confirmation"].typeText("OrchidMeadow1!")
        XCTAssertTrue(app.buttons["signup-create-password"].isEnabled)
        XCTAssertEqual(app.staticTexts["fixture-signup-transport-counts"].label, "create=0;login=0")
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary,auth.login.method-convergence
    func testUncertainPasskeyCompletionRetainsCredentialAndRetryUsesLoginOnly() {
        let app = launch("passkey-uncertain")
        let passkey = app.buttons["signup-passkey-option"]
        tap(passkey, in: app)
        XCTAssertTrue(app.staticTexts["signup-runtime-error"].waitForExistence(timeout: 10))
        XCTAssertEqual(app.staticTexts["fixture-signup-transport-counts"].label, "create=1;login=0")
        XCTAssertFalse(app.buttons["signup-password-option"].isEnabled)
        XCTAssertFalse(app.staticTexts["fixture-signup-complete"].exists)
        tap(passkey, in: app)
        XCTAssertTrue(app.staticTexts["fixture-signup-complete"].waitForExistence(timeout: 10))
        XCTAssertEqual(app.staticTexts["fixture-signup-transport-counts"].label, "create=1;login=1")
    }

    private func capture(_ app: XCUIApplication, name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
    }
    private func tap(_ element: XCUIElement, in app: XCUIApplication) {
        XCTAssertTrue(element.waitForExistence(timeout: 5))
        for _ in 0..<6 {
            if element.isHittable { break }
            let scroll = app.scrollViews.firstMatch
            if element.frame.minY < app.windows.firstMatch.frame.midY { scroll.swipeDown() }
            else { scroll.swipeUp() }
        }
        XCTAssertTrue(element.isHittable); element.tap()
    }
    private func launch(_ variant: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "signup", "--dev-preview-variant", variant,
            "--dev-preview-theme", "light", "--dev-preview-width", "390", "--dev-preview-height", "844", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch(); return app
    }
}
