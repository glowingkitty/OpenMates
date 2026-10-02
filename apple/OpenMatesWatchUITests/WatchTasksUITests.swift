// Production Watch task editor exercised with encrypted, network-free fixtures.
import XCTest
import CoreGraphics

final class WatchTasksUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.tasks.edit-private
    func testSaveShowsReturnedTaskStatusAndPriority() {
        let app = launch("--ui-test-watch-task-edit")
        openEditor(app)
        chooseStatus("done", in: app)
        choosePriority(4, in: app)
        let save = app.buttons["watch-task-edit-save"]
        XCTAssertTrue(save.isEnabled)
        XCTAssertTrue(save.isHittable)
        keepScreenshot("Watch task draft before save")
        save.tap()
        XCTAssertTrue(app.staticTexts["watch-task-detail-status"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.staticTexts["watch-task-detail-status"].label, "Done")
        XCTAssertEqual(app.staticTexts["watch-task-detail-priority"].label, "Urgent")
        XCTAssertFalse(app.otherElements["watch-task-editor"].exists)
        keepScreenshot("Watch task returned save state")
        app.buttons["watch-task-detail-back"].tap()
        XCTAssertTrue(app.staticTexts["watch-task-fixture-returned-group"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.staticTexts["watch-task-fixture-returned-group"].label, "Done")
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.tasks.edit-private
    func testCancelRestoresOriginalTaskWithoutRequest() {
        let app = launch("--ui-test-watch-task-edit")
        openEditor(app)
        chooseStatus("blocked", in: app)
        let priority = app.buttons["watch-task-edit-priority"]
        scrollTo(priority, in: app)
        priority.tap()
        XCTAssertTrue(app.otherElements["watch-task-priority-choices"].waitForExistence(timeout: 5))
        app.buttons["watch-task-detail-back"].tap()
        XCTAssertTrue(app.buttons["watch-task-edit-status"].label.contains("Blocked"))
        XCTAssertTrue(app.buttons["watch-task-edit-save"].isEnabled)
        app.buttons["watch-task-edit-cancel"].tap()
        XCTAssertTrue(app.staticTexts["watch-task-detail-status"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.staticTexts["watch-task-detail-status"].label, "Todo")
        XCTAssertEqual(app.staticTexts["watch-task-fixture-request-count"].label, "0")
        openEditor(app)
        scrollTo(app.buttons["watch-task-edit-status"], in: app)
        XCTAssertTrue(app.buttons["watch-task-edit-status"].label.contains("Todo"))
        XCTAssertFalse(app.buttons["watch-task-edit-save"].isEnabled)
        keepScreenshot("Watch task cancel retained original")
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.tasks.edit-private
    func testFailedSaveKeepsDraftAndExposesRetryWithoutFalseSuccess() {
        let app = launch("--ui-test-watch-task-edit-failure")
        openEditor(app)
        chooseStatus("blocked", in: app)
        choosePriority(3, in: app)
        app.buttons["watch-task-edit-save"].tap()
        let error = app.staticTexts["watch-task-save-error"]
        XCTAssertTrue(error.waitForExistence(timeout: 5))
        XCTAssertTrue(app.otherElements["watch-task-editor"].exists)
        scrollTo(app.buttons["watch-task-edit-status"], in: app)
        XCTAssertTrue(app.buttons["watch-task-edit-status"].label.contains("Blocked"))
        scrollTo(app.buttons["watch-task-edit-priority"], in: app)
        XCTAssertTrue(app.buttons["watch-task-edit-priority"].label.contains("High"))
        XCTAssertTrue(app.buttons["watch-task-edit-save"].isEnabled)
        keepScreenshot("Watch failed save preserves draft")
        app.buttons["watch-task-edit-save"].tap()
        XCTAssertTrue(error.waitForExistence(timeout: 5))
        app.buttons["watch-task-edit-cancel"].tap()
        XCTAssertTrue(app.staticTexts["watch-task-detail-status"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.staticTexts["watch-task-detail-status"].label, "Todo")
    }

    @MainActor
    // contract-test: direct surface=gui.apple assertions=apple-watch.tasks.edit-private,apple-watch.lists.read-only-private
    func testWorkflowProjectionHasReaderAndNoEditControl() {
        let app = launch("--ui-test-watch-task-edit-workflow")
        XCTAssertTrue(app.staticTexts["watch-task-detail-title"].waitForExistence(timeout: 12))
        XCTAssertEqual(app.staticTexts["watch-task-detail-title"].label, "Read-only workflow task")
        XCTAssertFalse(app.buttons["watch-task-detail-edit"].exists)
        XCTAssertFalse(app.buttons["watch-task-edit-save"].exists)
        keepScreenshot("Watch workflow projection remains read only")
    }

    @MainActor private func launch(_ argument: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = [argument]
        app.launch()
        return app
    }

    @MainActor private func openEditor(_ app: XCUIApplication) {
        let edit = app.buttons["watch-task-detail-edit"]
        XCTAssertTrue(edit.waitForExistence(timeout: 12))
        XCTAssertTrue(edit.isHittable)
        edit.tap()
        XCTAssertTrue(app.buttons["watch-task-edit-cancel"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.textFields["watch-task-title-input"].exists)
    }

    @MainActor private func chooseStatus(_ status: String, in app: XCUIApplication) {
        let choice = app.buttons["watch-task-edit-status"]
        scrollTo(choice, in: app)
        choice.tap()
        let option = app.buttons["watch-task-status-\(status)"]
        scrollTo(option, in: app)
        option.tap()
    }

    @MainActor private func choosePriority(_ priority: Int, in app: XCUIApplication) {
        let choice = app.buttons["watch-task-edit-priority"]
        scrollTo(choice, in: app)
        choice.tap()
        let option = app.buttons["watch-task-priority-\(priority)"]
        scrollTo(option, in: app)
        option.tap()
    }

    @MainActor private func scrollTo(_ element: XCUIElement, in app: XCUIApplication) {
        let scroll = app.scrollViews["watch-task-editor-scroll"]
        XCTAssertTrue(element.waitForExistence(timeout: 5))
        XCTAssertTrue(scroll.exists)
        // Production choices occupy their own page. Ordinary scroll gestures
        // navigate that page without pressing the Watch's real text inputs,
        // which would open the OS keyboard and obscure the task controls.
        for _ in 0..<8 where !element.isHittable {
            if app.keyboards.firstMatch.exists { break }
            let viewport = scroll.frame.intersection(app.frame)
            if element.frame.midY < viewport.midY { scroll.swipeDown() }
            else { scroll.swipeUp() }
        }
        if !element.isHittable {
            keepScreenshot("Watch task target not reachable")
            let layout = XCTAttachment(string: app.debugDescription)
            layout.name = "Synthetic Watch task editor reachability layout"
            layout.lifetime = .keepAlways
            add(layout)
        }
        XCTAssertFalse(app.keyboards.firstMatch.exists,
                       "Scrolling task controls must not activate text entry")
        XCTAssertTrue(element.isHittable,
                      "Task editor target remains unreachable: \(element.identifier), target=\(element.frame), viewport=\(scroll.frame)")
    }

    @MainActor private func keepScreenshot(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
