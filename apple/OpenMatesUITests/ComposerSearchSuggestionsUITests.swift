import XCTest

@MainActor
final class ComposerSearchSuggestionsUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // contract-test: direct surface=gui.apple assertions=message-input.suggestions.contextual,message-input.embeds.gated-send
    func testTypedSearchCardsAreVisibleAndSelectionInsertsExistingEmbed() {
        let app = launch()
        let embed = app.buttons["recent-embed-search-result"].firstMatch
        XCTAssertTrue(embed.waitForExistence(timeout: 10))
        XCTAssertTrue(embed.isHittable)
        attach("Typed composer embeds and chats")
        embed.tap()
        let action = app.staticTexts["composer-search-preview-action"]
        expectation(for: NSPredicate(format: "label == %@", "inserted-embed:preview-berlin-notebook"), evaluatedWith: action)
        waitForExpectations(timeout: 5)
        let editor = app.descendants(matching: .any).matching(identifier: "message-editor").firstMatch
        XCTAssertTrue(editor.exists)
        attach("Existing durable embed inserted into composer")
    }

    // contract-test: direct surface=gui.apple assertions=message-input.suggestions.contextual
    func testRelatedChatCardNavigatesAndClearingQueryHidesResults() {
        let app = launch()
        let chat = app.buttons["chat-search-result"].firstMatch
        XCTAssertTrue(chat.waitForExistence(timeout: 10))
        let carousel = app.scrollViews["composer-search-results-carousel"]
        XCTAssertTrue(carousel.exists)
        // An edge of the next card is intentionally visible. `isHittable` can
        // be true while its center is outside the scroll viewport, so reveal
        // the complete card before synthesizing the center tap.
        for _ in 0..<3 where chat.frame.maxX > carousel.frame.maxX - 8 {
            carousel.swipeLeft()
        }
        XCTAssertGreaterThanOrEqual(chat.frame.minX, carousel.frame.minX + 8)
        XCTAssertLessThanOrEqual(chat.frame.maxX, carousel.frame.maxX - 8)
        XCTAssertTrue(chat.isHittable)
        chat.tap()
        let action = app.staticTexts["composer-search-preview-action"]
        expectation(for: NSPredicate(format: "label == %@", "opened-chat:preview-berlin"), evaluatedWith: action)
        waitForExpectations(timeout: 5)
        let editor = app.descendants(matching: .any).matching(identifier: "message-editor").firstMatch
        XCTAssertTrue(editor.exists)
        editor.tap()
        #if os(macOS)
        editor.typeKey("a", modifierFlags: .command)
        #else
        editor.press(forDuration: 1.1)
        let menuSelectAll = app.menuItems["Select All"]
        let selectAll = menuSelectAll.exists ? menuSelectAll : app.buttons["Select All"]
        XCTAssertTrue(selectAll.waitForExistence(timeout: 5), "Native Select All must be available to clear the query")
        selectAll.tap()
        #endif
        editor.typeText(XCUIKeyboardKey.delete.rawValue)
        expectation(for: NSPredicate(format: "value == %@", ""), evaluatedWith: editor)
        waitForExpectations(timeout: 5)
        expectation(for: NSPredicate(format: "exists == false"), evaluatedWith: chat)
        waitForExpectations(timeout: 5)
        XCTAssertFalse(app.buttons["recent-embed-search-result"].firstMatch.exists)
        attach("Cleared composer hides contextual results")
    }

    private func launch() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "composer", "--dev-preview-variant", "search-suggestions",
            "--dev-preview-theme", "light", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        return app
    }

    private func attach(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
