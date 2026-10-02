// Simulator smoke coverage for native composer inline embed preview families.
// Uses a debug-only synthetic gallery without accounts, providers, or AI calls.
// Every asserted state is non-sensitive and deterministic across test runs.
// The gallery proves product chrome, lifecycle states, and explicit registry use.
// Screenshots provide durable visual evidence for the web-to-native comparison.

import XCTest

@MainActor
final class NativeComposerInlineEmbedUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle,message-input.embeds.gated-send
    func testFailedRecordingKeepsPlayableAudioAndOperableRetryAndRemove() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "composer", "--dev-preview-variant", "recording-error", "--dev-preview-width", "390"]
        app.launch()
        let audio = app.descendants(matching: .any)["native-composer-audio-content"].firstMatch
        XCTAssertTrue(audio.waitForExistence(timeout: 12))
        let play = app.buttons["native-composer-audio-play-button"].firstMatch
        let retry = app.buttons["native-composer-preview-action-refresh"].firstMatch
        let remove = app.buttons["native-composer-preview-action-close"].firstMatch
        XCTAssertTrue(play.waitForExistence(timeout: 5), "Failed recording must expose local playback: \(app.debugDescription)")
        XCTAssertTrue(retry.waitForExistence(timeout: 5), "Missing recording retry control: \(app.debugDescription)")
        XCTAssertFalse(remove.exists, "The failed card must not display a permanent close overlay")
        XCTAssertFalse(app.buttons["native-composer-preview-action-visible"].exists)
        XCTAssertTrue(play.isHittable)
        XCTAssertTrue(retry.isHittable)
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshot.name = "Retained failed audio attachment with retry"
        screenshot.lifetime = .keepAlways
        add(screenshot)
        play.tap()
        XCTAssertTrue(play.isHittable, "Local recorded audio must remain operable after upload failure")
        retry.tap()
        let action = app.descendants(matching: .any)["dev-preview-local-action"].firstMatch
        expectation(for: NSPredicate(format: "label == %@", "audio-retry-finished"), evaluatedWith: action)
        waitForExpectations(timeout: 5)
        XCTAssertFalse(retry.exists)
        // Retry replaces the attachment's hosted preview. Resolve its finished
        // card, which owns the long-press action, after that lifecycle change.
        let finishedRecording = app.descendants(matching: .any)["native-composer-preview-recording-finished"].firstMatch
        XCTAssertTrue(finishedRecording.waitForExistence(timeout: 5), "Retry must finish the recording card: \(app.debugDescription)")
        XCTAssertTrue(finishedRecording.isHittable)
        let retriedScreenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        retriedScreenshot.name = "Retried recording before card removal"
        retriedScreenshot.lifetime = .keepAlways
        add(retriedScreenshot)
        finishedRecording.press(forDuration: 1.1)
        XCTAssertTrue(remove.waitForExistence(timeout: 3), "Long press must expose the retried card's removal control: \(app.debugDescription)")
        XCTAssertTrue(remove.isHittable)
        remove.tap()
        expectation(for: NSPredicate(format: "label == %@", "audio-removed"), evaluatedWith: action)
        waitForExpectations(timeout: 5)
        XCTAssertFalse(audio.exists)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle,message-input.embeds.gated-send
    func testRegistryFamiliesAndLifecycleStatesRenderWithoutGenericFallback() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "composer-embeds"]
        app.launchEnvironment["DEV_PREVIEW"] = "composer-embeds"
        app.launch()

        let gallery = app.descendants(matching: .any)["dev-native-composer-embed-gallery"]
        XCTAssertTrue(gallery.waitForExistence(timeout: 8))
        XCTAssertEqual(gallery.value as? String, "54")

        assertVisible(app: app, identifier: "native-composer-preview-recording-finished")
        assertVisible(app: app, identifier: "native-composer-preview-recording-transcribing")
        assertVisible(app: app, identifier: "native-composer-audio-waveform")
        assertVisible(app: app, identifier: "native-composer-audio-transcript")
        assertVisible(app: app, identifier: "native-composer-audio-status")
        assertVisible(app: app, identifier: "native-composer-audio-attribution")
        assertVisible(app: app, identifier: "native-composer-preview-app-skill-use-draft")
        assertVisible(app: app, identifier: "native-composer-preview-code-repo-group-cancelled")
        assertVisible(app: app, identifier: "native-composer-preview-electronics-pcb-schematic-error")
        assertVisible(app: app, identifier: "native-composer-preview-fitness-location-uploading")
        assertVisible(app: app, identifier: "native-composer-preview-focus-mode-activation-finished")
        XCTAssertFalse(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "{\"")).firstMatch.exists)
        XCTAssertFalse(app.staticTexts.containing(NSPredicate(
            format: "label CONTAINS %@",
            "voxtral-mini-transcribe-realtime-2602"
        )).firstMatch.exists)
        XCTAssertFalse(app.tables.firstMatch.exists)

        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = "Native composer embed registry lifecycle gallery"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle,message-input.embeds.gated-send
    func testRecordingPreviewUsesCardInteractionWithoutTopRightActions() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "composer-embeds"]
        app.launchEnvironment["DEV_PREVIEW"] = "composer-embeds"
        app.launch()

        assertVisible(app: app, identifier: "native-composer-preview-recording-finished")
        let recording = app.descendants(matching: .any)["native-composer-preview-recording-finished"]
        XCTAssertFalse(recording.buttons["native-composer-preview-action-visible"].exists)
        XCTAssertFalse(recording.buttons["native-composer-preview-action-close"].exists)

        recording.press(forDuration: 1.1)
        XCTAssertTrue(app.buttons["Remove"].waitForExistence(timeout: 3))
    }

    private func assertVisible(app: XCUIApplication, identifier: String) {
        let element = app.descendants(matching: .any)[identifier]
        for _ in 0..<20 where !element.exists {
            app.swipeUp()
        }
        XCTAssertTrue(element.exists, "Missing composer preview: \(identifier)")
    }
}
