// Web source: frontend/packages/ui/src/components/AssistantSpeechPlayer.svelte (assistant-speech-player testids)
// Specification: specifications/features/assistant-response-speech/specification.yml
// Assertions: assistant-speech.playback.pinned-full-response-waveform, assistant-speech.playback.deterministic-chapter-labels, assistant-speech.playback.single-queue-segment-control
import XCTest

@MainActor
final class AssistantSpeechBarParityUITests: XCTestCase {
    private func launch() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "composer", "--dev-preview-variant", "assistant-speech",
            "--dev-preview-theme", "light", "--ui-test-embed-presentation", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        return app
    }

    // contract-test: direct surface=gui.apple assertions=assistant-speech.playback.pinned-full-response-waveform,assistant-speech.playback.deterministic-chapter-labels
    func testSpeechBarIsPinnedAtTopWithWaveformPlayPauseAndCurrentChapter() {
        let app = launch()
        let bar = app.otherElements["assistant-speech-player"]
        XCTAssertTrue(bar.waitForExistence(timeout: 10))
        let window = app.windows.firstMatch.frame
        XCTAssertLessThan(bar.frame.minY - window.minY, 160, "bar is pinned at the top of the chat area")
        XCTAssertGreaterThan(bar.frame.width, window.width * 0.85, "bar spans the chat width")
        XCTAssertTrue(app.otherElements["assistant-speech-waveform"].exists)
        let primary = app.buttons["assistant-speech-primary-control"]
        XCTAssertTrue(primary.isHittable)
        XCTAssertEqual(primary.frame.midX, bar.frame.midX, accuracy: 40, "play/pause is centered over the waveform")
        XCTAssertEqual(app.staticTexts["assistant-speech-current-chapter"].label, "Key considerations")
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = "Assistant speech bar pinned at top"; shot.lifetime = .keepAlways; add(shot)
    }

    // contract-test: direct surface=gui.apple assertions=assistant-speech.playback.single-queue-segment-control
    func testSpeechBarPauseRevealsCloseAndChapterNavigationStaysInOneQueue() {
        let app = launch()
        let bar = app.otherElements["assistant-speech-player"]
        XCTAssertTrue(bar.waitForExistence(timeout: 10))
        XCTAssertTrue(app.buttons["assistant-speech-next-chapter"].isHittable)
        XCTAssertTrue(app.buttons["assistant-speech-previous-chapter"].isHittable)
        let primary = app.buttons["assistant-speech-primary-control"]
        XCTAssertTrue(primary.isHittable)
        primary.tap()
        XCTAssertTrue(app.buttons["assistant-speech-close"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.otherElements.matching(identifier: "assistant-speech-player").count, 1)
    }
}
