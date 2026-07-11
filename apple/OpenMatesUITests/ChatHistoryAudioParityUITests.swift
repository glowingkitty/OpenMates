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
        let processing = app.descendants(matching: .any)["recording-processing-state"]
        let error = app.descendants(matching: .any)["recording-error-state"]

        XCTAssertTrue(scrollToElement(processing, in: app))
        XCTAssertTrue(scrollToElement(error, in: app))
        XCTAssertTrue(processing.label.contains("Synthetic Voxtral"))
        XCTAssertTrue(error.label.contains("Audio unavailable"))
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
        let audio = application.buttons["embed-preview"]

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

        application.descendants(matching: .any)["recording-preview"].tap()

        let fullscreen = application.descendants(matching: .any)["recording-fullscreen"]
        let fullscreenPlay = application.descendants(matching: .any)["recording-fullscreen-playback-toggle"]
        let seek = application.descendants(matching: .any)["recording-seek"]
        XCTAssertTrue(fullscreen.waitForExistence(timeout: 5))
        XCTAssertTrue(fullscreenPlay.isHittable)
        XCTAssertTrue(seek.isHittable)
        XCTAssertTrue(application.descendants(matching: .any)["recording-time"].exists)
        XCTAssertTrue(application.descendants(matching: .any)["recording-fullscreen-transcript"].exists)
        seek.tap()
    }

    private func scrollToElement(_ element: XCUIElement, in application: XCUIApplication) -> Bool {
        let scrollView = application.scrollViews.firstMatch
        for _ in 0..<6 {
            if element.exists { return true }
            scrollView.swipeUp()
        }
        return element.exists
    }

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
