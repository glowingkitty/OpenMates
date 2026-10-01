// Watch simulator UI coverage for the opened-chat layout and embed card.
// Launches a debug-only, non-networked fixture through the production Watch chat
// views so geometry assertions measure rendered simulator output. Screenshots are
// retained as durable evidence without exposing real account or chat content.

import XCTest

final class WatchChatLayoutUITests: XCTestCase {
    @MainActor
    // contract-test: supporting surface=gui.apple assertions=apple-notifications.action.routing-coherent
    func testNotificationRouteOpensTargetAndMissingTargetShowsError() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-chat-notification-route"]
        app.launch()
        XCTAssertTrue(app.descendants(matching: .any)["watch-chat-thread"].waitForExistence(timeout: 12))
        XCTAssertTrue(app.descendants(matching: .any)["watch-embed-preview-code"].exists)
        XCTAssertFalse(app.descendants(matching: .any)["watch-chat-list"].exists)
        app.terminate()
        app.launchArguments = ["--ui-test-watch-chat-notification-missing"]
        app.launch()
        XCTAssertTrue(app.descendants(matching: .any)["watch-chat-list"].waitForExistence(timeout: 12))
        XCTAssertFalse(app.descendants(matching: .any)["watch-chat-thread"].exists)
        let error = app.descendants(matching: .any)["watch-chat-load-error"]
        for _ in 0..<3 where !error.exists { app.swipeUp() }
        XCTAssertTrue(error.waitForExistence(timeout: 3))
    }

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
        XCTAssertTrue(app.textFields["watch-message-input"].isHittable)
        XCTAssertLessThanOrEqual(app.textFields["watch-message-input"].frame.height, 39, "Native text entry must fit within the 38pt composer capsule")
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

extension WatchChatLayoutUITests {
    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.new-text-reply,drafts.draft-only.lifecycle
    func testNewChatBackDoesNotCreateAnEmptyChat() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-chat-new"]
        app.launch()
        XCTAssertTrue(app.buttons["watch-chat-back"].waitForExistence(timeout: 12))
        app.buttons["watch-chat-back"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["watch-chat-list"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["watch-chat-row-watch-ui-test-chat"].exists)
        XCTAssertTrue(app.staticTexts["watch-chat-empty"].exists)
        app.buttons["watch-new-chat-button"].tap()
        XCTAssertTrue(app.textFields["watch-message-input"].waitForExistence(timeout: 5))
        app.buttons["watch-chat-back"].tap()
        XCTAssertTrue(app.staticTexts["watch-chat-empty"].waitForExistence(timeout: 5))
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=drafts.draft-only.lifecycle,drafts.persistence.local-first-encrypted,apple-watch.chats.new-text-reply
    func testContentBearingDraftSurvivesBackAndReopensSameChat() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-chat-draft"]
        app.launch()
        let input = app.textFields["watch-message-input"]
        XCTAssertTrue(input.waitForExistence(timeout: 12))
        XCTAssertEqual(input.value as? String, "Berlin meetup draft")
        app.buttons["watch-chat-back"].tap()
        let row = app.buttons["watch-chat-row-watch-ui-test-chat"]
        XCTAssertTrue(row.waitForExistence(timeout: 5))
        row.tap()
        XCTAssertTrue(input.waitForExistence(timeout: 5))
        XCTAssertEqual(input.value as? String, "Berlin meetup draft")
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.compact-layout
    func testMarkdownAndEventsSkillPreviewRenderSemanticContent() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-chat-markdown"]
        app.launch()
        let heading = app.descendants(matching: .any)["watch-markdown-heading-0"]
        XCTAssertTrue(heading.waitForExistence(timeout: 12))
        XCTAssertTrue(app.staticTexts["Berlin Meetup"].exists)
        XCTAssertFalse(app.staticTexts["## Berlin **Meetup**"].exists)
        let preview = app.buttons["watch-embed-preview-searchResults"]
        for _ in 0..<4 where !preview.isHittable { app.swipeUp() }
        XCTAssertTrue(preview.exists)
        XCTAssertTrue(app.staticTexts["Berlin meetups"].exists)
        XCTAssertEqual(preview.frame.width, 156, accuracy: 1)
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = "Watch Markdown and Events preview"
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}

extension WatchChatLayoutUITests {
    @MainActor
    // contract-test: direct surface=gui.apple assertions=drafts.sync.version-authoritative,drafts.draft-only.lifecycle,apple-watch.chats.browse-search-open
    func testRemotePhasedDraftAppearsAndReopensItsComposer() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-chat-remote-draft"]
        app.launch()
        let row = app.buttons["watch-chat-row-watch-remote-draft"]
        XCTAssertTrue(row.waitForExistence(timeout: 12))
        row.tap()
        let input = app.textFields["watch-message-input"]
        XCTAssertTrue(input.waitForExistence(timeout: 5))
        XCTAssertEqual(input.value as? String, "Berlin remote draft")
        XCTAssertTrue(input.isHittable)
        XCTAssertLessThanOrEqual(input.frame.height, 39, "Restored draft entry must fit within the composer capsule")
        app.buttons["watch-chat-back"].tap()
        XCTAssertTrue(row.waitForExistence(timeout: 5))
        row.tap()
        XCTAssertTrue(input.waitForExistence(timeout: 5))
        XCTAssertEqual(input.value as? String, "Berlin remote draft")
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = "Watch restored remote draft"
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
