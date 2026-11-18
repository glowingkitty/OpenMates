// Call media stage rendered by the production view in the local Debug component
// preview (message variants voice-call-media-*); no account. Real EmbedRecords
// go through the core stage policy, only the encrypted fetch is replaced.
// Screenshots pair with web /dev/preview voicecall/VoiceCallMedia.
import XCTest

@MainActor
final class VoiceCallMediaStagePreviewUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: direct surface=gui.apple assertions=video-call.video.generated-media-stage
    func testGeneratedResultsExpandStageWithAIBadgePagingAndCollapse() {
        let app = launch("voice-call-media-multiple")
        let stage = element(app, "voice-call-media")
        XCTAssertTrue(stage.waitForExistence(timeout: 10), "Missing call media stage")
        let image = element(app, "voice-call-generated-image")
        XCTAssertTrue(image.waitForExistence(timeout: 10), "A finished generated image is displayed")
        XCTAssertTrue(element(app, "voice-call-media-ai").exists, "AI icon at the top right")
        XCTAssertGreaterThan(stage.frame.height, 400, "A completed result expands the stage")
        let ai = element(app, "voice-call-media-ai")
        XCTAssertGreaterThan(ai.frame.midX, stage.frame.midX)
        XCTAssertLessThan(ai.frame.midY, stage.frame.midY)

        let previous = app.buttons["voice-call-media-previous"]
        let next = app.buttons["voice-call-media-next"]
        XCTAssertTrue(next.waitForExistence(timeout: 5), "Multiple outputs have previous/next controls")
        XCTAssertFalse(previous.isEnabled)
        XCTAssertTrue(next.isEnabled)
        XCTAssertTrue(app.staticTexts["1 / 2"].exists)
        attach("Call media stage first of two results")

        next.tap()
        XCTAssertTrue(app.staticTexts["2 / 2"].waitForExistence(timeout: 5))
        XCTAssertTrue(previous.isEnabled)
        XCTAssertFalse(next.isEnabled)
        attach("Call media stage second result")

        let expand = app.buttons["voice-call-media-expand"]
        XCTAssertTrue(expand.isHittable)
        XCTAssertGreaterThan(expand.frame.midX, stage.frame.midX, "Collapse control at the bottom right")
        XCTAssertGreaterThan(expand.frame.midY, stage.frame.midY)
        expand.tap()
        let collapsed = NSPredicate { _, _ in stage.frame.height < 120 }
        expectation(for: collapsed, evaluatedWith: stage)
        waitForExpectations(timeout: 3)
        XCTAssertTrue(element(app, "voice-call-generated-image").exists, "The result stays until the user returns to the camera")
        attach("Call media stage collapsed")
    }

    // contract-test: supporting surface=gui.apple assertions=video-call.video.generated-media-stage
    func testSingleResultHasNoPaging() {
        let app = launch("voice-call-media-image")
        XCTAssertTrue(element(app, "voice-call-generated-image").waitForExistence(timeout: 10))
        XCTAssertFalse(app.buttons["voice-call-media-next"].exists)
        XCTAssertFalse(app.buttons["voice-call-media-previous"].exists)
        attach("Call media stage single result")
    }

    private func element(_ app: XCUIApplication, _ id: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: id).firstMatch
    }

    private func attach(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
    }

    private func launch(_ variant: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "message", "--dev-preview-variant", variant,
            "--dev-preview-theme", "light", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        XCTAssertTrue(app.descendants(matching: .any).matching(identifier: "dev-preview-root").firstMatch
            .waitForExistence(timeout: 10))
        return app
    }
}
