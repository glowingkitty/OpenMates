// Prepared app/share user messages rendered through the production bubble/parser.
// Synthetic inputs; no login, persistence, inference, or real-account operations.
import XCTest

@MainActor
final class URLMessageEmbedUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testRegularAndShareWebsiteURLsRenderInteractiveCardsWithSurroundingText() {
        for variant in ["url-regular-website", "url-share-website"] {
            let app = launch(variant)
            let scroll = app.descendants(matching: .any)["dev-url-message-scroll"].firstMatch
            XCTAssertTrue(scroll.waitForExistence(timeout: 10))
            XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "summarize this website")).firstMatch.exists)
            let title = app.staticTexts["Public URL fixture article"].firstMatch
            XCTAssertTrue(title.waitForExistence(timeout: 5))
            XCTAssertTrue(title.isHittable)
            screenshot(variant)
            title.tap()
            let fullscreen = app.descendants(matching: .any)["dev-url-message-fullscreen"].firstMatch
            XCTAssertTrue(fullscreen.waitForExistence(timeout: 5))
            let minimize = app.buttons["embed-minimize"].firstMatch
            XCTAssertTrue(minimize.waitForExistence(timeout: 5))
            XCTAssertTrue(minimize.isHittable)
            minimize.tap()
            XCTAssertTrue(fullscreen.waitForNonExistence(timeout: 5))
            app.terminate()
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testRegularAndShareMobileYouTubeURLsRenderVideoCardsAndKeepSummaryRequest() {
        for variant in ["url-regular-video", "url-share-video"] {
            let app = launch(variant)
            XCTAssertTrue(app.descendants(matching: .any)["dev-url-message-scroll"].firstMatch.waitForExistence(timeout: 10))
            let video = app.descendants(matching: .any)["youtube-video-preview"].firstMatch
            XCTAssertTrue(video.waitForExistence(timeout: 5), app.debugDescription)
            XCTAssertTrue(video.isHittable)
            XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "summarize the video")).firstMatch.exists)
            XCTAssertFalse(app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "https://m.youtube.com/watch")).firstMatch.exists)
            screenshot(variant)
            app.terminate()
        }
    }

    private func launch(_ variant: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "message", "--dev-preview-variant", variant, "--dev-preview-width", "390"]
        app.launch()
        return app
    }

    private func screenshot(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
