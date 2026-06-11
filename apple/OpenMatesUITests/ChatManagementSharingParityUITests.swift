// UI smoke coverage for the native chat-management testability surface.
// Uses public unauthenticated chats only, avoiding credentials, private chat
// records, share URLs, webhook secrets, or encrypted user content. Deeper
// live-account share/import/export parity remains covered by the executable spec.

import XCTest

@MainActor
final class ChatManagementSharingParityUITests: XCTestCase {
    private let fixtureShareURL = "https://app.dev.openmates.org/s/Abc123XY#testKey"

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
        XCTAssertFalse(app.tables.firstMatch.exists, "Chat management UI must not render default List/table chrome")

        attachScreenshot(name: "Public chat management identifiers")
    }

    func testChatSharePreviewGeneratesLinkQRCodeAndOpensSystemShareSheet() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "chat-share"]
        app.launchEnvironment["DEV_PREVIEW"] = "chat-share"
        app.launchEnvironment["UI_TEST_CHAT_SHARE_URL"] = fixtureShareURL
        app.launch()

        let generateButton = app.buttons["share-generate-link"]
        XCTAssertTrue(
            generateButton.waitForExistence(timeout: 10),
            "Expected native chat share controls. Visible UI: \(visibleStateLabels(in: app))"
        )
        generateButton.tap()

        let generatedLink = app.staticTexts["share-short-link-url"]
        XCTAssertTrue(generatedLink.waitForExistence(timeout: 5))
        XCTAssertEqual(generatedLink.label, fixtureShareURL)
        XCTAssertTrue(accessibilityElement(in: app, identifier: "share-qr-code").waitForExistence(timeout: 5))

        let nativeShareButton = app.buttons["share-native-sheet-button"]
        XCTAssertTrue(nativeShareButton.waitForExistence(timeout: 5))
        nativeShareButton.tap()

        XCTAssertTrue(
            waitForSystemShareSheet(in: app, timeout: 8),
            "Expected iOS system share sheet after tapping native share button. Visible UI: \(visibleStateLabels(in: app))"
        )
        attachScreenshot(name: "Native chat share sheet")
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

    private func waitForSystemShareSheet(in app: XCUIApplication, timeout: TimeInterval) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        repeat {
            if app.sheets.firstMatch.exists { return true }
            if app.buttons["Copy"].exists || app.buttons["Add to Reading List"].exists { return true }
            if app.otherElements.matching(NSPredicate(format: "label CONTAINS[c] %@", "Activity")).firstMatch.exists {
                return true
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        } while Date() < deadline
        return false
    }

    private func accessibilityElement(in app: XCUIApplication, identifier: String) -> XCUIElement {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier == %@", identifier))
            .firstMatch
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
