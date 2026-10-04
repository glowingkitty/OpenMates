import XCTest

@MainActor
final class WatchWorkflowDetailUITests: XCTestCase {
    override func tearDownWithError() throws {
        if let testRun, testRun.failureCount > 0 {
            let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
            screenshot.name = "Watch failure screenshot — " + name
            screenshot.lifetime = .keepAlways
            add(screenshot)
            let hierarchy = XCTAttachment(string: XCUIApplication().debugDescription)
            hierarchy.name = "Watch failure accessibility tree — " + name
            hierarchy.lifetime = .keepAlways
            add(hierarchy)
        }
        try super.tearDownWithError()
    }

    override func setUpWithError() throws { continueAfterFailure = false }
    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.workflows.compact-editor,apple-watch.handoff.exact-private
    func testHubOpensRealCompactGraphExpandsNodesAndReturnsToWorkflowList() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-hub-lists"]
        app.launch()
        let workflows = app.buttons["watch-hub-select-workflows"]
        XCTAssertTrue(workflows.waitForExistence(timeout: 12)); workflows.tap()
        let row = app.buttons["watch-workflow-row-workflow-one"]
        XCTAssertTrue(row.waitForExistence(timeout: 5)); row.tap()
        XCTAssertTrue(app.staticTexts["watch-workflow-detail-title"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts["watch-ui-test-open-request"].exists)
        let scroll = app.scrollViews["watch-workflow-detail-scroll"]
        for node in ["trigger", "weather", "ask", "check", "message"] {
            let card = app.buttons["watch-workflow-node-\(node)"]
            reveal(card, in: scroll); card.tap()
            let expanded = app.otherElements["watch-workflow-node-expanded-\(node)"]
            XCTAssertTrue(expanded.waitForExistence(timeout: 3))
            let edit = app.buttons["watch-workflow-edit-\(node)"]
            reveal(edit, in: scroll)
            XCTAssertTrue(edit.isHittable)
            edit.tap()
            XCTAssertTrue(app.staticTexts["watch-workflow-editor-title"].waitForExistence(timeout: 3))
            let back = app.buttons["watch-workflow-detail-back"]
            XCTAssertTrue(back.isHittable); back.tap()
            reveal(card, in: scroll)
            XCTAssertTrue(expanded.exists)
            card.tap()
            XCTAssertFalse(expanded.exists)
        }
        let phone = app.buttons["watch-workflow-detail-open-on-phone"]
        reveal(phone, in: scroll); phone.tap()
        let request = app.staticTexts["watch-ui-test-open-request"]
        XCTAssertTrue(request.waitForExistence(timeout: 3))
        XCTAssertEqual(request.label, "workflow:workflow-one")
        screenshot("Watch compact graph and explicit iPhone handoff")
        let back = app.buttons["watch-workflow-detail-back"]
        XCTAssertTrue(back.isHittable); back.tap()
        XCTAssertTrue(row.waitForExistence(timeout: 5)); XCTAssertTrue(row.isHittable)
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.workflows.compact-editor
    func testProductionEditorCancelDiscardsChangeThenSaveConfirmsChangedValue() {
        let app = launch("--ui-test-watch-workflow-detail")
        let scroll = app.scrollViews["watch-workflow-detail-scroll"]
        openMessageEditor(app, scroll: scroll)
        let boolean = app.buttons["watch-workflow-edit-field-config/blocks/0/only_new_results"]
        XCTAssertFalse(app.textFields["watch-workflow-edit-field-title"].exists)
        let title = app.buttons["watch-workflow-choose-field-title"]
        reveal(title, in: scroll); title.tap()
        XCTAssertTrue(app.otherElements["watch-workflow-field-editor"].waitForExistence(timeout: 3))
        XCTAssertTrue(app.textFields["watch-workflow-edit-field-title"].exists)
        app.buttons["watch-workflow-detail-back"].tap()
        XCTAssertFalse(app.otherElements["watch-workflow-field-editor"].exists)
        reveal(boolean, in: scroll); XCTAssertEqual(boolean.value as? String, "true"); boolean.tap()
        let cancel = app.buttons["watch-workflow-cancel"]
        XCTAssertTrue(cancel.isHittable); cancel.tap()
        XCTAssertFalse(app.otherElements["watch-workflow-editor"].exists)
        openMessageEditor(app, scroll: scroll)
        reveal(boolean, in: scroll); XCTAssertEqual(boolean.value as? String, "true"); boolean.tap()
        let save = app.buttons["watch-workflow-save"]
        XCTAssertTrue(save.isHittable); save.tap()
        let editorGone = NSPredicate(format: "exists == false")
        expectation(for: editorGone, evaluatedWith: app.otherElements["watch-workflow-editor"])
        waitForExpectations(timeout: 5)
        openMessageEditor(app, scroll: scroll)
        reveal(boolean, in: scroll); XCTAssertEqual(boolean.value as? String, "false")
        screenshot("Watch edited message delivery option persisted through server-confirmed fixture save")
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.workflows.compact-editor
    func testSaveFailureRetainsExactDraftAndRetryUsesProductionSaveControl() {
        let app = launch("--ui-test-watch-workflow-save-failure")
        let scroll = app.scrollViews["watch-workflow-detail-scroll"]
        openMessageEditor(app, scroll: scroll)
        let boolean = app.buttons["watch-workflow-edit-field-config/blocks/0/only_new_results"]
        reveal(boolean, in: scroll); boolean.tap()
        let save = app.buttons["watch-workflow-save"]
        XCTAssertTrue(save.isHittable); save.tap()
        XCTAssertTrue(app.staticTexts["watch-workflow-save-error"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["watch-workflow-save-error"].isHittable)
        reveal(boolean, in: scroll); XCTAssertEqual(boolean.value as? String, "false")
        XCTAssertTrue(save.isHittable); XCTAssertTrue(save.isEnabled); save.tap()
        expectation(for: NSPredicate(format: "exists == false"), evaluatedWith: app.otherElements["watch-workflow-editor"])
        waitForExpectations(timeout: 5)
        openMessageEditor(app, scroll: scroll)
        reveal(boolean, in: scroll); XCTAssertEqual(boolean.value as? String, "false")
        screenshot("Watch retained draft after failed save and successful retry")
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.workflows.compact-editor
    func testFailedDetailRetriesAndEmptyGraphHasVisibleState() {
        let app = launch("--ui-test-watch-workflow-retry", expectsLoaded: false)
        XCTAssertTrue(app.staticTexts["watch-workflow-detail-error"].waitForExistence(timeout: 5))
        let retry = app.buttons["watch-workflow-detail-retry"]
        XCTAssertTrue(retry.isHittable); retry.tap()
        XCTAssertTrue(app.buttons["watch-workflow-node-trigger"].waitForExistence(timeout: 5))
        app.terminate()
        app.launchArguments = ["--ui-test-watch-workflow-empty"]
        app.launch()
        XCTAssertTrue(app.staticTexts["watch-workflow-detail-empty"].waitForExistence(timeout: 12))
        XCTAssertFalse(app.buttons["watch-workflow-node-trigger"].exists)
        screenshot("Watch empty workflow graph")
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.workflows.compact-editor
    func testDigitalCrownScrollsGraphWhileBackRemainsVisible() {
        let app = launch("--ui-test-watch-workflow-detail")
        let first = app.buttons["watch-workflow-node-trigger"]
        let last = app.buttons["watch-workflow-node-message"]
        let back = app.buttons["watch-workflow-detail-back"]
        XCTAssertTrue(first.isHittable); XCTAssertFalse(last.isHittable)
        let backY = back.frame.minY
        for _ in 0..<12 where !last.isHittable {
            XCUIDevice.shared.rotateDigitalCrown(delta: -1)
            XCTAssertTrue(back.isHittable)
            XCTAssertEqual(back.frame.minY, backY, accuracy: 0.5)
        }
        XCTAssertTrue(last.isHittable)
        XCTAssertFalse(first.isHittable)
        last.tap()
        XCTAssertTrue(app.buttons["watch-workflow-edit-message"].waitForExistence(timeout: 3))
        let selectedNodeY = last.frame.minY
        XCUIDevice.shared.rotateDigitalCrown(delta: -0.25)
        XCTAssertLessThan(last.frame.minY, selectedNodeY,
                          "Crown must continue from the expanded node's viewport")
        XCTAssertTrue(back.isHittable)
        XCTAssertEqual(back.frame.minY, backY, accuracy: 0.5)
        screenshot("Watch Crown scrolled compact graph")
        back.tap()
        XCTAssertTrue(app.buttons["watch-workflow-row-workflow-one"].waitForExistence(timeout: 5))
    }

    @MainActor private func launch(_ argument: String, expectsLoaded: Bool = true) -> XCUIApplication {
        let app = XCUIApplication(); app.launchArguments = [argument]; app.launch()
        XCTAssertTrue(app.staticTexts["watch-workflow-detail-title"].waitForExistence(timeout: 12))
        if expectsLoaded { XCTAssertTrue(app.buttons["watch-workflow-node-trigger"].waitForExistence(timeout: 5)) }
        return app
    }
    @MainActor private func openMessageEditor(_ app: XCUIApplication, scroll: XCUIElement) {
        let card = app.buttons["watch-workflow-node-message"]
        // Returning from edit preserves the expanded card. Locate its Edit
        // control before toggling so this exercises both retained and new states.
        let edit = app.buttons["watch-workflow-edit-message"]
        if !edit.exists { reveal(card, in: scroll); card.tap() }
        reveal(edit, in: scroll); edit.tap()
        XCTAssertTrue(app.staticTexts["watch-workflow-editor-title"].waitForExistence(timeout: 3))
    }
    @MainActor private func reveal(_ element: XCUIElement, in scroll: XCUIElement) {
        // Lazy cards outside the viewport may have no accessibility element.
        // Search both directions, but use known geometry when available and
        // stop immediately so an already reached control is never overshot.
        for attempt in 0..<24 {
            if element.exists, element.isHittable { return }
            var moveDown = attempt >= 12
            if element.exists {
                let target = element.frame
                let viewport = scroll.frame
                if target.height > 0 {
                    moveDown = target.midY < viewport.midY
                }
            }
            if moveDown { scroll.swipeDown() }
            else { scroll.swipeUp() }
        }
        screenshot("Watch workflow control not reachable: \(element.identifier)")
        let hierarchy = XCTAttachment(string: XCUIApplication().debugDescription)
        hierarchy.name = "Watch workflow reachability hierarchy"
        hierarchy.lifetime = .keepAlways; add(hierarchy)
        XCTAssertTrue(element.exists && element.isHittable, "Unreachable \(element.identifier)")
    }
    @MainActor private func screenshot(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
    }
}

extension WatchWorkflowDetailUITests {
    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-workspaces.watch-retention,apple-watch.workflows.compact-editor
    func testRunHistoryOpensReadOnlySavedResultAndReturnsToGraph() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-workflow-detail"]
        app.launch()
        let history = app.buttons["watch-workflow-runs-open"]
        XCTAssertTrue(history.waitForExistence(timeout: 12)); XCTAssertTrue(history.isHittable); history.tap()
        let run = app.buttons["watch-workflow-run-fixture-run"]
        XCTAssertTrue(run.waitForExistence(timeout: 5)); XCTAssertTrue(run.isHittable); run.tap()
        XCTAssertTrue(app.descendants(matching: .any)["watch-workflow-run-detail"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["answer: Fixture run output"].waitForExistence(timeout: 3))
        XCTAssertFalse(app.buttons["watch-workflow-save"].exists)
        XCTAssertFalse(app.buttons["watch-workflow-edit-message"].exists)
        app.buttons["watch-workflow-detail-back"].tap()
        XCTAssertTrue(run.waitForExistence(timeout: 5))
        app.buttons["watch-workflow-detail-back"].tap()
        XCTAssertTrue(history.waitForExistence(timeout: 5))
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = "Watch read-only Workflow run history and result"
        attachment.lifetime = .keepAlways; add(attachment)
    }
}
