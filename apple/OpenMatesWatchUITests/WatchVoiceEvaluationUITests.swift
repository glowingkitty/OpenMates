// Public routing must never expose the development paid evaluation entry.
import XCTest

@MainActor
final class WatchVoiceEvaluationUITests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.input-actions,video-call.privacy
    func testSignedOutSettingsCannotExposeOrStartPaidEvaluation() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-guest"]
        app.launch()
        XCTAssertTrue(app.buttons["watch-chat-settings-button"].waitForExistence(timeout: 10))
        app.buttons["watch-chat-settings-button"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["watch-guest-settings"].waitForExistence(timeout: 3))
        XCTAssertFalse(app.buttons["watch-settings-voice-hardware-probe"].exists)
        XCTAssertFalse(app.buttons["watch-voice-evaluation-start"].exists)
        XCTAssertFalse(app.descendants(matching: .any)["watch-voice-evaluation"].exists)
    }
}
