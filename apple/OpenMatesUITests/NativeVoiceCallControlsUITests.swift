// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.call-strip-layout, video-call.privacy.first-call-warning
import XCTest

@MainActor
final class NativeVoiceCallControlsUITests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.call-strip-layout
    func testProductionControlsMuteAndHangUp() {
        let app = launch(variant: "native-voice-call")
        let bar = app.otherElements["voice-call-bar"]
        XCTAssertTrue(bar.waitForExistence(timeout: 10))
        XCTAssertEqual(bar.frame.height, 68, accuracy: 1)
        let mute = app.buttons["voice-call-mute"]
        XCTAssertEqual(mute.frame.width, 44, accuracy: 1)
        XCTAssertEqual(mute.label, "Mute")
        mute.tap()
        expectation(for: NSPredicate(format: "label == %@", "Unmute"), evaluatedWith: mute)
        waitForExpectations(timeout: 3)
        XCTAssertEqual(mute.value as? String, "Microphone muted")
        XCTAssertFalse(app.buttons["voice-call-minimize"].exists)
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = "Native voice call controls muted fixture"; screenshot.lifetime = .keepAlways; add(screenshot)
        app.buttons["voice-call-hangup"].tap()
        expectation(for: NSPredicate(format: "exists == false"), evaluatedWith: bar)
        waitForExpectations(timeout: 3)
    }
    // contract-test: supporting surface=gui.apple assertions=video-call.video.input-and-output,video-call.video.apple-screen-share
    func testLiveControlsShowVideoAndScreenShareForWebComparison() {
        let app = launch(variant: "native-voice-call")
        let bar = app.otherElements["voice-call-bar"]
        XCTAssertTrue(bar.waitForExistence(timeout: 10))
        let video = app.buttons["voice-call-video"]
        XCTAssertTrue(video.waitForExistence(timeout: 3))
        XCTAssertEqual(video.frame.width, 44, accuracy: 1)
        XCTAssertGreaterThanOrEqual(video.frame.minY, bar.frame.minY - 0.5)
        XCTAssertLessThanOrEqual(video.frame.maxY, bar.frame.maxY + 0.5)
        // Web grid order: video at the left edge, duration + waveform centered, hang-up at the right edge.
        let timer = app.buttons["voice-call-return"], mute = app.buttons["voice-call-mute"]
        let hangup = app.buttons["voice-call-hangup"]
        XCTAssertLessThan(video.frame.minX - bar.frame.minX, 20)
        XCTAssertLessThan(bar.frame.maxX - hangup.frame.maxX, 20)
        XCTAssertLessThan(timer.frame.maxX, mute.frame.minX + 0.5)
        // The duration + waveform group is centered: equal room on both sides of it.
        // The mic sits at the waveform's middle, so the waveform ends as far right of it as it starts left.
        let waveRight = mute.frame.midX + (mute.frame.midX - timer.frame.maxX)
        XCTAssertEqual(timer.frame.minX - bar.frame.minX, bar.frame.maxX - waveRight, accuracy: 12)
        #if os(iOS)
        let share = app.buttons["voice-call-screen-share"]
        XCTAssertTrue(share.waitForExistence(timeout: 3))
        XCTAssertEqual(share.frame.width, 44, accuracy: 1)
        XCTAssertLessThan(video.frame.maxX, share.frame.minX + 0.5)
        XCTAssertLessThan(share.frame.maxX, timer.frame.minX + 0.5)
        #endif
        let live = XCTAttachment(screenshot: app.screenshot())
        live.name = "parity-live-call-controls-390"; live.lifetime = .keepAlways; add(live)
    }
    // contract-test: supporting surface=gui.apple assertions=video-call.privacy.first-call-warning
    func testConsentBlocksCallControlsUntilExplicitContinue() {
        let app = launch(variant: "native-voice-call-consent")
        XCTAssertTrue(app.otherElements["voice-call-consent"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "Mistral")).firstMatch.exists)
        XCTAssertTrue(app.descendants(matching: .any)["voice-call-consent-terms"].isHittable)
        XCTAssertTrue(app.buttons["voice-call-consent-continue"].isHittable)
        app.buttons["voice-call-consent-continue"].tap()
        XCTAssertTrue(app.otherElements["voice-call-bar"].waitForExistence(timeout: 3))
        XCTAssertFalse(app.otherElements["voice-call-consent"].exists)
        // Fixture cannot prove saved profile consent or actual microphone order.
    }
    private func launch(variant: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "composer", "--dev-preview-variant", variant,
            "--dev-preview-theme", "light", "--dev-preview-width", "390",
            "--ui-test-disable-auth-cache", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch(); return app
    }
}
