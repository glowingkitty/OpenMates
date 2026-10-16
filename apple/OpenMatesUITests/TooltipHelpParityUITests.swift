// Tooltip/help parity coverage for native Apple app chrome.
// macOS exposes SwiftUI `.help(Text(...))` as a native help tag/tooltip;
// this UI test hovers an icon-only workspace tab and verifies the tooltip text
// appears instead of relying only on VoiceOver labels.

import XCTest

#if os(macOS)
@MainActor
final class TooltipHelpParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // contract-test: direct surface=gui.apple assertions=chats.layout.responsive-history
    func testMainMacWindowCannotResizeBelowCompactViewport() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache"]
        app.launch()
        let window = app.windows.firstMatch
        XCTAssertTrue(window.waitForExistence(timeout: 12))
        let original = window.frame
        let corner = window.coordinate(withNormalizedOffset: CGVector(dx: 1, dy: 1))
            .withOffset(CGVector(dx: -2, dy: -2))
        let narrow = window.coordinate(withNormalizedOffset: .zero)
            .withOffset(CGVector(dx: 100, dy: original.height - 2))
        corner.press(forDuration: 0.1, thenDragTo: narrow)
        XCTAssertGreaterThanOrEqual(window.frame.width, 320,
                                    "The actual resizable app window must retain the iPhone 4 logical viewport")
        let restoreCorner = window.coordinate(withNormalizedOffset: CGVector(dx: 1, dy: 1))
            .withOffset(CGVector(dx: -2, dy: -2))
        restoreCorner.press(forDuration: 0.1, thenDragTo:
            window.coordinate(withNormalizedOffset: .zero)
                .withOffset(CGVector(dx: original.width - 2, dy: original.height - 2)))
    }

    // contract-test: supporting surface=gui.apple assertions=workspace-shell.nav.released-surfaces-visible
    func testWorkspaceTabHelpAppearsAsNativeTooltipOnHover() throws {
        let app = XCUIApplication()
        app.launchArguments = [
            "--ui-test-disable-auth-cache",
            "--ui-test-show-workspace-tabs"
        ]
        app.launch()

        let projectsTab = element(in: app, identifier: "projects-nav-link")
        XCTAssertTrue(
            projectsTab.waitForExistence(timeout: 12),
            "Expected workspace projects tab. Visible UI: \(app.debugDescription)"
        )
        XCTAssertEqual(projectsTab.label, "Projects")

        projectsTab.hover()

        XCTAssertTrue(
            waitForTooltip(named: "Projects", in: app, timeout: 4),
            "Expected native tooltip text for the Projects tab after hover. Visible UI: \(app.debugDescription)"
        )
    }

    // contract-test: supporting surface=gui.apple assertions=apple-task-board.drag-move,tasks.surface.semantic-parity
    func testTasksCardPointerHoverScalesOnlyThatCardAndKeepsNativeDrop() {
        assertTaskPointerHighlight(workspace: "tasks")
    }

    // contract-test: supporting surface=gui.apple assertions=projects.surface.semantic-parity,workflows-ui.responsive-accessible-reachable
    func testWorkspaceHomeCardHoverScalesWithoutMovingLayoutAndStillOpens() {
        let app = XCUIApplication()
        app.launchEnvironment = ["UI_TEST_SHELL_METRICS": "1"]
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-show-workspace-tabs",
            "--ui-test-workspace-sidebar-fixture", "--ui-test-shell-metrics",
            "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let metrics = app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "shell-width=")).firstMatch
        XCTAssertTrue(metrics.waitForExistence(timeout: 12))
        let ready = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label CONTAINS %@", "fixture-ready=true"), object: metrics)
        XCTAssertEqual(XCTWaiter.wait(for: [ready], timeout: 5), .completed)
        XCTAssertFalse(element(in: app, identifier: "dev-preview-root").exists)
        for workspace in ["projects", "workflows"] {
            let tab = app.buttons["\(workspace)-nav-link"]
            if !tab.isHittable { app.buttons["workspace-switcher"].tap() }
            XCTAssertTrue(tab.waitForExistence(timeout: 5)); XCTAssertTrue(tab.isHittable)
            tab.tap()
            let card = workspace == "projects"
                ? app.buttons["project-card-preview-project"]
                : app.buttons.matching(identifier: "workflow-landing-card").firstMatch
            XCTAssertTrue(card.waitForExistence(timeout: 8)); XCTAssertTrue(card.isHittable)
            assertHomeCardHover(card, pointerAway: tab, app: app)
            card.tap()
            let opened = workspace == "projects" ? "project-tab-tasks" : "workflow-detail-back"
            XCTAssertTrue(app.buttons[opened].waitForExistence(timeout: 8),
                          "Hover must retain the production card's navigation action")
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apps.presentation.shared-detail-and-recency
    func testAppHomeCardHoverRestoresGeometryAndRetainsDetailNavigation() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-apps-workspace"]
        app.launch()
        let card = app.buttons["apps-app-card-web"]
        let pointerAway = app.buttons["apps-inspiration-next"]
        XCTAssertTrue(card.waitForExistence(timeout: 15)); XCTAssertTrue(card.isHittable)
        XCTAssertTrue(pointerAway.waitForExistence(timeout: 5)); XCTAssertTrue(pointerAway.isHittable)
        assertHomeCardHover(card, pointerAway: pointerAway, app: app)
        card.tap()
        XCTAssertTrue(element(in: app, identifier: "apps-detail-fullscreen").waitForExistence(timeout: 8))
    }

    private func assertHomeCardHover(_ card: XCUIElement, pointerAway: XCUIElement, app: XCUIApplication) {
        pointerAway.hover()
        let original = card.frame
        let originalAway = pointerAway.frame
        card.hover()
        let enlarged = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            abs(card.frame.width - original.width * 1.05) <= 2 &&
            abs(card.frame.height - original.height * 1.05) <= 2
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [enlarged], timeout: 3), .completed)
        XCTAssertEqual(pointerAway.frame.minX, originalAway.minX, accuracy: 2)
        XCTAssertEqual(pointerAway.frame.minY, originalAway.minY, accuracy: 2)
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = "Home card 1.05 pointer feedback"; screenshot.lifetime = .keepAlways; add(screenshot)
        pointerAway.hover()
        let restored = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            abs(card.frame.width - original.width) <= 2 &&
            abs(card.frame.height - original.height) <= 2
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [restored], timeout: 3), .completed)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-task-board.drag-move,projects.surface.semantic-parity
    func testProjectKanbanCardPointerHoverScalesOnlyThatCardAndKeepsNativeDrop() {
        assertTaskPointerHighlight(workspace: "projects")
    }

    private func assertTaskPointerHighlight(workspace: String) {
        let app = XCUIApplication()
        // Exercise the genuine MainAppView workspace router. Component DevPreview
        // pages remain Simulator-only; this signed-out fixture is a full app shell.
        app.launchEnvironment = ["UI_TEST_SHELL_METRICS": "1"]
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-show-workspace-tabs",
            "--ui-test-workspace-sidebar-fixture", "--ui-test-shell-metrics",
            "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let metrics = app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "shell-width=")).firstMatch
        XCTAssertTrue(metrics.waitForExistence(timeout: 12))
        let ready = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label CONTAINS %@", "fixture-ready=true"), object: metrics)
        XCTAssertEqual(XCTWaiter.wait(for: [ready], timeout: 5), .completed)
        XCTAssertFalse(element(in: app, identifier: "dev-preview-root").exists,
                       "Hover proof must use the production full-parent route")
        let tab = app.buttons["\(workspace)-nav-link"]
        if !tab.isHittable { app.buttons["workspace-switcher"].tap() }
        XCTAssertTrue(tab.waitForExistence(timeout: 5)); XCTAssertTrue(tab.isHittable)
        tab.tap()
        if workspace == "projects" {
            let project = app.buttons["project-card-preview-project"]
            XCTAssertTrue(project.waitForExistence(timeout: 5)); XCTAssertTrue(project.isHittable)
            project.tap()
            let tasksTab = app.buttons["project-tab-tasks"]
            XCTAssertTrue(tasksTab.waitForExistence(timeout: 5)); XCTAssertTrue(tasksTab.isHittable)
            tasksTab.tap()
        }
        let board = element(in: app, identifier: "task-board")
        XCTAssertTrue(board.waitForExistence(timeout: 10))
        let backlog = element(in: app, identifier: "task-column-backlog")
        let todo = element(in: app, identifier: "task-column-todo")
        let title = backlog.buttons.matching(identifier: "task-card-open").firstMatch
        XCTAssertTrue(title.waitForExistence(timeout: 5)); XCTAssertTrue(title.isHittable)
        // Move the actual pointer away first; launch may restore its location.
        todo.staticTexts.firstMatch.hover()
        let originalTitle = title.frame
        let originalColumn = backlog.frame
        let neighbor = todo.buttons.matching(identifier: "task-card-open").firstMatch
        XCTAssertTrue(neighbor.exists)
        let originalNeighbor = neighbor.frame
        title.hover()
        let enlarged = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            abs(title.frame.width - originalTitle.width * 1.1) <= 2 &&
            abs(title.frame.height - originalTitle.height * 1.1) <= 2
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [enlarged], timeout: 3), .completed,
                       "Actual pointer hover must render the shared card at 1.1")
        XCTAssertEqual(backlog.frame.width, originalColumn.width, accuracy: 2)
        XCTAssertEqual(neighbor.frame.width, originalNeighbor.width, accuracy: 2)
        let hovered = XCTAttachment(screenshot: app.screenshot())
        hovered.name = "\(workspace) actual task pointer highlight 1.1"; hovered.lifetime = .keepAlways; add(hovered)
        todo.staticTexts.firstMatch.hover()
        let restored = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            abs(title.frame.width - originalTitle.width) <= 2 &&
            abs(title.frame.height - originalTitle.height) <= 2
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [restored], timeout: 3), .completed)
        let movedTitle = title.label
        let card = backlog.descendants(matching: .any).matching(identifier: "task-card").firstMatch
        XCTAssertTrue(card.isHittable)
        // Retain the existing actual native lift/drag timings and full-card surface.
        card.coordinate(withNormalizedOffset: CGVector(dx: 0.06, dy: 0.95))
            .press(forDuration: 0.8, thenDragTo: todo.coordinate(withNormalizedOffset: CGVector(dx: 0.1, dy: 0.18)),
                   withVelocity: .default, thenHoldForDuration: 0.35)
        let moved = todo.buttons.matching(NSPredicate(format: "identifier == %@ AND label == %@", "task-card-open", movedTitle)).firstMatch
        XCTAssertTrue(moved.waitForExistence(timeout: 5), "The real native drop must still move the highlighted task")
        XCTAssertFalse(element(in: app, identifier: "task-action-menu-items").exists)
        let dropped = XCTAttachment(screenshot: app.screenshot())
        dropped.name = "\(workspace) native drop after pointer highlight"; dropped.lifetime = .keepAlways; add(dropped)
    }

    private func element(in app: XCUIApplication, identifier: String) -> XCUIElement {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier == %@", identifier))
            .firstMatch
    }

    private func waitForTooltip(named label: String, in app: XCUIApplication, timeout: TimeInterval) -> Bool {
        let appTooltip = app.staticTexts.matching(NSPredicate(format: "label == %@", label)).firstMatch
        let accessibilityTooltip = XCUIApplication(bundleIdentifier: "com.apple.AccessibilityUIServer")
            .staticTexts
            .matching(NSPredicate(format: "label == %@", label))
            .firstMatch
        let deadline = Date().addingTimeInterval(timeout)

        while Date() < deadline {
            if appTooltip.exists || accessibilityTooltip.exists {
                return true
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        return false
    }
}
#endif
