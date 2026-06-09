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
        app.launchArguments = ["--dev-preview", "chat-opening", "--ui-test-header-contract"]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
        app.launchEnvironment["UI_TEST_HEADER_CONTRACT"] = "1"
        app.launch()

        let counter = app.staticTexts
            .containing(NSPredicate(format: "label CONTAINS %@", "initial-window-count=50"))
            .firstMatch
        XCTAssertTrue(counter.waitForExistence(timeout: 12))
        attachScreenshot(name: "Seeded chat-flow loaded")

        XCTAssertTrue(app.staticTexts["Native Chat Opening Preview"].exists)
        let headerContract = element(in: app, identifier: "chat-header-contract")
        XCTAssertTrue(headerContract.waitForExistence(timeout: 5))
        XCTAssertTrue(headerContract.label.contains("chat-header-title=Seeded Large Chat"))
        XCTAssertTrue(headerContract.label.contains("chat-header-icon=true"))
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

        attachScreenshot(name: "Seeded chat-flow parity hierarchy")
    }

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func element(in app: XCUIApplication, identifier: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }
}
