// Shared forms, deterministic local transport. These assertions cover state and
// interaction contracts, not account security or exact rendered visual approval.
// Web references: Basics.svelte; PasswordAndTfaOtp.svelte; signup-flow-passkey.spec.ts;
// passkey-login-alternatives.spec.ts; backup-code-login-flow.spec.ts.
import XCTest

@MainActor final class DevAuthFormUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testSignupConsentLinksDoNotGrantConsentAndAcceptedFormReplacesInputs() {
        let app = launch("signup", "basics")
        for id in ["signup-stay", "signup-newsletter", "signup-terms", "signup-privacy"] {
            XCTAssertTrue(app.switches[id].waitForExistence(timeout: 5))
            XCTAssertEqual(app.switches[id].value as? String, "Off", id)
        }
        fillSignup(app)
        let submit = app.buttons["signup-submit"]
        XCTAssertFalse(submit.isEnabled)
        tap(app.buttons["signup-terms-link"], in: app)
        XCTAssertEqual(app.staticTexts["fixture-auth-destination"].label, "https://openmates.org/legal/terms")
        app.buttons["fixture-auth-return"].tap()
        XCTAssertEqual(app.switches["signup-terms"].value as? String, "Off")
        XCTAssertEqual(app.textFields["signup-email"].value as? String, "fixture@example.test")
        tap(app.switches["signup-terms"], in: app)
        XCTAssertFalse(submit.isEnabled)
        tap(app.switches["signup-privacy"], in: app)
        XCTAssertTrue(submit.isEnabled)
        XCTAssertEqual(app.switches["signup-newsletter"].value as? String, "Off")
        tap(submit, in: app)
        XCTAssertTrue(app.staticTexts["signup-code-requested"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.staticTexts["signup-requested-email"].label, "fixture@example.test")
        XCTAssertTrue(app.staticTexts["fixture-signup-boundary"].exists)
        XCTAssertFalse(app.textFields["signup-email"].exists)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testSignupRejectedAndSuspendedRequestsPreserveCorrectFormState() {
        var app = launch("signup", "error")
        fillSignup(app)
        acceptSignupConsents(app)
        tap(app.buttons["signup-submit"], in: app)
        XCTAssertTrue(app.staticTexts["auth-form-error"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts["signup-code-requested"].exists)
        XCTAssertEqual(app.textFields["signup-email"].value as? String, "fixture@example.test")
        XCTAssertTrue(app.buttons["signup-submit"].isEnabled)
        app.terminate()

        app = launch("signup", "loading")
        fillSignup(app)
        acceptSignupConsents(app)
        tap(app.buttons["signup-submit"], in: app)
        XCTAssertTrue(app.buttons["fixture-complete-signup-request"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["signup-submit"].isEnabled)
        XCTAssertFalse(app.textFields["signup-email"].isEnabled)
        XCTAssertFalse(app.staticTexts["signup-code-requested"].exists)
        tap(app.buttons["fixture-complete-signup-request"], in: app)
        XCTAssertTrue(app.staticTexts["signup-code-requested"].waitForExistence(timeout: 5))
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testUnavailableSignupExplainsBoundaryAndFreshLaunchClearsFixtureState() {
        var app = launch("signup", "unavailable")
        fillSignup(app)
        acceptSignupConsents(app)
        XCTAssertTrue(app.staticTexts["signup-unavailable"].exists)
        XCTAssertFalse(app.buttons["signup-submit"].isEnabled)
        XCTAssertFalse(app.staticTexts["auth-form-error"].exists)
        app.terminate()
        app = launch("signup", "basics")
        XCTAssertEqual(app.textFields["signup-email"].value as? String, "Enter E-Mail address")
        XCTAssertEqual(app.switches["signup-terms"].value as? String, "Off")
        XCTAssertFalse(app.buttons["signup-submit"].isEnabled)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence,auth.surface.first-party-boundary
    func testLookupKeyboardSubmitAndAlternativeReturnUseRealFormTransitions() {
        let app = launch("login", "email")
        let email = app.textFields["email-input"]
        XCTAssertTrue(email.waitForExistence(timeout: 5))
        email.tap()
        email.typeText("invalid")
        XCTAssertFalse(app.buttons["continue-button"].isEnabled)
        XCTAssertTrue(app.staticTexts["lookup-error"].exists)
        tap(app.buttons["login-passkey-option"], in: app)
        XCTAssertEqual(app.staticTexts["fixture-auth-destination"].label, "passkey")
        app.buttons["fixture-auth-return"].tap()
        XCTAssertEqual(email.value as? String, "invalid")
        email.tap()
        email.typeText("@example.test")
        tap(app.buttons["stay-logged-in-toggle"], in: app)
        XCTAssertEqual(app.buttons["stay-logged-in-toggle"].value as? String, "On")
        email.tap()
        email.typeText("\n")
        XCTAssertTrue(app.secureTextFields["password-input"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.textFields["email-input"].exists)
        tap(app.buttons["login-another-account"], in: app)
        XCTAssertTrue(email.waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["continue-button"].isEnabled)
        XCTAssertEqual(app.buttons["stay-logged-in-toggle"].value as? String, "On")
    }

    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence
    func testPasswordKeyboardSubmitRevealsOTPAndRejectedCodeCannotComplete() {
        let app = launch("login", "password")
        let password = app.secureTextFields["password-input"]
        XCTAssertTrue(password.waitForExistence(timeout: 5))
        XCTAssertFalse(app.textFields["tfa-code-input"].exists)
        password.tap()
        password.typeText("fixture-only-password\n")
        let otp = app.textFields["tfa-code-input"]
        XCTAssertTrue(otp.waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["login-button"].isEnabled)
        otp.tap()
        otp.typeText("000000")
        tap(app.buttons["login-button"], in: app)
        XCTAssertTrue(app.staticTexts["password-login-error"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts["fixture-login-complete"].exists)
        XCTAssertFalse(app.buttons["login-button"].isEnabled)
        otp.tap()
        otp.typeText("123456")
        tap(app.buttons["login-button"], in: app)
        XCTAssertTrue(app.staticTexts["fixture-login-complete"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.secureTextFields["password-input"].exists)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence
    func testOTPVariantStartsVisibleAndBackupModeFormatsTheSubmittedCode() {
        let app = launch("login", "otp")
        let password = app.secureTextFields["password-input"]
        let code = app.textFields["tfa-code-input"]
        XCTAssertTrue(code.waitForExistence(timeout: 5))
        password.tap()
        password.typeText("fixture-only-password")
        code.tap()
        code.typeText("123")
        XCTAssertFalse(app.buttons["login-button"].isEnabled)
        tap(app.buttons["login-code-mode"], in: app)
        XCTAssertFalse(app.buttons["login-button"].isEnabled)
        code.tap()
        code.typeText("abcdefgh1234")
        XCTAssertEqual(code.value as? String, "ABCD-EFGH-1234")
        XCTAssertTrue(app.buttons["login-button"].isEnabled)
        tap(app.buttons["login-button"], in: app)
        XCTAssertTrue(app.staticTexts["fixture-login-complete"].waitForExistence(timeout: 5))
    }

    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence
    func testLookupAndPasswordErrorVariantsCannotProduceLocalCompletion() {
        var app = launch("login", "lookup-error")
        let email = app.textFields["email-input"]
        XCTAssertTrue(email.waitForExistence(timeout: 5))
        email.tap()
        email.typeText("fixture@example.test\n")
        XCTAssertTrue(app.staticTexts["lookup-error"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.secureTextFields["password-input"].exists)
        XCTAssertTrue(app.buttons["continue-button"].isEnabled)
        app.terminate()
        app = launch("login", "password-error")
        let password = app.secureTextFields["password-input"]
        XCTAssertTrue(password.waitForExistence(timeout: 5))
        password.tap()
        password.typeText("fixture-only-password\n")
        XCTAssertTrue(app.textFields["tfa-code-input"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["password-login-error"].exists)
        XCTAssertFalse(app.staticTexts["fixture-login-complete"].exists)
    }

    private func fillSignup(_ app: XCUIApplication) {
        let email = app.textFields["signup-email"]
        XCTAssertTrue(email.waitForExistence(timeout: 5))
        email.tap()
        email.typeText("fixture@example.test\n")
        XCTAssertEqual(app.textFields["signup-username"].value as? String, "fixture")
    }
    private func acceptSignupConsents(_ app: XCUIApplication) {
        tap(app.switches["signup-terms"], in: app)
        tap(app.switches["signup-privacy"], in: app)
    }
    private func tap(_ element: XCUIElement, in app: XCUIApplication) {
        XCTAssertTrue(element.waitForExistence(timeout: 5))
        for _ in 0..<6 {
            if element.isHittable { break }
            let scroll = app.scrollViews.firstMatch
            if element.frame.minY < app.windows.firstMatch.frame.midY { scroll.swipeDown() }
            else { scroll.swipeUp() }
        }
        XCTAssertTrue(element.isHittable)
        element.tap()
    }
    private func launch(_ component: String, _ variant: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", component, "--dev-preview-variant", variant,
            "--dev-preview-theme", "light", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        return app
    }
}
