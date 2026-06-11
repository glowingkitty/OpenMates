// UI parity coverage for the native Interface → Language settings path.
// Mirrors the web language settings flow as closely as native allows without
// browser DOM/localStorage assertions or a private authenticated account.
// Verifies language selection state, translated UI refresh, reset to English,
// stable identifiers, and absence of default table chrome.

import XCTest

@MainActor
final class SettingsInterfaceLanguageParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testLanguageSelectionSwitchesDeutschAndBackToEnglish() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache"]
        app.launch()

        openLanguageSettings(in: app)

        XCTAssertTrue(waitForElement("settings-language-option-en", in: app, timeout: 5))
        XCTAssertTrue(waitForElement("settings-language-option-de", in: app, timeout: 5))

        app.descendants(matching: .any)["settings-language-option-de"].tap()
        returnToInterfaceIfNeeded(in: app, expectedText: "Sprache")

        app.descendants(matching: .any)["settings-interface-language-row"].tap()
        XCTAssertTrue(waitForElement("settings-language-option-en", in: app, timeout: 5))
        app.descendants(matching: .any)["settings-language-option-en"].tap()
        returnToInterfaceIfNeeded(in: app, expectedText: "Language")
        XCTAssertFalse(app.tables.firstMatch.exists, "Language settings must not render default List/table chrome")

        attachScreenshot(name: "Interface language parity")
    }

    private func openLanguageSettings(in app: XCUIApplication) {
        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15))
        app.buttons["settings-button"].tap()
        XCTAssertTrue(waitForElement("settings-menu", in: app, timeout: 10))
        XCTAssertTrue(waitForElement("settings-interface-row", in: app, timeout: 5))
        app.descendants(matching: .any)["settings-interface-row"].tap()
        XCTAssertTrue(waitForElement("settings-interface-page", in: app, timeout: 8))
        XCTAssertTrue(waitForElement("settings-interface-language-row", in: app, timeout: 5))
        app.descendants(matching: .any)["settings-interface-language-row"].tap()
        XCTAssertTrue(waitForElement("settings-language-option-en", in: app, timeout: 5))
    }

    private func waitForElement(_ identifier: String, in app: XCUIApplication, timeout: TimeInterval) -> Bool {
        let element = app.descendants(matching: .any)[identifier]
        if element.waitForExistence(timeout: timeout) { return true }

        let scrollView = app.scrollViews.firstMatch
        for _ in 0..<6 where scrollView.exists {
            scrollView.swipeUp()
            if element.waitForExistence(timeout: 1) { return true }
        }
        return false
    }

    private func returnToInterfaceIfNeeded(in app: XCUIApplication, expectedText: String) {
        let backButton = app.descendants(matching: .any)["settings-language-back"]
        if backButton.waitForExistence(timeout: 2) {
            backButton.tap()
        }
        XCTAssertTrue(waitForElement("settings-interface-page", in: app, timeout: 5))
        XCTAssertTrue(waitForText(expectedText, in: app, timeout: 5))
    }

    private func waitForText(_ text: String, in app: XCUIApplication, timeout: TimeInterval) -> Bool {
        let label = app.staticTexts[text]
        if label.waitForExistence(timeout: timeout) { return true }

        let scrollView = app.scrollViews.firstMatch
        for _ in 0..<4 where scrollView.exists {
            scrollView.swipeUp()
            if label.waitForExistence(timeout: 1) { return true }
        }
        return false
    }

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
