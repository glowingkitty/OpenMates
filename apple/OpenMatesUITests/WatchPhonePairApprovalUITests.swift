// Synthetic GUI proof exercises production iPhone approval controls and bridge.
// It does not prove real WCSession/APNs, account auth or backend PAKE.
import XCTest

@MainActor
final class WatchPhonePairApprovalUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.iphone-first-fallback,apple-watch.pairing.private-session
    func testAcceptRetainsPendingUntilPINReceiptAndPAKECompletion() {
        let app = launch()
        tap(app.buttons["watch-pair-approve-button"], app)
        waitForLabel("1", "fixture-pair-authorizations", app)
        waitForLabel("pending", "fixture-pair-buffer", app)
        XCTAssertEqual(app.staticTexts["fixture-pair-sends"].label, "0")
        XCTAssertFalse(app.buttons["watch-pair-approve-button"].isEnabled)
        XCTAssertFalse(app.staticTexts["fixture-pair-dismissed"].exists)
        tap(app.buttons["fixture-pair-reachable-error"], app)
        let attempted = NSPredicate { _, _ in
            (Int(app.staticTexts["fixture-pair-sends"].label) ?? 0) > 0
        }
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: attempted, object: nil)], timeout: 5), .completed)
        XCTAssertEqual(app.staticTexts["fixture-pair-buffer"].label, "pending")
        XCTAssertEqual(app.staticTexts["fixture-pair-receipt"].label, "waiting")
        XCTAssertFalse(app.staticTexts["fixture-pair-dismissed"].exists)
        tap(app.buttons["fixture-pair-deliver"], app)
        waitForLabel("received", "fixture-pair-receipt", app)
        XCTAssertEqual(app.staticTexts["fixture-pair-authorizations"].label, "1")
        XCTAssertEqual(app.staticTexts["fixture-pair-buffer"].label, "pending")
        XCTAssertFalse(app.staticTexts["fixture-pair-dismissed"].exists)
        tap(app.buttons["fixture-pair-complete"], app)
        XCTAssertTrue(app.staticTexts["fixture-pair-dismissed"].waitForExistence(timeout: 5))
        waitForLabel("empty", "fixture-pair-buffer", app)
        XCTAssertEqual(app.staticTexts["fixture-pair-cancellations"].label, "0")
        let evidence = XCTAttachment(screenshot: app.screenshot())
        evidence.name = "Synthetic production bridge approval completes after receipt and exchange acknowledgement"
        evidence.lifetime = .keepAlways
        add(evidence)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.iphone-first-fallback,apple-watch.pairing.private-session
    func testExpiredOrLoggedOutApprovalNeverResendsPIN() {
        for action in ["fixture-pair-expire", "fixture-pair-logout", "fixture-pair-profile"] {
            let app = launch()
            tap(app.buttons["watch-pair-approve-button"], app)
            waitForLabel("pending", "fixture-pair-buffer", app)
            tap(app.buttons[action], app)
            waitForLabel("empty", "fixture-pair-buffer", app)
            tap(app.buttons["fixture-pair-deliver"], app)
            tap(app.buttons["fixture-pair-reachable-error"], app)
            XCTAssertEqual(app.staticTexts["fixture-pair-sends"].label, "0")
            XCTAssertFalse(app.staticTexts["fixture-pair-dismissed"].exists)
            XCTAssertEqual(app.staticTexts["fixture-pair-authorizations"].label, "1")
            app.terminate()
        }
    }

    private func launch() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "login", "--dev-preview-variant", "watch-pair-approval",
                               "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        XCTAssertTrue(app.staticTexts["fixture-pair-boundary"].waitForExistence(timeout: 5))
        return app
    }
    private func waitForLabel(_ label: String, _ id: String, _ app: XCUIApplication) {
        let element = app.staticTexts[id]
        XCTAssertTrue(element.waitForExistence(timeout: 5))
        let expected = NSPredicate(format: "label == %@", label)
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: expected, object: element)], timeout: 5), .completed)
    }
    private func tap(_ element: XCUIElement, _ app: XCUIApplication) {
        XCTAssertTrue(element.waitForExistence(timeout: 5))
        for _ in 0..<6 {
            if element.isHittable { break }
            app.scrollViews.firstMatch.swipeUp()
        }
        XCTAssertTrue(element.isHittable)
        element.tap()
    }
}
