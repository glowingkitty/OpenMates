// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.call-strip-layout, video-call.privacy.first-call-warning
import XCTest

@MainActor
final class NativeVoiceCallControlsUITests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.call-strip-layout
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
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.call-strip-layout
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
    // contract-test: direct surface=gui.apple assertions=video-call.chat.call-strip-layout
    func testCallStripSitsBelowHeaderAtRestAndPinsWithMoreAndCloseWhenScrolled() {
        let app = launch(variant: "native-voice-call-chat")
        let header = app.descendants(matching: .any)["chat-header-banner"]
        let bar = app.otherElements["voice-call-bar"]
        XCTAssertTrue(bar.waitForExistence(timeout: 10))
        XCTAssertTrue(header.exists)
        XCTAssertGreaterThanOrEqual(bar.frame.minY, header.frame.maxY - 0.5, "strip sits directly beneath the header at rest")
        XCTAssertLessThan(bar.frame.minY - header.frame.maxY, 24)
        XCTAssertFalse(app.buttons["voice-call-more"].exists)
        XCTAssertFalse(app.buttons["voice-call-close-chat"].exists)
        let restDuration = app.buttons["voice-call-return"]
        XCTAssertTrue(restDuration.exists)
        let restDurationWidth = restDuration.frame.width
        let rest = XCTAttachment(screenshot: app.screenshot())
        rest.name = "parity-strip-rest"; rest.lifetime = .keepAlways; add(rest)
        for _ in 0..<4 where !app.buttons["voice-call-more"].exists {
            app.swipeUp(velocity: .slow)
        }
        let more = app.buttons["voice-call-more"]
        XCTAssertTrue(more.waitForExistence(timeout: 5))
        let pinned = app.otherElements["voice-call-bar"]
        XCTAssertLessThan(pinned.frame.minY - app.windows.firstMatch.frame.minY, 140, "strip stays at the top of the viewport")
        let video = app.buttons["voice-call-video"], hangup = app.buttons["voice-call-hangup"]
        let close = app.buttons["voice-call-close-chat"]
        XCTAssertTrue(close.exists)
        XCTAssertLessThan(more.frame.maxX, video.frame.minX + 0.5, "More comes before Video")
        XCTAssertLessThan(hangup.frame.maxX, close.frame.minX + 0.5, "Close comes after Hang up")
        XCTAssertEqual(app.otherElements.matching(identifier: "voice-call-bar").count, 1, "controls are not duplicated")
        // Phone width: the pinned strip keeps the full duration readable (no "0…" truncation).
        let duration = app.buttons["voice-call-return"]
        XCTAssertTrue(duration.exists)
        XCTAssertGreaterThanOrEqual(duration.frame.width, restDurationWidth - 0.5,
            "duration keeps its full at-rest width while pinned")
        XCTAssertFalse(app.buttons["voice-call-screen-share"].exists, "screen share leaves the pinned strip unless a share runs")
        let fixed = XCTAttachment(screenshot: app.screenshot())
        fixed.name = "parity-strip-pinned"; fixed.lifetime = .keepAlways; add(fixed)
    }
    // contract-test: direct surface=gui.apple assertions=video-call.chat.fixed-binding
    func testHeaderPillReplacesBrandWhileBoundChatIsClosedAndReturnsToIt() {
        let app = launch(variant: "native-voice-call-header-pill")
        let pill = app.buttons["voice-call-pill"]
        XCTAssertTrue(pill.waitForExistence(timeout: 10))
        XCTAssertTrue(pill.isHittable)
        let header = app.descendants(matching: .any)["fixture-global-header"]
        XCTAssertTrue(header.exists)
        XCTAssertTrue(header.frame.contains(CGPoint(x: pill.frame.midX, y: pill.frame.midY)), "pill sits in the header brand slot")
        XCTAssertFalse(app.descendants(matching: .any)["fixture-header-brand"].exists, "pill replaces the brand mark")
        XCTAssertEqual(app.descendants(matching: .any)["voice-call-pill-timer"].label, "00:15")
        XCTAssertGreaterThanOrEqual(pill.frame.height, 40)
        XCTAssertFalse(app.otherElements["voice-call-bar"].exists, "no floating call bar while the pill shows")
        let shot = XCTAttachment(screenshot: app.screenshot())
        shot.name = "parity-header-pill-390"; shot.lifetime = .keepAlways; add(shot)
        pill.tap()
        XCTAssertTrue(app.descendants(matching: .any)["chat-header-banner"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.otherElements["voice-call-bar"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.otherElements.matching(identifier: "voice-call-bar").count, 1, "the chat strip takes over")
        XCTAssertTrue(app.descendants(matching: .any)["fixture-header-brand"].waitForExistence(timeout: 5), "brand returns")
        XCTAssertFalse(app.buttons["voice-call-pill"].exists)
        let returned = XCTAttachment(screenshot: app.screenshot())
        returned.name = "parity-header-pill-returned-390"; returned.lifetime = .keepAlways; add(returned)
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
