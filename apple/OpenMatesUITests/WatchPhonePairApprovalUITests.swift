// Synthetic GUI proof exercises production iPhone approval controls and bridge.
// It does not prove real WCSession/APNs, account auth or backend PAKE.
import XCTest
import UIKit

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

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.iphone-first-fallback,apple-watch.pairing.private-session,settings-ui.navigation.parent-return,settings-ui.parity.web-apple-shell
    func testConnectedDevicesBackRetainsRequestAndCancelDenies() {
        let app = launch()
        let initialEvidence = XCTAttachment(screenshot: app.screenshot())
        initialEvidence.name = "Watch approval mounted in portrait Settings parent"
        initialEvidence.lifetime = .keepAlways
        add(initialEvidence)
        XCTAssertTrue(app.scrollViews["settings-watch-pair-page"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.otherElements["settings-banner-shell"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.buttons.matching(identifier: "settings-destination-back").count, 1)
        let breadcrumb = app.buttons["settings-destination-back"]
        XCTAssertTrue(breadcrumb.label.contains("Active Sessions"))
        XCTAssertFalse(breadcrumb.label.contains("settings.sessions"))
        let watchIcon = app.images["settings-banner-symbol-applewatch"]
        XCTAssertTrue(watchIcon.waitForExistence(timeout: 5))
        XCTAssertNotNil(UIImage(systemName: "applewatch"), "The exact rendered Watch symbol must exist")
        XCTAssertGreaterThan(watchIcon.frame.width, 0)
        XCTAssertGreaterThan(watchIcon.frame.height, 0)
        XCTAssertTrue(app.otherElements["settings-banner-shell"].frame.contains(watchIcon.frame))
        XCTAssertFalse(app.buttons["settings-account-subpage-back"].exists)
        tap(app.buttons["settings-destination-back"], app)
        XCTAssertTrue(app.descendants(matching: .any).matching(identifier: "settings-connected-devices-content").firstMatch.waitForExistence(timeout: 5))
        XCTAssertEqual(app.staticTexts["fixture-pair-cancellations"].label, "0")
        tap(app.buttons["settings-sessions-watch-pair-row"], app)
        XCTAssertTrue(app.buttons["watch-pair-approve-button"].isHittable)
        let evidence = XCTAttachment(screenshot: app.screenshot())
        evidence.name = "Watch approval reopened within Connected devices"
        evidence.lifetime = .keepAlways
        add(evidence)
        tap(app.buttons["watch-pair-cancel-button"], app)
        waitForLabel("empty", "fixture-pair-buffer", app)
        XCTAssertTrue(app.staticTexts["fixture-pair-dismissed"].waitForExistence(timeout: 5))
        waitForLabel("1", "fixture-pair-cancellations", app)
    }

    private func launch() -> XCUIApplication {
        XCUIDevice.shared.orientation = .portrait
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "login", "--dev-preview-variant", "watch-pair-approval",
                               "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let portrait = NSPredicate { _, _ in
            let frame = app.windows.firstMatch.frame
            return frame.width > 0 && frame.height > frame.width
        }
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: portrait, object: nil)], timeout: 5), .completed,
                       "Mount the fixture only after its window returns to portrait geometry")
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
