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

    func testSignedOutWelcomeShortTapShowsPressHoldHintWithoutSignup() throws {
        let app = launchFocusedWelcomeComposer(extraArguments: ["--ui-test-welcome-mic-granted"])

        let recordButton = element(in: app, identifier: "record-audio-button")
        XCTAssertTrue(recordButton.waitForExistence(timeout: 5))
        recordButton.tap()

        XCTAssertFalse(element(in: app, identifier: "record-overlay").exists)
        XCTAssertTrue(element(in: app, identifier: "press-hold-label").waitForExistence(timeout: 3))
        XCTAssertFalse(app.buttons["send-button"].exists, "Short tapping audio must not surface signup CTA")
        XCTAssertTrue(element(in: app, identifier: "message-field").isHittable)
    }

    func testSignedOutWelcomeHoldReleaseInsertsRecordingPreview() throws {
        let app = launchFocusedWelcomeComposer(extraArguments: [
            "--ui-test-welcome-mic-granted",
            "--ui-test-welcome-simulated-recording"
        ])

        let recordButton = element(in: app, identifier: "record-audio-button")
        XCTAssertTrue(recordButton.waitForExistence(timeout: 5))
        recordButton.press(forDuration: 0.45)

        XCTAssertTrue(element(in: app, identifier: "native-composer-preview-recording-finished").waitForExistence(timeout: 5))
        XCTAssertFalse(element(in: app, identifier: "pending-composer-embed").exists)
        XCTAssertTrue(textContaining("recording", in: app).waitForExistence(timeout: 5))
        XCTAssertFalse(textContaining("```json", in: app).exists)
        XCTAssertTrue(app.buttons["send-button"].waitForExistence(timeout: 5))
    }

    func testSignedOutWelcomeRecordingCancelDoesNotInsertPreview() throws {
        let app = launchFocusedWelcomeComposer(extraArguments: [
            "--ui-test-welcome-mic-granted",
            "--ui-test-welcome-simulated-recording",
            "--ui-test-welcome-force-keyboard-recording-overlay"
        ])

        XCTAssertTrue(element(in: app, identifier: "record-overlay").waitForExistence(timeout: 5))
        assertCancelHint(in: app, contains: "Press ESC to cancel", excludes: "Slide left to cancel")

        element(in: app, identifier: "cancel-hint").tap()

        XCTAssertTrue(waitForAbsence(element(in: app, identifier: "record-overlay")))
        XCTAssertFalse(element(in: app, identifier: "native-composer-preview-recording-finished").exists)
        XCTAssertFalse(element(in: app, identifier: "pending-composer-embed").exists)
    }

    func testSignedOutWelcomeDragLeftCancelsRecordingWithoutPreview() throws {
        let app = launchFocusedWelcomeComposer(extraArguments: [
            "--ui-test-welcome-mic-granted",
            "--ui-test-welcome-simulated-recording"
        ])

        let recordButton = element(in: app, identifier: "record-audio-button")
        XCTAssertTrue(recordButton.waitForExistence(timeout: 5))
        let start = recordButton.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
        let end = recordButton.coordinate(withNormalizedOffset: CGVector(dx: -5.0, dy: 0.5))
        start.press(forDuration: 0.35, thenDragTo: end)

        XCTAssertTrue(waitForAbsence(element(in: app, identifier: "record-overlay")))
        XCTAssertFalse(element(in: app, identifier: "native-composer-preview-recording-finished").exists)
        XCTAssertFalse(element(in: app, identifier: "pending-composer-embed").exists)
    }

    func testRecordButtonAndForcedOverlayMatchContractStructure() throws {
        let welcomeApp = launchFocusedWelcomeComposer(extraArguments: ["--ui-test-welcome-mic-granted"])
        XCTAssertTrue(element(in: welcomeApp, identifier: "record-audio-button").waitForExistence(timeout: 5))
        welcomeApp.terminate()

        let app = XCUIApplication()

        app.launchArguments = ["--dev-preview", "chat-opening-recording"]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening-recording"
        app.launch()

        XCTAssertTrue(app.staticTexts["Native Chat Opening Preview"].waitForExistence(timeout: 12))
        XCTAssertTrue(element(in: app, identifier: "release-text").waitForExistence(timeout: 2))
        XCTAssertTrue(element(in: app, identifier: "timer-pill").waitForExistence(timeout: 2))
        XCTAssertTrue(element(in: app, identifier: "cancel-hint").waitForExistence(timeout: 2))
        assertCancelHint(in: app, contains: "Slide left to cancel", excludes: "Press ESC to cancel")
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
        assertCancelHint(in: app, contains: "Press ESC to cancel", excludes: "Slide left to cancel")
    }

    private func element(in app: XCUIApplication, identifier: String) -> XCUIElement {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier == %@", identifier))
            .firstMatch
    }

    private func textContaining(_ text: String, in app: XCUIApplication) -> XCUIElement {
        app.staticTexts
            .matching(NSPredicate(format: "label CONTAINS[c] %@", text))
            .firstMatch
    }

    private func assertCancelHint(in app: XCUIApplication, contains expected: String, excludes unexpected: String) {
        let hint = element(in: app, identifier: "cancel-hint")
        XCTAssertTrue(hint.waitForExistence(timeout: 2))
        let label = hint.label
        XCTAssertTrue(label.localizedCaseInsensitiveContains(expected), "Expected cancel hint label to contain \(expected); label=\(label)")
        XCTAssertFalse(label.localizedCaseInsensitiveContains(unexpected), "Expected cancel hint label to exclude \(unexpected); label=\(label)")
    }

    private func waitForAbsence(_ element: XCUIElement, timeout: TimeInterval = 5) -> Bool {
        let predicate = NSPredicate(format: "exists == false")
        let expectation = XCTNSPredicateExpectation(predicate: predicate, object: element)
        return XCTWaiter.wait(for: [expectation], timeout: timeout) == .completed
    }

    private func launchFocusedWelcomeComposer(extraArguments: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-start-new-chat"] + extraArguments
        app.launch()

        let skipInterests = app.buttons["guest-interest-skip"]
        if skipInterests.waitForExistence(timeout: 12) {
            skipInterests.tap()
        }

        if !extraArguments.contains("--ui-test-welcome-force-keyboard-recording-overlay") {
            let editor = waitForMessageEditor(in: app)
            editor.tap()
        }
        XCTAssertTrue(element(in: app, identifier: "record-audio-button").waitForExistence(timeout: 5))
        return app
    }

    private func waitForMessageEditor(in app: XCUIApplication) -> XCUIElement {
        let candidates = [element(in: app, identifier: "message-editor")]

        for candidate in candidates where candidate.waitForExistence(timeout: 5) {
            return candidate
        }

        XCTFail("Expected welcome message editor to exist. Visible UI: \(app.debugDescription)")
        return candidates[0]
    }
}
