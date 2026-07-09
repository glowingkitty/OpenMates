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
        let editor = waitForMessageEditor(in: app)
        XCTAssertTrue(waitForEditorOwnedEmbedDiagnostics(editor, expectedCount: 1), "Expected editor-owned embed diagnostics after seeded attachment")
        XCTAssertFalse(element(in: app, identifier: "pending-composer-embed").exists, "Editor-owned embeds must replace the native pending strip")
        XCTAssertFalse(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "```json")).firstMatch.exists)

        XCTAssertTrue(editor.waitForExistence(timeout: 5))
        XCTAssertTrue(element(in: app, identifier: "message-field").exists)

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
        let app = launchChatOpeningPreview(arguments: ["--ui-test-pii-composer-banner-fixture"])
        XCTAssertTrue(app.staticTexts["Native Chat Opening Preview"].waitForExistence(timeout: 12))
        XCTAssertTrue(app.staticTexts["PII Composer Banner Fixture"].waitForExistence(timeout: 5))

        XCTAssertTrue(app.staticTexts["Sensitive data detected"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["alice@example.com"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts["chat.pii_banner.title"].exists)
        XCTAssertFalse(app.tables.firstMatch.exists, "Product chat UI must not render default List/table chrome")
    }

    func testWelcomeComposerSeededPendingAttachmentsEnableSendWithoutRawJson() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "--ui-test-disable-auth-cache",
            "--ui-test-start-new-chat",
            "--ui-test-welcome-seed-pending-content"
        ]
        app.launch()

        let skipInterests = app.buttons["guest-interest-skip"]
        if skipInterests.waitForExistence(timeout: 8) {
            skipInterests.tap()
        }

        let messageEditor = waitForMessageEditor(in: app)
        messageEditor.tap()

        XCTAssertTrue(waitForEditorOwnedEmbedDiagnostics(messageEditor, expectedCount: 3), "Expected welcome seeded content to become editor-owned embeds")
        XCTAssertFalse(element(in: app, identifier: "pending-composer-embed").exists, "Welcome composer must not use native pending strips for seeded embeds")
        XCTAssertTrue(textContaining("welcome-file.pdf", in: app).waitForExistence(timeout: 5))
        XCTAssertTrue(textContaining("welcome-sketch.png", in: app).waitForExistence(timeout: 5))
        XCTAssertTrue(textContaining("welcome-recording.m4a", in: app).waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["send-button"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "```json")).firstMatch.exists)
        XCTAssertFalse(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "embed_id")).firstMatch.exists)
        XCTAssertFalse(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "/private/")).firstMatch.exists)
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

    private func assertPendingLabel(
        _ label: String,
        in app: XCUIApplication,
        scrollContainer: XCUIElement,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        let element = app.staticTexts[label]
        if element.waitForExistence(timeout: 2) { return }

        for _ in 0..<4 {
            scrollContainer.swipeLeft()
            if element.waitForExistence(timeout: 2) { return }
        }

        XCTFail("Expected pending composer embed named \(label)", file: file, line: line)
    }

    private func waitForMessageEditor(in app: XCUIApplication) -> XCUIElement {
        let candidates = [element(in: app, identifier: "message-editor")]

        for candidate in candidates where candidate.waitForExistence(timeout: 5) {
            return candidate
        }

        XCTFail("Expected welcome message editor to exist. Visible UI: \(app.debugDescription)")
        return candidates[0]
    }

    private func waitForEditorOwnedEmbedDiagnostics(_ editor: XCUIElement, expectedCount: Int, timeout: TimeInterval = 8) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if let value = editor.value as? String,
               value.contains("embedCount=\(expectedCount)") {
                return true
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        }
        return false
    }

    private func assertElement(
        _ child: XCUIElement,
        isVisuallyInside parent: XCUIElement,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        XCTAssertTrue(parent.waitForExistence(timeout: 5), "Expected parent element to exist", file: file, line: line)
        XCTAssertTrue(child.waitForExistence(timeout: 5), "Expected child element to exist", file: file, line: line)

        let parentFrame = parent.frame.insetBy(dx: -1, dy: -1)
        let childCenter = CGPoint(x: child.frame.midX, y: child.frame.midY)
        XCTAssertTrue(
            parentFrame.contains(childCenter),
            "Expected \(child.identifier) to render inside \(parent.identifier); child=\(child.frame), parent=\(parent.frame)",
            file: file,
            line: line
        )
    }
}
