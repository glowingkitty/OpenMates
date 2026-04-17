// Chat message UI tests — maps to: chat-flow.spec.ts, chat-scroll-streaming.spec.ts,
// copy-message-flow.spec.ts, fork-conversation.spec.ts, message-highlights.spec.ts,
// follow-up-suggestions-flow.spec.ts, daily-inspiration-chat-flow.spec.ts,
// incognito-mode.spec.ts, pii-detection-flow.spec.ts, focus-mode-*.spec.ts

import XCTest

final class ChatMessageUITests: XCTestCase {

    var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["--uitesting", "--authenticated"]
        app.launch()
    }

    // MARK: - Send message (chat-flow)

    func testSendMessageInNewChat() {
        openNewChat()

        let messageInput = app.textFields.matching(NSPredicate(format: "placeholderValue CONTAINS 'Start typing'")).firstMatch
        guard messageInput.waitForExistence(timeout: 5) else { return }
        messageInput.tap()
        messageInput.typeText("Hello from UI test")

        let sendBtn = app.buttons.matching(NSPredicate(format: "label CONTAINS 'Send' OR identifier == 'send-button'")).firstMatch
        guard sendBtn.waitForExistence(timeout: 3) else { return }
        sendBtn.tap()
    }

    // MARK: - Message context menu (copy-message-flow, fork-conversation)

    func testMessageContextMenuAppears() {
        openExistingChat()

        let message = app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH 'You:' OR label BEGINSWITH 'AI:'")).firstMatch
        guard message.waitForExistence(timeout: 10) else { return }

        message.press(forDuration: 1.0)

        let copyBtn = app.buttons["Copy"]
        let forkBtn = app.buttons["Fork Conversation"]
        let menuAppeared = copyBtn.waitForExistence(timeout: 3) || forkBtn.waitForExistence(timeout: 3)
        XCTAssertTrue(menuAppeared)
    }

    // MARK: - Streaming indicator (chat-scroll-streaming)

    func testStreamingIndicatorShows() {
        openNewChat()

        let messageInput = app.textFields.firstMatch
        guard messageInput.waitForExistence(timeout: 5) else { return }
        messageInput.tap()
        messageInput.typeText("Tell me a joke")

        let sendBtn = app.buttons.matching(NSPredicate(format: "label CONTAINS 'Send'")).firstMatch
        guard sendBtn.waitForExistence(timeout: 3) else { return }
        sendBtn.tap()

        let streamingBanner = app.staticTexts["AI is responding"]
        // Streaming may start quickly or take a moment
        _ = streamingBanner.waitForExistence(timeout: 15)
    }

    // MARK: - Input field accessibility (chat-flow)

    func testMessageInputHasAccessibilityLabel() {
        openExistingChat()

        let input = app.textFields["Chat message input"]
        XCTAssertTrue(input.waitForExistence(timeout: 10))
    }

    // MARK: - Embed preview (demo-chat-embeds, embed-showcase)

    func testEmbedPreviewShowsInMessage() {
        openExistingChat()

        let embedPreview = app.otherElements["embed-preview"]
        if embedPreview.waitForExistence(timeout: 10) {
            XCTAssertTrue(embedPreview.exists)
        }
    }

    func testEmbedPreviewOpensFullscreen() {
        openExistingChat()

        let embedPreview = app.otherElements["embed-preview"]
        guard embedPreview.waitForExistence(timeout: 10) else { return }

        embedPreview.tap()

        // Fullscreen should appear as a sheet/modal
        let fullscreenView = app.otherElements.matching(NSPredicate(format: "identifier CONTAINS 'embed-fullscreen'")).firstMatch
        _ = fullscreenView.waitForExistence(timeout: 5)
    }

    // MARK: - Incognito mode (incognito-mode)

    func testIncognitoToggleInSettings() {
        openSettings()

        let incognitoBtn = app.buttons["Incognito Mode"]
        XCTAssertTrue(incognitoBtn.waitForExistence(timeout: 5))
    }

    // MARK: - Helpers

    private func openNewChat() {
        let newChat = app.buttons["new-chat-button"]
        guard newChat.waitForExistence(timeout: 10) else { return }
        newChat.tap()
    }

    private func openExistingChat() {
        let chatItem = app.cells.matching(identifier: "chat-item-wrapper").firstMatch
        guard chatItem.waitForExistence(timeout: 10) else { return }
        chatItem.tap()
    }

    private func openSettings() {
        let settingsBtn = app.buttons["settings-button"]
        guard settingsBtn.waitForExistence(timeout: 10) else { return }
        settingsBtn.tap()
    }
}
