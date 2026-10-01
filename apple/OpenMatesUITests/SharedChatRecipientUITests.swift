// Isolated recipient fixtures: no account, production share request or owner chat.
// Specification: specifications/features/chat-share-settings/specification.yml
import XCTest
import CoreGraphics
import ImageIO

@MainActor
final class SharedChatRecipientUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testLoadingRemainsInRecipientGate() {
        let app = launch("loading")
        XCTAssertTrue(element(app, "shared-recipient-loading").waitForExistence(timeout: 15))
        XCTAssertFalse(element(app, "shared-recipient-transcript").exists)
        XCTAssertFalse(app.buttons["shared-recipient-open-settings"].exists)
        attach(app, "Shared recipient loading")
    }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testPasswordGateUsesSecureInputAndLocalSubmit() {
        let app = launch("password")
        let input = app.secureTextFields["shared-chat-password-input"]
        XCTAssertTrue(input.waitForExistence(timeout: 15)); XCTAssertTrue(input.isHittable)
        XCTAssertTrue(app.buttons["shared-chat-password-submit"].isHittable)
        attach(app, "Shared recipient password")
        input.tap(); input.typeText("synthetic")
        app.buttons["shared-chat-password-submit"].tap()
        XCTAssertTrue(element(app, "shared-chat-password-form").exists)
        XCTAssertFalse(element(app, "shared-recipient-transcript").exists)
    }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testInvalidPasswordKeepsRetryFormVisible() {
        let app = launch("invalidPassword")
        XCTAssertTrue(element(app, "shared-chat-password-error").waitForExistence(timeout: 15))
        XCTAssertTrue(app.secureTextFields["shared-chat-password-input"].isHittable)
        XCTAssertTrue(app.buttons["shared-chat-password-submit"].isHittable)
        XCTAssertFalse(element(app, "shared-recipient-transcript").exists)
        attach(app, "Shared recipient invalid password")
    }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testUnavailableGateHasBackAndNoTranscript() {
        let app = launch("error")
        let back = app.buttons["shared-recipient-error-close"]
        XCTAssertTrue(back.waitForExistence(timeout: 15)); XCTAssertTrue(back.isHittable)
        XCTAssertFalse(element(app, "shared-chat-password-form").exists)
        XCTAssertFalse(element(app, "shared-recipient-transcript").exists)
        attach(app, "Shared recipient unavailable")
    }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open,chat-share-settings.readonly-viewer-controls,chat-share-settings.generated-link-controls
    func testRecipientSettingsUseScopedPlanningFilesAndOriginalShareURL() {
        let app = launch("ready")
        XCTAssertTrue(app.staticTexts["Launch preparation"].waitForExistence(timeout: 15))
        XCTAssertTrue(element(app, "shared-recipient-readonly").exists)
        attach(app, "Shared recipient transcript")
        let settings = app.buttons["shared-recipient-open-settings"]
        XCTAssertTrue(settings.isHittable); settings.tap()
        XCTAssertTrue(app.staticTexts["Prepare the launch"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["chat-settings-plan-create-button"].exists)
        tab(app, "tasks").tap()
        XCTAssertTrue(app.staticTexts["Review the release checklist"].waitForExistence(timeout: 3))
        XCTAssertFalse(app.textFields["chat-settings-task-title-input"].exists)
        XCTAssertFalse(app.buttons["chat-settings-task-create-button"].exists)
        XCTAssertFalse(element(app, "chat-settings-task-done-toggle").exists)
        tab(app, "files").tap()
        XCTAssertTrue(app.staticTexts["verification.py"].waitForExistence(timeout: 3))
        attach(app, "Shared recipient scoped files")
        tab(app, "usage").tap()
        XCTAssertTrue(element(app, "chat-settings-tabpanel-usage").waitForExistence(timeout: 3))
        tab(app, "share").tap()
        XCTAssertTrue(element(app, "chat-settings-share-readonly").waitForExistence(timeout: 3))
        XCTAssertFalse(app.buttons["share-generate-link"].exists)
        XCTAssertFalse(element(app, "chat-settings-share-password").exists)
        let scroll = app.scrollViews["chat-settings-scroll"]
        let showURL = app.buttons["chat-settings-share-show-url"]
        if !showURL.isHittable { scroll.swipeUp() }
        XCTAssertTrue(showURL.isHittable); showURL.tap()
        let originalURL = app.staticTexts["https://openmates.org/share/chat/recipient-preview#key=synthetic-preview-ciphertext"]
        XCTAssertTrue(originalURL.waitForExistence(timeout: 3))
        XCTAssertTrue(app.buttons["share-copy-link"].exists)
        attach(app, "Shared recipient original URL disclosure")
        scroll.swipeDown()
        let back = app.buttons["banner-back-button"]
        XCTAssertTrue(back.isHittable); back.tap()
        XCTAssertTrue(app.buttons["shared-recipient-open-settings"].waitForExistence(timeout: 3))
    }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open,chat-share-settings.readonly-viewer-controls
    func testSyntheticCodeOpensExactFileInSafeFullscreenAndReturns() {
        let app = launch("embed")
        XCTAssertTrue(app.staticTexts["Launch preparation"].waitForExistence(timeout: 15))
        let preview = app.buttons["embed-preview"].firstMatch
        XCTAssertTrue(preview.waitForExistence(timeout: 5))
        if !preview.isHittable { app.scrollViews["shared-recipient-transcript"].swipeUp() }
        XCTAssertTrue(preview.isHittable); preview.tap()
        let fullscreen = recipientFullscreen(app)
        XCTAssertTrue(fullscreen.staticTexts["verification.py"].exists)
        XCTAssertTrue(fullscreen.descendants(matching: .any)["code-source-panel"].exists)
        XCTAssertTrue(fullscreen.staticTexts["print('Synthetic file')"].exists)
        XCTAssertFalse(element(app, "embed-pii-toggle").exists)
        XCTAssertFalse(element(app, "code-run-terminal").exists)
        XCTAssertFalse(element(app, "code-run-output-preview").exists)
        assertRecipientIsolation(app)
        attach(app, "Shared recipient code fullscreen")
        let back = app.buttons["shared-recipient-embed-back"]
        XCTAssertTrue(back.isHittable); back.tap()
        XCTAssertTrue(app.buttons["embed-preview"].firstMatch.waitForExistence(timeout: 3))
        XCTAssertFalse(app.buttons["shared-recipient-embed-back"].exists)
        XCTAssertFalse(element(app, "code-source-panel").exists)
    }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testEncryptedImageSiblingsRenderRedThenBlueThenRed() {
        let app = launch("imageSiblings")
        XCTAssertTrue(app.staticTexts["Launch preparation"].waitForExistence(timeout: 15))
        let preview = app.buttons["embed-preview"].firstMatch
        XCTAssertTrue(preview.waitForExistence(timeout: 5))
        if !preview.isHittable { app.scrollViews["shared-recipient-transcript"].swipeUp() }
        XCTAssertTrue(preview.isHittable); preview.tap()
        let fullscreen = recipientFullscreen(app)
        XCTAssertTrue(fullscreen.staticTexts["Synthetic red.png"].exists)
        waitForSyntheticImage(app, red: true)
        assertRecipientIsolation(app)
        attach(app, "Shared recipient encrypted sibling red")
        XCTAssertFalse(app.buttons["shared-recipient-embed-previous"].isEnabled)
        app.buttons["shared-recipient-embed-next"].tap()
        XCTAssertTrue(app.staticTexts["Synthetic blue.png"].waitForExistence(timeout: 3))
        waitForSyntheticImage(app, red: false)
        assertRecipientIsolation(app)
        XCTAssertFalse(app.buttons["shared-recipient-embed-next"].isEnabled)
        attach(app, "Shared recipient encrypted sibling blue")
        app.buttons["shared-recipient-embed-previous"].tap()
        XCTAssertTrue(app.staticTexts["Synthetic red.png"].waitForExistence(timeout: 3))
        waitForSyntheticImage(app, red: true)
        assertRecipientIsolation(app)
        attach(app, "Shared recipient encrypted sibling red restored")
    }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testCanonicalMessageTargetIsScrolledIntoViewport() {
        let app = launch("target")
        let target = element(app, "shared-recipient-message-recipient-target")
        XCTAssertTrue(target.waitForExistence(timeout: 15))
        let visible = NSPredicate { _, _ in
            target.exists && target.frame.height > 0 && app.frame.intersects(target.frame)
        }
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: visible, object: target)], timeout: 5), .completed)
        XCTAssertTrue(app.staticTexts["Synthetic target message."].exists)
        attach(app, "Shared recipient canonical target")
    }

    private func launch(_ state: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "component", "--dev-preview-component", "shared-recipient",
                               "--dev-preview-variant", state, "--dev-preview-theme", "light",
                               "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch(); return app
    }
    private func element(_ app: XCUIApplication, _ id: String) -> XCUIElement {
        app.descendants(matching: .any)[id].firstMatch
    }
    private func waitForSyntheticImage(_ app: XCUIApplication, red: Bool) {
        let fullscreen = recipientFullscreen(app)
        // The recipient wrapper bounds the real decrypted image renderer.
        // Scope to this pane so a hidden transcript thumbnail cannot satisfy
        // the color assertion; changing the filename alone cannot pass it.
        let image = fullscreen.descendants(matching: .any)["shared-recipient-image-content"].firstMatch
        XCTAssertTrue(image.waitForExistence(timeout: 3))
        XCTAssertTrue(image.frame.width > 0 && image.frame.height > 0)
        XCTAssertTrue(app.frame.intersects(image.frame))
        // The fixed encrypted fixture is a solid-color PNG, so this proves the
        // actual renderer replaced decrypted imageData, beyond changing titles.
        let matchesColor = NSPredicate { _, _ in
            guard image.exists, let pixel = self.centerPixel(image) else { return false }
            return red ? pixel[0] > 200 && pixel[2] < 50 : pixel[2] > 200 && pixel[0] < 50
        }
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: matchesColor, object: image)], timeout: 5), .completed)
    }
    private func recipientFullscreen(_ app: XCUIApplication) -> XCUIElement {
        // ChatEmbedWorkspace owns the pane container identifier and replaces
        // the nested fullscreen wrapper identifier. Prove the actual pane and
        // recipient controls rather than an identifier absent from native AX.
        let recipient = element(app, "shared-recipient-view")
        let pane = recipient.descendants(matching: .any)["workspace-embed"].firstMatch
        XCTAssertTrue(pane.waitForExistence(timeout: 3))
        let back = pane.buttons["shared-recipient-embed-back"]
        XCTAssertTrue(back.exists && back.isHittable)
        XCTAssertTrue(pane.buttons["shared-recipient-embed-close"].isHittable)
        XCTAssertTrue(pane.frame.width > 0 && pane.frame.height > 0 && app.frame.intersects(pane.frame))
        return pane
    }
    private func assertRecipientIsolation(_ app: XCUIApplication) {
        XCTAssertEqual(element(app, "dev-preview-root").value as? String,
                       "auth=not-started;store=detached;socket=disconnected")
        XCTAssertFalse(element(app, "embed-pii-toggle").exists)
        XCTAssertFalse(app.buttons["Download"].exists)
        XCTAssertFalse(element(app, "message-editor").exists)
    }
    private func centerPixel(_ element: XCUIElement) -> [UInt8]? {
        guard element.frame.width > 0, element.frame.height > 0,
              let source = CGImageSourceCreateWithData(element.screenshot().pngRepresentation as CFData, nil),
              let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else { return nil }
        var bytes = [UInt8](repeating: 0, count: 4)
        let succeeded = bytes.withUnsafeMutableBytes { buffer -> Bool in
            guard let context = CGContext(data: buffer.baseAddress, width: 1, height: 1, bitsPerComponent: 8,
                                          bytesPerRow: 4, space: CGColorSpaceCreateDeviceRGB(),
                                          bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue) else { return false }
            context.draw(image, in: CGRect(x: -CGFloat(image.width / 2), y: -CGFloat(image.height / 2),
                                          width: CGFloat(image.width), height: CGFloat(image.height)))
            return true
        }
        return succeeded ? bytes : nil
    }
    private func tab(_ app: XCUIApplication, _ id: String) -> XCUIElement {
        let control = app.buttons["chat-settings-tab-\(id)"]
        XCTAssertTrue(control.isHittable); return control
    }
    private func attach(_ app: XCUIApplication, _ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
    }
}
