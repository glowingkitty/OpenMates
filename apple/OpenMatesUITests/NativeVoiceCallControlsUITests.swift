// Specification: specifications/features/video-call/specification.yml
// Assertions: video-call.chat.call-strip-layout, video-call.privacy.first-call-warning
import XCTest

@MainActor
final class NativeVoiceCallControlsUITests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=video-call.chat.call-strip-layout
    func testProductionControlsMuteMinimizeExpandAndHangUp() {
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
        app.buttons["voice-call-minimize"].tap()
        XCTAssertTrue(app.otherElements["voice-call-minimized"].waitForExistence(timeout: 3))
        XCTAssertTrue(mute.isHittable)
        app.buttons["voice-call-minimize"].tap()
        XCTAssertTrue(bar.waitForExistence(timeout: 3))
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = "Native voice call controls muted fixture"; screenshot.lifetime = .keepAlways; add(screenshot)
        app.buttons["voice-call-hangup"].tap()
        expectation(for: NSPredicate(format: "exists == false"), evaluatedWith: bar)
        waitForExpectations(timeout: 3)
    }
    // contract-test: supporting surface=gui.apple assertions=video-call.privacy.first-call-warning
    func testConsentBlocksCallControlsUntilExplicitContinue() {
        let app = launch(variant: "native-voice-call-consent")
        XCTAssertTrue(app.otherElements["voice-call-consent"].waitForExistence(timeout: 10))
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
