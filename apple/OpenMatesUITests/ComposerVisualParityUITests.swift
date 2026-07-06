// Visual contract smoke coverage for the shared Apple message composer.
// Uses deterministic dev-preview surfaces to assert shared identifiers and the
// web 629pt max-width contract without credentials, network calls, private chat
// records, or system picker automation.
// Screenshots are attached as review artifacts; assertions stay deterministic.

import XCTest

@MainActor
final class ComposerVisualParityUITests: XCTestCase {
    private let maxComposerWidth: CGFloat = 629
    private let widthTolerance: CGFloat = 8

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testChatPreviewComposerUsesSharedIdentifiersAndWidthCap() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "chat-opening"]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
        app.launch()

        XCTAssertTrue(app.staticTexts["Native Chat Opening Preview"].waitForExistence(timeout: 12))

        let editor = app.textViews.firstMatch.exists ? app.textViews.firstMatch : app.textFields.firstMatch

        XCTAssertTrue(editor.waitForExistence(timeout: 8), "Expected visible composer editor. Visible UI: \(app.debugDescription)")
        XCTAssertLessThanOrEqual(editor.frame.width, maxComposerWidth + widthTolerance)

        editor.tap()
        XCTAssertFalse(app.tables.firstMatch.exists, "Product composer UI must not render default List/table chrome")

        attachScreenshot(name: "Shared composer chat preview width cap")
    }

    func testQuickCaptureComposerUsesSameSharedIdentifierContract() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "--dev-preview",
            "quick-capture",
            "--ui-test-seed-quick-capture-recent-chat"
        ]
        app.launchEnvironment["DEV_PREVIEW"] = "quick-capture"
        app.launch()

        XCTAssertTrue(element(in: app, identifier: "quick-capture-tab-chats").waitForExistence(timeout: 12))
        XCTAssertTrue(element(in: app, identifier: "quick-capture-composer").exists)
        XCTAssertTrue(element(in: app, identifier: "message-composer").exists)
        XCTAssertTrue(element(in: app, identifier: "message-field").exists)
        XCTAssertTrue(element(in: app, identifier: "message-editor").exists)
        XCTAssertTrue(element(in: app, identifier: "action-buttons").exists)
        XCTAssertTrue(element(in: app, identifier: "quick-capture-recent-chats").exists)
        XCTAssertTrue(element(in: app, identifier: "quick-capture-status-list").exists)

        attachScreenshot(name: "Shared composer quick capture contract")
    }

    private func element(in app: XCUIApplication, identifier: String) -> XCUIElement {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier == %@", identifier))
            .firstMatch
    }

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
