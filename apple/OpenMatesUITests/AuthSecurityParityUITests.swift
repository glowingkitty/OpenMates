// UI smoke coverage for native auth entry parity.
// Starts from a forced unauthenticated state and verifies public auth controls
// only. No credentials, recovery keys, backup codes, passkeys, or private account
// data are entered or captured.

import XCTest

@MainActor
final class AuthSecurityParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // contract-test: direct surface=gui.apple assertions=auth.login.method-convergence,auth.surface.first-party-boundary
    func testUnauthenticatedAuthEntryExposesLoginIdentifiers() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-open-login"]
        app.launch()

        let loginTab = app.buttons["auth-login-tab"]
        XCTAssertTrue(loginTab.waitForExistence(timeout: 15))
        loginTab.tap()

        XCTAssertTrue(app.buttons["auth-signup-tab"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.textFields["email-input"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["continue-button"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["stay-logged-in-toggle"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.tables.firstMatch.exists, "Auth product UI must not render default List/table chrome")

        attachScreenshot(name: "Unauthenticated auth entry identifiers")
    }

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
