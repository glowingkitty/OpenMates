import XCTest

@MainActor
final class AssistantSpeechPlayerParityUITests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testPlayerPausesResumesAndClosesWithProductionControls() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "composer", "--dev-preview-variant", "assistant-speech", "--dev-preview-theme", "light", "--ui-test-embed-presentation", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let player = app.otherElements["assistant-speech-player"]
        XCTAssertTrue(player.waitForExistence(timeout: 10))
        let primary = app.buttons["assistant-speech-primary-control"]
        XCTAssertTrue(primary.isHittable)
        waitForPlayback("playing", primaryLabel: "Pause voice response", player: player, primary: primary)
        XCTAssertEqual(primary.label, "Pause voice response")
        XCTAssertEqual(player.frame.height, app.frame.width <= 730 ? 92 : 82, accuracy: 1)
        XCTAssertEqual(primary.frame.width, 40, accuracy: 1)
        XCTAssertEqual(primary.frame.height, 40, accuracy: 1)
        let playing = XCTAttachment(screenshot: app.screenshot())
        playing.name = "Assistant speech playing canonical chapter"
        playing.lifetime = .keepAlways
        add(playing)
        primary.tap()
        waitForPlayback("paused", primaryLabel: "Play voice response", player: player, primary: primary)
        XCTAssertEqual(primary.label, "Play voice response")
        let close = app.buttons["assistant-speech-close"]
        XCTAssertTrue(close.isHittable)
        primary.tap()
        waitForPlayback("playing", primaryLabel: "Pause voice response", player: player, primary: primary)
        XCTAssertEqual(primary.label, "Pause voice response")
        XCTAssertFalse(close.exists)
        primary.tap()
        waitForPlayback("paused", primaryLabel: "Play voice response", player: player, primary: primary)
        XCTAssertTrue(close.waitForExistence(timeout: 3))
        XCTAssertTrue(close.isHittable)
        close.tap()
        expectation(for: NSPredicate(format: "exists == false"), evaluatedWith: player)
        waitForExpectations(timeout: 3)
        XCTAssertFalse(player.exists)
    }
    // contract-test: supporting surface=gui.apple assertions=assistant-speech.surface.semantic-parity
    func testSelectingPendingChapterShowsLoadingAndHydratesWithoutLeavingThePlayer() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "composer", "--dev-preview-variant", "assistant-speech",
            "--dev-preview-theme", "light", "--ui-test-embed-presentation", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let player = app.otherElements["assistant-speech-player"]
        XCTAssertTrue(player.waitForExistence(timeout: 10))
        let next = app.buttons["assistant-speech-next-chapter"]
        XCTAssertTrue(next.isHittable)
        next.tap()
        XCTAssertEqual(app.staticTexts["assistant-speech-current-chapter"].label, "Optimization")
        XCTAssertTrue(app.staticTexts["assistant-speech-loading"].waitForExistence(timeout: 2))
        let loading = XCTAttachment(screenshot: app.screenshot())
        loading.name = "Assistant speech pending selected chapter"; loading.lifetime = .keepAlways; add(loading)
        let primary = app.buttons["assistant-speech-primary-control"]
        expectation(for: NSPredicate(format: "value == %@", "playing"), evaluatedWith: player)
        waitForExpectations(timeout: 6)
        XCTAssertTrue(primary.isHittable)
        let ready = XCTAttachment(screenshot: app.screenshot())
        ready.name = "Assistant speech hydrated selected chapter"; ready.lifetime = .keepAlways; add(ready)
        app.buttons["assistant-speech-previous-chapter"].tap()
        XCTAssertEqual(app.staticTexts["assistant-speech-current-chapter"].label, "Key considerations")
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
