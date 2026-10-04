// Production memory CTA and header with synthetic encrypted in-process transport.
import XCTest

@MainActor
final class NativeEmbedMemoryActionUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=app-memories.surface.semantic-parity
    func testAddPendingForgetAndRemovalUseProductionHeaderAt320Points() {
        let app = launch("action-memory")
        let button = app.buttons["save-embed-cta"].firstMatch
        XCTAssertTrue(button.waitForExistence(timeout: 5))
        wait(button, predicate: "enabled == true AND label == %@", argument: "Add memory")
        assertHeaderBounds(app: app, button: button)
        XCTAssertTrue(button.isHittable); button.tap()
        wait(button, predicate: "enabled == false AND label == %@", argument: "Add memory")
        wait(button, predicate: "enabled == true AND label == %@", argument: "Forget")
        assertHeaderBounds(app: app, button: button)
        screenshot("memory-forget-header-320")
        XCTAssertTrue(button.isHittable); button.tap()
        wait(button, predicate: "enabled == false AND label == %@", argument: "Forget")
        wait(button, predicate: "enabled == true AND label == %@", argument: "Add memory")
        XCTAssertFalse(app.descendants(matching: .any)["save-embed-error"].firstMatch.exists)
    }

    // contract-test: supporting surface=gui.apple assertions=app-memories.surface.semantic-parity
    func testSaveErrorRetainsAddLabelAndRetryThenSucceeds() {
        let app = launch("action-memory-error")
        let button = app.buttons["save-embed-cta"].firstMatch
        XCTAssertTrue(button.waitForExistence(timeout: 5))
        wait(button, predicate: "enabled == true AND label == %@", argument: "Add memory")
        button.tap()
        let error = app.descendants(matching: .any)["save-embed-error"].firstMatch
        XCTAssertTrue(error.waitForExistence(timeout: 5))
        wait(button, predicate: "enabled == true AND label == %@", argument: "Add memory")
        XCTAssertTrue(button.isHittable); screenshot("memory-error-retry")
        button.tap()
        wait(button, predicate: "enabled == true AND label == %@", argument: "Forget")
        XCTAssertTrue(error.waitForNonExistence(timeout: 5))
    }

    private func assertHeaderBounds(app: XCUIApplication, button: XCUIElement) {
        let canvas = app.descendants(matching: .any)["dev-embed-memory-action-fixture"].firstMatch
        let provider = app.buttons["external-provider-cta"].firstMatch
        XCTAssertTrue(canvas.exists); XCTAssertTrue(provider.exists); XCTAssertTrue(provider.isHittable)
        XCTAssertEqual(canvas.frame.width, 320, accuracy: 1)
        for control in [button, provider] {
            XCTAssertGreaterThanOrEqual(control.frame.minX, canvas.frame.minX - 1)
            XCTAssertLessThanOrEqual(control.frame.maxX, canvas.frame.maxX + 1)
            XCTAssertGreaterThan(control.frame.height, 0)
        }
        XCTAssertFalse(button.frame.intersects(provider.frame), "Header actions must have separate hit regions")
    }
    private func wait(_ element: XCUIElement, predicate: String, argument: String) {
        let expectation = XCTNSPredicateExpectation(predicate: NSPredicate(format: predicate, argument), object: element)
        XCTAssertEqual(XCTWaiter.wait(for: [expectation], timeout: 5), .completed)
    }
    private func launch(_ variant: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "message", "--dev-preview-variant", variant, "--dev-preview-width", "320", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch(); return app
    }
    private func screenshot(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
    }
}
