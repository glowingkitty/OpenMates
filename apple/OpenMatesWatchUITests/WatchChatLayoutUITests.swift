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

        let layoutShell = app.descendants(matching: .any)
            .matching(identifier: "watch-chat-shell")
            .firstMatch
        XCTAssertTrue(layoutShell.waitForExistence(timeout: 12))

        let screenFrame = XCUIScreen.main.screenshot().image.size
        let appWindow = app.windows.firstMatch
        XCTAssertTrue(appWindow.exists)
        XCTAssertGreaterThanOrEqual(appWindow.frame.height, screenFrame.height * 0.8)
        XCTAssertGreaterThanOrEqual(appWindow.frame.maxY, screenFrame.height - 1)

        let embed = app.descendants(matching: .any)
            .matching(identifier: "watch-embed-preview-website")
            .firstMatch
        XCTAssertTrue(embed.waitForExistence(timeout: 5))
        XCTAssertEqual(embed.frame.width, 156, accuracy: 1)
        XCTAssertLessThanOrEqual(embed.frame.maxX, screenFrame.width)

        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = "Watch opened chat fixed-width embed"
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
