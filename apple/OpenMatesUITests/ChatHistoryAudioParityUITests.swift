// UI contract coverage for semantic source quotes, system messages, and sent audio.
// Uses synthetic debug-only chat history so no account, provider, or private media is needed.
// Verifies controls remain visible and operable after a cold app relaunch.
// Paired browser contracts come from the web source files listed on the product views.
// This file requires OpenMatesUITests target membership before Xcode can execute it.

import XCTest

final class ChatHistoryAudioParityUITests: XCTestCase {
    @MainActor
    func testOrderedSemanticHistoryAndSentAudioSurviveColdBoot() throws {
        continueAfterFailure = false
        var app = launchFixture()
        defer { app.terminate() }
        assertSemanticHistory(in: app)
        assertFinishedAudioInteractions(in: app)
        attachScreenshot(name: "Semantic sent audio preview")

        app.terminate()
        app = launchFixture()

        assertSemanticHistory(in: app)
        XCTAssertTrue(app.descendants(matching: .any)["recording-playback-toggle"].isHittable)
        attachScreenshot(name: "Semantic sent audio after cold boot")
    }

    @MainActor
    func testSentAudioProcessingAndErrorStatesAreExplicit() throws {
        continueAfterFailure = false
        let app = launchFixture()
        defer { app.terminate() }
        let processing = recordingCard(in: app, value: "Loading")
        let error = recordingCard(in: app, value: "Failed to load")

        XCTAssertTrue(processing.waitForExistence(timeout: 10))
        XCTAssertTrue(error.waitForExistence(timeout: 10))
        XCTAssertEqual(processing.value as? String, "Loading")
        XCTAssertEqual(error.value as? String, "Failed to load")
        XCTAssertFalse(app.tables.firstMatch.exists, "Chat product UI must not use default List/table chrome")
    }

    @MainActor
    private func launchFixture() -> XCUIApplication {
        let application = XCUIApplication()
        application.launchArguments = [
            "--dev-preview",
            "chat-opening",
            "--ui-test-chat-history-audio-parity"
        ]
        application.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
        application.launch()
        XCTAssertTrue(
            application.descendants(matching: .any)["chat-history-audio-parity-fixture"]
                .waitForExistence(timeout: 12)
        )
        return application
    }

    @MainActor
    private func assertSemanticHistory(in application: XCUIApplication) {
        let paragraph = application.staticTexts["Synthetic ordered introduction"]
        let sourceQuote = application.descendants(matching: .any)["source-quote-block"]
        let systemMessage = application.descendants(matching: .any)["chat-history-system-message"]
        let audio = recordingCard(in: application, value: "Ready")

        XCTAssertTrue(paragraph.waitForExistence(timeout: 10))
        XCTAssertTrue(sourceQuote.waitForExistence(timeout: 10))
        XCTAssertTrue(systemMessage.waitForExistence(timeout: 10))
        XCTAssertTrue(audio.waitForExistence(timeout: 10))
        XCTAssertLessThan(paragraph.frame.minY, sourceQuote.frame.minY)
        XCTAssertLessThan(sourceQuote.frame.minY, systemMessage.frame.minY)
        XCTAssertLessThan(systemMessage.frame.minY, audio.frame.minY)
        XCTAssertFalse(systemMessage.label.contains("OpenMates"))
        XCTAssertFalse(systemMessage.label.contains("Synthetic Mate"))
    }

    @MainActor
    private func assertFinishedAudioInteractions(in application: XCUIApplication) {
        let previewPlay = application.descendants(matching: .any)["recording-playback-toggle"]
        XCTAssertTrue(previewPlay.waitForExistence(timeout: 10))
        XCTAssertTrue(previewPlay.isHittable)
        XCTAssertTrue(application.descendants(matching: .any)["recording-transcript"].exists)
        XCTAssertTrue(application.descendants(matching: .any)["recording-model"].exists)
        XCTAssertTrue(application.descendants(matching: .any)["recording-correction-state"].exists)

        recordingCard(in: application, value: "Ready").tap()

        let fullscreen = application.descendants(matching: .any)["recording-fullscreen"]
        let fullscreenPlay = application.descendants(matching: .any)["recording-fullscreen-playback-toggle"]
        let seek = application.descendants(matching: .any)["recording-fullscreen-seek"]
        XCTAssertTrue(fullscreen.waitForExistence(timeout: 5))
        XCTAssertTrue(fullscreenPlay.isHittable)
        XCTAssertTrue(seek.isHittable)
        XCTAssertTrue(application.descendants(matching: .any)["recording-time"].exists)
        XCTAssertTrue(application.descendants(matching: .any)["recording-fullscreen-transcript"].exists)
        seek.tap()
    }

    private func recordingCard(in application: XCUIApplication, value: String) -> XCUIElement {
        application.descendants(matching: .any).matching(
            NSPredicate(format: "identifier == %@ AND value == %@", "embed-preview", value)
        ).firstMatch
    }

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
