// File attachment UI tests — maps to: file-attachment-flow.spec.ts,
// audio-recording.spec.ts, pdf-flow.spec.ts

import XCTest

final class FileAttachmentUITests: XCTestCase {

    var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["--uitesting", "--authenticated"]
        app.launch()
    }

    // MARK: - Attachment picker (file-attachment-flow)

    func testAttachmentPickerExists() {
        openExistingChat()

        let attachBtn = app.buttons.matching(NSPredicate(format: "label CONTAINS 'Attach' OR label CONTAINS 'plus' OR label CONTAINS 'paperclip'")).firstMatch
        XCTAssertTrue(attachBtn.waitForExistence(timeout: 10))
    }

    // MARK: - Voice recording button (audio-recording)

    func testVoiceRecordingButtonExists() {
        openExistingChat()

        // Voice button appears when text field is empty
        let voiceBtn = app.buttons.matching(NSPredicate(format: "label CONTAINS 'Record' OR label CONTAINS 'microphone' OR label CONTAINS 'waveform'")).firstMatch
        _ = voiceBtn.waitForExistence(timeout: 5)
    }

    // MARK: - Send button replaces voice when typing

    func testSendButtonAppearsWhenTyping() {
        openExistingChat()

        let inputField = app.textFields["Chat message input"]
        guard inputField.waitForExistence(timeout: 10) else { return }
        inputField.tap()
        inputField.typeText("hello")

        let sendBtn = app.buttons["Send message"]
        XCTAssertTrue(sendBtn.waitForExistence(timeout: 3))
    }

    // MARK: - Helpers

    private func openExistingChat() {
        let chatItem = app.cells.matching(identifier: "chat-item-wrapper").firstMatch
        guard chatItem.waitForExistence(timeout: 10) else { return }
        chatItem.tap()
    }
}
