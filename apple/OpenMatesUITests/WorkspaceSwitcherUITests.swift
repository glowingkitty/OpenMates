import XCTest

@MainActor
final class WorkspaceSwitcherUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
        #if os(iOS)
        XCUIDevice.shared.orientation = .portrait
        #endif
    }

    // contract-test: direct surface=gui.apple assertions=workspace-shell.nav.released-surfaces-visible
    func testCompactGradientPickerExpandsAndNavigatesEveryWorkspace() {
        let app = launch()
        let picker = app.buttons["workspace-switcher"]
        XCTAssertTrue(picker.waitForExistence(timeout: 10)); XCTAssertTrue(picker.isHittable)
        for (id, destination) in [("apps-nav-link", "apps"), ("projects-nav-link", "projects"),
                                  ("tasks-nav-link", "tasks"), ("workflows-nav-link", "workflows"),
                                  ("chats-nav-link", "chat")] {
            picker.tap()
            waitForValue("expanded", element: picker)
            let row = app.buttons[id]
            XCTAssertTrue(row.waitForExistence(timeout: 5)); XCTAssertTrue(row.isHittable)
            XCTAssertGreaterThanOrEqual(row.frame.height, 59)
            XCTAssertGreaterThan(element(app, "workspace-picker-panel").frame.height, 300)
            row.tap()
            waitForValue("collapsed", element: picker)
            waitForLabel("select:\(destination)", element: element(app, "workspace-picker-fixture-action"))
            XCTAssertFalse(app.buttons[id].exists, "Closed options leave the accessibility tree")
        }
        picker.tap()
        app.buttons["chats-nav-link"].tap()
        waitForLabel("new-chat", element: element(app, "workspace-picker-fixture-action"))
        attach(app, name: "workspace-picker-collapsed")
    }

    // contract-test: direct surface=gui.apple assertions=workspace-shell.nav.released-surfaces-visible
    func testOutsideDismissAndExternalNavigationPreserveSelectionWithReducedMotion() {
        let app = launch(variant: "reduced-motion")
        let picker = app.buttons["workspace-switcher"]
        XCTAssertTrue(picker.waitForExistence(timeout: 10))
        assertCollapsedHeaderControlsDoNotOverlap(app, picker: picker)
        picker.tap()
        waitForValue("expanded", element: picker)
        assertExpandedTriggerHasOwnBounds(app, picker: picker)
        XCTAssertEqual(element(app, "workspace-picker-panel").value as? String, "reduced-motion")
        attach(app, name: "workspace-picker-gradient-expanded-reduced-motion")
        // The backdrop intercepts this first outside tap and dismisses the menu.
        app.buttons["workspace-picker-fixture-external"].coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        waitForValue("collapsed", element: picker)
        XCTAssertEqual(element(app, "workspace-picker-fixture-action").label, "ready")
        app.buttons["workspace-picker-fixture-external"].tap()
        waitForLabel("external-tasks", element: element(app, "workspace-picker-fixture-action"))
        picker.tap()
        waitForValue("expanded", element: picker)
        assertExpandedTriggerHasOwnBounds(app, picker: picker)
        XCTAssertTrue(app.buttons["tasks-nav-link"].isSelected)
        picker.tap()
        waitForValue("collapsed", element: picker)
        XCTAssertEqual(element(app, "workspace-picker-fixture-action").label, "external-tasks")
        app.buttons["workspace-picker-fixture-resize"].tap()
        XCTAssertEqual(element(app, "workspace-picker-fixture-action").label, "external-tasks")
    }

    // contract-test: direct surface=gui.apple assertions=workspace-shell.nav.released-surfaces-visible
    func testShortViewportKeepsGradientPanelInsideCanvasAndScrollsToEveryOption() {
        let app = launch(variant: "short-viewport")
        let picker = app.buttons["workspace-switcher"]
        XCTAssertTrue(picker.waitForExistence(timeout: 10))
        assertCollapsedHeaderControlsDoNotOverlap(app, picker: picker)
        for id in ["sidebar-toggle", "compact-logo-button", "settings-button"] {
            app.buttons[id].tap()
            XCTAssertFalse(app.buttons["tasks-nav-link"].exists)
        }
        for (id, destination) in [("tasks-nav-link", "tasks"), ("workflows-nav-link", "workflows")] {
            picker.tap()
            waitForValue("expanded", element: picker)
            assertExpandedTriggerHasOwnBounds(app, picker: picker)
            let panel = element(app, "workspace-picker-panel")
            let canvas = element(app, "workspace-picker-fixture-canvas")
            XCTAssertLessThanOrEqual(panel.frame.maxY, canvas.frame.maxY)
            XCTAssertGreaterThanOrEqual(panel.frame.minY, canvas.frame.minY)
            XCTAssertLessThanOrEqual(panel.frame.height, 320)
            let options = element(app, "workspace-picker-options")
            XCTAssertTrue(options.waitForExistence(timeout: 5))
            options.swipeUp()
            let row = app.buttons[id]
            XCTAssertTrue(row.isHittable)
            XCTAssertGreaterThanOrEqual(row.frame.height, 59)
            XCTAssertGreaterThanOrEqual(row.frame.minY, options.frame.minY - 1)
            XCTAssertLessThanOrEqual(row.frame.maxY, options.frame.maxY + 1)
            attach(app, name: "workspace-picker-short-scrolled-\(destination)")
            row.tap()
            waitForValue("collapsed", element: picker)
            waitForLabel("select:\(destination)", element: element(app, "workspace-picker-fixture-action"))
        }
    }

    // contract-test: direct surface=gui.apple assertions=workspace-shell.nav.released-surfaces-visible
    func testWideHeaderRetainsTabsAndNarrowResizeRetainsActiveWorkspace() throws {
        let app = launch(variant: "wide", fixedViewport: false)
        guard app.windows.firstMatch.frame.width >= 700 else { throw XCTSkip("Wide layout requires an iPad or macOS test destination") }
        let canvas = element(app, "workspace-picker-fixture-canvas")
        XCTAssertTrue(canvas.waitForExistence(timeout: 5))
        XCTAssertEqual(canvas.frame.width, app.windows.firstMatch.frame.width, accuracy: 1)
        let tasks = app.buttons["tasks-nav-link"]
        XCTAssertTrue(tasks.waitForExistence(timeout: 5)); XCTAssertTrue(tasks.isHittable)
        tasks.tap()
        waitForLabel("select:tasks", element: element(app, "workspace-picker-fixture-action"))
        XCTAssertTrue(tasks.isSelected)
        for id in ["chats-nav-link", "apps-nav-link", "projects-nav-link", "workflows-nav-link"] {
            XCTAssertTrue(app.buttons[id].isHittable)
        }
        attach(app, name: "workspace-picker-wide-existing-tabs")
        app.buttons["workspace-picker-fixture-resize"].tap()
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate:
            NSPredicate { _, _ in abs(canvas.frame.width - 320) <= 1 }, object: canvas)], timeout: 5), .completed)
        let picker = app.buttons["workspace-switcher"]
        XCTAssertTrue(picker.waitForExistence(timeout: 5)); picker.tap()
        waitForLabel("select:tasks", element: element(app, "workspace-picker-fixture-action"))
        XCTAssertTrue(app.buttons["tasks-nav-link"].isSelected)
    }

    // contract-test: supporting surface=gui.apple assertions=workspace-shell.nav.released-surfaces-visible
    func testWideColdInitialAppsTapRoutesBeforeTasks() throws {
        let app = launch(variant: "wide", fixedViewport: false)
        guard app.windows.firstMatch.frame.width >= 700 else { throw XCTSkip("Wide layout requires an iPad or macOS test destination") }
        defer {
            let hierarchy = XCTAttachment(string: app.debugDescription)
            hierarchy.name = "workspace-wide-cold-apps-hierarchy"
            hierarchy.lifetime = .keepAlways
            add(hierarchy)
            attach(app, name: "workspace-wide-cold-apps-state")
        }
        let canvas = element(app, "workspace-picker-fixture-canvas")
        XCTAssertTrue(canvas.waitForExistence(timeout: 5))
        XCTAssertEqual(canvas.frame.width, app.windows.firstMatch.frame.width, accuracy: 1)
        for destination in ["apps", "tasks"] {
            let tab = app.buttons["\(destination)-nav-link"]
            XCTAssertTrue(tab.waitForExistence(timeout: 5)); XCTAssertTrue(tab.isHittable)
            tab.tap()
            waitForLabel("select:\(destination)", element: element(app, "workspace-picker-fixture-action"))
            XCTAssertTrue(tab.isSelected)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=workspace-shell.nav.released-surfaces-visible
    func testWideTabsRouteExternalSelectionAndSubsequentTabActions() throws {
        let app = launch(variant: "wide", fixedViewport: false)
        guard app.windows.firstMatch.frame.width >= 700 else { throw XCTSkip("Wide layout requires an iPad or macOS test destination") }
        let canvas = element(app, "workspace-picker-fixture-canvas")
        XCTAssertTrue(canvas.waitForExistence(timeout: 5))
        XCTAssertEqual(canvas.frame.width, app.windows.firstMatch.frame.width, accuracy: 1)
        defer { attach(app, name: "workspace-wide-external-and-tab-actions") }
        let external = app.buttons["workspace-picker-fixture-external"]
        XCTAssertTrue(external.isHittable)
        external.tap()
        waitForLabel("external-tasks", element: element(app, "workspace-picker-fixture-action"))
        XCTAssertTrue(app.buttons["tasks-nav-link"].isSelected)
        for destination in ["apps", "tasks"] {
            let tab = app.buttons["\(destination)-nav-link"]
            XCTAssertTrue(tab.isHittable)
            tab.tap()
            waitForLabel("select:\(destination)", element: element(app, "workspace-picker-fixture-action"))
            XCTAssertTrue(tab.isSelected)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testSyncActivityAppearsBesideProfileAndStopsWithoutBlockingHeader() {
        let app = launch(variant: "reduced-motion")
        let indicator = element(app, "header-sync-indicator")
        XCTAssertFalse(indicator.exists)
        let toggle = app.buttons["workspace-picker-fixture-toggle-sync"]
        XCTAssertTrue(toggle.waitForExistence(timeout: 5))
        XCTAssertTrue(toggle.isHittable)
        toggle.tap()
        XCTAssertTrue(indicator.waitForExistence(timeout: 5))
        let settings = app.buttons["settings-button"]
        XCTAssertTrue(settings.isHittable)
        XCTAssertLessThanOrEqual(indicator.frame.maxX, settings.frame.minX)
        XCTAssertFalse(indicator.frame.intersects(settings.frame))
        XCTAssertTrue(app.buttons["workspace-switcher"].isHittable)
        attach(app, name: "Sync indicator beside profile with accessible header controls")
        app.buttons["workspace-picker-fixture-toggle-sync"].tap()
        let disappeared = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: indicator)
        XCTAssertEqual(XCTWaiter.wait(for: [disappeared], timeout: 5), .completed)
    }

    private func launch(variant: String = "default", fixedViewport: Bool = true) -> XCUIApplication {
        let app = XCUIApplication()
        // Match the parser's environment-first precedence for every option.
        app.launchEnvironment = [
            "DEV_PREVIEW": "workspace-switcher", "DEV_PREVIEW_COMPONENT": "workspace-switcher",
            "DEV_PREVIEW_VARIANT": variant, "DEV_PREVIEW_THEME": "light"
        ]
        if fixedViewport {
            app.launchEnvironment["DEV_PREVIEW_WIDTH"] = variant == "short-viewport" ? "320" : "390"
            app.launchEnvironment["DEV_PREVIEW_HEIGHT"] = variant == "short-viewport" ? "320" : "844"
        }
        app.launchArguments = ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        #if os(iOS)
        XCUIDevice.shared.orientation = .portrait
        #endif
        let window = app.windows.firstMatch
        let canvas = element(app, "dev-component-preview-bounds")
        let viewportReady = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            guard window.exists, canvas.exists else { return false }
            let bounds = window.frame, fixture = canvas.frame
            #if os(iOS)
            guard bounds.height > bounds.width else { return false }
            #endif
            if fixedViewport {
                let expectedHeight: CGFloat = variant == "short-viewport" ? 320 : 844
                guard abs(fixture.height - expectedHeight) <= 1 else { return false }
            }
            return fixture.width > 0 && fixture.height > 0 && bounds.contains(fixture)
        }, object: canvas)
        XCTAssertEqual(XCTWaiter.wait(for: [viewportReady], timeout: 10), .completed,
                       "The header fixture must fit the actual portrait window before interaction")
        XCTAssertFalse(element(app, "dev-preview-error").exists)
        return app
    }
    private func assertCollapsedHeaderControlsDoNotOverlap(_ app: XCUIApplication, picker: XCUIElement) {
        XCTAssertEqual(picker.frame.height, 44, accuracy: 1)
        XCTAssertTrue(picker.isHittable)
        for id in ["sidebar-toggle", "compact-logo-button", "settings-button", "referral-cta"] {
            let control = app.buttons[id]
            XCTAssertTrue(control.isHittable, id)
            XCTAssertFalse(picker.frame.intersects(control.frame), id)
        }
    }
    private func assertExpandedTriggerHasOwnBounds(_ app: XCUIApplication, picker: XCUIElement) {
        let panel = element(app, "workspace-picker-panel")
        attach(app, name: "workspace-picker-expanded-trigger-bounds")
        XCTAssertEqual(picker.frame.height, 44, accuracy: 1,
            "Expanded trigger must not inherit the full panel's accessibility bounds: \(picker.debugDescription)")
        XCTAssertEqual(picker.frame.minY, panel.frame.minY, accuracy: 1)
        XCTAssertTrue(picker.isHittable)
    }

    private func element(_ app: XCUIApplication, _ id: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: id).firstMatch
    }
    private func waitForValue(_ value: String, element: XCUIElement) {
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate:
            NSPredicate(format: "value == %@", value), object: element)], timeout: 5), .completed)
    }
    private func waitForLabel(_ value: String, element: XCUIElement) {
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate:
            NSPredicate(format: "label == %@", value), object: element)], timeout: 5), .completed)
    }
    private func attach(_ app: XCUIApplication, name: String) {
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = name; shot.lifetime = .keepAlways; add(shot)
    }
}
