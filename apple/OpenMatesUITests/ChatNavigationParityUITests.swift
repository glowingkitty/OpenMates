// Chat header/sidebar navigation parity coverage.
// Launches a DEBUG-only authenticated fixture with deterministic in-memory chats
// so the native app can prove the same sidebar/header order as the web spec
// without credentials, private records, WebSocket traffic, or provider calls.
//
// Web source: frontend/apps/web_app/tests/chat-header-navigation-order.spec.ts

import XCTest

@MainActor
final class ChatNavigationParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // contract-test: direct surface=gui.apple assertions=chat-navigation.draft-only.addressable,chat-navigation.order.sidebar-header-match,chat-navigation.empty-new-chat.excluded
    func testHeaderNavigationFollowsSidebarOrderIncludingDraftOnlyChat() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-authenticated-chat-navigation"]
        app.launchEnvironment["UI_TEST_AUTHENTICATED_CHAT_NAVIGATION"] = "1"
        app.launch()

        XCTAssertTrue(app.wait(for: .runningForeground, timeout: 12))
        try assertHeaderTitle("Current Chat", in: app)

        let metrics = app.staticTexts
            .containing(NSPredicate(format: "label CONTAINS %@", "chat-navigation-order="))
            .firstMatch
        XCTAssertTrue(metrics.waitForExistence(timeout: 12))
        let order = try stringMetric("chat-navigation-order", in: metrics.label)
        XCTAssertTrue(
            order.hasPrefix("ui-test-draft-chat,ui-test-newer-chat,ui-test-current-chat,ui-test-older-chat"),
            "Header navigation order must match the rendered sidebar order. Actual: \(order)"
        )
        XCTAssertFalse(order.contains("ui-test-empty-shell-chat"), "Empty new-chat shells must not be navigable.")
        XCTAssertEqual(try stringMetric("selected-chat-id", in: metrics.label), "ui-test-current-chat")

        let sidebarToggle = app.buttons["sidebar-toggle"]
        sidebarToggle.tap()
        XCTAssertTrue(app.descendants(matching: .any)["chat-history-panel"].waitForExistence(timeout: 5))
        try assertSidebarRowsInOrder(["Header navigation draft", "Newer Chat", "Current Chat", "Older Chat"], in: app)
        app.terminate()
        app.launch()
        XCTAssertTrue(app.wait(for: .runningForeground, timeout: 12))
        try assertHeaderTitle("Current Chat", in: app)

        let nextButton = app.buttons["chat-header-next"]
        let previousButton = app.buttons["chat-header-previous"]
        XCTAssertTrue(nextButton.waitForExistence(timeout: 5))
        XCTAssertTrue(previousButton.waitForExistence(timeout: 5))
        XCTAssertLessThan(nextButton.frame.midX, previousButton.frame.midX, "Next/newer control belongs on the left; previous/older belongs on the right.")

        previousButton.tap()
        try assertHeaderTitle("Older Chat", in: app)
        XCTAssertEqual(try waitForMetric("selected-chat-id", equals: "ui-test-older-chat", in: metrics), "ui-test-older-chat")

        app.buttons["chat-header-next"].tap()
        try assertHeaderTitle("Current Chat", in: app)
        XCTAssertEqual(try waitForMetric("selected-chat-id", equals: "ui-test-current-chat", in: metrics), "ui-test-current-chat")

        app.buttons["chat-header-next"].tap()
        try assertHeaderTitle("Newer Chat", in: app)
        XCTAssertEqual(try waitForMetric("selected-chat-id", equals: "ui-test-newer-chat", in: metrics), "ui-test-newer-chat")

        app.buttons["chat-header-next"].tap()
        try assertHeaderTitle("Header navigation draft", in: app)
        XCTAssertTrue(app.descendants(matching: .any)["draft-chat-badge"].waitForExistence(timeout: 5))
        XCTAssertEqual(try waitForMetric("selected-chat-id", equals: "ui-test-draft-chat", in: metrics), "ui-test-draft-chat")
    }

    // contract-test: direct surface=gui.apple assertions=drafts.draft-only.lifecycle,chat-navigation.empty-new-chat.excluded
    func testClearingAdoptedDraftReturnsToUnfocusedWorkspaceLanding() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-window-drafts", "-AppleLanguages", "(en)"]
        app.launch()
        let editor = app.textViews["message-editor"].firstMatch
        XCTAssertTrue(editor.waitForExistence(timeout: 15))
        editor.tap()
        let draft = "Draft to clear"
        editor.typeText(draft)
        try assertHeaderTitle(draft, in: app)
        let adopted = app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier BEGINSWITH %@", "chat-view-")).firstMatch
        XCTAssertTrue(adopted.waitForExistence(timeout: 10))
        let removedID = adopted.identifier
        editor.tap()
        editor.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: draft.count))
        let closed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"),
                                               object: app.descendants(matching: .any)[removedID])
        XCTAssertEqual(XCTWaiter.wait(for: [closed], timeout: 12), .completed)
        XCTAssertTrue(app.descendants(matching: .any)["chat-workspace-welcome"].waitForExistence(timeout: 5))
        let keyboardClosed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"),
                                                       object: app.keyboards.firstMatch)
        XCTAssertEqual(XCTWaiter.wait(for: [keyboardClosed], timeout: 5), .completed,
                       "Deleting the draft returns to reading the workspace")
        XCTAssertEqual(app.textViews["message-editor"].firstMatch.value as? String, "")
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.open.local-first-coherent
    func testContinuationOpensPersistedChatWithoutReplayingComposerFocus() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-authenticated-chat-navigation", "--ui-test-stale-composer-focus"]
        app.launch()
        try assertHeaderTitle("Current Chat", in: app)
        app.buttons["chat-close-button"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["chat-workspace-welcome"].waitForExistence(timeout: 5))
        let card = app.descendants(matching: .any).matching(NSPredicate(format: "identifier IN %@",
            ["welcome-chat-card-ui-test-current-chat", "welcome-chat-compact-card-ui-test-current-chat"])).firstMatch
        XCTAssertTrue(card.waitForExistence(timeout: 8))
        card.tap()
        try assertHeaderTitle("Current Chat", in: app)
        XCTAssertFalse(app.keyboards.firstMatch.exists, "A continuation card opens the transcript for reading")
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label == %@", "Current Chat")).firstMatch.exists)
    }

    // contract-test: direct surface=gui.apple assertions=chat-navigation.open.local-first-coherent
    func testSelectingSidebarChatClosesPreviousFullscreenEmbedAndPreservesTranscript() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-authenticated-chat-navigation", "--ui-test-navigation-embed"]
        app.launch()
        try assertHeaderTitle("Current Chat", in: app)
        // Code cards combine their children into the production open button.
        // Scope the action to the persisted assistant's named code artifact.
        let assistant = app.descendants(matching: .any)["message-assistant"].firstMatch
        let preview = assistant.buttons.matching(NSPredicate(
            format: "identifier == %@ AND label CONTAINS %@", "embed-preview", "example.py")).firstMatch
        XCTAssertTrue(preview.waitForExistence(timeout: 10))
        preview.tap()
        let fullscreen = app.descendants(matching: .any)["embed-fullscreen-header"].firstMatch
        XCTAssertTrue(fullscreen.waitForExistence(timeout: 8))
        try selectSidebarChat("Newer Chat", in: app)
        let closed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: fullscreen)
        XCTAssertEqual(XCTWaiter.wait(for: [closed], timeout: 5), .completed)
        XCTAssertFalse(app.keyboards.firstMatch.exists)
        try selectSidebarChat("Current Chat", in: app)
        XCTAssertTrue(preview.waitForExistence(timeout: 8), "Original persisted embed remains in the transcript")
        XCTAssertFalse(fullscreen.exists, "Returning to a chat does not restore a dismissed overlay")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chat-navigation.open.local-first-coherent
    func testSavedSheetReferenceHydratesPreviewFullscreenAndSurvivesChatReparse() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-authenticated-chat-navigation", "--ui-test-sheet-reference-hydration"]
        app.launch()
        try assertHeaderTitle("Current Chat", in: app)
        XCTAssertTrue(app.descendants(matching: .any)["sheet-preview-table"].waitForExistence(timeout: 10))
        let preview = app.descendants(matching: .any)["embed-preview-ui-test-sheet-reference"].firstMatch
        if app.windows.firstMatch.frame.width >= 600 {
            XCTAssertGreaterThan(preview.frame.width, 400,
                "A standalone assistant Sheet must use its large preview in a wide transcript")
            let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
            screenshot.name = "Persisted standalone assistant Sheet uses large preview"
            screenshot.lifetime = .keepAlways
            add(screenshot)
        }
        preview.tap()
        XCTAssertTrue(app.descendants(matching: .any)["sheet-fullscreen-table"].waitForExistence(timeout: 8))
        try assertSheetFullscreenValue("Saved Row A", in: app)
        try assertSheetFullscreenValue("Saved Row B", in: app)
        try selectSidebarChat("Newer Chat", in: app)
        XCTAssertTrue(app.descendants(matching: .any)["sheet-fullscreen-table"].firstMatch
            .waitForNonExistence(timeout: 5), "Changing chats dismisses the previous Sheet fullscreen")
        try selectSidebarChat("Current Chat", in: app)
        XCTAssertTrue(app.descendants(matching: .any)["sheet-preview-table"].waitForExistence(timeout: 8))
        app.descendants(matching: .any)["embed-preview-ui-test-sheet-reference"].firstMatch.tap()
        try assertSheetFullscreenValue("Saved Row B", in: app)
    }

    private func selectSidebarChat(_ title: String, in app: XCUIApplication) throws {
        let close = app.buttons["chat-sidebar-close"]
        if !close.exists {
            let open = app.buttons["sidebar-toggle"]
            XCTAssertTrue(open.waitForExistence(timeout: 5))
            XCTAssertTrue(open.isHittable)
            open.tap()
        }
        // The sidebar stays open after selection on regular-width viewports.
        // Wait for its animated rail to reach the screen before choosing a row.
        let row = app.buttons.matching(NSPredicate(format: "label == %@", title)).firstMatch
        let visible = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            row.exists && row.isHittable && row.frame.minX >= 0 &&
                app.windows.firstMatch.frame.contains(row.frame)
        }, object: row)
        XCTAssertEqual(XCTWaiter.wait(for: [visible], timeout: 5), .completed,
                       "Expected visible sidebar chat \(title)")
        row.tap()
        try assertHeaderTitle(title, in: app)
        // Close through the sidebar's production header when selection retains it.
        // Compact selection closes the drawer itself and restores the menu button.
        let navigationSettled = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            (close.exists && close.isHittable && close.frame.minX >= 0) ||
                app.buttons["sidebar-toggle"].isHittable
        }, object: app)
        XCTAssertEqual(XCTWaiter.wait(for: [navigationSettled], timeout: 5), .completed)
        if close.exists && close.isHittable && close.frame.minX >= 0 { close.tap() }
        XCTAssertTrue(app.buttons["sidebar-toggle"].waitForExistence(timeout: 5))
    }

    private func assertHeaderTitle(_ expected: String, in app: XCUIApplication) throws {
        let title = app.staticTexts["chat-header-title"]
        let settled = XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "exists == true AND label == %@", expected), object: title)
        XCTAssertEqual(XCTWaiter.wait(for: [settled], timeout: 12), .completed,
                       "Expected chat header title \(expected); observed \(title.exists ? title.label : "missing")")
        XCTAssertEqual(title.label, expected)
    }

    private func assertSheetFullscreenValue(_ expected: String, in app: XCUIApplication) throws {
        let table = app.descendants(matching: .any)["sheet-fullscreen-table"].firstMatch
        // Fullscreen cells use selectable UITextViews so long values wrap and
        // remain copyable. Match the exact value within this table.
        let cell = table.textViews.matching(NSPredicate(format: "value == %@", expected)).firstMatch
        XCTAssertTrue(cell.waitForExistence(timeout: 8), "Missing saved table value \(expected)")
        XCTAssertEqual(cell.value as? String, expected)
    }

    // contract-test: supporting surface=gui.apple assertions=chat-navigation.order.sidebar-header-match
    func testGlobalSearchFromWorkflowRestoresCurrentChatOnCancel() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-authenticated-chat-navigation",
                               "--ui-test-workflows-fixture", "home",
                               "--ui-test-workspace-search"]
        app.launchEnvironment["UI_TEST_AUTHENTICATED_CHAT_NAVIGATION"] = "1"
        app.launch()
        // SwiftUI exposes the identifier on an enclosing Other element; read
        // the static text, as the existing navigation case does.
        let metrics = app.staticTexts
            .containing(NSPredicate(format: "label CONTAINS %@", "chat-navigation-order="))
            .firstMatch
        XCTAssertTrue(metrics.waitForExistence(timeout: 12))
        XCTAssertEqual(try waitForMetric("selected-workspace", equals: "workflows", in: metrics), "workflows")
        let before = try XCTUnwrap(Int(try stringMetric("active-chat-revision", in: metrics.label)))
        app.buttons["workspace-search-ui-test"].tap()
        XCTAssertTrue(app.textFields["search-input"].waitForExistence(timeout: 5))
        app.buttons["search-close-button"].tap()
        let searchClosed = XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "exists == false"),
            object: app.textFields["search-input"])
        XCTAssertEqual(XCTWaiter.wait(for: [searchClosed], timeout: 5), .completed,
                       "Closing Search must remove its input before returning to the chat history.")
        let sidebarClose = app.buttons["chat-sidebar-close"]
        if sidebarClose.waitForExistence(timeout: 3), sidebarClose.isHittable { sidebarClose.tap() }
        try assertHeaderTitle("Current Chat", in: app)
        XCTAssertEqual(try waitForMetric("selected-workspace", equals: "chat", in: metrics), "chat")
        XCTAssertEqual(try waitForMetric("active-chat-id", equals: "ui-test-current-chat", in: metrics), "ui-test-current-chat")
        let announced = XCTNSPredicateExpectation(
            predicate: NSPredicate { _, _ in
                (self.metric("active-chat-revision", in: metrics.label).flatMap(Int.init) ?? 0) > before
            }, object: metrics)
        XCTAssertEqual(XCTWaiter.wait(for: [announced], timeout: 5), .completed,
                       "Returning from a workspace through Search must reannounce the unchanged chat.")
    }

    private func assertSidebarRowsInOrder(_ titles: [String], in app: XCUIApplication) throws {
        let rows = titles.map { title in
            app.buttons.matching(NSPredicate(format: "label == %@", title)).firstMatch
        }
        for (index, row) in rows.enumerated() {
            XCTAssertTrue(row.waitForExistence(timeout: 5), "Missing sidebar row: \(titles[index])")
        }
        for index in 1..<rows.count {
            XCTAssertLessThan(rows[index - 1].frame.minY, rows[index].frame.minY)
        }
    }

    private func waitForMetric(_ key: String, equals expected: String, in element: XCUIElement) throws -> String {
        let deadline = Date().addingTimeInterval(5)
        while Date() < deadline {
            if let value = metric(key, in: element.label), value == expected {
                return value
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        XCTFail("Timed out waiting for \(key)=\(expected). Last metrics: \(element.label)")
        return try stringMetric(key, in: element.label)
    }

    private func stringMetric(_ key: String, in label: String) throws -> String {
        try XCTUnwrap(metric(key, in: label), "Missing metric \(key) in: \(label)")
    }

    private func metric(_ key: String, in label: String) -> String? {
        label
            .split(separator: ";")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .first { $0.hasPrefix("\(key)=") }?
            .dropFirst(key.count + 1)
            .description
    }
}
