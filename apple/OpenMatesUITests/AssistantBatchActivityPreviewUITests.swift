// Recorded local fixture exercises the production message/activity/batch views.
import XCTest

@MainActor
final class AssistantBatchActivityPreviewUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }
    // contract-test: supporting surface=gui.apple assertions=chats.streaming.progressive-presentation,chats.rendering.assistant-document-convergence,chats.surface.semantic-parity
    func testDistinctBatchProgressAndLateChildHistoryKeepTheAuthoredParagraphMounted() {
        let app = launch()
        let prefix = element(app, "progressive-block-batch-fixture-response:block:0")
        XCTAssertTrue(prefix.waitForExistence(timeout: 10))
        let mount = prefix.label
        let probe = element(app, "progressive-render-state")
        let parsed = field("parsed", from: probe.label)
        count(2, id: "sub-chat-card", app: app)
        count(0, id: "focus-mode-bar", app: app)
        count(0, id: "sub-chat-status-completed", app: app)
        app.buttons["dev-batch-foreign"].tap()
        count(2, id: "sub-chat-card", app: app)
        count(0, id: "sub-chat-status-completed", app: app)
        XCTAssertEqual(prefix.label, mount)
        app.buttons["dev-batch-complete-first"].tap()
        count(1, id: "sub-chat-card", app: app)
        XCTAssertTrue(app.staticTexts["Second batch child"].exists)
        XCTAssertFalse(app.staticTexts["First batch child"].exists)
        XCTAssertEqual(prefix.label, mount)
        app.buttons["dev-batch-run-second"].tap()
        count(1, id: "sub-chat-card", app: app)
        XCTAssertFalse(app.staticTexts["First batch child"].exists, "A later batch cannot revive the earlier completed batch")
        app.buttons["dev-batch-hydrate-second"].tap()
        count(0, id: "sub-chat-card", app: app)
        XCTAssertTrue(element(app, "assistant-activity-body").exists, "The skill remains live after both batches settle")
        XCTAssertEqual(prefix.label, mount)
        XCTAssertEqual(field("parsed", from: probe.label), parsed, "Status/store hydration must not reparse authored Markdown")
        app.buttons["dev-batch-reflow"].tap()
        XCTAssertEqual(prefix.label, mount)
        screenshot("Exact batch completion removes settled cards while the skill and authored paragraph remain mounted")
        let toggle = app.buttons["assistant-activity-toggle"].firstMatch
        toggle.tap(); XCTAssertTrue(element(app, "assistant-activity-body").waitForNonExistence(timeout: 5))
        toggle.tap(); count(2, id: "sub-chat-card", app: app)
        count(2, id: "sub-chat-status-completed", app: app)
        count(1, id: "focus-mode-bar", app: app)
        XCTAssertEqual(prefix.label, mount)
        screenshot("Manual disclosure restores both settled batches and Focus acknowledgement")
    }
    private func launch() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "message", "--dev-preview-variant", "response-batches",
            "--dev-preview-theme", "light", "--ui-test-progressive-render", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        XCTAssertTrue(element(app, "dev-preview-root").waitForExistence(timeout: 10))
        return app
    }
    private func element(_ app: XCUIApplication, _ id: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: id).firstMatch
    }
    private func count(_ expected: Int, id: String, app: XCUIApplication) {
        let query = app.descendants(matching: .any).matching(identifier: id)
        let expectation = XCTNSPredicateExpectation(predicate: NSPredicate(format: "count == %d", expected), object: query)
        XCTAssertEqual(XCTWaiter.wait(for: [expectation], timeout: 5), .completed)
    }
    private func field(_ name: String, from value: String) -> String? {
        value.split(separator: ";").first { $0.hasPrefix(name + "=") }.map { String($0.dropFirst(name.count + 1)) }
    }
    private func screenshot(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
    }
}
