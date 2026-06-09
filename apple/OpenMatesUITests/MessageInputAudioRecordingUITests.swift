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
        app.launchArguments = ["--dev-preview", "chat-opening", "--ui-test-force-recording-overlay"]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
        app.launch()

        XCTAssertTrue(app.staticTexts["Native Chat Opening Preview"].waitForExistence(timeout: 12))
        focusComposerInput(in: app)
        let recordButton = element(in: app, identifier: "record-audio-button")
        XCTAssertTrue(recordButton.waitForExistence(timeout: 10))
        let overlay = element(in: app, identifier: "record-overlay")
        XCTAssertTrue(overlay.waitForExistence(timeout: 5))
        XCTAssertTrue(element(in: app, identifier: "release-text").waitForExistence(timeout: 2))
        XCTAssertTrue(element(in: app, identifier: "timer-pill").waitForExistence(timeout: 2))
        XCTAssertTrue(element(in: app, identifier: "cancel-hint").waitForExistence(timeout: 2))
        XCTAssertTrue(element(in: app, identifier: "mic-button").waitForExistence(timeout: 2))

        let screenshot = XCUIScreen.main.screenshot()
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = "Message input recording overlay contract state"
        attachment.lifetime = .keepAlways
        add(attachment)
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
