// Isolated production Tasks UI with DEBUG-only, disposable synthetic records.
// Specification: specifications/features/apple-task-board-interactions/specification.yml
// Assertions: apple-task-board.context-menu, apple-task-board.drag-move, apple-task-board.workflow-run
import XCTest

@MainActor
final class TasksWorkspaceInteractionUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=apple-task-board.context-menu
    func testLongPressOpensChatStyleActionsAndMoveKeepsBoard() {
        let app = launch()
        let title = app.buttons.matching(identifier: "task-card-open").firstMatch
        XCTAssertTrue(title.isHittable)
        #if os(macOS)
        title.rightClick()
        #else
        title.press(forDuration: 1)
        #endif
        let menu = element(app, "task-action-menu-items")
        XCTAssertTrue(menu.waitForExistence(timeout: 3))
        XCTAssertEqual(menu.frame.width, 280, accuracy: 2)
        XCTAssertFalse(element(app, "task-detail-content").exists)
        let move = app.buttons["task-move-todo"]
        XCTAssertTrue(move.isHittable)
        move.tap()
        XCTAssertTrue(menu.waitForNonExistence(timeout: 3))
        let destination = element(app, "task-column-todo")
        let moved = destination.buttons.matching(identifier: "task-card-open").firstMatch
        XCTAssertTrue(moved.waitForExistence(timeout: 3))
        XCTAssertEqual(moved.label, "Research how expensive hoverboard motors are to carry 2–3 people")
        XCTAssertTrue(element(app, "task-board").exists)
        attach(app, "Task context menu moved card to first position")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-task-board.drag-move
    func testRealCardDragMovesToFirstPositionWithoutOpeningReader() {
        let app = launch()
        dragFirstBacklogCard(app)
        let destination = element(app, "task-column-todo")
        let moved = destination.buttons.matching(identifier: "task-card-open").firstMatch
        expectation(for: NSPredicate(format: "label == %@", "Research how expensive hoverboard motors are to carry 2–3 people"), evaluatedWith: moved)
        waitForExpectations(timeout: 5)
        XCTAssertFalse(element(app, "task-detail-content").exists)
        XCTAssertFalse(element(app, "task-action-menu-items").exists)
        XCTAssertEqual(element(app, "task-column-count-backlog").label, "(2)",
                       "One task and one draft Plan remain in Backlog")
        XCTAssertEqual(element(app, "task-column-count-todo").label, "(2)")
        attach(app, "Real task card drag across status columns")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-task-board.drag-move
    func testFailedRealCardDropRollsBackAndReportsFailure() {
        let app = launch(extra: ["--ui-test-task-move-failure"])
        dragFirstBacklogCard(app)
        XCTAssertTrue(element(app, "task-move-error").waitForExistence(timeout: 5))
        XCTAssertEqual(element(app, "task-column-count-backlog").label, "(3)")
        XCTAssertEqual(element(app, "task-column-count-todo").label, "(1)")
        let original = element(app, "task-column-backlog").buttons.matching(identifier: "task-card-open").firstMatch
        XCTAssertEqual(original.label, "Research how expensive hoverboard motors are to carry 2–3 people")
        XCTAssertTrue(element(app, "task-board").exists)
        XCTAssertFalse(element(app, "tasks-load-error").exists)
        attach(app, "Failed task drag restores original placement")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-task-board.workflow-run,tasks.workflow-projections.read-only
    func testWorkflowProjectionOpensExactRunDetailAndRunDestination() {
        let app = launch()
        revealDoneColumn(app)
        let title = app.buttons["workflow-run-projection"]
        XCTAssertTrue(title.isHittable)
        title.tap()
        XCTAssertTrue(element(app, "workflow-run-projection-detail").waitForExistence(timeout: 5))
        XCTAssertEqual(element(app, "workflow-run-detail-id").label, "weather-report-run")
        XCTAssertFalse(element(app, "task-action-menu-items").exists)
        app.buttons["workflow-run-detail-close"].tap()
        XCTAssertTrue(element(app, "workflow-run-projection-detail").waitForNonExistence(timeout: 3))
        let openRun = app.buttons["workflow-run-open"]
        XCTAssertTrue(openRun.isHittable)
        openRun.tap()
        XCTAssertEqual(element(app, "dev-preview-local-action").label,
                       "opened-workflow-weather-report-run-weather-report-run")
        attach(app, "Tasks workflow exact run navigation")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-task-board.edit
    func testEditTitleAndDescriptionSaveClosesEditorAndUpdatesBoard() {
        let app = launch()
        openFirstTaskEditor(app)
        let title = element(app, "task-detail-title-input")
        replaceText(title, with: "Edited task title")
        let detailScroll = app.scrollViews["task-detail-content"]
        XCTAssertTrue(detailScroll.exists)
        let description = element(app, "task-detail-description-input")
        // Editing the title opens the keyboard; the description is farther
        // down the real reader rather than simultaneously visible on phones.
        for _ in 0..<6 where !description.isHittable { detailScroll.swipeUp() }
        XCTAssertTrue(description.isHittable)
        description.tap()
        description.typeText("Edited task description")
        XCTAssertEqual(description.value as? String, "Edited task description")
        let save = app.buttons["task-detail-save"]
        for _ in 0..<6 where !save.isHittable { detailScroll.swipeDown() }
        XCTAssertTrue(save.isHittable)
        save.tap()
        XCTAssertTrue(title.waitForNonExistence(timeout: 5))
        XCTAssertEqual(app.buttons["task-detail-title"].label, "Edited task title")
        app.buttons["task-detail-minimize"].tap()
        let boardTitle = element(app, "task-column-backlog").buttons.matching(identifier: "task-card-open").firstMatch
        XCTAssertEqual(boardTitle.label, "Edited task title")
        boardTitle.tap()
        XCTAssertTrue(element(app, "task-detail-content").waitForExistence(timeout: 3))
        XCTAssertTrue(app.staticTexts["Edited task description"].exists)
        attach(app, "Saved task content survives returning from board")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-task-board.edit
    func testEditFailureRetainsDraftAndCancelPreservesAuthoritativeTitle() {
        let app = launch(extra: ["--ui-test-task-edit-failure"])
        assertFailedEditRetainsDraft(app)
        app.buttons["task-detail-cancel"].tap()
        XCTAssertTrue(element(app, "task-detail-title-input").waitForNonExistence(timeout: 3))
        XCTAssertEqual(app.buttons["task-detail-title"].label,
                       "Research how expensive hoverboard motors are to carry 2–3 people")
        XCTAssertFalse(element(app, "task-detail-edit-error").exists)
        attach(app, "Cancel discards failed local task edit")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-task-board.edit
    func testVersionConflictRetainsDraftAndShowsConflict() {
        let app = launch(extra: ["--ui-test-task-edit-conflict"])
        assertFailedEditRetainsDraft(app)
        XCTAssertTrue(element(app, "task-detail-edit-error").label.contains("changed elsewhere"))
        attach(app, "Version conflict keeps the editable task draft")
    }

    private func openFirstTaskEditor(_ app: XCUIApplication) {
        app.buttons.matching(identifier: "task-card-open").firstMatch.tap()
        let edit = app.buttons["task-detail-edit"]
        XCTAssertTrue(edit.waitForExistence(timeout: 5))
        XCTAssertTrue(edit.isHittable, "Editing has an explicit visible entry point on touch devices")
        edit.tap()
        XCTAssertTrue(element(app, "task-detail-title-input").waitForExistence(timeout: 3))
    }

    private func assertFailedEditRetainsDraft(_ app: XCUIApplication) {
        openFirstTaskEditor(app)
        let title = element(app, "task-detail-title-input")
        replaceText(title, with: "Draft kept after failure")
        app.buttons["task-detail-save"].tap()
        XCTAssertTrue(element(app, "task-detail-edit-error").waitForExistence(timeout: 5))
        XCTAssertEqual(title.value as? String, "Draft kept after failure")
        XCTAssertTrue(app.buttons["task-detail-save"].isEnabled)
        XCTAssertTrue(app.buttons["task-detail-cancel"].isEnabled)
    }

    private func replaceText(_ field: XCUIElement, with value: String) {
        field.tap()
        #if os(macOS)
        field.typeKey("a", modifierFlags: .command)
        field.typeText(value)
        #else
        let existing = field.value as? String ?? ""
        field.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: existing.count) + value)
        #endif
    }

    #if os(iOS)
    // contract-test: direct surface=gui.apple assertions=apple-task-board.new-task-shortcuts
    func testHomeScreenNewTaskShortcutFocusesRealWorkspaceComposerAndPreservesDraft() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-shell-metrics",
            "--ui-test-show-workspace-tabs", "--ui-test-workspace-sidebar-fixture",
            "-AppleLanguages", "(en)", "-AppleLocale", "en_US", "-app_language", "en"]
        app.launchEnvironment["UI_TEST_SHELL_METRICS"] = "1"
        app.launch()
        let metrics = app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "shell-width=")).firstMatch
        XCTAssertTrue(metrics.waitForExistence(timeout: 12))
        expectation(for: NSPredicate(format: "label CONTAINS %@", "fixture-ready=true"), evaluatedWith: metrics)
        waitForExpectations(timeout: 5)
        XCTAssertFalse(element(app, "dev-preview-root").exists, "Use the production MainAppView router")

        selectRootWorkspace("tasks", in: app)
        let input = element(app, "task-workspace-input")
        XCTAssertTrue(input.waitForExistence(timeout: 5))
        XCTAssertTrue(input.isHittable)
        let draft = "Prepare a release task"
        input.tap()
        input.typeText(draft)
        let backlogCount = element(app, "task-column-count-backlog").label
        let todoCount = element(app, "task-column-count-todo").label
        selectRootWorkspace("chats", in: app)
        XCTAssertTrue(input.waitForNonExistence(timeout: 5), "Switching workspaces unmounts the Tasks composer")

        XCUIDevice.shared.press(.home)
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        let icon = springboard.icons["OpenMates"].firstMatch
        // A simulator may have placed the installed app on a later Home page.
        for _ in 0..<6 {
            if icon.isHittable { break }
            springboard.swipeLeft()
        }
        XCTAssertTrue(icon.isHittable, "The installed OpenMates app icon must be reachable")
        icon.press(forDuration: 1)
        let shortcut = springboard.descendants(matching: .any)
            .matching(NSPredicate(format: "label == %@", "New task")).firstMatch
        XCTAssertTrue(shortcut.waitForExistence(timeout: 5))
        XCTAssertTrue(shortcut.isHittable)
        shortcut.tap()

        XCTAssertTrue(element(app, "tasks-workspace").waitForExistence(timeout: 5))
        XCTAssertTrue(input.waitForExistence(timeout: 5))
        XCTAssertEqual(input.value as? String, draft)
        XCTAssertTrue(input.isHittable)
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5), "New task should focus its composer")
        let composer = element(app, "task-workspace-composer")
        let scroll = app.scrollViews["tasks-workspace-scroll"]
        let inspiration = element(app, "tasks-daily-inspiration-area")
        let visibleComposer = NSPredicate { _, _ in
            let keyboard = app.keyboards.firstMatch
            return keyboard.exists && composer.exists && input.exists && scroll.exists
                && composer.frame.height > 0 && scroll.frame.height > 0
                && composer.frame.maxY <= keyboard.frame.minY + 1
                && input.frame.maxY <= keyboard.frame.minY + 1
                && input.frame.minY >= scroll.frame.minY
                && abs(inspiration.frame.minY - scroll.frame.minY) <= 2
        }
        expectation(for: visibleComposer, evaluatedWith: app)
        waitForExpectations(timeout: 5)
        XCTAssertLessThanOrEqual(composer.frame.maxY, app.keyboards.firstMatch.frame.minY + 1,
                                 "The entire composer must remain above the real keyboard")
        XCTAssertEqual(inspiration.frame.minY, scroll.frame.minY, accuracy: 2,
                       "The board starts at the viewport top without a keyboard-induced blank gap")
        // No field tap here: app-wide typing must reach the field selected by
        // the real SceneDelegate -> quick-action -> MainAppView focus request.
        app.typeText(" after shortcut")
        XCTAssertEqual(input.value as? String, draft + " after shortcut")
        XCTAssertEqual(element(app, "task-column-count-backlog").label, backlogCount)
        XCTAssertEqual(element(app, "task-column-count-todo").label, todoCount)
        XCTAssertFalse(element(app, "task-detail-content").exists)
        XCTAssertTrue(app.buttons["task-workspace-submit"].isEnabled)
        attach(app, "App icon New task focuses retained workspace draft without dispatch")
    }

    private func selectRootWorkspace(_ workspace: String, in app: XCUIApplication) {
        let tab = app.buttons["\(workspace)-nav-link"]
        if !tab.isHittable { app.buttons["workspace-switcher"].tap() }
        XCTAssertTrue(tab.waitForExistence(timeout: 5))
        expectation(for: NSPredicate(format: "hittable == true"), evaluatedWith: tab)
        waitForExpectations(timeout: 3)
        tab.tap()
    }
    #endif

    private func launch(extra: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "tasks", "--dev-preview-variant", "default",
            "--dev-preview-theme", "light", "--ui-test-embed-presentation",
            "-AppleLanguages", "(en)", "-AppleLocale", "en_US", "-app_language", "en"] + extra
        app.launch()
        XCTAssertTrue(element(app, "task-board").waitForExistence(timeout: 10))
        XCTAssertTrue(element(app, "dev-preview-root").exists)
        return app
    }

    private func dragFirstBacklogCard(_ app: XCUIApplication) {
        let backlog = element(app, "task-column-backlog")
        let card = backlog.descendants(matching: .any).matching(identifier: "task-card").firstMatch
        XCTAssertTrue(card.isHittable)
        let handle = card.descendants(matching: .any).matching(identifier: "task-drag-handle").firstMatch
        // Phone title long press opens actions; its dedicated body handle owns
        // the OS drag recognizer. Mac/iPad pointer starts on the real card body.
        let start = handle.exists ? handle.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
                                 : card.coordinate(withNormalizedOffset: CGVector(dx: 0.06, dy: 0.95))
        let destination = element(app, "task-column-todo")
        let end = destination.coordinate(withNormalizedOffset: CGVector(dx: 0.10, dy: 0.18))
        start.press(forDuration: 0.8, thenDragTo: end)
    }

    private func revealDoneColumn(_ app: XCUIApplication) {
        let board = element(app, "task-board")
        for _ in 0..<4 {
            if app.buttons["workflow-run-projection"].isHittable { return }
            board.swipeLeft()
        }
        XCTAssertTrue(app.buttons["workflow-run-projection"].isHittable)
    }

    private func element(_ app: XCUIApplication, _ id: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: id).firstMatch
    }

    private func attach(_ app: XCUIApplication, _ title: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = title
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
