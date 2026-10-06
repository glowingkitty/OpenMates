// UI contract coverage for semantic source quotes, system messages, and sent audio.
// Uses synthetic debug-only chat history so no account, provider, or private media is needed.
// Verifies controls remain visible and operable after a cold app relaunch.
// Paired browser contracts come from the web source files listed on the product views.
// This file requires OpenMatesUITests target membership before Xcode can execute it.

import XCTest

final class ChatHistoryAudioParityUITests: XCTestCase {
    // contract-test: direct surface=gui.apple assertions=chats.rendering.inline-entity-interaction,message-input.recording.lifecycle
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
        let restoredPlay = app.buttons["recording-playback-toggle"]
        revealSentAudio(in: app, control: restoredPlay)
        XCTAssertTrue(restoredPlay.isHittable)
        attachScreenshot(name: "Semantic sent audio after cold boot")
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle
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

    // contract-test: direct surface=gui.apple assertions=chats.layout.responsive-history,message-input.recording.lifecycle
    @MainActor
    func testAudioOnlyUserBubbleHugsPreviewAtTrailingEdge() throws {
        continueAfterFailure = false
        for variant in ["reference", "whitespace"] {
            let app = launchFixture(audioContent: variant)
            let row = app.descendants(matching: .any)["chat-history-sent-audio-message"]
            let bubble = row.descendants(matching: .any)["user-embed-only-bubble"]
            let card = row.descendants(matching: .any)["embed-preview-card"]
            let play = row.buttons["recording-playback-toggle"]
            XCTAssertTrue(row.waitForExistence(timeout: 10))
            XCTAssertTrue(bubble.waitForExistence(timeout: 10))
            XCTAssertTrue(card.exists)
            revealSentAudio(in: app, control: play)
            XCTAssertTrue(play.isHittable)
            XCTAssertEqual(card.frame.width, 300, accuracy: 2)
            XCTAssertEqual(card.frame.height, 200, accuracy: 2)
            XCTAssertEqual(bubble.frame.width, card.frame.width + 24, accuracy: 2)
            // The row's accessibility bounds include the 12pt speech tail.
            // History content is centered, capped at 1000pt, and padded by 8pt.
            XCTAssertEqual(bubble.frame.maxX, row.frame.maxX - 12, accuracy: 2)
            let historyBounds = app.scrollViews["chat-history-container"].frame
            let contentTrailingEdge = historyBounds.midX + min(historyBounds.width, 1000) / 2
            XCTAssertEqual(bubble.frame.maxX, contentTrailingEdge - 8, accuracy: 2)
            XCTAssertEqual(card.frame.minX, bubble.frame.minX + 12, accuracy: 2)
            XCTAssertEqual(card.frame.maxX, bubble.frame.maxX - 12, accuracy: 2)
            XCTAssertEqual(play.value as? String, "play-triangle")
            XCTAssertEqual(play.frame.width, 36, accuracy: 2)
            XCTAssertEqual(play.frame.height, 36, accuracy: 2)
            XCTAssertEqual(play.frame.maxX, card.frame.maxX - 10, accuracy: 2)
            attachScreenshot(name: "Trailing compact audio bubble \(variant) triangle")
            app.terminate()
        }
    }

    // contract-test: direct surface=gui.apple assertions=chats.surface.semantic-parity,message-input.recording.lifecycle
    @MainActor
    func testMixedUserAudioPreservesTextAndEmbedOrder() throws {
        continueAfterFailure = false
        let app = launchFixture(audioContent: "mixed")
        defer { app.terminate() }
        let row = app.descendants(matching: .any)["chat-history-sent-audio-message"]
        XCTAssertTrue(row.waitForExistence(timeout: 10))
        XCTAssertFalse(row.descendants(matching: .any)["user-embed-only-bubble"].exists)
        let introduction = row.descendants(matching: .any).matching(
            NSPredicate(format: "label == %@ OR value == %@", "Synthetic audio introduction", "Synthetic audio introduction")
        ).firstMatch
        let conclusion = row.descendants(matching: .any).matching(
            NSPredicate(format: "label == %@ OR value == %@", "Synthetic audio conclusion", "Synthetic audio conclusion")
        ).firstMatch
        let card = row.descendants(matching: .any)["embed-preview-card"]
        XCTAssertTrue(introduction.exists)
        XCTAssertTrue(conclusion.exists)
        XCTAssertTrue(card.exists)
        XCTAssertLessThan(introduction.frame.minY, card.frame.minY)
        XCTAssertLessThan(card.frame.maxY, conclusion.frame.maxY)
        attachScreenshot(name: "Mixed user audio preserves text order")
    }

    @MainActor
    private func launchFixture(audioContent: String = "reference") -> XCUIApplication {
        let application = XCUIApplication()
        application.launchArguments = [
            "--dev-preview",
            "chat-opening",
            "--ui-test-chat-history-audio-parity"
        ]
        application.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
        application.launchEnvironment["UI_TEST_AUDIO_MESSAGE_CONTENT"] = audioContent
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
        let previewPlay = application.buttons["recording-playback-toggle"]
        XCTAssertTrue(previewPlay.waitForExistence(timeout: 10))
        revealSentAudio(in: application, control: previewPlay)
        XCTAssertTrue(previewPlay.isHittable)
        XCTAssertTrue(application.descendants(matching: .any)["recording-transcript"].exists)

        let details = application.descendants(matching: .any)["recording-preview"]
        let infoBar = application.descendants(matching: .any)["recording-preview-info-bar"]
        XCTAssertTrue(details.exists)
        XCTAssertTrue(infoBar.exists)
        XCTAssertEqual(infoBar.frame.height, 61, accuracy: 3)
        XCTAssertLessThanOrEqual(details.frame.maxY, infoBar.frame.minY + 2)

        let recording = recordingCard(in: application, value: "Ready")
        revealSentAudio(in: application, control: recording)
        XCTAssertTrue(recording.isHittable)
        recording.tap()

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

    @MainActor
    private func revealSentAudio(in application: XCUIApplication, control: XCUIElement) {
        let history = application.scrollViews["chat-history-container"]
        let card = application.descendants(matching: .any)["chat-history-sent-audio-message"]
            .descendants(matching: .any)["embed-preview-card"]
        XCTAssertTrue(control.waitForExistence(timeout: 10))
        XCTAssertTrue(history.exists)
        // The floating history controls occupy the first 54pt of the viewport.
        // Keep the complete card below them and use short held drags so inertia
        // cannot carry the card past the viewport as a full-page swipe can.
        let topControlClearance: CGFloat = 72
        for _ in 0..<10 {
            let visibleBounds = history.frame
            let cardBounds = card.frame
            let safeTop = visibleBounds.minY + topControlClearance
            let safeBottom = visibleBounds.maxY - 12
            if control.isHittable && cardBounds.minY >= safeTop
                && cardBounds.maxY <= safeBottom { break }

            let displacement: CGFloat
            if cardBounds.minY < safeTop {
                displacement = min(120, safeTop - cardBounds.minY)
            } else if cardBounds.maxY > safeBottom {
                displacement = -min(120, cardBounds.maxY - safeBottom)
            } else {
                // Geometry is already correct; retain the hittability assertion
                // rather than scrolling a covered or disabled control away.
                break
            }
            let start = history.coordinate(withNormalizedOffset: CGVector(dx: 0.08, dy: 0.5))
            start.press(forDuration: 0.05,
                        thenDragTo: start.withOffset(CGVector(dx: 0, dy: displacement)),
                        withVelocity: .slow, thenHoldForDuration: 0.2)
        }
        XCTAssertGreaterThanOrEqual(card.frame.minY, history.frame.minY)
        XCTAssertLessThanOrEqual(card.frame.maxY, history.frame.maxY)
        XCTAssertGreaterThanOrEqual(card.frame.minY, history.frame.minY + topControlClearance)
        XCTAssertTrue(control.isHittable)
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
