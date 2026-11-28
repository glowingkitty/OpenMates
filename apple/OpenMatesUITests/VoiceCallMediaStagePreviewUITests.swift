// Call media stage rendered by the production view in the local Debug component
// preview (message variants voice-call-media-*); no account. Real EmbedRecords
// go through the core stage policy, only the encrypted fetch is replaced.
// Screenshots pair with web /dev/preview voicecall/VoiceCallMedia.
import XCTest

@MainActor
final class VoiceCallMediaStagePreviewUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: direct surface=gui.apple assertions=video-call.video.generated-media-stage
    func testGeneratedResultsExpandStageWithAIBadgePagingAndCollapse() {
        let app = launch("voice-call-media-multiple")
        let stage = element(app, "voice-call-media")
        XCTAssertTrue(stage.waitForExistence(timeout: 10), "Missing call media stage")
        let image = element(app, "voice-call-generated-image")
        XCTAssertTrue(image.waitForExistence(timeout: 10), "A finished generated image is displayed")
        XCTAssertTrue(element(app, "voice-call-media-ai").exists, "AI icon at the top right")
        XCTAssertGreaterThan(stage.frame.height, 400, "A completed result expands the stage")
        let ai = element(app, "voice-call-media-ai")
        XCTAssertGreaterThan(ai.frame.midX, stage.frame.midX)
        XCTAssertLessThan(ai.frame.midY, stage.frame.midY)

        let previous = app.buttons["voice-call-media-previous"]
        let next = app.buttons["voice-call-media-next"]
        XCTAssertTrue(next.waitForExistence(timeout: 5), "Multiple outputs have previous/next controls")
        XCTAssertFalse(previous.isEnabled)
        XCTAssertTrue(next.isEnabled)
        XCTAssertTrue(app.staticTexts["1 / 2"].exists)
        attach("Call media stage first of two results")

        next.tap()
        XCTAssertTrue(app.staticTexts["2 / 2"].waitForExistence(timeout: 5))
        XCTAssertTrue(previous.isEnabled)
        XCTAssertFalse(next.isEnabled)
        attach("Call media stage second result")

        let expand = app.buttons["voice-call-media-expand"]
        XCTAssertTrue(expand.isHittable)
        XCTAssertGreaterThan(expand.frame.midX, stage.frame.midX, "Collapse control at the bottom right")
        XCTAssertGreaterThan(expand.frame.midY, stage.frame.midY)
        expand.tap()
        let collapsed = NSPredicate { _, _ in stage.frame.height < 120 }
        expectation(for: collapsed, evaluatedWith: stage)
        waitForExpectations(timeout: 3)
        XCTAssertTrue(element(app, "voice-call-generated-image").exists, "The result stays until the user returns to the camera")
        attach("Call media stage collapsed")
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.video.generated-media-stage
    func testSingleResultHasNoPaging() {
        let app = launch("voice-call-media-image")
        XCTAssertTrue(element(app, "voice-call-generated-image").waitForExistence(timeout: 10))
        XCTAssertFalse(app.buttons["voice-call-media-next"].exists)
        XCTAssertFalse(app.buttons["voice-call-media-previous"].exists)
        attach("Call media stage single result")
    }

    #if os(iOS)
    // Starts the production call audio on the Simulator microphone and speaker:
    // permission, voice-chat session, voice-processing engine, microphone and
    // playback taps, a played buffer. Build 100 crashed here on the first audio
    // callback (main-actor closures run on AVFoundation's audio threads).
    // contract-test: supporting surface=gui.apple assertions=video-call.audio.single-owner
    func testStartingCallAudioRunsAudioCallbacksWithoutCrashing() {
        addUIInterruptionMonitor(withDescription: "Microphone permission") { alert in
            let allow = alert.buttons.matching(NSPredicate(format: "label IN %@", ["Allow", "OK"])).firstMatch
            guard allow.exists else { return false }
            allow.tap(); return true
        }
        let app = launch("native-voice-call-audio-engine", component: "composer")
        let status = element(app, "voice-call-audio-engine-status")
        XCTAssertTrue(status.waitForExistence(timeout: 10))
        app.tap() // delivers a pending permission alert to the monitor
        let settled = NSPredicate { _, _ in
            let label = status.label
            return label.hasPrefix("running ") || label.hasPrefix("failed")
        }
        expectation(for: settled, evaluatedWith: status)
        waitForExpectations(timeout: 30)
        attach("Call audio engine after start: \(status.label)")
        XCTAssertEqual(app.state, .runningForeground, "Starting call audio must not crash the app")
        XCTAssertTrue(status.label.hasPrefix("running "), "Call audio started: \(status.label)")
        // A buffer was scheduled on the running engine without a crash. The
        // simulator on a hosted CI machine does not render output, so the
        // played-back completion may stay pending; the label records which.
        // NativeVoiceCallMeterTests runs that completion off the main thread.
        XCTAssertTrue(status.label.contains("playback "), "Playback was scheduled: \(status.label)")
        XCTAssertTrue(status.label.contains("with microphone input"),
                      "Microphone tap callbacks ran on the audio thread: \(status.label)")
    }
    #endif

    private func element(_ app: XCUIApplication, _ id: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: id).firstMatch
    }

    private func attach(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
    }

    private func launch(_ variant: String, component: String = "message") -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", component, "--dev-preview-variant", variant,
            "--dev-preview-theme", "light", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        XCTAssertTrue(app.descendants(matching: .any).matching(identifier: "dev-preview-root").firstMatch
            .waitForExistence(timeout: 10))
        return app
    }
}
