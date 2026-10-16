// Isolated production Tasks UI with DEBUG-only, disposable synthetic records.
// Specification: specifications/features/apple-task-board-interactions/specification.yml
// Assertions: apple-task-board.context-menu, apple-task-board.drag-move, apple-task-board.workflow-run
import XCTest

@MainActor
final class TasksWorkspaceInteractionUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
        #if os(iOS)
        XCUIDevice.shared.orientation = .portrait
        #endif
    }

    // contract-test: supporting surface=gui.apple assertions=apple-tasks-widget.links,tasks.detail.embed-responsive
    func testTaskWidgetIssuedGUIDURLColdAndRepeatedTapOpenExistingTaskFullscreen() {
        let app = launch(extra: ["--ui-test-task-widget-links"])
        let detail = element(app, "task-detail-content")
        XCTAssertTrue(detail.waitForExistence(timeout: 5), "The actual widget-issued GUID URL must route through DeepLinkHandler into the production fullscreen Task reader")
        let title = element(app, "task-detail-header-title")
        XCTAssertTrue(title.label.contains("hoverboard motors"))
        XCTAssertFalse(element(app, "task-detail-description-input").isHittable,
            "The widget does not request editing or New Task focus")
        app.buttons["task-detail-minimize"].tap()
        let closed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: detail)
        XCTAssertEqual(XCTWaiter.wait(for: [closed], timeout: 5), .completed)
        let link = app.buttons["task-widget-issued-link"]
        XCTAssertTrue(link.isHittable)
        link.tap()
        XCTAssertTrue(detail.waitForExistence(timeout: 5), "A fresh request for the same issued URL must reopen its existing Task")
        XCTAssertTrue(title.label.contains("hoverboard motors"))
        XCTAssertFalse(app.keyboards.firstMatch.exists)
        attach(app, "Synthetic widget GUID route opens Task fullscreen")
    }

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
        let menuOpened = menu.waitForExistence(timeout: 3)
        if !menuOpened { attachDragDiagnostics(app) }
        XCTAssertTrue(menuOpened)
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

    // contract-test: supporting surface=gui.apple assertions=apple-task-board.context-menu,apple-task-board.drag-move
    func testWholeCardStationaryReleaseAfterLiftKeepsNextTitleTapUsable() {
        let app = launch()
        let card = element(app, "task-column-backlog").descendants(matching: .any)
            .matching(identifier: "task-card").firstMatch
        XCTAssertTrue(card.isHittable)
        card.coordinate(withNormalizedOffset: CGVector(dx: 0.06, dy: 0.95)).press(forDuration: 1)
        let menu = element(app, "task-action-menu-items")
        let opened = menu.waitForExistence(timeout: 3)
        if !opened { attachDragDiagnostics(app) }
        XCTAssertTrue(opened, "Stationary touch-up during a native lift must open whole-card actions even before session start")
        XCTAssertFalse(element(app, "task-detail-content").exists)
        XCTAssertEqual(element(app, "task-column-count-backlog").label, "(3)")
        XCTAssertEqual(element(app, "task-column-count-todo").label, "(1)")
        element(app, "task-actions-dismiss").tap()
        XCTAssertTrue(menu.waitForNonExistence(timeout: 3))
        let title = element(app, "task-column-backlog").buttons.matching(identifier: "task-card-open").firstMatch
        XCTAssertTrue(title.isHittable); title.tap()
        XCTAssertTrue(element(app, "task-detail-content").waitForExistence(timeout: 3),
            "The next ordinary title tap must retain its normal selection")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-task-board.drag-move
    func testRealCardDragMovesToFirstPositionWithoutOpeningReader() {
        for origin in [CGVector(dx: 0.3, dy: 0.2), CGVector(dx: 0.06, dy: 0.95), CGVector(dx: 0.92, dy: 0.88)] {
        let app = launch()
        dragFirstBacklogCard(app, origin: origin)
        let destination = element(app, "task-column-todo")
        let moved = destination.buttons.matching(identifier: "task-card-open").firstMatch
        let dragWait = XCTWaiter.wait(for: [XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "label == %@", "Research how expensive hoverboard motors are to carry 2–3 people"),
            object: moved)], timeout: 5)
        if dragWait != .completed { attachDragDiagnostics(app) }
        XCTAssertEqual(dragWait, .completed)
        XCTAssertFalse(element(app, "task-detail-content").exists)
        XCTAssertFalse(element(app, "task-action-menu-items").exists)
        XCTAssertEqual(element(app, "task-column-count-backlog").label, "(2)",
                       "One task and one draft Plan remain in Backlog")
        XCTAssertEqual(element(app, "task-column-count-todo").label, "(2)")
        attach(app, "Real task card drag across status columns from \(origin)")
        app.terminate()
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-task-board.drag-move
    func testFailedRealCardDropRollsBackAndReportsFailure() {
        let app = launch(extra: ["--ui-test-task-move-failure"])
        dragFirstBacklogCard(app)
        let reportedFailure = element(app, "task-move-error").waitForExistence(timeout: 5)
        if !reportedFailure { attachDragDiagnostics(app) }
        XCTAssertTrue(reportedFailure)
        XCTAssertEqual(element(app, "task-column-count-backlog").label, "(3)")
        XCTAssertEqual(element(app, "task-column-count-todo").label, "(1)")
        let original = element(app, "task-column-backlog").buttons.matching(identifier: "task-card-open").firstMatch
        XCTAssertEqual(original.label, "Research how expensive hoverboard motors are to carry 2–3 people")
        XCTAssertTrue(element(app, "task-board").exists)
        XCTAssertFalse(element(app, "tasks-load-error").exists)
        attach(app, "Failed task drag restores original placement")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-task-board.drag-move
    func testHoveredDestinationShowsBoundedInsertionBeforeCards() {
        let app = launch(extra: ["--ui-test-task-drop-hover"])
        let column = element(app, "task-column-todo")
        let target = element(app, "task-column-drop-target-todo")
        XCTAssertTrue(target.waitForExistence(timeout: 5))
        XCTAssertEqual(target.label, "Drop here to mark as Todo")
        XCTAssertGreaterThanOrEqual(target.frame.height, 88)
        XCTAssertLessThan(target.frame.height, column.frame.height / 2)
        let firstCard = column.descendants(matching: .any).matching(identifier: "task-card").firstMatch
        XCTAssertLessThanOrEqual(target.frame.maxY, firstCard.frame.minY)
        XCTAssertFalse(element(app, "task-column-drop-target-backlog").exists)
        XCTAssertFalse(element(app, "task-column-drop-target-done").exists)
        attach(app, "Bounded tinted destination insertion before first card")
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.layout.responsive-parity,apple-task-board.new-task-shortcuts,message-input.focus.workspace-suppression
    func testTaskPromptUsesNativeExpandCancelOutsideDismissAndAcceptedRejectedSend() {
        for rejected in [false, true] {
            let app = launch(extra: ["--ui-test-task-prompt-submit"] + (rejected ? ["--ui-test-task-create-failure"] : []))
            let composer = element(app, "task-workspace-composer")
            let editor = app.textViews["task-workspace-input"]
            XCTAssertTrue(editor.waitForExistence(timeout: 5))
            let idleHeight = composer.frame.height
            let workspace = app.scrollViews["tasks-workspace-scroll"].firstMatch
            XCTAssertTrue(workspace.exists); XCTAssertTrue(workspace.isEnabled)
            editor.tap()
            let cancel = app.buttons["task-workspace-composer-cancel"]
            XCTAssertTrue(cancel.waitForExistence(timeout: 3))
            let focusedMic = app.buttons["task-workspace-mic"]
            XCTAssertTrue(focusedMic.waitForExistence(timeout: 3))
            XCTAssertGreaterThan(focusedMic.frame.midX, composer.frame.midX, "Empty focused microphone must stay on the right")
            let focusedField = composer.descendants(matching: .any)["message-field"].firstMatch
            XCTAssertEqual(cancel.frame.width, focusedField.frame.width, accuracy: 1)
            XCTAssertEqual(cancel.frame.minX, focusedField.frame.minX, accuracy: 1)
            XCTAssertGreaterThan(focusedMic.frame.midY, focusedField.frame.midY, "Microphone must stay in the bottom action row")
            let focusBackdrop = app.buttons["task-workspace-backdrop"]
            XCTAssertTrue(focusBackdrop.waitForExistence(timeout: 3))
            XCTAssertEqual(focusBackdrop.value as? String, "background-opacity=0;background-interactive=false")
            XCTAssertTrue(!workspace.exists || !workspace.isEnabled)
            let expand = app.buttons["task-workspace-composer-expand"]
            XCTAssertFalse(expand.exists, "An empty focused editor has no overflow action")
            let shortDraft = "Synthetic task prompt\nSecond line\nThird line"
            editor.typeText(shortDraft)
            XCTAssertFalse(expand.exists, "Three short native lines fit without Expand")
            let continuation = "\nFourth line\nFifth line"
            let draft = shortDraft + continuation
            editor.typeText(continuation)
            XCTAssertEqual(editor.value as? String, draft)
            XCTAssertTrue(expand.waitForExistence(timeout: 5)); XCTAssertTrue(expand.isHittable)
            XCTAssertGreaterThan(composer.frame.height, idleHeight)
            XCTAssertTrue(expand.isHittable)
            NativeComposerRenderedLayoutAssertions.assertBeside(expand, field: focusedField, editor: editor)
            NativeComposerRenderedLayoutAssertions.assertSelectedCaretClears(expand, field: focusedField, editor: editor)
            let typedMic = app.buttons["task-workspace-mic"]
            let typedSubmit = app.buttons["task-workspace-submit"]
            XCTAssertTrue(typedMic.exists); XCTAssertTrue(typedSubmit.exists)
            XCTAssertLessThan(typedSubmit.frame.midX, typedMic.frame.midX, "Microphone must be the rightmost bottom action")
            let editingHeight = composer.frame.height
            let editingEditorHeight = editor.frame.height
            expand.tap()
            attach(app, "Task composer immediately after fullscreen tap")
            let field = composer.descendants(matching: .any).matching(identifier: "message-field").firstMatch
            let bounds = XCTAttachment(string: "idleHeight=\(idleHeight) editingHeight=\(editingHeight) expandedComposer=\(composer.frame) nativeEditor=\(editor.frame) field=\(field.frame) expandLabel=\(expand.label)\n\(app.debugDescription)")
            bounds.name = "Task fullscreen native bounds and accessibility"
            bounds.lifetime = .keepAlways
            add(bounds)
            expectation(for: NSPredicate { _, _ in composer.frame.height > editingHeight && editor.frame.height > editingEditorHeight }, evaluatedWith: composer)
            waitForExpectations(timeout: 3)
            NativeComposerRenderedLayoutAssertions.assertBeside(expand, field: focusedField, editor: editor)
            NativeComposerRenderedLayoutAssertions.assertSelectedCaretClears(expand, field: focusedField, editor: editor, requiresScroll: false)
            XCTAssertEqual(cancel.frame.width, focusedField.frame.width, accuracy: 1)
            XCTAssertEqual(cancel.frame.minX, focusedField.frame.minX, accuracy: 1)
            cancel.tap()
            XCTAssertTrue(cancel.waitForNonExistence(timeout: 3))
            XCTAssertTrue(focusBackdrop.waitForNonExistence(timeout: 3))
            XCTAssertTrue(workspace.exists); XCTAssertTrue(workspace.isEnabled)
            XCTAssertFalse(app.keyboards.firstMatch.exists)
            XCTAssertEqual(editor.value as? String, draft)
            editor.tap()
            let backdrop = element(app, "task-workspace-backdrop")
            XCTAssertTrue(backdrop.isHittable)
            backdrop.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.1)).tap()
            XCTAssertTrue(cancel.waitForNonExistence(timeout: 3))
            XCTAssertTrue(focusBackdrop.waitForNonExistence(timeout: 3))
            XCTAssertTrue(workspace.exists); XCTAssertTrue(workspace.isEnabled)
            XCTAssertFalse(app.keyboards.firstMatch.exists)
            XCTAssertEqual(editor.value as? String, draft)
            editor.tap()
            app.buttons["task-workspace-submit"].tap()
            if rejected {
                XCTAssertTrue(element(app, "task-move-error").waitForExistence(timeout: 3))
                XCTAssertTrue(cancel.exists)
                XCTAssertEqual(editor.value as? String, draft)
                // Rejection retains the user's tapped insertion point. Request
                // the draft end explicitly for this append-edit assertion.
                editor.coordinate(withNormalizedOffset: CGVector(dx: 0.9, dy: 0.95)).tap()
                editor.typeText(" revised")
                XCTAssertEqual(editor.value as? String, draft + " revised")
            } else {
                XCTAssertTrue(cancel.waitForNonExistence(timeout: 3))
                XCTAssertEqual(editor.value as? String, "")
                XCTAssertEqual(element(app, "task-column-count-backlog").label, "(4)")
            }
            attach(app, rejected ? "Rejected Task send retains native editable draft" : "Accepted Task send collapses native composer")
            app.terminate()
        }
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.focus.workspace-suppression,apple-task-board.context-menu,apple-task-board.drag-move
    func testFocusedPromptOutsideHoldCannotOpenHiddenTaskActions() {
        let app = launch(extra: ["--ui-test-task-prompt-submit"])
        let card = element(app, "task-column-backlog").descendants(matching: .any)
            .matching(identifier: "task-card").firstMatch
        XCTAssertTrue(card.isHittable)
        let cardFrame = card.frame
        let editor = app.textViews["task-workspace-input"]
        editor.tap()
        let backdrop = app.buttons["task-workspace-backdrop"]
        let promptActivated = backdrop.waitForExistence(timeout: 3)
        if !promptActivated { attachDragDiagnostics(app) }
        XCTAssertTrue(promptActivated, "The editor tap must activate prompt suppression before the outside hold")
        let origin = app.windows.firstMatch.coordinate(withNormalizedOffset: CGVector(dx: 0, dy: 0))
        origin.withOffset(CGVector(dx: cardFrame.minX + 8, dy: cardFrame.minY + 8)).press(forDuration: 1)
        XCTAssertFalse(element(app, "task-action-menu-items").exists,
            "The native window hold reader must not act on a faded background card")
        XCTAssertFalse(element(app, "task-detail-content").exists)
        if backdrop.exists { app.buttons["task-workspace-composer-cancel"].tap() }
        XCTAssertTrue(backdrop.waitForNonExistence(timeout: 3))
        XCTAssertEqual(element(app, "task-column-count-backlog").label, "(3)")
        XCTAssertEqual(element(app, "task-column-count-todo").label, "(1)")
        XCTAssertTrue(card.isHittable)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-task-board.workflow-run,tasks.workflow-projections.read-only
    func testWorkflowProjectionOpensExactRunDetailAndRunDestination() {
        let app = launch()
        revealDoneColumn(app)
        let title = app.buttons["workflow-run-projection"]
        XCTAssertTrue(title.isHittable)
        title.tap()
        XCTAssertTrue(element(app, "workflow-run-projection-detail").waitForExistence(timeout: 5))
        XCTAssertTrue(element(app, "workflow-run-task-graph").waitForExistence(timeout: 5))
        XCTAssertTrue(element(app, "workflow-run-detail-live-status").exists)
        XCTAssertTrue(element(app, "workflow-run-detail-started-at").exists)
        XCTAssertFalse(element(app, "workflow-run-detail-id").exists)
        XCTAssertFalse(app.staticTexts["weather-report-run"].exists)
        XCTAssertFalse(element(app, "workflow-run-detail-load-error").exists)
        XCTAssertFalse(element(app, "task-action-menu-items").exists)
        app.buttons["workflow-run-detail-close"].tap()
        XCTAssertTrue(element(app, "workflow-run-projection-detail").waitForNonExistence(timeout: 3))
        revealDoneColumn(app)
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
            "--dev-preview-theme", "light", "--ui-test-embed-presentation", "--ui-test-drag-diagnostics",
            "-AppleLanguages", "(en)", "-AppleLocale", "en_US", "-app_language", "en"] + extra
        app.launch()
        XCTAssertTrue(element(app, "task-board").waitForExistence(timeout: 10))
        XCTAssertTrue(element(app, "dev-preview-root").exists)
        return app
    }

    private func dragFirstBacklogCard(_ app: XCUIApplication,
                                      origin: CGVector = CGVector(dx: 0.06, dy: 0.95)) {
        let backlog = element(app, "task-column-backlog")
        let card = backlog.descendants(matching: .any).matching(identifier: "task-card").firstMatch
        XCTAssertTrue(card.isHittable)
        XCTAssertFalse(card.descendants(matching: .any).matching(identifier: "task-drag-handle").firstMatch.exists)
        let start = card.coordinate(withNormalizedOffset: origin)
        let destination = element(app, "task-column-todo")
        let end = destination.coordinate(withNormalizedOffset: CGVector(dx: 0.10, dy: 0.18))
        // Retain the pointer at the destination for native lift/target delivery;
        // all three real card origins and placement assertions stay identical.
        start.press(forDuration: 0.8, thenDragTo: end, withVelocity: .default, thenHoldForDuration: 0.35)
    }

    private func revealDoneColumn(_ app: XCUIApplication) {
        let board = element(app, "task-board")
        let outerScroll = app.scrollViews["tasks-workspace-scroll"]
        let title = app.buttons["workflow-run-projection"]
        let openRun = app.buttons["workflow-run-open"]
        for _ in 0..<4 {
            let viewport = board.frame.intersection(outerScroll.frame)
                .intersection(app.windows.firstMatch.frame)
            // UI518 considered the title hittable with only 1.3pt visible while
            // its footer was wholly outside the horizontal board viewport.
            // Expose both real controls before asking AX for their hit points.
            if title.exists && openRun.exists && !viewport.isNull && !viewport.isEmpty
                && !title.frame.isEmpty && !openRun.frame.isEmpty
                && viewport.contains(title.frame) && viewport.contains(openRun.frame) {
                XCTAssertTrue(title.isHittable)
                XCTAssertTrue(openRun.isHittable)
                return
            }
            board.swipeLeft()
        }
        XCTFail("The workflow title and Open workflow run button must both fit inside the actual board viewport")
    }

    private func element(_ app: XCUIApplication, _ id: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: id).firstMatch
    }

    private func attachDragDiagnostics(_ app: XCUIApplication) {
        let probe = element(app, "native-drag-diagnostics")
        let metrics = XCTAttachment(string: String(describing: probe.value) + "\n" + app.debugDescription)
        metrics.name = "Synthetic real drag lifecycle and geometry"; metrics.lifetime = .keepAlways; add(metrics)
        attach(app, "Synthetic real drag failure viewport")
    }

    private func attach(_ app: XCUIApplication, _ title: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = title
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
