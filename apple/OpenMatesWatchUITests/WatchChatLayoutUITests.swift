// Watch simulator UI coverage for the opened-chat layout and embed card.
// Launches a debug-only, non-networked fixture through the production Watch chat
// views so geometry assertions measure rendered simulator output. Screenshots are
// retained as durable evidence without exposing real account or chat content.

import XCTest

final class WatchChatLayoutUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    @MainActor
    func testOpenedChatUsesFullHeightAndFixedEmbedWidth() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-chat-layout"]
        app.launch()

        let thread = app.otherElements["watch-chat-thread"]
        XCTAssertTrue(thread.waitForExistence(timeout: 12))

        let screenFrame = XCUIScreen.main.screenshot().image.size
        XCTAssertGreaterThanOrEqual(thread.frame.height, screenFrame.height * 0.8)
        XCTAssertGreaterThanOrEqual(thread.frame.maxY, screenFrame.height - 1)

        let embed = app.buttons["watch-embed-preview-website"]
        XCTAssertTrue(embed.waitForExistence(timeout: 5))
        XCTAssertEqual(embed.frame.width, 156, accuracy: 1)
        XCTAssertLessThanOrEqual(embed.frame.maxX, screenFrame.width)

        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = "Watch opened chat fixed-width embed"
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
