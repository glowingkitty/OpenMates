import XCTest

final class PasskeyAssertionLifecycleUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence,auth.session.isolation
    func testManualPasskeyWaitsForAutomaticCancellationAndLeavingCancelsManualRequest() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "login", "--dev-preview-variant", "passkey-lifecycle",
            "--dev-preview-theme", "light", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let phase = app.staticTexts["fixture-passkey-phase"]
        waitForPhase("automatic-active", phase: phase)
        let passkey = app.buttons["login-passkey-option"]
        XCTAssertTrue(passkey.isHittable)
        passkey.tap()
        waitForPhase("automatic-cancelling", phase: phase)
        XCTAssertTrue(app.buttons["fixture-passkey-return"].isHittable)
        XCTAssertNotEqual(phase.label, "manual-active", "Manual OS request must wait for the previous callback")
        let acknowledgement = app.buttons["fixture-passkey-acknowledge-cancel"]
        XCTAssertTrue(acknowledgement.isHittable)
        acknowledgement.tap()
        waitForPhase("manual-active", phase: phase)
        app.buttons["fixture-passkey-return"].tap()
        waitForPhase("manual-cancelled", phase: phase)
        XCTAssertTrue(passkey.isHittable)
        passkey.tap()
        waitForPhase("manual-active", phase: phase)
        app.buttons["fixture-passkey-return"].tap()
        waitForPhase("manual-cancelled", phase: phase)
    }

    private func waitForPhase(_ expected: String, phase: XCUIElement) {
        XCTAssertTrue(phase.waitForExistence(timeout: 5))
        let predicate = NSPredicate(format: "label == %@", expected)
        let expectation = XCTNSPredicateExpectation(predicate: predicate, object: phase)
        XCTAssertEqual(XCTWaiter.wait(for: [expectation], timeout: 5), .completed)
    }
}
