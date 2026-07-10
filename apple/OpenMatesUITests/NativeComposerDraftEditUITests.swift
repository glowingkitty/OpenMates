// UI coverage for reachable native composer draft/edit behavior.
// Uses debug-only deterministic fixtures without private chat data or network calls.
// Assertions target accessibility identifiers exposed by production composer surfaces.
// Encrypted draft restoration has no UI-test key fixture, so it remains unit-tested.
// Screenshots are retained as simulator evidence for cancel/save edit semantics.

import XCTest

@MainActor
final class NativeComposerDraftEditUITests: XCTestCase {
    private let originalContent = "Original message content"
    private let updatedSuffix = " updated"

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testEditCancelRestoresTheOriginalMessageContent() throws {
        let app = launchMessageEditFixture()

        let editor = editor(in: app)
        appendUpdatedSuffix(to: editor)
        XCTAssertEqual(editor.value as? String, originalContent + updatedSuffix)

        let cancel = element(in: app, identifier: "native-message-edit-cancel")
        XCTAssertTrue(cancel.waitForExistence(timeout: 5))
        cancel.tap()

        let message = element(in: app, identifier: "native-message-edit-fixture-content")
        XCTAssertTrue(message.waitForExistence(timeout: 5))
        XCTAssertEqual(message.label, originalContent)
        XCTAssertFalse(element(in: app, identifier: "native-message-edit").exists)

        attachScreenshot(name: "Native composer edit cancel restores original content")
    }

    func testEditSaveCommitsOnlyTheEditedMessageContent() throws {
        let app = launchMessageEditFixture()

        let editor = editor(in: app)
        appendUpdatedSuffix(to: editor)

        let save = element(in: app, identifier: "native-message-edit-save")
        XCTAssertTrue(save.waitForExistence(timeout: 5))
        XCTAssertTrue(save.isEnabled)
        save.tap()

        let message = element(in: app, identifier: "native-message-edit-fixture-content")
        XCTAssertTrue(message.waitForExistence(timeout: 5))
        XCTAssertEqual(message.label, originalContent + updatedSuffix)
        XCTAssertFalse(element(in: app, identifier: "native-message-edit").exists)

        attachScreenshot(name: "Native composer edit save commits edited content")
    }

    func testPendingInlineEmbedFixtureExposesOneAccessibleAtomAfterColdLaunch() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "--dev-preview", "chat-opening",
            "--ui-test-seed-pending-composer-embed"
        ]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
        app.launch()

        let atom = element(in: app, identifier: "composer:embed:ui-test")
        XCTAssertTrue(atom.waitForExistence(timeout: 12))
        XCTAssertEqual(
            app.descendants(matching: .any)
                .matching(NSPredicate(format: "identifier == %@", "composer:embed:ui-test"))
                .count,
            1,
            "The pending embed fixture must remain one inline atom after a cold launch"
        )
    }

    private func launchMessageEditFixture() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "composer-draft-edit"]
        app.launchEnvironment["DEV_PREVIEW"] = "composer-draft-edit"
        app.launch()

        XCTAssertTrue(element(in: app, identifier: "message-editor").waitForExistence(timeout: 8))
        return app
    }

    private func editor(in app: XCUIApplication) -> XCUIElement {
        let editor = element(in: app, identifier: "message-editor")
        XCTAssertTrue(editor.waitForExistence(timeout: 5))
        return editor
    }

    private func appendUpdatedSuffix(to editor: XCUIElement) {
        editor.typeText(updatedSuffix)
    }

    private func element(in app: XCUIApplication, identifier: String) -> XCUIElement {
        app.descendants(matching: .any)[identifier]
    }

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
