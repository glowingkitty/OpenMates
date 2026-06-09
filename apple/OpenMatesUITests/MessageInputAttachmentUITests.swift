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
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "chat-opening", "--ui-test-seed-pending-composer-embed"]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
        app.launch()

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

    private func focusComposerInput(in app: XCUIApplication) {
        let textView = app.textViews.firstMatch
        let textField = app.textFields.firstMatch
        XCTAssertTrue(textView.exists || textField.exists)
        if textView.exists {
            textView.tap()
        } else {
            textField.tap()
        }
    }
}
