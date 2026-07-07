// Message input audio recording parity coverage for Apple UI contracts.
// Exercises the real native composer record gesture inside the debug-only ChatView
// preview and asserts the same structural identifiers captured from web
// RecordAudio.svelte are exposed to XCUITest.

import XCTest

@MainActor
final class MessageInputAudioRecordingUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testRecordButtonAndForcedOverlayMatchContractStructure() throws {
        let app = XCUIApplication()

        app.launchArguments = ["--dev-preview", "chat-opening"]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
        app.launch()

        XCTAssertTrue(app.staticTexts["Native Chat Opening Preview"].waitForExistence(timeout: 12))
        focusComposerInput(in: app)
        XCTAssertTrue(element(in: app, identifier: "record-audio-button").waitForExistence(timeout: 10))

        app.terminate()

        app.launchArguments = ["--dev-preview", "chat-opening-recording"]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening-recording"
        app.launch()

        XCTAssertTrue(app.staticTexts["Native Chat Opening Preview"].waitForExistence(timeout: 12))
        XCTAssertTrue(element(in: app, identifier: "release-text").waitForExistence(timeout: 2))
        XCTAssertTrue(element(in: app, identifier: "timer-pill").waitForExistence(timeout: 2))
        XCTAssertTrue(element(in: app, identifier: "cancel-hint").waitForExistence(timeout: 2))
        XCTAssertTrue(app.staticTexts["Slide left to cancel"].waitForExistence(timeout: 2))
        XCTAssertFalse(app.staticTexts["Press ESC to cancel"].exists)
        XCTAssertTrue(element(in: app, identifier: "mic-button").waitForExistence(timeout: 2))

        let screenshot = XCUIScreen.main.screenshot()
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = "Message input recording overlay contract state"
        attachment.lifetime = .keepAlways
        add(attachment)

        app.terminate()

        app.launchArguments = ["--dev-preview", "chat-opening", "--ui-test-force-keyboard-recording-overlay"]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
        app.launchEnvironment["UI_TEST_FORCE_KEYBOARD_RECORDING_OVERLAY"] = "1"
        app.launch()

        XCTAssertTrue(app.staticTexts["Native Chat Opening Preview"].waitForExistence(timeout: 12))
        XCTAssertTrue(element(in: app, identifier: "cancel-hint").waitForExistence(timeout: 2))
        XCTAssertTrue(app.staticTexts["Press ESC to cancel"].waitForExistence(timeout: 2))
        XCTAssertFalse(app.staticTexts["Slide left to cancel"].exists)
    }

    private func element(in app: XCUIApplication, identifier: String) -> XCUIElement {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier == %@", identifier))
            .firstMatch
    }

    private func focusComposerInput(in app: XCUIApplication) {
        let textView = app.textViews.firstMatch
        let textField = app.textFields.firstMatch
        XCTAssertTrue(textView.exists || textField.exists)
        if textView.exists {
            textView.tap()
        } else {
            textField.tap()
        }
    }
}
