import XCTest

/// Editing a stored personal Project code file in the embed fullscreen: Edit opens the
/// editor, Save commits the next version (local preview client) and shows the saved code.
final class CodeEmbedEditUITests: XCTestCase {
    override func setUp() {
        continueAfterFailure = false
    }

    private func headerButton(_ app: XCUIApplication, _ id: String) -> XCUIElement {
        let direct = app.buttons[id]
        if direct.waitForExistence(timeout: 3), direct.isHittable { return direct }
        let more = app.buttons["embed-more-button"]
        XCTAssertTrue(more.waitForExistence(timeout: 5), "\(id) must be in the header or its More menu")
        more.tap()
        XCTAssertTrue(direct.waitForExistence(timeout: 5))
        return direct
    }

    private func attachScreenshot(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    // contract-test: direct surface=gui.apple assertions=embed-user-edits.edit.next-version,embed-user-edits.header.edit-save-button
    func testEditAndSaveCodeEmbedShowsSavedVersion() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "code",
                               "--embed-registry-key", "code-code", "--embed-surface", "fullscreen", "--embed-variant", "singleEmbed",
                               "--ui-test-code-edit-versions", "--dev-preview-theme", "light",
                               "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        XCTAssertTrue(app.descendants(matching: .any)["code-source-panel"].firstMatch.waitForExistence(timeout: 10))
        let subtitle = app.staticTexts["embed-header-subtitle"].firstMatch
        XCTAssertTrue(subtitle.waitForExistence(timeout: 5))
        let subtitleBefore = subtitle.label
        attachScreenshot("Code embed before edit")

        headerButton(app, "embed-edit-button").tap()
        let editor = app.textViews["code-editor-textarea"]
        XCTAssertTrue(editor.waitForExistence(timeout: 5), "Edit opens the code editor")
        editor.tap()
        editor.typeText("\n# edited on Apple")
        attachScreenshot("Code embed editor with change")

        headerButton(app, "embed-edit-button").tap()
        let saved = app.descendants(matching: .any)["code-saved-text"].firstMatch
        XCTAssertTrue(saved.waitForExistence(timeout: 10), "Save shows the saved next version")
        // The highlighted code view exposes its source as one read-only text view.
        let source = saved.textViews["code-readonly-source"].firstMatch
        XCTAssertTrue(source.waitForExistence(timeout: 5), "The saved version renders in the highlighted code view")
        XCTAssertTrue((source.value as? String ?? source.label).contains("# edited on Apple"),
                      "The saved version shows the edited line")
        XCTAssertNotEqual(subtitle.label, subtitleBefore, "The header counts the saved version's lines")
        XCTAssertFalse(app.descendants(matching: .any)["code-editor-error"].firstMatch.exists)
        XCTAssertFalse(editor.exists, "Save closes the editor")
        attachScreenshot("Code embed saved as next version")
    }
}
