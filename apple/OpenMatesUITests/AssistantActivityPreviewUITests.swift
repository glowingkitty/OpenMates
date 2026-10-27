// Core production renderer recording targets; local Debug fixture, no account.
import XCTest

@MainActor
final class AssistantActivityPreviewUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }
    // contract-test: supporting surface=gui.apple assertions=chats.streaming.progressive-presentation,chats.rendering.assistant-document-convergence,chats.surface.semantic-parity
    func testConfirmedTransientHandoffAndSourcePositionDisclosureKeepParagraphIdentity() {
        let app = launch("response-activity")
        XCTAssertTrue(element(app, "assistant-response-transient").waitForExistence(timeout: 10))
        XCTAssertTrue(element(app, "assistant-transient-thinking").exists)
        XCTAssertFalse(element(app, "message-assistant").exists)
        app.buttons["dev-activity-next"].tap()
        XCTAssertTrue(element(app, "message-assistant").waitForExistence(timeout: 5))
        XCTAssertFalse(element(app, "assistant-response-transient").exists)
        let prefix = element(app, "progressive-block-activity-response:block:0")
        XCTAssertTrue(prefix.waitForExistence(timeout: 5))
        let mounted = prefix.label
        XCTAssertTrue(element(app, "assistant-activity-body").waitForExistence(timeout: 5))
        app.buttons.matching(identifier: "assistant-activity-toggle").element(boundBy: 0).tap()
        XCTAssertTrue(element(app, "assistant-activity-body").waitForNonExistence(timeout: 5))
        app.buttons["dev-activity-next"].tap()
        count(2, identifier: "assistant-activity-toggle", app: app)
        count(1, identifier: "assistant-activity-body", app: app)
        XCTAssertTrue(app.staticTexts["The first comparison is ready."].exists)
        XCTAssertEqual(prefix.label, mounted)
        app.buttons["dev-activity-reflow"].tap()
        XCTAssertEqual(prefix.label, mounted, "Reflow across the responsive branch keeps the mounted paragraph")
        app.buttons["dev-activity-next"].tap()
        count(0, identifier: "assistant-activity-body", app: app)
        XCTAssertEqual(prefix.label, mounted, "Finalization retains the authored paragraph identity")
        app.buttons.matching(identifier: "assistant-activity-toggle").element(boundBy: 0).tap()
        XCTAssertTrue(element(app, "loaded-memory-pill").waitForExistence(timeout: 5))
        app.buttons["loaded-memory-pill"].tap()
        XCTAssertTrue(element(app, "applied-memory-body").waitForExistence(timeout: 5))
        XCTAssertTrue(element(app, "applied-rule-revision").label.contains(String(repeating: "a", count: 64)))
        screenshot("Completed activities and exact applied Memory guide")
    }
    // contract-test: supporting surface=gui.apple assertions=chats.rendering.inline-entity-interaction,chats.surface.semantic-parity
    func testCompletedActivityKeepsTheRealSkillPreviewAndFullscreenAction() {
        let app = launch("response-activity")
        for _ in 0..<3 { app.buttons["dev-activity-next"].tap() }
        count(2, identifier: "assistant-activity-toggle", app: app)
        app.buttons.matching(identifier: "assistant-activity-toggle").element(boundBy: 0).tap()
        let preview = element(app, "embed-preview-preview-web-search-1")
        XCTAssertTrue(preview.waitForExistence(timeout: 5))
        let scroll = element(app, "dev-activity-scroll")
        for _ in 0..<6 { if preview.isHittable { break }; scroll.swipeUp() }
        XCTAssertTrue(preview.isHittable)
        preview.tap()
        XCTAssertTrue(element(app, "dev-activity-fullscreen").waitForExistence(timeout: 5))
        screenshot("Original skill fullscreen action retained inside activity disclosure")
        app.buttons["embed-minimize"].firstMatch.tap()
        XCTAssertTrue(element(app, "dev-activity-fullscreen").waitForNonExistence(timeout: 5))
    }
    // contract-test: supporting surface=gui.apple assertions=chats.streaming.progressive-presentation,chats.surface.semantic-parity
    func testReducedMotionRetainsLiveResponseAndAccessibleDisclosure() {
        let app = launch("response-activity-reduced-motion")
        XCTAssertTrue(element(app, "assistant-response-transient").waitForExistence(timeout: 10))
        app.buttons["dev-activity-next"].tap()
        let probe = element(app, "progressive-render-state")
        let expected = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label CONTAINS %@", "fade=none"), object: probe)
        XCTAssertEqual(XCTWaiter.wait(for: [expected], timeout: 5), .completed)
        XCTAssertTrue(element(app, "assistant-activity-body").waitForExistence(timeout: 5))
        screenshot("Reduced motion keeps the live response and activity disclosure")
    }
    private func launch(_ variant: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "message", "--dev-preview-variant", variant,
            "--dev-preview-theme", "light", "--ui-test-progressive-render", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        XCTAssertTrue(element(app, "dev-preview-root").waitForExistence(timeout: 10))
        return app
    }
    private func element(_ app: XCUIApplication, _ id: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: id).firstMatch
    }
    private func count(_ expected: Int, identifier: String, app: XCUIApplication) {
        let query = app.descendants(matching: .any).matching(identifier: identifier)
        let expectation = XCTNSPredicateExpectation(predicate: NSPredicate(format: "count == %d", expected), object: query)
        XCTAssertEqual(XCTWaiter.wait(for: [expectation], timeout: 5), .completed)
    }
    private func screenshot(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
    }
}
