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
    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.compact-layout
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
            .matching(identifier: "watch-embed-preview-code")
            .firstMatch
        XCTAssertTrue(embed.waitForExistence(timeout: 5))
        XCTAssertEqual(embed.frame.width, 156, accuracy: 1)
        XCTAssertLessThanOrEqual(embed.frame.maxX, screenFrame.width)
        XCTAssertTrue(app.staticTexts["Write"].exists)
        XCTAssertTrue(app.staticTexts["28 lines ..."].exists)

        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = "Watch opened chat Write embed"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.browse-search-open,apple-watch.chats.new-text-reply
    func testChatsListShowsSearchNewChatAndExistingConversation() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-chat-layout"]
        app.launch()

        let back = app.buttons["watch-chat-back"]
        XCTAssertTrue(back.waitForExistence(timeout: 12))
        back.tap()

        XCTAssertTrue(app.descendants(matching: .any)["watch-chat-list"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["watch-chat-search-button"].exists)
        XCTAssertTrue(app.buttons["watch-new-chat-button"].exists)
        XCTAssertTrue(app.buttons["watch-chat-settings-button"].exists)

        let row = app.buttons["watch-chat-row-watch-ui-test-chat"]
        XCTAssertTrue(row.exists)

        let listAttachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        listAttachment.name = "Watch Chats list"
        listAttachment.lifetime = .keepAlways
        add(listAttachment)

        app.buttons["watch-chat-search-button"].tap()
        let search = app.textFields["watch-chat-search-input"]
        XCTAssertTrue(search.waitForExistence(timeout: 3))
        // Watch simulator text entry uses a separate system input sheet and
        // does not provide keyboard focus to XCUI typeText. Seed the same
        // bound search state in a second network-free launch to verify filtering.
        app.terminate()
        app.launchArguments = ["--ui-test-watch-chat-search"]
        app.launch()
        XCTAssertTrue(search.waitForExistence(timeout: 12))
        XCTAssertFalse(row.exists)

        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = "Watch Chats filtered list"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.compact-layout,apple-watch.chats.audio-reply
    func testOpenedChatShowsTextAndAudioReplyControls() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-chat-layout"]
        app.launch()

        XCTAssertTrue(app.descendants(matching: .any)["watch-chat-thread"].waitForExistence(timeout: 12))
        XCTAssertTrue(app.textFields["watch-message-input"].exists)
        XCTAssertTrue(app.buttons["watch-audio-record-button"].exists)

        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = "Watch chat reply composer"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.new-text-reply,apple-watch.chats.compact-layout
    func testNewChatShowsPersonalizedWelcomeAndComposer() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-chat-new"]
        app.launch()

        XCTAssertTrue(app.staticTexts["Hey Kitty!"].waitForExistence(timeout: 12))
        XCTAssertTrue(app.staticTexts["What do you want to learn or need help with?"].exists)
        XCTAssertTrue(app.buttons["watch-chat-back"].isHittable)
        XCTAssertTrue(app.textFields["watch-message-input"].exists)
        XCTAssertTrue(app.buttons["watch-audio-record-button"].isHittable)

        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = "Watch new chat personalized welcome"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.audio-reply,apple-watch.chats.compact-layout
    func testRecordingShowsHeaderAndInsetCardWithCancelAndSend() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-chat-recording"]
        app.launch()

        let back = app.buttons["watch-audio-back-button"]
        let card = app.descendants(matching: .any)["watch-audio-recording-screen"]
        let duration = app.descendants(matching: .any)["watch-audio-recording-duration"]
        let cancel = app.buttons["watch-audio-cancel-button"]
        let send = app.buttons["watch-audio-send-button"]
        XCTAssertTrue(back.waitForExistence(timeout: 12))
        XCTAssertTrue(card.exists)
        XCTAssertTrue(duration.exists)
        XCTAssertTrue(cancel.isHittable)
        XCTAssertTrue(send.isHittable)
        XCTAssertGreaterThan(card.frame.minY, back.frame.minY)

        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = "Watch audio recording card"
        attachment.lifetime = .keepAlways
        add(attachment)

        cancel.tap()
        XCTAssertTrue(app.textFields["watch-message-input"].waitForExistence(timeout: 5))
    }
}
