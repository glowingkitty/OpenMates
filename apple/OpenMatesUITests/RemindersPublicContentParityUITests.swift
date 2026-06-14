// UI smoke coverage for public-content parity entry points.
// Uses public unauthenticated chats only; no reminder scheduling, private chat IDs,
// notification tokens, credentials, or private screenshots are created.

import XCTest

@MainActor
final class RemindersPublicContentParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testPublicChatEntryOpensReadOnlyChatSurface() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-shell-metrics"]
        app.launchEnvironment["UI_TEST_SHELL_METRICS"] = "1"
        app.launch()

        let publicChatRows = app.buttons.matching(identifier: "chat-item-wrapper")
        let publicChatRow = publicChatRows.firstMatch
        if !publicChatRow.waitForExistence(timeout: 5) {
            let sidebarToggle = app.buttons["sidebar-toggle"]
            if sidebarToggle.waitForExistence(timeout: 3) {
                sidebarToggle.tap()
            }
        }

        XCTAssertTrue(
            publicChatRow.waitForExistence(timeout: 12),
            "Expected public chat row. Visible UI: \(visibleStateLabels(in: app))"
        )
        publicChatRow.tap()

        XCTAssertTrue(app.descendants(matching: .any)["active-chat-header"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.descendants(matching: .any)["message-assistant"].waitForExistence(timeout: 10))
        XCTAssertFalse(app.tables.firstMatch.exists, "Public chat content must not render default List/table chrome")

        attachScreenshot(name: "Public chat read-only entry")
    }

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func visibleStateLabels(in app: XCUIApplication) -> String {
        let buttons = elementSummaries(app.buttons.allElementsBoundByIndex, prefix: "button")
        let staticTexts = elementSummaries(app.staticTexts.allElementsBoundByIndex, prefix: "text")
        return (buttons + staticTexts).prefix(30).joined(separator: " | ")
    }

    private func elementSummaries(_ elements: [XCUIElement], prefix: String) -> [String] {
        elements.compactMap { element in
            let identifier = element.identifier.trimmingCharacters(in: .whitespacesAndNewlines)
            let label = element.label.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !identifier.isEmpty || !label.isEmpty else { return nil }
            if identifier.isEmpty { return "\(prefix):\(redact(label))" }
            if label.isEmpty || label == identifier { return "\(prefix)#\(identifier)" }
            return "\(prefix)#\(identifier)=\(redact(label))"
        }
    }

    private func redact(_ value: String) -> String {
        value.contains("@") ? "<email>" : value
    }
}
