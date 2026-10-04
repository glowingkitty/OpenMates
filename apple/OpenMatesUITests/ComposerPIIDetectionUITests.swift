// Real native editor/coordinator orchestration with explicitly stubbed model spans.
// No weights, private account, network inference, or model-quality claims.
import XCTest

@MainActor
final class ComposerPIIDetectionUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=pii.apple.enhanced-local-detection,pii.composer.detect-redact-exclude
    func testExactNativeHighlightsExclusionAndImmutableVerificationPreserveLaterTyping() {
        let app = launch()
        let receipt = app.staticTexts["composer-pii-fixture-receipt"]
        wait(receipt, contains: "exact=true;matches=2;excluded=0;mode=enhanced")
        let editor = app.descendants(matching: .any).matching(identifier: "message-editor").firstMatch
        XCTAssertTrue(editor.waitForExistence(timeout: 5) && editor.isHittable)
        attach("Real editor exact highlighting with stubbed model spans")
        let verify = app.buttons["composer-pii-fixture-verify"]
        XCTAssertTrue(verify.isEnabled && verify.isHittable)
        verify.tap()
        let action = app.staticTexts["composer-pii-fixture-action"]
        wait(action, contains: "verifying")
        XCTAssertFalse(verify.isEnabled, "The real final verification must keep the send action busy")
        editor.tap()
        editor.typeText(" later typing")
        let typed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value CONTAINS %@", "later typing"), object: editor)
        XCTAssertEqual(XCTWaiter.wait(for: [typed], timeout: 5), .completed)
        app.buttons["composer-pii-fixture-release"].tap()
        wait(action, contains: "completed;mappings=2")
        XCTAssertTrue((editor.value as? String)?.contains("later typing") == true)
        let redacted = app.staticTexts["composer-pii-fixture-redacted"]
        XCTAssertFalse(redacted.label.contains("later typing"), "The final result belongs to the earlier immutable document")
        XCTAssertFalse(redacted.label.contains("Ada Lovelace"))
        XCTAssertFalse(redacted.label.contains("ada@example.test"))
        wait(receipt, contains: "exact=true;matches=2;excluded=0;mode=enhanced")
        // Tap the first highlighted glyph through the actual TextKit gesture,
        // rather than exposing a fixture-only exclusion control.
        editor.coordinate(withNormalizedOffset: .zero).withOffset(CGVector(dx: 30, dy: 23)).tap()
        wait(receipt, contains: "exact=true;matches=1;excluded=1;mode=enhanced")
        attach("Real highlighted text exclusion after final verification")
        app.buttons["composer-pii-fixture-toggle"].tap()
        wait(receipt, contains: "exact=false;matches=0;excluded=1")
        XCTAssertTrue((editor.value as? String)?.contains("later typing") == true)
    }

    // contract-test: supporting surface=gui.apple assertions=pii.apple.enhanced-local-detection
    func testCancelledFinalKeepsOwnershipUntilHeldNativeKernelDrains() {
        let app = launch()
        wait(app.staticTexts["composer-pii-fixture-receipt"], contains: "mode=enhanced")
        let verify = app.buttons["composer-pii-fixture-verify"]
        verify.tap()
        let cancel = app.buttons["composer-pii-fixture-cancel"]
        XCTAssertTrue(cancel.waitForExistence(timeout: 5) && cancel.isEnabled && cancel.isHittable)
        cancel.tap()
        let action = app.staticTexts["composer-pii-fixture-action"]
        wait(action, contains: "cancelling")
        XCTAssertFalse(verify.isEnabled, "Task cancellation must not force a running native operation to appear finished")
        XCTAssertTrue(cancel.exists)
        attach("Final cancellation retains the held native owner")
        app.buttons["composer-pii-fixture-release"].tap()
        wait(action, contains: "cancelled")
        XCTAssertTrue(verify.isEnabled)
        XCTAssertFalse(cancel.exists)
        XCTAssertEqual(app.staticTexts["composer-pii-fixture-redacted"].label, "not-verified")
    }

    private func launch() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "composer", "--dev-preview-variant", "pii",
            "--dev-preview-theme", "light", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        XCTAssertTrue(app.staticTexts["composer-pii-fixture-label"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["composer-pii-fixture-label"].label.contains("stub inference"))
        return app
    }
    private func wait(_ element: XCUIElement, contains value: String) {
        XCTAssertTrue(element.waitForExistence(timeout: 5))
        let expectation = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label CONTAINS %@", value), object: element)
        XCTAssertEqual(XCTWaiter.wait(for: [expectation], timeout: 5), .completed)
    }
    private func attach(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
    }
}
