// Manual snapshots drive real production message + citation/fullscreen views.
// No account credentials, backend or synthetic timing sleeps are needed.
import XCTest

@MainActor
final class ProgressiveMessagePreviewUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }
    override func tearDownWithError() throws {
        if let testRun, testRun.failureCount > 0 { screenshot("Progressive message failure") }
        try super.tearDownWithError()
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testParagraphsAndCitationRenderBeforeFinalAndKeepTheirMountedPrefix() throws {
        let app = launch("streaming")
        let probe = element(app, "progressive-render-state")
        XCTAssertTrue(probe.waitForExistence(timeout: 10))
        assertState("blocks=1;", app: app)
        assertState("streaming=true", app: app)
        let firstBlock = element(app, "progressive-block-progressive-fixture-0:block:0")
        XCTAssertTrue(firstBlock.waitForExistence(timeout: 5))
        let originalMount = firstBlock.label
        XCTAssertFalse(originalMount.isEmpty)
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@",
            "The first paragraph is available")).firstMatch.exists)
        app.buttons["dev-stream-next"].tap()
        assertState("blocks=2;", app: app)
        XCTAssertFalse(app.buttons["Berlin guide"].exists, "An unfinished citation is not a live target")
        app.buttons["dev-stream-next"].tap()
        assertState("streaming=true", app: app)
        XCTAssertFalse(app.buttons["Berlin guide"].exists, "A source must hydrate before it becomes clickable")
        let parsedBeforeHydration = field("parsed", from: probe.label)
        app.buttons["dev-stream-hydrate"].tap()
        let citation = app.buttons["Berlin guide"].firstMatch
        XCTAssertTrue(citation.waitForExistence(timeout: 5))
        XCTAssertEqual(field("parsed", from: probe.label), parsedBeforeHydration)
        XCTAssertEqual(firstBlock.label, originalMount)
        citation.tap()
        let fullscreen = element(app, "dev-stream-fullscreen")
        XCTAssertTrue(fullscreen.waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Top 10 Restaurants in Berlin - Local Guide"].firstMatch.waitForExistence(timeout: 5))
        screenshot("Citation opened while the message is streaming")
        let minimize = app.buttons["embed-minimize"].firstMatch
        XCTAssertTrue(minimize.isHittable)
        minimize.tap()
        XCTAssertTrue(fullscreen.waitForNonExistence(timeout: 5))
        XCTAssertEqual(firstBlock.label, originalMount)
        app.buttons["dev-stream-reflow"].tap()
        XCTAssertTrue(citation.isHittable)
        XCTAssertEqual(firstBlock.label, originalMount, "Changing width must reflow the existing paragraph")
        XCTAssertEqual(field("parsed", from: probe.label), parsedBeforeHydration)
        app.buttons["dev-stream-next"].tap()
        assertState("blocks=3;", app: app)
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@",
            "A third paragraph arrives")).firstMatch.exists)
        assertState("streaming=true", app: app)
        screenshot("Three production paragraphs and live citation before finalization")
        let ids = field("ids", from: probe.label)
        app.buttons["dev-stream-finalize"].tap()
        assertState("streaming=false", app: app)
        XCTAssertEqual(field("ids", from: probe.label), ids)
        XCTAssertEqual(firstBlock.label, originalMount, "Finalization must not remount the previously visible prefix")
        XCTAssertTrue(citation.exists)
        app.buttons["dev-stream-reset"].tap()
        XCTAssertTrue(element(app, "progressive-block-progressive-fixture-1:block:0").waitForExistence(timeout: 5))
        XCTAssertFalse(firstBlock.exists, "A new message identity must discard the old mounted state")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testLongParagraphRetainsBothReferencesAndOpensItsLastSourceDuringStreaming() {
        let app = launch("streaming-long")
        app.buttons["dev-stream-hydrate"].tap()
        let first = app.buttons["First Berlin guide"].firstMatch
        XCTAssertTrue(first.waitForExistence(timeout: 5))
        let last = app.buttons["Last Berlin guide"].firstMatch
        XCTAssertTrue(last.waitForExistence(timeout: 5), "References must survive the former 3,000-character cutoff")
        let scroll = element(app, "dev-stream-scroll")
        for _ in 0..<18 {
            if last.isHittable { break }
            scroll.swipeUp()
        }
        XCTAssertTrue(last.isHittable)
        assertState("streaming=true", app: app)
        last.tap()
        XCTAssertTrue(element(app, "dev-stream-fullscreen").waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Top 10 Restaurants in Berlin - Local Guide"].firstMatch.waitForExistence(timeout: 5))
        screenshot("Long paragraph final citation remains interactive during streaming")
        app.buttons["embed-minimize"].firstMatch.tap()
        XCTAssertTrue(element(app, "dev-stream-fullscreen").waitForNonExistence(timeout: 5))
        XCTAssertTrue(last.exists)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testReducedMotionUsesTheSameProgressiveBlocksWithoutFade() {
        let app = launch("streaming-reduced-motion")
        assertState("fade=none", app: app)
        app.buttons["dev-stream-next"].tap()
        assertState("blocks=2;", app: app)
        assertState("fade=none", app: app)
        app.buttons["dev-stream-finalize"].tap()
        assertState("streaming=false", app: app)
    }

    private func launch(_ variant: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "message", "--dev-preview-variant", variant,
            "--dev-preview-theme", "light", "--ui-test-progressive-render",
            "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let root = element(app, "dev-preview-root")
        XCTAssertTrue(root.waitForExistence(timeout: 10))
        XCTAssertEqual(root.value as? String, "auth=not-started;store=detached;socket=disconnected")
        return app
    }
    private func element(_ app: XCUIApplication, _ id: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: id).firstMatch
    }
    private func assertState(_ fragment: String, app: XCUIApplication,
                             file: StaticString = #filePath, line: UInt = #line) {
        let probe = element(app, "progressive-render-state")
        let expectation = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label CONTAINS %@", fragment), object: probe)
        XCTAssertEqual(XCTWaiter.wait(for: [expectation], timeout: 5), .completed, file: file, line: line)
    }
    private func field(_ key: String, from value: String) -> String? {
        value.split(separator: ";").first { $0.hasPrefix(key + "=") }.map { String($0.dropFirst(key.count + 1)) }
    }
    nonisolated private func screenshot(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
