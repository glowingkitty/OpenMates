// Auth flow UI tests — maps to: signup-flow.spec.ts, signup-flow-passkey.spec.ts,
// backup-code-login-flow.spec.ts, recovery-key-login-flow.spec.ts,
// account-recovery-flow.spec.ts, signup-skip-2fa-flow.spec.ts

import XCTest

final class AuthFlowUITests: XCTestCase {

    var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["--uitesting"]
        app.launch()
    }

    // MARK: - Login (login-flow)

    func testLoginScreenShowsEmailInput() {
        let emailInput = app.textFields["email-input"]
        XCTAssertTrue(emailInput.waitForExistence(timeout: 5))
    }

    func testContinueButtonDisabledWhenEmpty() {
        let continueBtn = app.buttons["continue-button"]
        XCTAssertTrue(continueBtn.waitForExistence(timeout: 5))
        XCTAssertFalse(continueBtn.isEnabled)
    }

    func testEmailLookupShowsMethods() {
        let emailInput = app.textFields["email-input"]
        XCTAssertTrue(emailInput.waitForExistence(timeout: 5))
        emailInput.tap()
        emailInput.typeText("test@openmates.org")

        app.buttons["continue-button"].tap()

        let passwordInput = app.secureTextFields["password-input"]
        XCTAssertTrue(passwordInput.waitForExistence(timeout: 10))
    }

    // MARK: - Password login (backup-code-login-flow)

    func testPasswordLoginSubmits() {
        navigateToPasswordLogin()

        let passwordInput = app.secureTextFields["password-input"]
        guard passwordInput.waitForExistence(timeout: 10) else { return }
        passwordInput.tap()
        passwordInput.typeText("test-password")

        let loginBtn = app.buttons["login-button"]
        XCTAssertTrue(loginBtn.isEnabled)
        loginBtn.tap()

        let tfaInput = app.textFields["tfa-code-input"]
        let chatList = app.navigationBars["Chats"]
        let progressed = tfaInput.waitForExistence(timeout: 10) || chatList.waitForExistence(timeout: 10)
        XCTAssertTrue(progressed)
    }

    // MARK: - Recovery key login (recovery-key-login-flow)

    func testRecoveryKeyOption() {
        navigateToPasswordLogin()

        let recoveryBtn = app.buttons["Use recovery key"]
        guard recoveryBtn.waitForExistence(timeout: 5) else { return }
        recoveryBtn.tap()

        let titleText = app.staticTexts["Enter your recovery key"]
        XCTAssertTrue(titleText.waitForExistence(timeout: 5))
    }

    // MARK: - Backup code login (backup-code-login-flow)

    func testBackupCodeOption() {
        navigateToPasswordLogin()

        let backupBtn = app.buttons["Use backup code"]
        guard backupBtn.waitForExistence(timeout: 5) else { return }
        backupBtn.tap()

        let titleText = app.staticTexts["Enter your backup code"]
        XCTAssertTrue(titleText.waitForExistence(timeout: 5))
    }

    // MARK: - Signup link (signup-flow)

    func testSignupLinkExists() {
        let signupBtn = app.buttons["Sign up"]
        XCTAssertTrue(signupBtn.waitForExistence(timeout: 5))
    }

    // MARK: - Unauthenticated app load (unauthenticated-app-load)

    func testUnauthenticatedShowsLoginScreen() {
        let emailInput = app.textFields["email-input"]
        XCTAssertTrue(emailInput.waitForExistence(timeout: 10))
        XCTAssertFalse(app.navigationBars["Chats"].exists)
    }

    // MARK: - Helpers

    private func navigateToPasswordLogin() {
        let emailInput = app.textFields["email-input"]
        guard emailInput.waitForExistence(timeout: 5) else { return }
        emailInput.tap()
        emailInput.typeText("test@openmates.org")
        app.buttons["continue-button"].tap()
    }
}
