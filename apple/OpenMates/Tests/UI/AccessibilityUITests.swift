// Accessibility UI tests — maps to: a11y-keyboard-nav.spec.ts,
// a11y-modal-dialogs.spec.ts, a11y-pages.spec.ts

import XCTest

final class AccessibilityUITests: XCTestCase {

    var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["--uitesting", "--authenticated"]
        app.launch()
    }

    // MARK: - Core elements have accessibility labels (a11y-pages)

    func testChatListHasAccessibilityLabels() {
        let chatNav = app.navigationBars["Chats"]
        XCTAssertTrue(chatNav.waitForExistence(timeout: 10))

        let newChatBtn = app.buttons["new-chat-button"]
        XCTAssertTrue(newChatBtn.waitForExistence(timeout: 5))
        XCTAssertFalse(newChatBtn.label.isEmpty, "New chat button should have accessibility label")
    }

    func testSettingsButtonHasLabel() {
        let settingsBtn = app.buttons["settings-button"]
        XCTAssertTrue(settingsBtn.waitForExistence(timeout: 10))
        XCTAssertFalse(settingsBtn.label.isEmpty)
    }

    func testChatItemsHaveLabels() {
        let chatItem = app.cells.matching(identifier: "chat-item-wrapper").firstMatch
        guard chatItem.waitForExistence(timeout: 10) else { return }
        XCTAssertFalse(chatItem.label.isEmpty, "Chat items should have combined accessibility label")
    }

    // MARK: - Message input accessibility (a11y-keyboard-nav)

    func testMessageInputAccessibility() {
        openExistingChat()
        let input = app.textFields["Chat message input"]
        XCTAssertTrue(input.waitForExistence(timeout: 10))
        XCTAssertFalse(input.label.isEmpty)
    }

    func testSendButtonAccessibility() {
        openExistingChat()
        let input = app.textFields["Chat message input"]
        guard input.waitForExistence(timeout: 10) else { return }
        input.tap()
        input.typeText("test")

        let sendBtn = app.buttons["Send message"]
        XCTAssertTrue(sendBtn.waitForExistence(timeout: 5))
    }

    // MARK: - Modal dialogs have dismiss actions (a11y-modal-dialogs)

    func testSettingsModalHasDoneButton() {
        let settingsBtn = app.buttons["settings-button"]
        guard settingsBtn.waitForExistence(timeout: 10) else { return }
        settingsBtn.tap()

        let done = app.buttons["Done"]
        XCTAssertTrue(done.waitForExistence(timeout: 5), "Settings modal should have Done button")
    }

    func testNewChatSheetHasCancelButton() {
        let newChat = app.buttons["new-chat-button"]
        guard newChat.waitForExistence(timeout: 10) else { return }
        newChat.tap()

        let cancel = app.buttons["Cancel"]
        XCTAssertTrue(cancel.waitForExistence(timeout: 5), "New chat sheet should have Cancel button")
    }

    // MARK: - Embed previews have accessibility info

    func testEmbedPreviewAccessibility() {
        openExistingChat()
        let embed = app.otherElements["embed-preview"]
        if embed.waitForExistence(timeout: 10) {
            XCTAssertFalse(embed.label.isEmpty, "Embed preview should have accessibility label")
        }
    }

    // MARK: - Helpers

    private func openExistingChat() {
        let chatItem = app.cells.matching(identifier: "chat-item-wrapper").firstMatch
        guard chatItem.waitForExistence(timeout: 10) else { return }
        chatItem.tap()
    }
}
