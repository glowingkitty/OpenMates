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
        XCTAssertTrue(element(in: app, identifier: "message-field").exists)
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
        XCTAssertTrue(element(in: app, identifier: "message-field").exists)
        XCTAssertTrue(sendButton(in: app).isEnabled)
    }

    func testClosingMainWindowKeepsQuickAccessRunningAndReactivationRestoresWindow() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache"]
        app.launch()

        let mainWindow = app.windows.firstMatch
        XCTAssertTrue(mainWindow.waitForExistence(timeout: 15), "Expected the regular OpenMates window on launch")
        XCTAssertEqual(app.windows.count, 1, "Expected exactly one regular OpenMates window on launch")

        mainWindow.typeKey("w", modifierFlags: .command)
        XCTAssertTrue(waitForWindowCount(0, in: app), "Expected Command-W to close the regular window")
        XCTAssertNotEqual(app.state, .notRunning, "Closing the regular window must keep Quick Access running")

        app.activate()
        XCTAssertTrue(
            app.windows.firstMatch.waitForExistence(timeout: 10),
            "Expected Dock activation to restore the regular OpenMates window"
        )
        XCTAssertEqual(app.windows.count, 1, "Expected Dock activation to restore exactly one regular window")
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

    private func waitForWindowCount(_ count: Int, in app: XCUIApplication) -> Bool {
        let predicate = NSPredicate { _, _ in app.windows.count == count }
        let expectation = XCTNSPredicateExpectation(predicate: predicate, object: nil)
        return XCTWaiter.wait(for: [expectation], timeout: 5) == .completed
    }
}
