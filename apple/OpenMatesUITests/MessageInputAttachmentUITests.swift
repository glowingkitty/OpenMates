// Message input attachment parity coverage for Apple UI contracts.
// Uses the debug-only seeded ChatView preview and simulator-safe fixture seeding
// so the inline native embed hierarchy can be verified without private
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
        let inlineEmbed = element(in: app, identifier: "native-composer-preview-image-finished")
        XCTAssertTrue(inlineEmbed.waitForExistence(timeout: 10))
        XCTAssertTrue(
            element(in: app, identifier: "native-composer-image-content").waitForExistence(timeout: 5),
            "A finished uploaded photo must render its image pixels instead of the generic metadata card"
        )
        assertElement(inlineEmbed, isVisuallyInside: element(in: app, identifier: "message-field"))
        XCTAssertFalse(element(in: app, identifier: "pending-composer-embed").exists)
        XCTAssertFalse(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "```json")).firstMatch.exists)

        XCTAssertTrue(waitForMessageEditor(in: app).waitForExistence(timeout: 5))
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

        let firstInlineEmbed = element(in: app, identifier: "native-composer-preview-docs-doc-finished")
        XCTAssertTrue(firstInlineEmbed.waitForExistence(timeout: 5))
        let visibleInlineEmbed = element(in: app, identifier: "native-composer-preview-recording-finished")
        XCTAssertTrue(visibleInlineEmbed.waitForExistence(timeout: 5))
        assertElement(visibleInlineEmbed, isVisuallyInside: element(in: app, identifier: "message-field"))
        XCTAssertFalse(element(in: app, identifier: "pending-composer-embed").exists)
        XCTAssertTrue(app.staticTexts["welcome-file.pdf"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["send-button"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "```json")).firstMatch.exists)
        XCTAssertFalse(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "embed_id")).firstMatch.exists)
        XCTAssertFalse(app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "/private/")).firstMatch.exists)
    }

    func testImagePreviewSurvivesBackgroundAndKeepsActionsAboveIPadKeyboard() throws {
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

        let editor = waitForMessageEditor(in: app)
        editor.tap()
        editor.typeText("Image draft")
        let imagePreview = element(in: app, identifier: "native-composer-preview-image-finished")
        XCTAssertTrue(imagePreview.waitForExistence(timeout: 8))
        let image = element(in: app, identifier: "native-composer-image-content")
        XCTAssertTrue(image.waitForExistence(timeout: 8))
        XCTAssertFalse(
            imagePreview.staticTexts["Tap to show details"].exists,
            "A finished local image uses web image metadata instead of the generic open-details subtitle"
        )

        let keyboard = app.keyboards.firstMatch
        XCTAssertTrue(keyboard.waitForExistence(timeout: 5))
        for identifier in ["attach-files-button", "share-location-button", "sketch-button", "take-photo-button", "send-button"] {
            let button = app.buttons[identifier]
            XCTAssertTrue(button.waitForExistence(timeout: 5), "Missing composer action: \(identifier)")
            XCTAssertTrue(button.isHittable, "Composer action is covered: \(identifier)")
            XCTAssertLessThanOrEqual(
                button.frame.maxY,
                keyboard.frame.minY - 2,
                "Composer action must stay above the iPad keyboard: \(identifier)"
            )
        }

        XCUIDevice.shared.press(.home)
        app.activate()

        XCTAssertTrue(
            image.waitForExistence(timeout: 8),
            "The local uploaded image preview must survive background/foreground restoration"
        )
        XCTAssertFalse(imagePreview.staticTexts["Tap to show details"].exists)
        attachScreenshot(name: "Image composer preview restored above iPad keyboard")
    }

    func testAttachmentMenuOverlaysComposerActions() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "--ui-test-disable-auth-cache",
            "--ui-test-start-new-chat"
        ]
        app.launch()

        let skipInterests = app.buttons["guest-interest-skip"]
        if skipInterests.waitForExistence(timeout: 8) {
            skipInterests.tap()
        }

        let editor = waitForMessageEditor(in: app)
        editor.tap()
        editor.typeText("Attachment menu")

        let actionIDs = ["attach-files-button", "share-location-button", "sketch-button", "take-photo-button", "send-button"]
        let actionFrames = Dictionary(uniqueKeysWithValues: actionIDs.map { identifier in
            (identifier, app.buttons[identifier].frame)
        })

        app.buttons["attach-files-button"].tap()

        let browseFiles = element(in: app, identifier: "attachment-browse-files-action")
        XCTAssertTrue(browseFiles.waitForExistence(timeout: 5), "Missing attachment menu browse-files action")
        XCTAssertTrue(browseFiles.isHittable, "Attachment menu browse-files action is not visible")
        for identifier in actionIDs {
            XCTAssertEqual(app.buttons[identifier].frame, actionFrames[identifier])
        }
        attachScreenshot(name: "Attachment menu overlays composer actions")
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

    private func waitForMessageEditor(in app: XCUIApplication) -> XCUIElement {
        let candidates = [element(in: app, identifier: "message-editor")]

        for candidate in candidates where candidate.waitForExistence(timeout: 5) {
            return candidate
        }

        XCTFail("Expected welcome message editor to exist. Visible UI: \(app.debugDescription)")
        return candidates[0]
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

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
