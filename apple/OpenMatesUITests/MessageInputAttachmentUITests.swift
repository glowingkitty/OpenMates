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
        let app = launchChatOpeningPreview(arguments: ["--ui-test-seed-pii-composer-text"])
        XCTAssertTrue(app.staticTexts["Native Chat Opening Preview"].waitForExistence(timeout: 12))

        let banner = element(in: app, identifier: "pii-warning-banner")
        XCTAssertTrue(banner.waitForExistence(timeout: 8))
        XCTAssertTrue(element(in: app, identifier: "pii-highlights").waitForExistence(timeout: 5))

        let emailHighlight = element(in: app, identifier: "pii-highlight-EMAIL")
        let phoneHighlight = element(in: app, identifier: "pii-highlight-PHONE")
        XCTAssertTrue(emailHighlight.waitForExistence(timeout: 5))
        XCTAssertTrue(phoneHighlight.waitForExistence(timeout: 5))

        emailHighlight.tap()
        XCTAssertTrue(waitForAbsence(element(in: app, identifier: "pii-highlight-EMAIL")))
        XCTAssertTrue(phoneHighlight.waitForExistence(timeout: 5))

        element(in: app, identifier: "pii-undo-all").tap()
        XCTAssertTrue(waitForAbsence(element(in: app, identifier: "pii-warning-banner")))
        XCTAssertTrue(waitForAbsence(element(in: app, identifier: "pii-highlights")))
    }

    func testPIIVisibilityToggleRevealHideAndReload() throws {
        let app = launchChatOpeningPreview(arguments: ["--ui-test-pii-visibility-fixture"])
        XCTAssertTrue(app.staticTexts["Native Chat Opening Preview"].waitForExistence(timeout: 12))

        XCTAssertTrue(textContaining("[EMAIL_1_com]", in: app).waitForExistence(timeout: 8))
        XCTAssertFalse(textContaining("alice@example.com", in: app).exists)

        let toggle = element(in: app, identifier: "chat-pii-toggle")
        XCTAssertTrue(toggle.waitForExistence(timeout: 5))
        toggle.tap()

        XCTAssertTrue(textContaining("alice@example.com", in: app).waitForExistence(timeout: 5))
        XCTAssertTrue(waitForAbsence(textContaining("[EMAIL_1_com]", in: app)))

        element(in: app, identifier: "chat-pii-toggle").tap()
        XCTAssertTrue(textContaining("[EMAIL_1_com]", in: app).waitForExistence(timeout: 5))
        XCTAssertFalse(textContaining("alice@example.com", in: app).exists)

        app.terminate()
        app.launch()
        XCTAssertTrue(app.staticTexts["Native Chat Opening Preview"].waitForExistence(timeout: 12))
        XCTAssertTrue(textContaining("[EMAIL_1_com]", in: app).waitForExistence(timeout: 8))
        XCTAssertFalse(textContaining("alice@example.com", in: app).exists)
    }

    private func launchChatOpeningPreview(arguments: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "chat-opening"] + arguments
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
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
