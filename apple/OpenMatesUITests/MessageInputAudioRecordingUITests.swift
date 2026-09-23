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

    // contract-test: direct surface=gui.apple assertions=message-input.actions.visibility,message-input.recording.lifecycle
    func testIdleWelcomeComposerShowsAiAndMicAndRecordsWithoutKeyboard() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "--ui-test-disable-auth-cache",
            "--ui-test-start-new-chat",
            "--ui-test-welcome-mic-granted",
            "--ui-test-welcome-simulated-recording"
        ]
        app.launch()

        let skipInterests = app.buttons["guest-interest-skip"]
        if skipInterests.waitForExistence(timeout: 3) {
            skipInterests.tap()
        }

        XCTAssertTrue(element(in: app, identifier: "message-input-idle-actions").waitForExistence(timeout: 5))
        let recordButton = element(in: app, identifier: "record-audio-button")
        XCTAssertTrue(recordButton.isHittable)
        XCTAssertFalse(app.keyboards.firstMatch.exists)

        let screenshotAttachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshotAttachment.name = "Idle welcome composer AI and microphone controls"
        screenshotAttachment.lifetime = .keepAlways
        add(screenshotAttachment)

        recordButton.tap()
        XCTAssertTrue(element(in: app, identifier: "record-overlay").waitForExistence(timeout: 5))
        XCTAssertFalse(app.keyboards.firstMatch.waitForExistence(timeout: 2))
    }

    // contract-test: direct surface=gui.apple assertions=message-input.actions.visibility,message-input.recording.lifecycle
    func testIdleChatComposerShowsAiAndMicWithoutOpeningKeyboard() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "--dev-preview", "chat-opening", "--ui-test-chat-mic-granted", "--ui-test-simulated-recording"
        ]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
        app.launch()

        XCTAssertTrue(app.staticTexts["Native Chat Opening Preview"].waitForExistence(timeout: 12))
        XCTAssertTrue(element(in: app, identifier: "message-input-idle-actions").waitForExistence(timeout: 5))
        let recordButton = element(in: app, identifier: "record-audio-button")
        XCTAssertTrue(recordButton.isHittable)
        XCTAssertFalse(app.keyboards.firstMatch.exists)

        recordButton.tap()
        XCTAssertTrue(element(in: app, identifier: "record-overlay").waitForExistence(timeout: 5))
        XCTAssertFalse(app.keyboards.firstMatch.waitForExistence(timeout: 2))
    }

    // contract-test: direct surface=gui.apple assertions=message-input.actions.visibility,message-input.recording.lifecycle
    func testSignedOutWelcomeSingleTapStartsRecordingUntilExplicitCancel() throws {
        let app = launchFocusedWelcomeComposer(extraArguments: [
            "--ui-test-welcome-mic-granted",
            "--ui-test-welcome-simulated-recording"
        ])

        let recordButton = element(in: app, identifier: "record-audio-button")
        XCTAssertTrue(recordButton.waitForExistence(timeout: 5))
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 3))
        recordButton.tap()

        let overlay = element(in: app, identifier: "record-overlay")
        XCTAssertTrue(overlay.waitForExistence(timeout: 5))
        XCTAssertEqual(
            app.descendants(matching: .any)
                .matching(NSPredicate(format: "identifier == %@", "record-overlay"))
                .count,
            1,
            "A tap must start exactly one recording overlay"
        )
        assertRecordingOverlayCopy(in: app)
        XCTAssertTrue(element(in: app, identifier: "record-cancel-button").isHittable)
        XCTAssertFalse(app.keyboards.firstMatch.waitForExistence(timeout: 3))
        XCTAssertEqual(overlay.frame.height, 220, accuracy: 1)
        let messageField = element(in: app, identifier: "message-field")
        XCTAssertTrue(messageField.exists, "The welcome composer must stay mounted beneath its recording panel")
        XCTAssertTrue(
            messageField.frame.intersects(overlay.frame),
            "The 220pt recording panel must occupy the actual welcome composer instead of a detached preview"
        )
        let screenshotAttachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshotAttachment.name = "Actual welcome composer recording overlay"
        screenshotAttachment.lifetime = .keepAlways
        add(screenshotAttachment)

        element(in: app, identifier: "record-cancel-button").tap()
        XCTAssertTrue(waitForAbsence(overlay))
        XCTAssertFalse(app.keyboards.firstMatch.waitForExistence(timeout: 2))
        XCTAssertFalse(element(in: app, identifier: "native-composer-preview-recording-finished").exists)
        XCTAssertTrue(element(in: app, identifier: "message-field").isHittable)
        messageField.tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5))
    }

    // contract-test: direct surface=gui.apple assertions=message-input.recording.lifecycle,message-input.embeds.gated-send
    func testSignedOutWelcomeHoldReleaseInsertsRecordingPreview() throws {
        let app = launchFocusedWelcomeComposer(extraArguments: [
            "--ui-test-welcome-mic-granted",
            "--ui-test-welcome-simulated-recording"
        ])

        let recordButton = element(in: app, identifier: "record-audio-button")
        XCTAssertTrue(recordButton.waitForExistence(timeout: 5))
        recordButton.press(forDuration: 0.6)

        let overlay = element(in: app, identifier: "record-overlay")
        XCTAssertTrue(overlay.waitForExistence(timeout: 5))
        XCTAssertTrue(element(in: app, identifier: "record-finish-button").isHittable)
        element(in: app, identifier: "record-finish-button").tap()

        XCTAssertTrue(element(in: app, identifier: "native-composer-preview-recording-finished").waitForExistence(timeout: 5))
        XCTAssertFalse(app.keyboards.firstMatch.waitForExistence(timeout: 2))
        XCTAssertFalse(element(in: app, identifier: "pending-composer-embed").exists)
        XCTAssertTrue(textContaining("recording", in: app).waitForExistence(timeout: 5))
        XCTAssertFalse(textContaining("```json", in: app).exists)
        XCTAssertTrue(app.buttons["send-button"].waitForExistence(timeout: 5))
        element(in: app, identifier: "message-field").tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5))
    }

    // contract-test: direct surface=gui.apple assertions=message-input.recording.lifecycle,message-input.focus.guest-welcome-suppression
    func testChatRecordingOverlayNeverShowsSoftwareKeyboard() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "--dev-preview", "chat-opening",
            "--ui-test-chat-mic-granted",
            "--ui-test-simulated-recording"
        ]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
        app.launch()

        XCTAssertTrue(app.staticTexts["Native Chat Opening Preview"].waitForExistence(timeout: 12))
        let editor = element(in: app, identifier: "message-editor")
        XCTAssertTrue(editor.waitForExistence(timeout: 5))
        editor.tap()

        element(in: app, identifier: "record-audio-button").tap()
        let overlay = element(in: app, identifier: "record-overlay")
        XCTAssertTrue(overlay.waitForExistence(timeout: 5))
        XCTAssertFalse(app.keyboards.firstMatch.waitForExistence(timeout: 3))

        element(in: app, identifier: "record-cancel-button").tap()
        XCTAssertTrue(waitForAbsence(overlay))
        XCTAssertFalse(app.keyboards.firstMatch.waitForExistence(timeout: 2))
    }

    // contract-test: direct surface=gui.apple assertions=message-input.recording.lifecycle
    func testFirstTapRecordsAfterMicrophonePermissionIsGranted() throws {
        let app = launchFocusedWelcomeComposer(extraArguments: [
            "--ui-test-mic-request-granted",
            "--ui-test-welcome-simulated-recording"
        ])

        let recordButton = element(in: app, identifier: "record-audio-button")
        XCTAssertTrue(recordButton.waitForExistence(timeout: 5))
        recordButton.tap()

        XCTAssertTrue(element(in: app, identifier: "record-overlay").waitForExistence(timeout: 5))
        element(in: app, identifier: "record-finish-button").tap()

        XCTAssertTrue(
            element(in: app, identifier: "native-composer-preview-recording-finished").waitForExistence(timeout: 5),
            "The first tap should continue recording after permission is granted"
        )
    }

    // contract-test: direct surface=gui.apple assertions=message-input.recording.lifecycle,message-input.embeds.gated-send
    func testFailedRecordingOutputNeverCreatesFinishedWelcomeEmbed() throws {
        let app = launchFocusedWelcomeComposer(extraArguments: [
            "--ui-test-welcome-mic-granted",
            "--ui-test-welcome-recording-output-failure"
        ])

        element(in: app, identifier: "record-audio-button").tap()
        let overlay = element(in: app, identifier: "record-overlay")
        XCTAssertTrue(overlay.waitForExistence(timeout: 5))
        element(in: app, identifier: "record-finish-button").tap()

        XCTAssertTrue(waitForAbsence(overlay))
        XCTAssertFalse(element(in: app, identifier: "native-composer-preview-recording-finished").exists)
        XCTAssertFalse(element(in: app, identifier: "pending-composer-embed").exists)
        XCTAssertFalse(app.buttons["send-button"].exists)
    }

    // contract-test: direct surface=gui.apple assertions=message-input.recording.lifecycle,message-input.embeds.gated-send,message-input.privacy-context
    func testGuestRecordingKeepsPlayableLocalPreviewWithoutDurableIdentity() throws {
        let app = launchFocusedWelcomeComposer(extraArguments: [
            "--ui-test-welcome-mic-granted",
            "--ui-test-welcome-guest-local-recording"
        ])

        element(in: app, identifier: "record-audio-button").tap()
        XCTAssertTrue(element(in: app, identifier: "record-overlay").waitForExistence(timeout: 5))
        element(in: app, identifier: "record-finish-button").tap()

        let preview = element(in: app, identifier: "native-composer-preview-recording-finished")
        XCTAssertTrue(preview.waitForExistence(timeout: 5))
        XCTAssertEqual(preview.value as? String, "local-preview-no-durable-id")
        XCTAssertFalse(element(in: app, identifier: "pending-composer-embed").exists)
    }

    // contract-test: direct surface=gui.apple assertions=message-input.focus.guest-welcome-suppression,message-input.recording.lifecycle
    func testRecordRequestLaunchStartsWelcomeRecordingOverlay() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "--ui-test-disable-auth-cache",
            "--ui-test-start-recording",
            "--ui-test-welcome-mic-granted",
            "--ui-test-welcome-simulated-recording"
        ]
        app.launch()

        let skipInterests = app.buttons["guest-interest-skip"]
        if skipInterests.waitForExistence(timeout: 3) {
            skipInterests.tap()
        }

        XCTAssertTrue(element(in: app, identifier: "record-overlay").waitForExistence(timeout: 8))
        assertRecordingOverlayCopy(in: app)
        XCTAssertTrue(element(in: app, identifier: "record-finish-button").waitForExistence(timeout: 2))
        assertWelcomeSuppressedAndComposerUsable(in: app)
    }

    // contract-test: direct surface=gui.apple assertions=message-input.recording.lifecycle
    func testSignedOutWelcomeRecordingCancelDoesNotInsertPreview() throws {
        let app = launchFocusedWelcomeComposer(extraArguments: [
            "--ui-test-welcome-mic-granted",
            "--ui-test-welcome-simulated-recording",
            "--ui-test-welcome-force-keyboard-recording-overlay"
        ])

        XCTAssertTrue(element(in: app, identifier: "record-overlay").waitForExistence(timeout: 5))
        assertRecordingOverlayCopy(in: app)
        XCTAssertTrue(element(in: app, identifier: "record-cancel-button").waitForExistence(timeout: 2))

        element(in: app, identifier: "record-cancel-button").tap()

        XCTAssertTrue(waitForAbsence(element(in: app, identifier: "record-overlay")))
        XCTAssertFalse(element(in: app, identifier: "native-composer-preview-recording-finished").exists)
        XCTAssertFalse(element(in: app, identifier: "pending-composer-embed").exists)
    }

    // contract-test: direct surface=gui.apple assertions=message-input.recording.lifecycle
    func testSignedOutWelcomePointerReleaseDoesNotFinishOrCancelRecording() throws {
        let app = launchFocusedWelcomeComposer(extraArguments: [
            "--ui-test-welcome-mic-granted",
            "--ui-test-welcome-simulated-recording"
        ])

        let recordButton = element(in: app, identifier: "record-audio-button")
        XCTAssertTrue(recordButton.waitForExistence(timeout: 5))
        let start = recordButton.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
        let end = recordButton.coordinate(withNormalizedOffset: CGVector(dx: -5.0, dy: 0.5))
        start.press(forDuration: 0.35, thenDragTo: end)

        let overlay = element(in: app, identifier: "record-overlay")
        XCTAssertTrue(overlay.waitForExistence(timeout: 5))
        XCTAssertFalse(element(in: app, identifier: "native-composer-preview-recording-finished").exists)
        XCTAssertFalse(element(in: app, identifier: "pending-composer-embed").exists)

        element(in: app, identifier: "record-cancel-button").tap()
        XCTAssertTrue(waitForAbsence(overlay))
    }

    // contract-test: direct surface=gui.apple assertions=message-input.actions.visibility,message-input.recording.lifecycle
    func testRecordButtonAndForcedOverlayMatchContractStructure() throws {
        let app = XCUIApplication()

        app.launchArguments = ["--dev-preview", "chat-opening-recording"]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening-recording"
        app.launch()

        XCTAssertTrue(app.staticTexts["Native Chat Opening Preview"].waitForExistence(timeout: 12))
        let overlay = element(in: app, identifier: "record-overlay")
        XCTAssertTrue(overlay.waitForExistence(timeout: 2))
        XCTAssertEqual(
            overlay.frame.height,
            220,
            accuracy: 1,
            "The native recording surface must match MessageInput's fixed 220px web contract"
        )
        let releaseText = element(in: app, identifier: "release-text")
        XCTAssertTrue(releaseText.waitForExistence(timeout: 2))
        XCTAssertTrue(releaseText.label.localizedCaseInsensitiveContains("Recording"), "Expected pointer overlay recording text; label=\(releaseText.label)")
        XCTAssertTrue(element(in: app, identifier: "record-shortcuts").waitForExistence(timeout: 2))
        XCTAssertTrue(element(in: app, identifier: "timer-pill").waitForExistence(timeout: 2))
        XCTAssertTrue(element(in: app, identifier: "record-action-buttons").waitForExistence(timeout: 2))
        XCTAssertTrue(element(in: app, identifier: "record-cancel-button").waitForExistence(timeout: 2))
        XCTAssertTrue(element(in: app, identifier: "record-finish-button").waitForExistence(timeout: 2))

        let controls = element(in: app, identifier: "record-controls")
        XCTAssertTrue(controls.waitForExistence(timeout: 2))
        XCTAssertGreaterThanOrEqual(
            controls.frame.height,
            44,
            "The 41pt web control visuals must retain Apple minimum touch targets"
        )
        XCTAssertTrue(element(in: app, identifier: "record-cancel-button").isHittable)
        XCTAssertTrue(element(in: app, identifier: "record-finish-button").isHittable)
        XCTAssertGreaterThanOrEqual(
            controls.frame.minY - releaseText.frame.maxY,
            64,
            "The decorative 64pt waveform track must remain between the release text and controls"
        )
        XCTAssertFalse(element(in: app, identifier: "recording-waveform").exists)

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
        assertRecordingOverlayCopy(in: app)
        XCTAssertTrue(element(in: app, identifier: "record-cancel-button").waitForExistence(timeout: 2))
        XCTAssertTrue(element(in: app, identifier: "record-finish-button").waitForExistence(timeout: 2))
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle,message-input.embeds.gated-send,message-input.send.ownership
    func testPendingRecordingShowsRawThenCorrectedTranscriptOnSameComposerNode() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "chat-opening", "--ui-test-seed-recording-raw-pending"]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
        app.launch()

        XCTAssertTrue(app.staticTexts["Native Chat Opening Preview"].waitForExistence(timeout: 12))
        let pendingCard = element(in: app, identifier: "native-composer-preview-recording-correcting")
        XCTAssertTrue(pendingCard.waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Raw realtime transcript"].waitForExistence(timeout: 2))
        XCTAssertTrue(app.buttons["send-button"].isHittable, "Send remains available while the recording atom is blocking")
        XCTAssertEqual(
            app.descendants(matching: .any)
                .matching(NSPredicate(format: "identifier BEGINSWITH %@", "native-composer-preview-recording-"))
                .count,
            1
        )

        XCTAssertTrue(app.staticTexts["Corrected realtime transcript"].waitForExistence(timeout: 10))
        XCTAssertTrue(element(in: app, identifier: "native-composer-preview-recording-finished").exists)
        XCTAssertEqual(
            app.descendants(matching: .any)
                .matching(NSPredicate(format: "identifier BEGINSWITH %@", "native-composer-preview-recording-"))
                .count,
            1,
            "Raw and corrected transcript states must reuse one composer atom"
        )
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

    private func assertRecordingOverlayCopy(in app: XCUIApplication) {
        let releaseText = element(in: app, identifier: "release-text")
        XCTAssertTrue(releaseText.waitForExistence(timeout: 2))
        XCTAssertTrue(
            releaseText.label.localizedCaseInsensitiveContains("Recording"),
            "Expected release text to match web recording label; label=\(releaseText.label)"
        )

        let shortcuts = element(in: app, identifier: "record-shortcuts")
        XCTAssertTrue(shortcuts.waitForExistence(timeout: 2))
        XCTAssertTrue(
            shortcuts.label.localizedCaseInsensitiveContains("Enter") &&
            shortcuts.label.localizedCaseInsensitiveContains("Escape"),
            "Expected web shortcut copy in record-shortcuts; label=\(shortcuts.label)"
        )
    }

    private func assertWelcomeSuppressedAndComposerUsable(in app: XCUIApplication) {
        XCTAssertFalse(element(in: app, identifier: "daily-inspiration-card").exists)
        XCTAssertFalse(element(in: app, identifier: "guest-interest-tags").exists)
        XCTAssertFalse(element(in: app, identifier: "welcome-chat-cards-carousel").exists)

        let messageField = element(in: app, identifier: "message-field")
        XCTAssertTrue(messageField.waitForExistence(timeout: 2))
        XCTAssertTrue(messageField.isHittable, "Message input must remain mounted and hittable while welcome UI is suppressed")
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
