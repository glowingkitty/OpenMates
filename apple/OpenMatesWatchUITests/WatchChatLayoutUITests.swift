// Watch simulator UI coverage for the opened-chat layout and embed card.
// Launches a debug-only, non-networked fixture through the production Watch chat
// views so geometry assertions measure rendered simulator output. Screenshots are
// retained as durable evidence without exposing real account or chat content.

import XCTest
import CoreGraphics

@MainActor
final class WatchChatLayoutUITests: XCTestCase {
    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.browse-search-open,apple-watch.chats.compact-layout
    func testForegroundRemoteWindowLoadsOlderMessagesWithoutFullHistory() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-message-window"]
        app.launch()
        let older = app.buttons["watch-chat-remote-older-messages"]
        XCTAssertTrue(older.waitForExistence(timeout: 12))
        for _ in 0..<3 where !older.isHittable { app.swipeUp() }
        XCTAssertTrue(older.isHittable)
        older.tap()
        let first = app.staticTexts["Remote message 0"]
        for _ in 0..<4 where !first.isHittable { app.swipeDown() }
        XCTAssertTrue(first.waitForExistence(timeout: 5))
        XCTAssertTrue(first.isHittable)
        XCTAssertFalse(older.exists, "The final before page removes the control without a repeated read")
        XCTAssertTrue(app.textFields["watch-message-input"].isHittable)
        let artifact = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        artifact.name = "Watch bounded remote history before page"
        artifact.lifetime = .keepAlways
        add(artifact)
    }

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

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.offline.recent-cohort,apple-watch.chats.compact-layout
    func testUnopenedRecentConversationIsFullyOfflineAndPagesWithoutNetwork() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-offline-cohort"]
        app.launch()
        XCTAssertTrue(app.descendants(matching: .any)["watch-chat-offline"].waitForExistence(timeout: 30))
        let recent = app.buttons["watch-chat-row-watch-offline-20"]
        XCTAssertTrue(recent.waitForExistence(timeout: 5))
        recent.tap()
        let sheet = app.buttons["watch-embed-preview-spreadsheet"]
        XCTAssertTrue(sheet.waitForExistence(timeout: 10), "Unopened cohort embed must hydrate with cached keys after transport disconnect")
        XCTAssertTrue(app.staticTexts["watch-embed-title-offline-sheet"].exists)
        XCTAssertEqual(app.staticTexts["watch-embed-title-offline-sheet"].label, "offline.xls")
        let older = app.buttons["watch-chat-older-messages"]
        XCTAssertTrue(older.exists)
        older.tap()
        XCTAssertTrue(app.buttons["watch-chat-newer-messages"].waitForExistence(timeout: 5))
        older.tap()
        XCTAssertFalse(app.buttons["watch-chat-older-messages"].exists)
        XCTAssertTrue(app.staticTexts["Offline message 0"].waitForExistence(timeout: 5))
        XCTAssertFalse(sheet.exists, "Pages discard unrelated decrypted embeds")
        let newer = app.buttons["watch-chat-newer-messages"]
        newer.tap()
        XCTAssertTrue(older.waitForExistence(timeout: 5))
        newer.tap()
        XCTAssertTrue(sheet.waitForExistence(timeout: 5))
        XCTAssertFalse(newer.exists)
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = "Watch unopened recent chat offline with cached sheet and page controls"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    override func tearDownWithError() throws {
        if let testRun, testRun.failureCount > 0 {
            let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
            screenshot.name = "Watch failure screenshot — " + name
            screenshot.lifetime = .keepAlways
            add(screenshot)
            let hierarchy = XCTAttachment(string: XCUIApplication().debugDescription)
            hierarchy.name = "Watch failure accessibility tree — " + name
            hierarchy.lifetime = .keepAlways
            add(hierarchy)
        }
        try super.tearDownWithError()
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
        XCTAssertTrue(app.staticTexts["28 lines"].exists)

        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = "Watch opened chat Write embed"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.browse-search-open,apple-watch.chats.new-text-reply,apple-watch.chats.compact-layout
    func testChatsListShowsSearchNewChatAndExistingConversation() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-chat-layout", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
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
        let icon = row.descendants(matching: .any)["watch-chat-row-icon-watch-ui-test-chat"].firstMatch
        let title = row.staticTexts["watch-chat-row-title-watch-ui-test-chat"]
        XCTAssertTrue(icon.exists)
        XCTAssertEqual(icon.value as? String, "lucide-code", "The cached icon and category gradient remain the visual identity")
        XCTAssertTrue(title.exists)
        XCTAssertEqual(title.label, "Offline Whisper iOS Integration")
        XCTAssertGreaterThanOrEqual(title.frame.minX, icon.frame.maxX)
        XCTAssertFalse(row.staticTexts["watch-chat-row-category-watch-ui-test-chat"].exists,
                       "The category is represented by the gradient circle, never a text subtitle")
        XCTAssertFalse(row.staticTexts["Draft: I think ..."].exists,
                       "Chat summaries must not appear in the compact Watch list")

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
        let transcript = app.descendants(matching: .any)["watch-chat-shell"]
        XCTAssertTrue(back.waitForExistence(timeout: 12))
        XCTAssertTrue(card.exists)
        XCTAssertFalse(transcript.exists, "The transcript is hidden while recording covers the screen")
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
        XCTAssertTrue(transcript.waitForExistence(timeout: 5),
                      "The transcript is measured again after leaving recording")
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

extension WatchChatLayoutUITests {
    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.compact-layout
    func testSheetPreviewUsesRealCellsAboveFullWidthAppBarAndCenteredMetadata() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-chat-mobile-preview", "--ui-test-watch-embed-family", "spreadsheet",
            "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let card = app.buttons["watch-embed-preview-spreadsheet"]
        XCTAssertTrue(card.waitForExistence(timeout: 12))
        // SwiftUI exposes the table's individual readable cells with the
        // visual identifier; its VStack is not a distinct AX element.
        let visualCells = card.staticTexts.matching(identifier: "watch-embed-visual-watch-mobile-preview")
        let bar = app.descendants(matching: .any)["watch-embed-app-bar-watch-mobile-preview"]
        let title = app.staticTexts["watch-embed-title-watch-mobile-preview"]
        let metadata = app.staticTexts["watch-embed-metadata-watch-mobile-preview"]
        XCTAssertEqual(visualCells.count, 12, "One header plus three real two-column rows and their row numbers")
        XCTAssertTrue(bar.exists)
        XCTAssertTrue(title.exists)
        let deviceCells = visualCells.matching(NSPredicate(format: "label == %@", "Nexus Fold X"))
        XCTAssertEqual(deviceCells.count, 1)
        XCTAssertEqual(card.frame.width, 156, accuracy: 1)
        XCTAssertEqual(bar.frame.width, card.frame.width, accuracy: 1)
        for cell in visualCells.allElementsBoundByIndex {
            XCTAssertLessThanOrEqual(cell.frame.maxY, bar.frame.minY + 1, cell.label)
            XCTAssertGreaterThanOrEqual(cell.frame.minX, card.frame.minX, cell.label)
            XCTAssertLessThanOrEqual(cell.frame.maxX, card.frame.maxX, cell.label)
        }
        XCTAssertGreaterThan(title.frame.minY, bar.frame.maxY)
        XCTAssertGreaterThan(metadata.frame.minY, title.frame.maxY - 1)
        XCTAssertEqual(title.frame.midX, card.frame.midX, accuracy: 2)
        XCTAssertEqual(metadata.label, "58 cells")
        let text = app.staticTexts["watch-markdown-paragraph-0"]
        XCTAssertEqual(text.label, "Hello Watch")
        XCTAssertGreaterThanOrEqual(text.frame.height, 18, "Reading text uses the approved scalable 15pt default")
        XCTAssertLessThanOrEqual(card.frame.maxX, app.windows.firstMatch.frame.maxX)
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = "Watch mobile sheet preview and readable chat text"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.compact-layout
    func testEveryWatchPreviewFamilyUsesVerticalComposition() {
        // One production card composition covers metadata, content summaries,
        // code and real tables. Each known family exercises that shared view.
        let families = ["website", "webVideo", "image", "audioRecording", "code", "pdf", "mapPlace",
            "searchResults", "travelStay", "travelConnection", "shoppingProduct", "weather", "reminder",
            "event", "document", "spreadsheet", "mindmap", "audio", "application"]
        let app = XCUIApplication()
        for family in families {
            app.launchArguments = ["--ui-test-watch-chat-mobile-preview", "--ui-test-watch-embed-family", family]
            app.launch()
            let card = app.buttons["watch-embed-preview-\(family)"]
            XCTAssertTrue(card.waitForExistence(timeout: 12), family)
            let bar = app.descendants(matching: .any)["watch-embed-app-bar-watch-mobile-preview"]
            let title = app.staticTexts["watch-embed-title-watch-mobile-preview"]
            XCTAssertTrue(bar.exists, family)
            XCTAssertTrue(title.exists, family)
            XCTAssertEqual(bar.frame.width, card.frame.width, accuracy: 1, family)
            XCTAssertGreaterThan(title.frame.minY, bar.frame.maxY, family)
            XCTAssertEqual(title.frame.midX, card.frame.midX, accuracy: 2, family)
            XCTAssertEqual(card.frame.width, 156, accuracy: 1, family)
            app.terminate()
        }
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.compact-layout
    func testMissingPreviewPayloadIsVisibleAndContinuationRemainsAvailable() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-chat-mobile-preview", "--ui-test-watch-preview-missing-payload",
            "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let card = app.buttons["watch-embed-preview-spreadsheet"]
        XCTAssertTrue(card.waitForExistence(timeout: 12))
        let unavailable = app.staticTexts["Preview not available"]
        let transcript = app.scrollViews["watch-chat-shell"]
        for _ in 0..<3 where !transcript.frame.contains(unavailable.frame) {
            transcript.swipeUp()
        }
        XCTAssertTrue(unavailable.exists)
        XCTAssertTrue(transcript.frame.contains(unavailable.frame), "Unavailable state must be visible above the composer")
        XCTAssertFalse(app.staticTexts["Nexus Fold X"].exists)
        XCTAssertTrue(card.isEnabled)
        let tappableCard = card.frame.intersection(transcript.frame).insetBy(dx: 4, dy: 4)
        XCTAssertFalse(tappableCard.isEmpty)
        // A tall card's AX center can be obscured by the fixed composer. Tap
        // its visible intersection with the real transcript viewport.
        app.coordinate(withNormalizedOffset: .zero)
            .withOffset(CGVector(dx: tappableCard.midX, dy: tappableCard.midY)).tap()
        XCTAssertTrue(app.descendants(matching: .any)["watch-embed-continuation"].waitForExistence(timeout: 3))
        let openDevice = app.buttons["watch-embed-open-device"]
        XCTAssertTrue(openDevice.exists)
        XCTAssertTrue(openDevice.isEnabled)
        XCTAssertTrue(openDevice.isHittable)
        XCTAssertEqual(openDevice.label, "Open on iPhone")
        let close = app.buttons["watch-embed-continuation-close"]
        XCTAssertTrue(close.isHittable)
        close.tap()
        XCTAssertFalse(app.descendants(matching: .any)["watch-embed-continuation"].exists)
        XCTAssertTrue(card.exists, "Closing continuation returns to the unavailable preview")
    }
}

extension WatchChatLayoutUITests {
    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.compact-layout
    func testWatchTranscriptTextRespondsToLargerDynamicType() {
        let app = XCUIApplication()
        let arguments = ["--ui-test-watch-chat-mobile-preview", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launchArguments = arguments
        app.launch()
        let paragraph = app.staticTexts["watch-markdown-paragraph-0"]
        XCTAssertTrue(paragraph.waitForExistence(timeout: 12))
        let regularHeight = paragraph.frame.height
        XCTAssertGreaterThanOrEqual(regularHeight, 18)
        app.terminate()
        app.launchArguments = arguments + ["--ui-test-watch-large-text"]
        app.launch()
        XCTAssertTrue(paragraph.waitForExistence(timeout: 12))
        XCTAssertGreaterThan(paragraph.frame.height, regularHeight)
        XCTAssertEqual(paragraph.label, "Hello Watch")
        XCTAssertLessThanOrEqual(paragraph.frame.maxX, app.windows.firstMatch.frame.maxX)
    }
}

extension WatchChatLayoutUITests {
    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.compact-layout
    func testLongPressZoomControlsResizeTextAndPersistPreference() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-chat-mobile-preview", "--ui-test-watch-reset-zoom"]
        app.launch()
        let paragraph = app.staticTexts["watch-markdown-paragraph-0"]
        XCTAssertTrue(paragraph.waitForExistence(timeout: 12))
        let initial = paragraph.frame.height
        paragraph.press(forDuration: 1)
        let increase = app.buttons["watch-message-zoom-in"]
        XCTAssertTrue(increase.waitForExistence(timeout: 3)); XCTAssertTrue(increase.isHittable)
        increase.tap(); XCTAssertGreaterThan(paragraph.frame.height, initial)
        app.terminate()
        app.launchArguments = ["--ui-test-watch-chat-mobile-preview"]
        app.launch(); XCTAssertTrue(paragraph.waitForExistence(timeout: 12))
        XCTAssertGreaterThan(paragraph.frame.height, initial)
        paragraph.press(forDuration: 1)
        let decrease = app.buttons["watch-message-zoom-out"]
        XCTAssertTrue(decrease.waitForExistence(timeout: 3)); decrease.tap()
        XCTAssertEqual(paragraph.frame.height, initial, accuracy: 1)
        app.buttons["watch-message-zoom-close"].tap()
        XCTAssertFalse(increase.exists)
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.chats.compact-layout,apple-watch.embeds.read-only-fullscreen
    func testInlineCarouselRemainsBetweenTextAndOpensFullReadOnlySheet() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-chat-mobile-preview", "--ui-test-watch-preview-group", "--ui-test-watch-reset-zoom"]
        app.launch()
        let before = app.staticTexts["Before the previews"]
        XCTAssertTrue(before.waitForExistence(timeout: 12))
        let group = app.scrollViews["watch-message-embed-group-1"]
        XCTAssertTrue(group.exists)
        let second = app.staticTexts["watch-embed-title-watch-second-preview"]
        XCTAssertTrue(second.exists)
        XCTAssertGreaterThan(second.frame.minY, before.frame.maxY)
        group.swipeLeft()
        let card = app.buttons.matching(identifier: "watch-embed-preview-spreadsheet").allElementsBoundByIndex
            .first { $0.staticTexts["watch-embed-title-watch-mobile-preview"].exists && $0.isHittable }
        XCTAssertNotNil(card)
        card?.tap()
        let table = app.descendants(matching: .any)["watch-embed-fullscreen-table"]
        XCTAssertTrue(table.waitForExistence(timeout: 3))
        XCTAssertTrue(app.staticTexts["Nexus Fold X"].exists)
        let fullscreenScreenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        fullscreenScreenshot.name = "Watch read-only sheet before composer exclusion assertion"
        fullscreenScreenshot.lifetime = .keepAlways
        add(fullscreenScreenshot)
        let fullscreenHierarchy = XCTAttachment(string: app.debugDescription)
        fullscreenHierarchy.name = "Watch read-only sheet accessibility tree"
        fullscreenHierarchy.lifetime = .keepAlways
        add(fullscreenHierarchy)
        XCTAssertFalse(app.textFields.firstMatch.exists, "Fullscreen has no editing controls")
        XCTAssertFalse(app.scrollViews["watch-chat-shell"].exists, "The underlying chat must be inaccessible in fullscreen")
        app.buttons["watch-embed-continuation-close"].tap()
        XCTAssertTrue(group.waitForExistence(timeout: 3))
        XCTAssertTrue(app.textFields["watch-message-input"].isHittable, "Back restores the chat composer")
        let transcript = app.scrollViews["watch-chat-shell"]
        for _ in 0..<4 where !app.staticTexts["After the previews"].isHittable { transcript.swipeUp() }
        XCTAssertTrue(app.staticTexts["After the previews"].isHittable)
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.embeds.read-only-fullscreen
    func testReadOnlyMapUsesCoordinatesAndImageUsesAvailableThumbnail() {
        let app = XCUIApplication()
        for family in ["mapPlace", "image"] {
            app.launchArguments = ["--ui-test-watch-chat-mobile-preview", "--ui-test-watch-embed-family", family]
            app.launch()
            let card = app.buttons["watch-embed-preview-" + family]
            XCTAssertTrue(card.waitForExistence(timeout: 12))
            let transcript = app.scrollViews["watch-chat-shell"]
            let visible = card.frame.intersection(transcript.frame).insetBy(dx: 4, dy: 4)
            XCTAssertFalse(visible.isEmpty)
            app.coordinate(withNormalizedOffset: .zero).withOffset(CGVector(dx: visible.midX, dy: visible.midY)).tap()
            let identifier = family == "mapPlace" ? "watch-embed-read-only-map" : "watch-embed-thumbnail"
            XCTAssertTrue(app.descendants(matching: .any)[identifier].waitForExistence(timeout: 3))
            XCTAssertTrue(app.buttons["watch-embed-continuation-close"].isHittable)
            app.terminate()
        }
    }
}


extension WatchChatLayoutUITests {
    @MainActor
    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.compact-layout,apple-watch.embeds.read-only-fullscreen
    func testCodeEnvelopePreviewOpensReadOnlyFullscreenAndReturnsToChat() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-chat-mobile-preview", "--ui-test-watch-embed-family", "code",
            "--ui-test-watch-code-envelope", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let card = app.buttons["watch-embed-preview-code"]
        XCTAssertTrue(card.waitForExistence(timeout: 12))
        let title = app.staticTexts["watch-embed-title-watch-mobile-preview"]
        XCTAssertEqual(title.label, "watch-preview.swift")
        XCTAssertEqual(app.staticTexts["watch-embed-metadata-watch-mobile-preview"].label, "3 lines")
        XCTAssertFalse(app.staticTexts["Preview not available"].exists)
        XCTAssertEqual(card.frame.width, 156, accuracy: 1)
        let transcript = app.scrollViews["watch-chat-shell"]
        XCTAssertTrue(transcript.exists)
        let visible = card.frame.intersection(transcript.frame).insetBy(dx: 5, dy: 5)
        XCTAssertFalse(visible.isEmpty)
        let before = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        before.name = "Watch hydrated code dark inline preview"
        before.lifetime = .keepAlways; add(before)
        app.coordinate(withNormalizedOffset: .zero)
            .withOffset(CGVector(dx: visible.midX, dy: visible.midY)).tap()
        XCTAssertTrue(app.descendants(matching: .any)["watch-embed-continuation"].waitForExistence(timeout: 5))
        let code = app.staticTexts["watch-embed-fullscreen-code-text"]
        XCTAssertTrue(code.waitForExistence(timeout: 5))
        XCTAssertTrue(code.label.contains("let lastLine = 3"), "Fullscreen preserves the complete source")
        XCTAssertFalse(app.textFields["watch-message-input"].exists)
        XCTAssertFalse(app.descendants(matching: .any)["watch-embed-fullscreen-unavailable"].exists)
        let close = app.buttons["watch-embed-continuation-close"]
        XCTAssertTrue(close.isHittable)
        assertWatchEmbedDarkPixel(at: CGPoint(x: app.frame.midX, y: app.frame.maxY - 4))
        let opened = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        opened.name = "Watch code read-only dark fullscreen"
        opened.lifetime = .keepAlways; add(opened)
        close.tap()
        XCTAssertTrue(card.waitForExistence(timeout: 5))
        XCTAssertTrue(app.textFields["watch-message-input"].exists)
    }

    @MainActor
    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.compact-layout,apple-watch.embeds.read-only-fullscreen
    func testUnavailableCodePreviewIsCompactAndStillOpensFullscreen() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-chat-mobile-preview", "--ui-test-watch-embed-family", "code",
            "--ui-test-watch-preview-missing-payload", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let card = app.buttons["watch-embed-preview-code"]
        XCTAssertTrue(card.waitForExistence(timeout: 12))
        XCTAssertLessThan(card.frame.height, 196, "Missing content must not reserve a second symbol-only visual")
        XCTAssertFalse(app.descendants(matching: .any)["watch-embed-visual-watch-mobile-preview"].exists)
        XCTAssertTrue(app.staticTexts["Preview not available"].exists)
        XCTAssertTrue(card.isEnabled)
        let transcript = app.scrollViews["watch-chat-shell"]
        let visible = card.frame.intersection(transcript.frame).insetBy(dx: 5, dy: 5)
        XCTAssertFalse(visible.isEmpty)
        for _ in 0..<3 where card.frame.maxY > transcript.frame.maxY { transcript.swipeUp() }
        XCTAssertLessThanOrEqual(card.frame.maxY, transcript.frame.maxY)
        assertWatchEmbedDarkPixel(at: CGPoint(x: card.frame.midX, y: card.frame.maxY - 3))
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = "Watch compact unavailable code dark preview"
        attachment.lifetime = .keepAlways; add(attachment)
        let tapBounds = card.frame.intersection(transcript.frame).insetBy(dx: 5, dy: 5)
        app.coordinate(withNormalizedOffset: .zero)
            .withOffset(CGVector(dx: tapBounds.midX, dy: tapBounds.midY)).tap()
        XCTAssertTrue(app.descendants(matching: .any)["watch-embed-continuation"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["watch-embed-fullscreen-unavailable"].waitForExistence(timeout: 3))
        XCTAssertTrue(app.buttons["watch-embed-open-device"].isHittable)
        let close = app.buttons["watch-embed-continuation-close"]
        XCTAssertTrue(close.isHittable)
        close.tap()
        XCTAssertTrue(card.waitForExistence(timeout: 5))
    }

    @MainActor
    private func assertWatchEmbedDarkPixel(at point: CGPoint, file: StaticString = #filePath, line: UInt = #line) {
        let image = XCUIScreen.main.screenshot().image
        guard let cgImage = image.cgImage else { return XCTFail("Watch screenshot is unavailable", file: file, line: line) }
        let pixelRect = CGRect(x: floor(point.x * CGFloat(cgImage.width) / image.size.width),
                               y: floor(point.y * CGFloat(cgImage.height) / image.size.height), width: 1, height: 1)
        guard let cropped = cgImage.cropping(to: pixelRect) else {
            return XCTFail("Dark surface point is outside the rendered screen", file: file, line: line)
        }
        var pixel = [UInt8](repeating: 0, count: 4)
        let rendered = pixel.withUnsafeMutableBytes { bytes -> Bool in
            guard let context = CGContext(data: bytes.baseAddress, width: 1, height: 1,
                bitsPerComponent: 8, bytesPerRow: 4, space: CGColorSpaceCreateDeviceRGB(),
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return false }
            context.draw(cropped, in: CGRect(x: 0, y: 0, width: 1, height: 1))
            return true
        }
        XCTAssertTrue(rendered, file: file, line: line)
        XCTAssertLessThan(pixel[0], 95, "Embed surface must match the dark Watch transcript", file: file, line: line)
        XCTAssertLessThan(pixel[1], 95, file: file, line: line)
        XCTAssertLessThan(pixel[2], 95, file: file, line: line)
    }

}
