import XCTest

@MainActor
final class NativeEmbedActionUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testCalendarOpensActualSystemEditorAndCancelsWithoutSaving() {
        let app = launch("action-calendar")
        tapAction("embed-calendar-button", app: app)
        let editor = app.descendants(matching: .any)["native-embed-calendar-editor"].firstMatch
        XCTAssertTrue(editor.waitForExistence(timeout: 5), app.debugDescription)
        XCTAssertTrue(app.buttons["Cancel"].firstMatch.waitForExistence(timeout: 5))
        XCTAssertTrue(app.textFields.matching(NSPredicate(format: "value CONTAINS %@", "Public calendar fixture")).firstMatch.exists,
            app.debugDescription)
        screenshot("native-calendar-editor")
        app.buttons["Cancel"].firstMatch.tap()
        // EventKit may confirm discarding the unsaved editor on some OS versions.
        let discard = app.buttons["Discard Changes"].firstMatch
        if discard.waitForExistence(timeout: 1) { discard.tap() }
        XCTAssertTrue(editor.waitForNonExistence(timeout: 5))
        XCTAssertTrue(app.descendants(matching: .any)["dev-fullscreen-action-fixture"].firstMatch.exists)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.persistence.client-encrypted
    func testCodeDownloadOpensActualPlatformExportAndCancels() {
        let app = launch("action-export")
        tapAction("embed-download-button", app: app)
        let export = app.descendants(matching: .any)["native-embed-file-export"].firstMatch
        XCTAssertTrue(export.waitForExistence(timeout: 5), app.debugDescription)
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "public-export")).firstMatch.exists,
            app.debugDescription)
        screenshot("native-file-export")
        let close = app.buttons["Close"].firstMatch
        XCTAssertTrue(close.waitForExistence(timeout: 5), app.debugDescription)
        close.tap()
        XCTAssertTrue(export.waitForNonExistence(timeout: 5))
        XCTAssertTrue(app.descendants(matching: .any)["dev-fullscreen-action-fixture"].firstMatch.exists)
    }

    private func tapAction(_ id: String, app: XCUIApplication) {
        let button = app.buttons[id].firstMatch
        if !button.isHittable {
            let more = app.buttons["embed-more-button"].firstMatch
            XCTAssertTrue(more.waitForExistence(timeout: 5)); more.tap()
        }
        XCTAssertTrue(button.waitForExistence(timeout: 5)); XCTAssertTrue(button.isHittable); button.tap()
    }
    private func launch(_ variant: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "message", "--dev-preview-variant", variant, "--dev-preview-width", "390"]
        app.launch(); return app
    }
    private func screenshot(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot()); attachment.name = name
        attachment.lifetime = .keepAlways; add(attachment)
    }
}
