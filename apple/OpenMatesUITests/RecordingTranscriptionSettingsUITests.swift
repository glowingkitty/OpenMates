// Native-only settings interaction. No microphone, model inference or download is started.
import XCTest

@MainActor
final class RecordingTranscriptionSettingsUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible,message-input.privacy-context,message-input.recording.lifecycle
    func testIncludedWhistleHasNoDownloadOrDeleteAndExplicitOffPersists() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-account-settings-fixture",
                               "-AppleLanguages", "(en)", "-AppleLocale", "en_US", "-app_language", "en"]
        app.launch()
        try openRecordingSettings(app)
        let card = app.descendants(matching: .any)["bundled-whistle-card"].firstMatch
        XCTAssertTrue(card.waitForExistence(timeout: 5))
        XCTAssertTrue(card.staticTexts["Included with this app"].exists, "Evaluation app must contain the bundled model")
        XCTAssertTrue(app.descendants(matching: .any)["bundled-whistle-size"].firstMatch.exists)
        XCTAssertFalse(app.buttons["offline-ai-remove-whistle"].exists)
        XCTAssertFalse(app.buttons["local-model-whistle-download"].exists)
        try choose("Whistle on this device", app: app)
        attach("Bundled Whistle explicitly selected", app: app)
        try choose("Off", app: app)
        XCTAssertTrue(app.staticTexts["No live transcription. You can still attach your audio recording."].exists)
        attach("Explicit Off preserves recording attachment intent", app: app)
        app.terminate()
        app.launch()
        try openRecordingSettings(app)
        XCTAssertEqual(selector(app).value as? String, "Off")
        try choose("Automatic (Whisper or online)", app: app)
    }

    private func openRecordingSettings(_ app: XCUIApplication) throws {
        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15))
        app.buttons["settings-button"].tap()
        let ai = app.descendants(matching: .any)["settings-ai-row"].firstMatch
        XCTAssertTrue(ai.waitForExistence(timeout: 8)); XCTAssertTrue(ai.isHittable); ai.tap()
        let offline = app.buttons["settings-ai-offline-models-row"].firstMatch
        XCTAssertTrue(offline.waitForExistence(timeout: 8)); XCTAssertTrue(offline.isHittable); offline.tap()
        XCTAssertTrue(app.descendants(matching: .any)["recording-transcription-settings"].firstMatch.waitForExistence(timeout: 8))
    }
    private func selector(_ app: XCUIApplication) -> XCUIElement { app.buttons["Recording transcription"].firstMatch }
    private func choose(_ label: String, app: XCUIApplication) throws {
        let control = selector(app)
        XCTAssertTrue(control.waitForExistence(timeout: 5)); XCTAssertTrue(control.isHittable); control.tap()
        let option = app.buttons[label].firstMatch
        XCTAssertTrue(option.waitForExistence(timeout: 3)); XCTAssertTrue(option.isHittable); option.tap()
        let changed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", label), object: control)
        XCTAssertEqual(XCTWaiter.wait(for: [changed], timeout: 5), .completed)
    }
    private func attach(_ name: String, app: XCUIApplication) {
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = name; screenshot.lifetime = .keepAlways; add(screenshot)
    }
}
