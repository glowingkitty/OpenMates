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
        let headerTitle = element(in: app, identifier: "chat-header-title")
        XCTAssertTrue(headerTitle.waitForExistence(timeout: 5))
        XCTAssertEqual(headerTitle.label, "Seeded Large Chat")
        XCTAssertTrue(element(in: app, identifier: "chat-header-icon").exists)
        XCTAssertTrue(element(in: app, identifier: "active-chat-header").exists)

        let userMessage = element(in: app, identifier: "message-user")
        let assistantMessage = element(in: app, identifier: "message-assistant")
        XCTAssertTrue(userMessage.waitForExistence(timeout: 5))
        XCTAssertTrue(assistantMessage.waitForExistence(timeout: 5))
        XCTAssertTrue(userMessage.label.contains("Seeded user message"))
        XCTAssertTrue(assistantMessage.label.contains("Seeded assistant message"))
        XCTAssertTrue(app.staticTexts["Latest assistant response visible after bounded open"].exists)
        XCTAssertTrue(app.textViews.firstMatch.exists || app.textFields.firstMatch.exists)
        XCTAssertFalse(app.tables.firstMatch.exists, "Product chat UI must not render default List/table chrome")

        let screenshot = XCUIScreen.main.screenshot()
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = "Seeded chat-flow parity hierarchy"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func element(in app: XCUIApplication, identifier: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }
}
