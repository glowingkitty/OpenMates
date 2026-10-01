import XCTest

@MainActor
final class PublicAssistantSpeechParityUITests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testPublicSpeakRevealsPlayerAndSupportsChapterPauseResumeClose() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "composer", "--dev-preview-variant", "assistant-speech-public",
            "--dev-preview-theme", "light", "--ui-test-embed-presentation", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let speak = app.buttons["assistant-message-speak"]
        XCTAssertTrue(speak.waitForExistence(timeout: 10))
        XCTAssertTrue(speak.isHittable)
        XCTAssertFalse(app.otherElements["assistant-speech-player"].exists)
        speak.tap()
        let player = app.otherElements["assistant-speech-player"]
        XCTAssertTrue(player.waitForExistence(timeout: 5))
        let primary = app.buttons["assistant-speech-primary-control"]
        waitForPlayback("playing", primaryLabel: "Pause voice response", player: player, primary: primary)
        primary.tap()
        waitForPlayback("paused", primaryLabel: "Play voice response", player: player, primary: primary)
        let close = app.buttons["assistant-speech-close"]
        XCTAssertTrue(close.isHittable)
        let chapter = app.staticTexts["assistant-speech-current-chapter"]
        XCTAssertEqual(chapter.label, "Part 1")
        app.buttons["assistant-speech-next-chapter"].tap()
        let selected = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "Part 2"), object: chapter)
        XCTAssertEqual(XCTWaiter.wait(for: [selected], timeout: 6), .completed)
        XCTAssertEqual(chapter.label, "Part 2")
        waitForPlayback("playing", primaryLabel: "Pause voice response", player: player, primary: primary)
        XCTAssertFalse(close.exists)
        let capture = XCTAttachment(screenshot: app.screenshot())
        capture.name = "Public immutable speech playback controls"; capture.lifetime = .keepAlways; add(capture)
        primary.tap()
        waitForPlayback("paused", primaryLabel: "Play voice response", player: player, primary: primary)
        primary.tap()
        waitForPlayback("playing", primaryLabel: "Pause voice response", player: player, primary: primary)
        XCTAssertEqual(chapter.label, "Part 2")
        primary.tap()
        waitForPlayback("paused", primaryLabel: "Play voice response", player: player, primary: primary)
        XCTAssertTrue(close.waitForExistence(timeout: 3))
        XCTAssertTrue(close.isHittable)
        close.tap()
        expectation(for: NSPredicate(format: "exists == false"), evaluatedWith: player)
        waitForExpectations(timeout: 3)
        XCTAssertFalse(player.exists)
    }

    private func waitForPlayback(_ status: String, primaryLabel: String,
                                 player: XCUIElement, primary: XCUIElement) {
        let state = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", status), object: player)
        let label = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", primaryLabel), object: primary)
        XCTAssertEqual(XCTWaiter.wait(for: [state, label], timeout: 6), .completed)
        XCTAssertEqual(player.value as? String, status)
        XCTAssertEqual(primary.label, primaryLabel)
    }
}
