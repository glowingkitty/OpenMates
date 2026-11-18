// Voice-call start/end transcript notices rendered by the production view in the
// local Debug component preview; no account. Screenshots pair with web
// /dev/preview ChatMessage voice-call notice states.
import XCTest

@MainActor
final class VoiceCallEventNoticePreviewUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=video-call.chat.call-events
    func testStartedAndEndedNoticesRenderWebTextAndTime() {
        for (variant, id, text) in [("voice-call-started", "voice-call-event-notice-started", "You started a voice call"),
                                    ("voice-call-ended", "voice-call-event-notice-ended", "You ended a voice call")] {
            let app = launch(variant)
            let notice = app.descendants(matching: .any).matching(identifier: id).firstMatch
            XCTAssertTrue(notice.waitForExistence(timeout: 10), "Missing \(id)")
            XCTAssertTrue(notice.label.contains(text), "Unexpected notice text: \(notice.label)")
            XCTAssertTrue(notice.label.contains(" – "), "Notice must append the local call time like web")
            XCTAssertGreaterThan(notice.frame.height, 0)
            let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
            attachment.name = "Voice call notice \(variant)"; attachment.lifetime = .keepAlways; add(attachment)
            app.terminate()
        }
    }

    private func launch(_ variant: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "message", "--dev-preview-variant", variant,
            "--dev-preview-theme", "light", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        XCTAssertTrue(app.descendants(matching: .any).matching(identifier: "dev-preview-root").firstMatch
            .waitForExistence(timeout: 10))
        return app
    }
}
