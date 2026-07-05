// macOS Quick Capture debug-preview UI coverage.
// Launches the same SwiftUI capture surface used by the MenuBarExtra through a
// deterministic dev-preview route so CI does not need to click the system menu
// bar. Covers default chat destination, placeholder tabs, composer affordances,
// and background status visibility without private credentials.

import XCTest

@MainActor
final class MacMenuBarQuickCaptureUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testQuickCapturePreviewShowsDefaultChatDestinationAndComposer() throws {
        let app = launchQuickCapturePreview()

        XCTAssertTrue(
            element(in: app, identifier: "quick-capture-tab-chats").waitForExistence(timeout: 12),
            "Expected Quick Capture preview to launch. Visible UI: \(app.debugDescription)"
        )
        XCTAssertTrue(element(in: app, identifier: "quick-capture-recent-chats").exists)
        XCTAssertTrue(app.staticTexts["New Chat"].exists)
        XCTAssertTrue(app.staticTexts["UI Test Chat"].exists)
        XCTAssertTrue(element(in: app, identifier: "quick-capture-composer").exists)
        XCTAssertTrue(element(in: app, identifier: "quick-capture-message-editor").exists)
        XCTAssertTrue(element(in: app, identifier: "quick-capture-record-audio-button").exists)
        XCTAssertTrue(sendButton(in: app).exists)
    }

    func testQuickCapturePreviewShowsNonChatPlaceholdersWithoutHistory() throws {
        let app = launchQuickCapturePreview()

        let projectsTab = element(in: app, identifier: "quick-capture-tab-projects")
        XCTAssertTrue(
            projectsTab.waitForExistence(timeout: 12),
            "Expected Quick Capture project tab. Visible UI: \(app.debugDescription)"
        )
        projectsTab.tap()
        XCTAssertTrue(element(in: app, identifier: "quick-capture-placeholder-projects").waitForExistence(timeout: 5))
        XCTAssertFalse(element(in: app, identifier: "chat-history").exists)

        let workflowsTab = element(in: app, identifier: "quick-capture-tab-workflows")
        XCTAssertTrue(workflowsTab.exists)
        workflowsTab.tap()
        XCTAssertTrue(element(in: app, identifier: "quick-capture-placeholder-workflows").waitForExistence(timeout: 5))
    }

    func testQuickCapturePreviewShowsSeededPendingAttachmentAndStatusList() throws {
        let app = launchQuickCapturePreview(seedAttachment: true)

        XCTAssertTrue(
            element(in: app, identifier: "quick-capture-tab-chats").waitForExistence(timeout: 12),
            "Expected seeded Quick Capture preview. Visible UI: \(app.debugDescription)"
        )
        XCTAssertTrue(element(in: app, identifier: "quick-capture-pending-attachments").waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Shared fixture.pdf"].exists)
        XCTAssertTrue(element(in: app, identifier: "quick-capture-status-list").exists)
        XCTAssertTrue(sendButton(in: app).isEnabled)
    }

    private func launchQuickCapturePreview(seedAttachment: Bool = false) -> XCUIApplication {
        let app = XCUIApplication()
        var arguments = [
            "--dev-preview",
            "quick-capture",
            "--ui-test-seed-quick-capture-recent-chat"
        ]
        if seedAttachment {
            arguments.append("--ui-test-seed-quick-capture-attachment")
        }
        app.launchArguments = arguments
        app.launchEnvironment["DEV_PREVIEW"] = "quick-capture"
        app.launch()
        return app
    }

    private func element(in app: XCUIApplication, identifier: String) -> XCUIElement {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier == %@", identifier))
            .firstMatch
    }

    private func sendButton(in app: XCUIApplication) -> XCUIElement {
        let identified = element(in: app, identifier: "quick-capture-send-button")
        return identified.exists ? identified : app.buttons["Send"].firstMatch
    }
}
