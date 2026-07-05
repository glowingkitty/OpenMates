// Message input attachment parity coverage for Apple UI contracts.
// Uses the debug-only seeded ChatView preview and simulator-safe fixture seeding
// so the composer pending-embed hierarchy can be verified without private
// credentials, system pickers, upload keys, or camera hardware.

import XCTest

@MainActor
final class MessageInputAttachmentUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testSeededPendingAttachmentMatchesMessageInputContractStructure() throws {
        let app = launchChatOpeningPreview(arguments: ["--ui-test-seed-pending-composer-embed"])

        XCTAssertTrue(app.staticTexts["Native Chat Opening Preview"].waitForExistence(timeout: 12))
        let pendingEmbed = element(in: app, identifiers: ["pending-composer-embed", "embed-full-width-wrapper"])
        XCTAssertTrue(pendingEmbed.waitForExistence(timeout: 10))
        XCTAssertFalse(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "```json")).firstMatch.exists)

        focusComposerInput(in: app)
        XCTAssertTrue(element(in: app, identifier: "attach-files-button").waitForExistence(timeout: 5))
        XCTAssertTrue(element(in: app, identifier: "take-photo-button").waitForExistence(timeout: 5))

        let screenshot = XCUIScreen.main.screenshot()
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = "Message input pending attachment contract state"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    func testComposerWarningHighlightsAndExclusions() throws {
        let app = launchChatOpeningPreview(arguments: ["--ui-test-pii-composer-banner-fixture"])
        XCTAssertTrue(app.staticTexts["Native Chat Opening Preview"].waitForExistence(timeout: 12))
        XCTAssertTrue(app.staticTexts["PII Composer Banner Fixture"].waitForExistence(timeout: 5))

        let banner = app.staticTexts["Sensitive data detected"]
        XCTAssertTrue(banner.waitForExistence(timeout: 8))

        let emailHighlight = app.buttons["alice@example.com"]
        let phoneHighlight = app.buttons["+49 170 1234567"]
        XCTAssertTrue(emailHighlight.waitForExistence(timeout: 5))
        XCTAssertTrue(phoneHighlight.waitForExistence(timeout: 5))

        emailHighlight.tap()
        XCTAssertTrue(waitForAbsence(app.buttons["alice@example.com"]))
        XCTAssertTrue(phoneHighlight.waitForExistence(timeout: 5))

        app.buttons["Undo all replacements"].tap()
        XCTAssertTrue(waitForAbsence(app.staticTexts["Sensitive data detected"]))
        XCTAssertTrue(waitForAbsence(app.buttons["+49 170 1234567"]))
    }

    func testPIIVisibilityToggleRevealHideAndReload() throws {
        let app = launchChatOpeningPreview(arguments: ["--ui-test-pii-visibility-fixture"])
        XCTAssertTrue(app.staticTexts["Native Chat Opening Preview"].waitForExistence(timeout: 12))

        XCTAssertTrue(textContaining("[EMAIL_1_com]", in: app).waitForExistence(timeout: 8))
        XCTAssertFalse(textContaining("alice@example.com", in: app).exists)

        let toggle = app.buttons["Show sensitive data"]
        XCTAssertTrue(toggle.waitForExistence(timeout: 5))
        toggle.tap()

        XCTAssertTrue(textContaining("alice@example.com", in: app).waitForExistence(timeout: 5))
        XCTAssertTrue(waitForAbsence(textContaining("[EMAIL_1_com]", in: app)))

        app.buttons["Hide sensitive data"].tap()
        XCTAssertTrue(textContaining("[EMAIL_1_com]", in: app).waitForExistence(timeout: 5))
        XCTAssertFalse(textContaining("alice@example.com", in: app).exists)

        app.terminate()
        app.launch()
        XCTAssertTrue(app.staticTexts["Native Chat Opening Preview"].waitForExistence(timeout: 12))
        XCTAssertTrue(textContaining("[EMAIL_1_com]", in: app).waitForExistence(timeout: 8))
        XCTAssertFalse(textContaining("alice@example.com", in: app).exists)
    }

    func testWelcomeComposerShowsPIIWarningHighlights() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-start-new-chat"]
        app.launch()

        let skipInterests = app.buttons["guest-interest-skip"]
        if skipInterests.waitForExistence(timeout: 8) {
            skipInterests.tap()
        }

        let messageEditor = app.textFields["message-editor"]
        XCTAssertTrue(messageEditor.waitForExistence(timeout: 5))
        messageEditor.tap()
        messageEditor.typeText("Email alice@example.com")

        XCTAssertTrue(app.staticTexts["Sensitive data detected"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["alice@example.com"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts["chat.pii_banner.title"].exists)
        XCTAssertFalse(app.tables.firstMatch.exists, "Product chat UI must not render default List/table chrome")
    }

    private func launchChatOpeningPreview(arguments: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "chat-opening"] + arguments
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
        if arguments.contains("--ui-test-pii-composer-banner-fixture") {
            app.launchEnvironment["UI_TEST_PII_COMPOSER_BANNER_FIXTURE"] = "1"
        }
        if arguments.contains("--ui-test-pii-visibility-fixture") {
            app.launchEnvironment["UI_TEST_PII_VISIBILITY_FIXTURE"] = "1"
        }
        app.launch()
        return app
    }

    private func element(in app: XCUIApplication, identifier: String) -> XCUIElement {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier == %@", identifier))
            .firstMatch
    }

    private func element(in app: XCUIApplication, identifiers: [String]) -> XCUIElement {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier IN %@", identifiers))
            .firstMatch
    }

    private func textContaining(_ text: String, in app: XCUIApplication) -> XCUIElement {
        app.staticTexts
            .matching(NSPredicate(format: "label CONTAINS %@", text))
            .firstMatch
    }

    private func waitForAbsence(_ element: XCUIElement, timeout: TimeInterval = 5) -> Bool {
        let predicate = NSPredicate(format: "exists == false")
        let expectation = XCTNSPredicateExpectation(predicate: predicate, object: element)
        return XCTWaiter.wait(for: [expectation], timeout: timeout) == .completed
    }

    @discardableResult
    private func focusComposerInput(in app: XCUIApplication) -> XCUIElement {
        let textView = app.textViews.firstMatch
        let textField = app.textFields.firstMatch
        XCTAssertTrue(textView.exists || textField.exists)
        if textView.exists {
            textView.tap()
            return textView
        } else {
            textField.tap()
            return textField
        }
    }
}
