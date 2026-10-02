// Responsive shell parity coverage for compact and regular native app chrome.
// Launches the real unauthenticated shell with debug-only metrics enabled so the
// test proves drawer versus side-by-side behavior without credentials, private
// chats, network setup, or fragile screenshot pixel comparisons.

import XCTest

final class ChatShellResponsiveParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // contract-test: supporting surface=gui.apple assertions=workspace-shell.nav.released-surfaces-visible,chats.layout.responsive-history
    func testEveryWorkspaceSidebarSharesSearchAndClosesFromItsOwnHeader() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-shell-metrics",
                               "--ui-test-show-workspace-tabs", "--ui-test-workspace-sidebar-fixture"]
        app.launchEnvironment["UI_TEST_SHELL_METRICS"] = "1"
        app.launch()
        let metrics = app.staticTexts
            .containing(NSPredicate(format: "label CONTAINS %@", "shell-width="))
            .firstMatch
        XCTAssertTrue(metrics.waitForExistence(timeout: 12))

        let workspaces = [
            ("tasks", "task-sidebar-row-preview-todo", "Design 3D model"),
            ("projects", "project-sidebar-card-preview-project", "OpenMates"),
            ("workflows", "workflow-sidebar-row", "Weekly AI events")
        ]
        for (workspace, rowIdentifier, query) in workspaces {
            let tab = app.buttons["\(workspace)-nav-link"]
            if !tab.isHittable { app.buttons["workspace-switcher"].tap() }
            XCTAssertTrue(tab.waitForExistence(timeout: 5))
            tab.tap()
            app.buttons["sidebar-toggle"].tap()
            _ = try waitForMetric("chat-panel-open", equals: true, in: metrics)
            let close = app.buttons["\(workspace)-sidebar-close"]
            XCTAssertTrue(close.waitForExistence(timeout: 5))
            try waitForVisibleSidebarControl(close, in: app)
            let search = app.buttons["\(workspace)-sidebar-search"]
            try waitForVisibleSidebarControl(search, in: app)
            XCTAssertTrue(app.buttons[rowIdentifier].firstMatch.exists)
            search.tap()
            let input = app.textFields["\(workspace)-sidebar-search-input"]
            XCTAssertTrue(input.waitForExistence(timeout: 5))
            try waitForVisibleSidebarControl(input, in: app)
            input.tap()
            input.typeText(query)
            XCTAssertTrue(app.buttons[rowIdentifier].firstMatch.waitForExistence(timeout: 5))
            if workspace == "tasks" {
                XCTAssertTrue(app.buttons["task-sidebar-row-preview-backlog-1"].waitForNonExistence(timeout: 5))
                XCTAssertTrue(app.buttons["plan-sidebar-row-preview-plan-draft"].waitForNonExistence(timeout: 5))
            }
            // Toggle search off to clear the query, then prove unmatched search
            // hides records rather than exposing unrelated cached items.
            search.tap()
            XCTAssertTrue(input.waitForNonExistence(timeout: 5), "Closing workspace search clears its input")
            try waitForVisibleSidebarControl(search, in: app)
            search.tap()
            XCTAssertTrue(input.waitForExistence(timeout: 5))
            try waitForVisibleSidebarControl(input, in: app)
            input.tap()
            input.typeText("no matching workspace record")
            XCTAssertTrue(app.descendants(matching: .any)["\(workspace)-sidebar-no-matches"].firstMatch
                .waitForExistence(timeout: 5))
            XCTAssertTrue(app.buttons[rowIdentifier].firstMatch.waitForNonExistence(timeout: 5))
            try waitForVisibleSidebarControl(close, in: app)
            close.tap()
            _ = try waitForMetric("chat-panel-open", equals: false, in: metrics)
            XCTAssertTrue(app.buttons["sidebar-toggle"].waitForExistence(timeout: 5))
        }
        let chatsTab = app.buttons["chats-nav-link"]
        if !chatsTab.isHittable { app.buttons["workspace-switcher"].tap() }
        chatsTab.tap()
        app.buttons["sidebar-toggle"].tap()
        let chatSearch = app.buttons["search-button"]
        try waitForVisibleSidebarControl(chatSearch, in: app)
        chatSearch.tap()
        let chatSearchInput = app.textFields["search-input"]
        XCTAssertTrue(chatSearchInput.waitForExistence(timeout: 5))
        try waitForVisibleSidebarControl(chatSearchInput, in: app)
        app.buttons["search-close-button"].tap()
        XCTAssertTrue(chatSearchInput.waitForNonExistence(timeout: 5))
        let chatClose = app.buttons["chat-sidebar-close"]
        try waitForVisibleSidebarControl(chatClose, in: app)
        chatClose.tap()
        _ = try waitForMetric("chat-panel-open", equals: false, in: metrics)
    }

    // contract-test: direct surface=gui.apple assertions=chats.layout.responsive-history
    func testShellSidebarToggleMatchesViewportMode() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-shell-metrics"]
        app.launchEnvironment["UI_TEST_SHELL_METRICS"] = "1"
        app.launch()

        let metrics = app.staticTexts
            .containing(NSPredicate(format: "label CONTAINS %@", "shell-width="))
            .firstMatch
        XCTAssertTrue(metrics.waitForExistence(timeout: 12))

        let initialLabel = metrics.label
        let initialMode = try stringMetric("shell-mode", in: initialLabel)
        XCTAssertFalse(try boolMetric("chat-panel-open", in: initialLabel))
        XCTAssertTrue(try boolMetric("active-chat-visible", in: initialLabel))

        let githubButton = app.buttons["github-repo-button"]
        XCTAssertTrue(githubButton.waitForExistence(timeout: 5))
        XCTAssertTrue(githubButton.isHittable)

        XCTAssertTrue(app.buttons["sidebar-toggle"].waitForExistence(timeout: 5))
        app.buttons["sidebar-toggle"].tap()

        let openMetrics = try waitForMetric("chat-panel-open", equals: true, in: metrics)
        XCTAssertEqual(try stringMetric("shell-mode", in: openMetrics), initialMode)
        XCTAssertTrue(try boolMetric("chat-panel-visible", in: openMetrics))
        XCTAssertTrue(try boolMetric("active-chat-visible", in: openMetrics))

        if initialMode == "compact" {
            XCTAssertEqual(try stringMetric("panel-mode", in: openMetrics), "drawer")
        } else {
            XCTAssertEqual(try stringMetric("panel-mode", in: openMetrics), "side-by-side")
            XCTAssertGreaterThan(try intMetric("active-main-width", in: openMetrics), 0)
        }

        let screenshot = XCUIScreen.main.screenshot()
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = "Shell responsive parity \(initialMode)"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    // contract-test: direct surface=gui.apple assertions=chats.layout.responsive-history
    func testSettingsEdgeSwipeSettlesFromLiveProgress() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-shell-metrics"]
        app.launchEnvironment["UI_TEST_SHELL_METRICS"] = "1"
        app.launch()

        let window = app.windows.firstMatch
        XCTAssertTrue(window.waitForExistence(timeout: 12))
        let settingsMenu = app.descendants(matching: .any)["settings-menu"].firstMatch

        let rightEdge = window.coordinate(withNormalizedOffset: CGVector(dx: 0.995, dy: 0.5))
        let settingsTravel = min(max(1, window.frame.width - 40), 323)
        rightEdge.press(
            forDuration: 0.1,
            thenDragTo: rightEdge.withOffset(CGVector(dx: -settingsTravel * 0.25, dy: 0))
        )
        XCTAssertTrue(waitUntil(timeout: 3) {
            !settingsMenu.exists || !settingsMenu.isEnabled || !settingsMenu.frame.intersects(window.frame)
        }, "A settings drag below the web 35% threshold must settle fully closed")

        rightEdge.press(
            forDuration: 0.1,
            thenDragTo: rightEdge.withOffset(CGVector(dx: -settingsTravel * 0.5, dy: 0))
        )
        XCTAssertTrue(waitUntil(timeout: 3) {
            settingsMenu.exists && settingsMenu.isEnabled && settingsMenu.frame.intersects(window.frame)
        }, "A settings drag above the web 35% threshold must settle fully open")
    }

    // contract-test: direct surface=gui.apple assertions=chats.layout.responsive-history
    func testSettingsEdgeSwipePreservesOpenRegularSidebar() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-shell-metrics"]
        app.launchEnvironment["UI_TEST_SHELL_METRICS"] = "1"
        app.launch()

        let window = app.windows.firstMatch
        XCTAssertTrue(window.waitForExistence(timeout: 12))
        let metrics = app.descendants(matching: .any)["shell-responsive-metrics"].firstMatch
        XCTAssertTrue(metrics.waitForExistence(timeout: 5))
        guard try stringMetric("shell-mode", in: metrics.label) == "regular" else {
            throw XCTSkip("Combined side-by-side pane regression requires a regular-width iPad viewport")
        }

        let sidebarToggle = app.buttons["sidebar-toggle"]
        XCTAssertTrue(sidebarToggle.waitForExistence(timeout: 5))
        sidebarToggle.tap()
        let sidebarMetrics = try waitForMetric("chat-panel-open", equals: true, in: metrics)
        let sidebarMainWidth = try intMetric("active-main-width", in: sidebarMetrics)

        let rightEdge = window.coordinate(withNormalizedOffset: CGVector(dx: 0.995, dy: 0.5))
        let settingsTravel = min(max(1, window.frame.width - 40), 323)
        rightEdge.press(
            forDuration: 0.1,
            thenDragTo: rightEdge.withOffset(CGVector(dx: -settingsTravel * 0.5, dy: 0))
        )

        let settingsMenu = app.descendants(matching: .any)["settings-menu"].firstMatch
        XCTAssertTrue(waitUntil(timeout: 3) {
            settingsMenu.exists && settingsMenu.isEnabled && settingsMenu.frame.intersects(window.frame)
        })
        let combinedMetrics = try waitForMetric("chat-panel-open", equals: true, in: metrics)
        XCTAssertEqual(try intMetric("active-main-width", in: combinedMetrics), sidebarMainWidth)
        XCTAssertTrue(app.descendants(matching: .any)["chat-history-panel"].firstMatch.exists)
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.parity.web-apple-shell
    func testSettingsOverlayDimsRetainedChatAndBackdropDismissesIt() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-shell-metrics", "-AppleLanguages", "(en)"]
        app.launchEnvironment["UI_TEST_SHELL_METRICS"] = "1"
        app.launch()
        let window = app.windows.firstMatch
        XCTAssertTrue(window.waitForExistence(timeout: 12))
        guard window.frame.width <= 1100 else { throw XCTSkip("Settings backdrop belongs to overlay-width windows") }
        let settings = app.buttons["settings-button"]
        XCTAssertTrue(settings.waitForExistence(timeout: 5)); settings.tap()
        let backdrop = app.buttons["settings-backdrop-dismiss"]
        XCTAssertTrue(backdrop.waitForExistence(timeout: 5))
        let panel = app.descendants(matching: .any)["workspace-settings"].firstMatch
        XCTAssertTrue(panel.exists)
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = "Settings overlay with retained active chat at web 30 percent opacity"; attachment.lifetime = .keepAlways; add(attachment)
        // Tap the visible gutter left of the panel, away from the header.
        let point = backdrop.coordinate(withNormalizedOffset: CGVector(dx: 0, dy: 0.5)).withOffset(CGVector(dx: 10, dy: 0))
        point.tap()
        XCTAssertTrue(backdrop.waitForNonExistence(timeout: 3))
        XCTAssertTrue(settings.isHittable)
    }

    private func waitForVisibleSidebarControl(_ element: XCUIElement, in app: XCUIApplication) throws {
        // Shell state changes before the rail's slide animation has settled.
        // Require the production control to be on screen before interacting.
        let visible = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            element.exists && element.isHittable && element.frame.minX >= 0 &&
                app.windows.firstMatch.frame.contains(element.frame)
        }, object: element)
        XCTAssertEqual(XCTWaiter.wait(for: [visible], timeout: 5), .completed,
                       "Expected visible sidebar control \(element.identifier)")
    }

    private func waitForMetric(_ key: String, equals expected: Bool, in element: XCUIElement) throws -> String {
        let deadline = Date().addingTimeInterval(5)
        while Date() < deadline {
            if (try? boolMetric(key, in: element.label)) == expected {
                return element.label
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        XCTFail("Timed out waiting for \(key)=\(expected). Last metrics: \(element.label)")
        return element.label
    }

    private func waitUntil(timeout: TimeInterval, condition: () -> Bool) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        repeat {
            if condition() { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        } while Date() < deadline
        return condition()
    }

    private func intMetric(_ key: String, in label: String) throws -> Int {
        let value = try XCTUnwrap(metric(key, in: label), "Missing integer metric \(key) in: \(label)")
        return try XCTUnwrap(Int(value), "Invalid integer metric \(key) in: \(label)")
    }

    private func boolMetric(_ key: String, in label: String) throws -> Bool {
        let value = try XCTUnwrap(metric(key, in: label), "Missing boolean metric \(key) in: \(label)")
        return try XCTUnwrap(Bool(value), "Invalid boolean metric \(key) in: \(label)")
    }

    private func stringMetric(_ key: String, in label: String) throws -> String {
        try XCTUnwrap(metric(key, in: label), "Missing string metric \(key) in: \(label)")
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
