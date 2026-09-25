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

    // contract-test: supporting surface=gui.apple assertions=message-input.actions.visibility
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

    // contract-test: tooling
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

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send
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

    // contract-test: infrastructure
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

        let restoredWindow = app.windows.firstMatch
        restoredWindow.typeKey("m", modifierFlags: .command)
        app.activate()
        XCTAssertTrue(restoredWindow.isHittable, "Expected Dock activation to restore a minimized regular window")
        XCTAssertEqual(app.windows.count, 1, "Expected reactivation not to duplicate a minimized regular window")
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.open.local-first-coherent
    func testFileNewWindowKeepsExistingChatVisible() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-authenticated-chat-navigation"]
        app.launchEnvironment["UI_TEST_AUTHENTICATED_CHAT_NAVIGATION"] = "1"
        app.launch()

        XCTAssertTrue(app.staticTexts["chat-header-title"].waitForExistence(timeout: 15))
        XCTAssertEqual(app.staticTexts["chat-header-title"].label, "Current Chat")
        XCTAssertEqual(app.windows.count, 1)

        app.windows.firstMatch.typeKey("n", modifierFlags: .command)
        XCTAssertTrue(waitForWindowCount(2, in: app), "File > New Window must create another chat window")
        XCTAssertTrue(element(in: app, identifier: "new-chat-suggestions").waitForExistence(timeout: 10))
        let windows = (0..<2).map { app.windows.element(boundBy: $0) }
        let original = try XCTUnwrap(windows.first { $0.staticTexts["chat-header-title"].exists })
        XCTAssertEqual(original.staticTexts["chat-header-title"].label, "Current Chat")
        let newWindow = try XCTUnwrap(windows.first {
            $0.descendants(matching: .any)["new-chat-suggestions"].exists
        })
        newWindow.buttons["sidebar-toggle"].tap()
        XCTAssertTrue(newWindow.staticTexts["Current Chat"].waitForExistence(timeout: 5),
                      "The new window must expose chats already loaded in the shared store")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.streaming.progressive-presentation
    func testTwoWindowsKeepSharedSocketRoutedToKeyChat() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-authenticated-chat-navigation"]
        app.launchEnvironment["UI_TEST_AUTHENTICATED_CHAT_NAVIGATION"] = "1"
        app.launch()

        let activeChat = element(in: app, identifier: "shared-socket-active-chat")
        XCTAssertTrue(activeChat.waitForExistence(timeout: 15))
        XCTAssertTrue(waitForLabel("ui-test-current-chat", on: activeChat))

        app.windows.firstMatch.typeKey("n", modifierFlags: .command)
        XCTAssertTrue(waitForWindowCount(2, in: app))
        XCTAssertTrue(waitForLabel("none", on: activeChat),
                      "The key New Window must route the shared socket to its welcome screen")

        let existingChatWindow = try XCTUnwrap((0..<2).map { app.windows.element(boundBy: $0) }
            .first { $0.staticTexts["chat-header-title"].exists })
        existingChatWindow.staticTexts["chat-header-title"].click()
        XCTAssertTrue(waitForLabel("ui-test-current-chat", on: activeChat),
                      "Returning to the existing chat must restore its stream route")
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.focus.parent-state
    func testFileNewChatOpensWindowWithFocusedComposer() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache"]
        app.launch()

        XCTAssertTrue(app.windows.firstMatch.waitForExistence(timeout: 15))
        XCTAssertEqual(app.windows.count, 1)
        app.windows.firstMatch.typeKey("n", modifierFlags: [.command, .shift])
        XCTAssertTrue(waitForWindowCount(2, in: app), "File > New Chat must create a new window")
        let newWindow = try XCTUnwrap((0..<2).map { app.windows.element(boundBy: $0) }
            .first { $0.buttons["message-input-fullscreen-button"].waitForExistence(timeout: 5) })
        let field = element(in: newWindow, identifier: "message-field")
        let editor = element(in: newWindow, identifier: "message-editor")
        XCTAssertTrue(editor.waitForExistence(timeout: 10))
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        XCTAssertLessThan(field.frame.height, newWindow.frame.height / 2,
                          "New Chat must start with the normal composer height")
        XCTAssertTrue(element(in: newWindow, identifier: "composer-attachment-toggle").isHittable)
        XCTAssertTrue(element(in: newWindow, identifier: "composer-model-selector").isHittable)
        let fullscreen = newWindow.buttons["message-input-fullscreen-button"]
        XCTAssertTrue(fullscreen.isHittable)
        app.typeText("Window focus proof")
        XCTAssertTrue(
            newWindow.textViews.matching(NSPredicate(format: "value CONTAINS %@", "Window focus proof"))
                .firstMatch.exists,
            "The new window's composer must receive keyboard input without another click"
        )

        fullscreen.click()
        XCTAssertGreaterThan(field.frame.height, newWindow.frame.height / 2)
        app.typeText(" expanded")
        fullscreen.click()
        XCTAssertLessThan(field.frame.height, newWindow.frame.height / 2)
        app.typeText(" shrunk")
        XCTAssertTrue(newWindow.textViews.matching(
            NSPredicate(format: "value CONTAINS %@", "Window focus proof expanded shrunk")
        ).firstMatch.exists, "Expand and shrink must preserve the editor's insertion focus")
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.focus.parent-state
    func testClosingChatReturnsToIdleWorkspaceLanding() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-authenticated-chat-navigation", "-AppleLanguages", "(en)"]
        app.launchEnvironment["UI_TEST_AUTHENTICATED_CHAT_NAVIGATION"] = "1"
        app.launch()

        XCTAssertTrue(app.staticTexts["chat-header-title"].waitForExistence(timeout: 15))
        app.typeKey("n", modifierFlags: [.command, .shift])
        XCTAssertTrue(waitForWindowCount(2, in: app))
        let newWindow = try XCTUnwrap((0..<2).map { app.windows.element(boundBy: $0) }
            .first { $0.buttons["message-input-fullscreen-button"].waitForExistence(timeout: 5) })
        newWindow.buttons["sidebar-toggle"].click()
        XCTAssertTrue(newWindow.staticTexts["Current Chat"].waitForExistence(timeout: 5))
        newWindow.staticTexts["Current Chat"].click()

        let close = element(in: newWindow, identifier: "chat-close-button")
        XCTAssertTrue(close.waitForExistence(timeout: 15))
        close.click()

        let field = element(in: newWindow, identifier: "message-field")
        XCTAssertTrue(element(in: newWindow, identifier: "new-chat-suggestions").waitForExistence(timeout: 10))
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        XCTAssertLessThanOrEqual(field.frame.height, 64,
                                 "Closing a chat must leave the workspace composer collapsed")
        XCTAssertFalse(newWindow.buttons["message-input-fullscreen-button"].exists)
        XCTAssertFalse(element(in: newWindow, identifier: "action-buttons").exists)
        newWindow.typeKey("x", modifierFlags: [])
        XCTAssertFalse(newWindow.textViews.matching(NSPredicate(format: "value CONTAINS %@", "x"))
            .firstMatch.exists, "Closing a chat must not place insertion focus in the composer")
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.draft-only.addressable
    func testTwoNewChatWindowsAdoptTheirOwnDraftHeaders() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-window-drafts", "-AppleLanguages", "(en)"]
        app.launch()

        let firstEditor = element(in: app, identifier: "message-editor")
        XCTAssertTrue(firstEditor.waitForExistence(timeout: 15))
        firstEditor.click()
        firstEditor.typeText("Window A draft")
        XCTAssertFalse(app.windows.firstMatch.staticTexts["chat-header-title"].exists,
                       "Window A must still be awaiting its draft save when window B opens")

        app.typeKey("n", modifierFlags: [.command, .shift])
        XCTAssertTrue(waitForWindowCount(2, in: app))
        XCTAssertTrue(app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier == %@", "message-editor"))
            .element(boundBy: 1).waitForExistence(timeout: 10))
        app.typeText("Window B draft")

        for draft in ["Window A draft", "Window B draft"] {
            let header = app.staticTexts.matching(
                NSPredicate(format: "identifier == %@ AND label == %@", "chat-header-title", draft)
            ).firstMatch
            XCTAssertTrue(header.waitForExistence(timeout: 20), "Expected the saved draft header for \(draft)")
        }
        let headerTitles = (0..<2).map { index in
            app.windows.element(boundBy: index).staticTexts["chat-header-title"].label
        }
        XCTAssertEqual(Set(headerTitles), Set(["Window A draft", "Window B draft"]))
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

    private func element(in app: XCUIElement, identifier: String) -> XCUIElement {
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

    private func waitForLabel(_ label: String, on element: XCUIElement) -> Bool {
        let expectation = XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "label == %@", label), object: element
        )
        return XCTWaiter.wait(for: [expectation], timeout: 8) == .completed
    }
}
