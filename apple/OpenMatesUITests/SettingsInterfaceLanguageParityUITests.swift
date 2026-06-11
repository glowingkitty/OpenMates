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
        XCTAssertTrue(app.buttons["settings-language-option-en"].isSelected)
        XCTAssertFalse(app.buttons["settings-language-option-de"].isSelected)

        app.descendants(matching: .any)["settings-language-option-de"].tap()
        XCTAssertTrue(waitForLanguageSelection("settings-language-option-de", selected: true, in: app, timeout: 5))
        XCTAssertFalse(app.buttons["settings-language-option-en"].isSelected)
        XCTAssertTrue(waitForElement("settings-language-back", in: app, timeout: 3))
        app.descendants(matching: .any)["settings-language-back"].tap()
        XCTAssertTrue(waitForElement("settings-interface-page", in: app, timeout: 5))
        XCTAssertTrue(waitForText("Sprache", in: app, timeout: 5))

        app.descendants(matching: .any)["settings-interface-language-row"].tap()
        XCTAssertTrue(waitForElement("settings-language-page", in: app, timeout: 5))
        app.descendants(matching: .any)["settings-language-option-en"].tap()
        XCTAssertTrue(waitForLanguageSelection("settings-language-option-en", selected: true, in: app, timeout: 5))
        XCTAssertFalse(app.buttons["settings-language-option-de"].isSelected)
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

    private func waitForLanguageSelection(
        _ identifier: String,
        selected: Bool,
        in app: XCUIApplication,
        timeout: TimeInterval
    ) -> Bool {
        let button = app.buttons[identifier]
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if button.exists, button.isSelected == selected { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        }
        return false
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
