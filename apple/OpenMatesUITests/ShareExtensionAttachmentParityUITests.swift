// Share-extension attachment parity smoke coverage.
// Uses the Quick Capture debug preview with a seeded pending attachment because
// the share extension and menu bar capture intentionally delegate to the same
// background attachment sender. This verifies the visible status/composer shape
// needed before exercising real extension-host automation.

import XCTest

@MainActor
final class ShareExtensionAttachmentParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testSharedBackgroundAttachmentSurfaceShowsSendableSeededAttachment() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "--dev-preview",
            "quick-capture",
            "--ui-test-seed-quick-capture-recent-chat",
            "--ui-test-seed-quick-capture-attachment"
        ]
        app.launchEnvironment["DEV_PREVIEW"] = "quick-capture"
        app.launch()

        XCTAssertTrue(element(in: app, identifier: "quick-capture-tab-chats").waitForExistence(timeout: 12))
        XCTAssertTrue(element(in: app, identifier: "quick-capture-pending-attachments").exists)
        XCTAssertTrue(app.staticTexts["Shared fixture.pdf"].exists)
        XCTAssertTrue(element(in: app, identifier: "quick-capture-status-list").exists)
        XCTAssertTrue(element(in: app, identifier: "quick-capture-send-button").isEnabled)
    }

    private func element(in app: XCUIApplication, identifier: String) -> XCUIElement {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier == %@", identifier))
            .firstMatch
    }
}
