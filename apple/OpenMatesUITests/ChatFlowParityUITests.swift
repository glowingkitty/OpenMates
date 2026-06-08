// UI parity smoke coverage for the native chat-flow surface.
// Uses the debug-only seeded chat preview so assertions are deterministic and
// do not require credentials, private chat records, network access, or AI calls.
// The deterministic parity audit covers token/source mappings; this simulator
// test verifies the visible native hierarchy exposes the expected chat elements.

import XCTest

@MainActor
final class ChatFlowParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testVisibleChatFlowElementsMatchWebParitySnapshot() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "chat-opening"]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
        app.launch()

        let counter = app.staticTexts
            .containing(NSPredicate(format: "label CONTAINS %@", "initial-window-count=50"))
            .firstMatch
        XCTAssertTrue(counter.waitForExistence(timeout: 12))

        XCTAssertTrue(app.staticTexts["Native Chat Opening Preview"].exists)
        XCTAssertTrue(app.staticTexts["Seeded Large Chat"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Latest assistant response visible after bounded open"].exists)
        XCTAssertTrue(app.textViews.firstMatch.exists || app.textFields.firstMatch.exists)
        XCTAssertFalse(app.tables.firstMatch.exists, "Product chat UI must not render default List/table chrome")

        let screenshot = XCUIScreen.main.screenshot()
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = "Seeded chat-flow parity hierarchy"
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
