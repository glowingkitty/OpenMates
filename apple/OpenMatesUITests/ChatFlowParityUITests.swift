// UI parity smoke coverage for the native chat-flow surface.
// Uses the debug-only seeded chat preview so assertions are deterministic and
// do not require credentials, private chat records, network access, or AI calls.
// The deterministic parity audit covers token/source mappings; this simulator
// test verifies the visible native hierarchy exposes the expected chat elements.

import XCTest

@MainActor
final class ChatFlowParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testVisibleChatFlowElementsMatchWebParitySnapshot() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "chat-opening", "--ui-test-header-contract"]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
        app.launchEnvironment["UI_TEST_HEADER_CONTRACT"] = "1"
        app.launch()

        let counter = app.staticTexts
            .containing(NSPredicate(format: "label CONTAINS %@", "initial-window-count=50"))
            .firstMatch
        XCTAssertTrue(counter.waitForExistence(timeout: 12))
        attachScreenshot(name: "Seeded chat-flow loaded")

        XCTAssertTrue(app.staticTexts["Native Chat Opening Preview"].exists)
        let headerContract = app.staticTexts
            .containing(NSPredicate(format: "label CONTAINS %@", "chat-header-title="))
            .firstMatch
        XCTAssertTrue(headerContract.waitForExistence(timeout: 5))
        XCTAssertTrue(headerContract.label.contains("chat-header-title=Seeded Large Chat"))
        XCTAssertTrue(headerContract.label.contains("chat-header-icon=true"))

        let userMessage = app.staticTexts
            .containing(NSPredicate(format: "label CONTAINS %@", "Seeded user message"))
            .firstMatch
        let assistantMessage = app.staticTexts
            .containing(NSPredicate(format: "label CONTAINS %@", "Seeded assistant message"))
            .firstMatch
        XCTAssertTrue(userMessage.waitForExistence(timeout: 5))
        XCTAssertTrue(assistantMessage.waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Latest assistant response visible after bounded open"].exists)
        XCTAssertTrue(app.textViews.firstMatch.exists || app.textFields.firstMatch.exists)
        XCTAssertFalse(app.tables.firstMatch.exists, "Product chat UI must not render default List/table chrome")

        attachScreenshot(name: "Seeded chat-flow parity hierarchy")
    }

    func testVisualChatFlowSurfaceUsesProductChromeOnly() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "chat-opening", "--ui-test-visual-snapshot"]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
        app.launchEnvironment["UI_TEST_VISUAL_SNAPSHOT"] = "1"
        app.launch()

        let scrollToBottom = app.buttons["Scroll to bottom"]
        XCTAssertTrue(scrollToBottom.waitForExistence(timeout: 12))
        scrollToBottom.tap()

        let latestAssistantMessage = app.staticTexts["Latest assistant response visible after bounded open"]
        XCTAssertTrue(latestAssistantMessage.waitForExistence(timeout: 12))
        XCTAssertFalse(app.staticTexts["Native Chat Opening Preview"].exists)
        XCTAssertFalse(app.tables.firstMatch.exists, "Product chat UI must not render default List/table chrome")

        attachScreenshot(name: "Seeded chat-flow visual snapshot")
    }

    func testGuestInterestTagsSelectAndFilterSuggestions() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-start-new-chat"]
        app.launch()

        XCTAssertTrue(app.descendants(matching: .any)["guest-interest-tags"].waitForExistence(timeout: 15))
        XCTAssertFalse(app.buttons["guest-interest-continue"].exists)

        tapInterestTag("privacy", in: app)
        tapInterestTag("learning", in: app)
        tapInterestTag("writing", in: app)
        XCTAssertFalse(app.buttons["guest-interest-continue"].exists)
        tapInterestTag("software_development", in: app)

        let continueButton = app.buttons["guest-interest-continue"]
        XCTAssertTrue(continueButton.waitForExistence(timeout: 5))
        continueButton.tap()

        XCTAssertTrue(app.buttons["guest-interest-select-interests"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["welcome-chat-card-demo-for-everyone"].waitForExistence(timeout: 10))

        let codingSuggestion = app.buttons["new-chat-suggestion-card-chat.new_chat_suggestions.learn_coding"]
        XCTAssertTrue(codingSuggestion.waitForExistence(timeout: 10))

        let messageEditor = app.textFields["message-editor"]
        XCTAssertTrue(messageEditor.waitForExistence(timeout: 5))
        messageEditor.tap()
        messageEditor.typeText("coding")

        XCTAssertTrue(codingSuggestion.waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["new-chat-suggestion-card-chat.new_chat_suggestions.cover_letter"].exists)
        XCTAssertFalse(app.tables.firstMatch.exists, "Product chat UI must not render default List/table chrome")

        attachScreenshot(name: "Guest interest tag selection filters suggestions")
    }

    private func tapInterestTag(_ tagId: String, in app: XCUIApplication) {
        let tag = app.buttons["interest-tag-\(tagId)"]
        XCTAssertTrue(tag.waitForExistence(timeout: 5), "Expected interest tag \(tagId)")
        tag.tap()
        XCTAssertTrue(app.descendants(matching: .any)["interest-tag-\(tagId)-check"].waitForExistence(timeout: 5))
    }

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

}
