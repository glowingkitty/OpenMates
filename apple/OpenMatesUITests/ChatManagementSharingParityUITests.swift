// UI smoke coverage for the native chat-management testability surface.
// Uses public unauthenticated chats only, avoiding credentials, private chat
// records, share URLs, webhook secrets, or encrypted user content. Deeper
// live-account share/import/export parity remains covered by the executable spec.

import XCTest

@MainActor
final class ChatManagementSharingParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testUnauthenticatedChatListExposesManagementIdentifiers() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-shell-metrics"]
        app.launchEnvironment["UI_TEST_SHELL_METRICS"] = "1"
        app.launch()

        let chatRow = app.descendants(matching: .any)["chat-item-wrapper"]
        if !chatRow.waitForExistence(timeout: 5) {
            let sidebarToggle = app.buttons["sidebar-toggle"]
            if sidebarToggle.waitForExistence(timeout: 3) {
                sidebarToggle.tap()
            }
        }

        XCTAssertTrue(
            chatRow.waitForExistence(timeout: 12),
            "Expected public chat row identifier. Visible UI: \(visibleStateLabels(in: app))"
        )
        XCTAssertTrue(app.buttons["search-button"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.tables.firstMatch.exists, "Chat management UI must not render default List/table chrome")

        attachScreenshot(name: "Public chat management identifiers")
    }

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func visibleStateLabels(in app: XCUIApplication) -> String {
        let buttons = elementSummaries(app.buttons.allElementsBoundByIndex, prefix: "button")
        let textFields = elementSummaries(app.textFields.allElementsBoundByIndex, prefix: "textField")
        let staticTexts = elementSummaries(app.staticTexts.allElementsBoundByIndex, prefix: "text")
        return (buttons + textFields + staticTexts).prefix(30).joined(separator: " | ")
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
