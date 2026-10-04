// UI parity target for Workflows V1 native surfaces.
// Uses deterministic workflow fixtures only; no credentials, workflow IDs,
// private chat content, or screenshots are stored.
//
// ─── Web contract ───────────────────────────────────────────────────
// Svelte: frontend/apps/web_app/src/routes/workflows/+page.svelte
// Tests:  frontend/apps/web_app/tests/workflows-editor.spec.ts
//         frontend/apps/web_app/tests/workflows-input.spec.ts
// ────────────────────────────────────────────────────────────────────

import XCTest
#if os(iOS)
import UIKit
#endif

@MainActor
final class WorkflowsParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // contract-test: supporting surface=gui.apple assertions=workflows-ui.workspace.recommendation-led-composition
    func testWorkflowHomeRendersComposerAndRecommendations() throws {
        let app = launchWorkflowFixture("home")

        assertVisible("workflow-input-composer", in: app, message: "Workflow home must provide the workflow prompt composer.")
        assertVisible("workflows-daily-inspiration-area", in: app,
                      message: "Workflow home must show the daily inspiration banner.")
        assertVisible("workflows-home-greeting", in: app,
                      message: "Workflow home must greet the owner above its action cards.")
        assertVisible("workflow-mixed-row", in: app,
                      message: "Workflow home must show recent owner workflow cards.")
        let cards = app.buttons.matching(identifier: "workflow-landing-card")
        // A starter and the fixture owner intentionally share this title.
        // Their real localized badges distinguish the available actions.
        let owner = cards.matching(NSPredicate(format: "label == %@ AND value == %@", "Weekly AI events", "Paused")).firstMatch
        XCTAssertEqual(cards.count, 1, "Recent contains the fixture owner workflow, without templates")
        XCTAssertTrue(owner.exists)
        attachScreenshot("Workflow home with inspiration and recent owner card")

        let templates = app.buttons["workflows-show-templates"]
        XCTAssertTrue(templates.isHittable); templates.tap()
        assertVisible("all-workflows-view", in: app, message: "Show templates must reveal the template grid")
        let heading = app.staticTexts["workflows-browse-heading"]
        XCTAssertEqual(heading.label, "Templates")
        XCTAssertEqual(cards.count, 3, "Templates contains exactly the three existing starter cards")
        XCTAssertTrue(cards.allElementsBoundByIndex.allSatisfy { $0.value as? String == "Starter" },
                      "Every template card must expose its starter action state")
        XCTAssertFalse(owner.exists, "Templates must not include owner workflows")
        XCTAssertTrue(cards.firstMatch.isHittable, "Starter cards retain their real creation action")
        app.buttons["workflows-back-to-recent"].tap()
        assertVisible("workflow-mixed-row", in: app, message: "Back must restore recent owner workflows")
        XCTAssertEqual(cards.count, 1); XCTAssertTrue(owner.exists)

        app.descendants(matching: .any)["workflows-show-all"].tap()
        assertVisible("all-workflows-view", in: app,
                      message: "Show all must reveal the owner's workflow grid.")
        XCTAssertEqual(app.staticTexts["workflows-browse-heading"].label, "My workflows")
        XCTAssertEqual(cards.count, 1); XCTAssertTrue(owner.exists)
        attachScreenshot("Workflow all workflows browse")
        app.descendants(matching: .any)["workflows-back-to-recent"].tap()
        assertVisible("workflow-mixed-row", in: app,
                      message: "Back to recent must restore recent owner cards.")
        XCTAssertFalse(
            app.descendants(matching: .any)["workspace-placeholder-workflows"].exists,
            "Workflow home must not fall back to WorkspacePlaceholderView."
        )
    }

    // contract-test: supporting surface=gui.apple assertions=workflows-ui.detail.stable-visual-header,workflows-ui.detail.shared-template-runs-tabs,workflows-ui.template.centered-in-place-editor,workflows-ui.template.explicit-guarded-save
    func testWorkflowEditorRendersIdentityTabsAndFocusedNodeEditing() throws {
        let app = launchWorkflowFixture("editor")

        assertVisible("workflow-editor", in: app, message: "Selecting a workflow must open the focused editor.")
        assertVisible("workspace-detail-header", in: app, message: "The editor must show the category header.")
        assertVisible("workflow-view-tabs", in: app, message: "The editor must show workflow and runs tabs.")
        assertVisible("workflow-node-stack", in: app, message: "The focused editor must render its vertical node stack.")
        assertVisible("workflow-node-summary", in: app, message: "The focused editor must expose expandable node summaries.")
        attachScreenshot("Workflow editor identity and graph")

        app.descendants(matching: .any)["workspace-detail-title"].tap()
        assertVisible("workflow-title-input", in: app, message: "Tapping identity must expose the title editor.")
        app.descendants(matching: .any)["workflow-node-summary"].firstMatch.tap()
        assertVisible("workflow-editor-header", in: app, message: "Tapping a step must expose its branded editor header.")
        assertVisible("workflow-time-trigger-schedule", in: app, message: "A time trigger must expose its schedule dropdown.")
        assertVisible("workflow-node-save", in: app, message: "A focused step must save independently.")
    }

    // contract-test: supporting surface=gui.apple assertions=workflows-ui.detail.stable-visual-header,workflows-ui.template.centered-in-place-editor
    func testWorkflowToolbarAndExpandedNodeControlsAreClickable() throws {
        let app = launchWorkflowFixture("editor")
        let more = app.buttons["workflow-detail-actions"]
        XCTAssertTrue(more.waitForExistence(timeout: 8))
        XCTAssertTrue(more.isHittable, "The header More pill must be visible and clickable.")
        more.tap()
        let run = app.buttons["run-workflow"]
        XCTAssertTrue(run.waitForExistence(timeout: 5))
        XCTAssertTrue(run.isHittable)
        let delete = app.buttons["delete-workflow"]
        XCTAssertTrue(delete.isHittable)
        attachScreenshot("Workflow header custom action pills")
        more.tap()

        let summaries = app.buttons.matching(identifier: "workflow-node-summary")
        let initialCount = summaries.count
        let trigger = summaries.firstMatch
        XCTAssertTrue(trigger.isHittable)
        let compactFrame = trigger.frame
        trigger.tap()
        XCTAssertEqual(summaries.count, initialCount - 1,
                       "An editable expanded panel must replace its compact summary card.")
        // The native hierarchy exposes the graph's scroll viewport directly;
        // SwiftUI may flatten the nested node-stack accessibility container.
        let editorScroll = app.scrollViews["workflow-management"]
        XCTAssertTrue(editorScroll.waitForExistence(timeout: 5))
        let dropdownContainer = app.descendants(matching: .any)["workflow-time-trigger-schedule"]
        XCTAssertTrue(dropdownContainer.waitForExistence(timeout: 5))
        let dropdown = editorScroll.buttons["Repeat"]
        XCTAssertTrue(dropdown.waitForExistence(timeout: 5))
        // Expanding the trigger near the viewport bottom must reveal its editor
        // automatically. No test scroll may make this interaction pass.
        let automaticallyVisible = XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "isHittable == true"), object: dropdown
        )
        XCTAssertEqual(XCTWaiter.wait(for: [automaticallyVisible], timeout: 5), .completed,
                       "Expansion must automatically bring the schedule into view.")
        let editorHeader = app.descendants(matching: .any)["workflow-editor-header"]
        XCTAssertTrue(editorHeader.exists)
        let expanded = app.descendants(matching: .any)["workflow-node-expanded"]
        XCTAssertTrue(expanded.waitForExistence(timeout: 5), "The actual expanded node panel must retain its own accessibility boundary")
        XCTAssertGreaterThan(expanded.frame.width, compactFrame.width,
                             "The focused node must expand horizontally from its summary card.")
        XCTAssertGreaterThan(expanded.frame.height, compactFrame.height,
                             "The focused node must expand vertically to contain its controls.")
        XCTAssertGreaterThanOrEqual(editorHeader.frame.minY, editorScroll.frame.minY - 1,
                                    "Automatic scrolling must retain the expanded editor header in the viewport.")
        XCTAssertLessThanOrEqual(editorHeader.frame.maxY, editorScroll.frame.maxY + 1)
        XCTAssertTrue(app.buttons["workflow-node-close"].isHittable)
        attachScreenshot("Workflow time trigger automatically revealed after expansion")
        dropdown.tap()
        let weekly = app.buttons["Every week"]
        XCTAssertTrue(weekly.waitForExistence(timeout: 5))
        for _ in 0..<3 where !weekly.isHittable { editorScroll.swipeUp() }
        XCTAssertTrue(weekly.isHittable, "The rendered schedule option must be clickable.")
        weekly.tap()
        XCTAssertEqual(dropdown.value as? String, "Every week",
                       "Choosing a repeat option must update the actual dropdown selection.")
        XCTAssertTrue(app.textFields["workflow-schedule-time"].exists)
        attachScreenshot("Workflow time trigger editor after schedule selection")
        let close = app.buttons["workflow-node-close"]
        for _ in 0..<6 where !close.isHittable { editorScroll.swipeDown() }
        XCTAssertTrue(close.isHittable, "The expanded editor's Close must become clickable after returning to its header.")
        close.tap()
        let contracted = XCTNSPredicateExpectation(
            predicate: NSPredicate { _, _ in
                summaries.count == initialCount
                    && abs(summaries.firstMatch.frame.width - compactFrame.width) < 2
                    && abs(summaries.firstMatch.frame.height - compactFrame.height) < 2
            }, object: nil
        )
        XCTAssertEqual(XCTWaiter.wait(for: [contracted], timeout: 5), .completed,
                       "Close must contract the node back to both compact dimensions.")
    }

    // contract-test: supporting surface=gui.apple assertions=workflows-ui.detail.stable-visual-header,workflows-ui.detail.shared-template-runs-tabs,workflows-ui.template.centered-in-place-editor
    func testWorkflowActionPillsStayFixedAndChangeSurfaceWhenBannerScrollsAway() throws {
        let app = launchWorkflowFixture("editor")
        let scroll = app.scrollViews["workflow-management"]
        XCTAssertTrue(scroll.waitForExistence(timeout: 8))
        let toolbar = app.descendants(matching: .any)["workflow-header-toolbar"]
        XCTAssertTrue(toolbar.waitForExistence(timeout: 5))
        let initialOverlay = XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "value == %@", "banner-overlay"), object: toolbar
        )
        XCTAssertEqual(XCTWaiter.wait(for: [initialOverlay], timeout: 5), .completed)
        let report = app.buttons["workflow-report-issue"]
        let more = app.buttons["workflow-detail-actions"]
        let close = app.buttons["workflow-detail-back"]
        XCTAssertTrue(report.isHittable); XCTAssertTrue(more.isHittable); XCTAssertTrue(close.isHittable)
        let fixedY = more.frame.minY
        XCTAssertEqual(fixedY, scroll.frame.minY + 15, accuracy: 2,
                       "The shared action pills must use the web toolbar's fixed top inset.")
        let panel = app.descendants(matching: .any)["workflow-template-panel"]
        XCTAssertTrue(panel.exists, "The template graph must have its own rounded surface inside the detail container.")
        XCTAssertGreaterThan(panel.frame.minX, scroll.frame.minX)
        XCTAssertLessThan(panel.frame.maxX, scroll.frame.maxX)
        attachScreenshot("Workflow shared chat action pills over gradient header and template container")

        for _ in 0..<8 where toolbar.value as? String != "standard" { scroll.swipeUp() }
        let standard = XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "value == %@", "standard"), object: toolbar
        )
        XCTAssertEqual(XCTWaiter.wait(for: [standard], timeout: 5), .completed,
                       "Leaving the gradient must restore the standard shared chat action surface.")
        let banner = app.descendants(matching: .any)["workspace-detail-header"]
        XCTAssertLessThan(banner.frame.maxY, more.frame.minY,
                          "The style transition must follow the actual banner leaving the fixed actions.")
        XCTAssertEqual(more.frame.minY, fixedY, accuracy: 1)
        XCTAssertTrue(report.isHittable); XCTAssertTrue(more.isHittable); XCTAssertTrue(close.isHittable)
        more.tap()
        let delete = app.buttons["delete-workflow"]
        XCTAssertTrue(delete.waitForExistence(timeout: 5))
        XCTAssertTrue(delete.isHittable, "More must still expose actionable menu pills after scrolling the header away.")
        XCTAssertTrue(app.buttons["run-workflow"].isHittable)
        attachScreenshot("Workflow fixed actions and More menu after header scroll")
        more.tap()
        close.tap()
        XCTAssertTrue(app.descendants(matching: .any)["workflow-input-composer"].waitForExistence(timeout: 5),
                      "The fixed Close control must return to the workflow home after scrolling.")
    }

    // contract-test: supporting surface=gui.apple assertions=workflows-ui.template.centered-in-place-editor,workflows-ui.template.explicit-guarded-save,workflows.control.typed-data
    func testExpandedNodeMatrixMatchesRenderedWebFieldComposition() throws {
        let app = launchWorkflowFixture("editor-all-nodes")
        let scroll = app.scrollViews["workflow-management"]
        XCTAssertTrue(scroll.waitForExistence(timeout: 8))
        let composer = app.descendants(matching: .any)["workflow-ai-editor-composer"]
        XCTAssertTrue(composer.exists)
        XCTAssertGreaterThanOrEqual(composer.frame.minY, scroll.frame.maxY - 1,
                                    "The workflow instruction composer must dock below the graph viewport.")

        let nodes: [(String, String, String)] = [
            ("Weather", "workflow-node-summary", "workflow-input-heading"),
            ("Check", "workflow-node-summary", "workflow-check-source"),
            ("News", "workflow-node-summary", "workflow-input-heading"),
            ("Ask AI", "workflow-ask-ai-node", "composer-model-selector"),
            ("Send message", "workflow-node-summary", "workflow-message-title")
        ]
        for (name, identifier, expectedField) in nodes {
            let summary = app.buttons.matching(identifier: identifier)
                .matching(NSPredicate(format: "label CONTAINS[c] %@", name)).firstMatch
            XCTAssertTrue(summary.exists)
            for _ in 0..<12 where !summary.isHittable { scroll.swipeUp() }
            XCTAssertTrue(summary.isHittable, "\(name) must be reachable in the graph.")
            summary.tap()
            XCTAssertTrue(app.descendants(matching: .any)[expectedField].waitForExistence(timeout: 5),
                          "\(name) must expose its rendered web field structure.")
            if name == "Weather" {
                XCTAssertTrue(app.descendants(matching: .any)["workflow-date-range-field"].exists)
                XCTAssertTrue(app.buttons["Show all fields"].exists)
            } else if name == "Check" {
                XCTAssertTrue(app.descendants(matching: .any)["workflow-check-variable"].exists)
                XCTAssertTrue(app.descendants(matching: .any)["workflow-check-compare-source"].exists)
                XCTAssertFalse(app.descendants(matching: .any)["workflow-check-mode"].exists,
                               "The source selector replaces the legacy mode-only dropdown.")
                let source = app.buttons["Select action or AI confirms"]
                for _ in 0..<5 where !source.isHittable { scroll.swipeUp() }
                XCTAssertTrue(source.isHittable); source.tap()
                let ai = app.buttons["AI confirms"]
                XCTAssertTrue(ai.waitForExistence(timeout: 5))
                for _ in 0..<3 where !ai.isHittable { scroll.swipeUp() }
                XCTAssertTrue(ai.isHittable); ai.tap()
                XCTAssertEqual(source.value as? String, "AI confirms",
                               "The check's real source selection must switch to AI confirmation.")
                XCTAssertTrue(app.descendants(matching: .any)["workflow-ai-check-instruction"].waitForExistence(timeout: 5))
                XCTAssertTrue(app.descendants(matching: .any)["workflow-variable-picker"].exists)
                let variables = app.buttons["workflow-variable-source-weather"]
                XCTAssertTrue(variables.isHittable,
                              "Earlier weather outputs must remain an actionable child of the AI instruction editor.")
                variables.tap()
                let rain = app.buttons.matching(identifier: "workflow-message-output-reference")
                    .matching(NSPredicate(format: "label CONTAINS[c] %@", "Rain Probability")).firstMatch
                XCTAssertTrue(rain.waitForExistence(timeout: 5))
                XCTAssertTrue(rain.isHittable)
                let instruction = app.textViews["workflow-message-template"]
                XCTAssertTrue(instruction.exists)
                let previousValue = instruction.value as? String ?? ""
                rain.tap()
                XCTAssertNotEqual(instruction.value as? String ?? "", previousValue,
                                  "Choosing an earlier output must insert a variable into the actual instruction.")
                let editor = app.otherElements["workflow-ai-check-instruction"]
                XCTAssertEqual(editor.value as? String, "{{steps.weather.rain_probability}}",
                               "The Check draft binding must receive the selected reference.")
                XCTAssertFalse(app.staticTexts["workflow-message-placeholder"].exists,
                               "A populated instruction must remove its placeholder.")
                XCTAssertTrue((instruction.value as? String ?? "").contains("Rain Probability"),
                              "The inserted chip must expose its readable output label.")
                XCTAssertFalse((instruction.value as? String ?? "").contains("{{steps."),
                               "The live editor must render the reference instead of raw storage syntax.")
            } else if name == "Ask AI" || name == "Send message" {
                let variables = app.descendants(matching: .any)["workflow-variable-picker"]
                let input = app.descendants(matching: .any)["workflow-message-template"]
                XCTAssertTrue(variables.exists); XCTAssertTrue(input.exists)
                XCTAssertLessThanOrEqual(variables.frame.maxY, input.frame.minY + 1,
                                         "Earlier-output choices must appear before the message input.")
                if name == "Send message" { XCTAssertTrue(app.staticTexts["Chat title"].exists) }
                if name == "Ask AI" {
                    let models = app.buttons["composer-model-selector"]
                    for _ in 0..<8 where !models.isHittable { scroll.swipeUp() }
                    XCTAssertTrue(models.isHittable); models.tap()
                    let auto = app.buttons["composer-model-auto"]
                    XCTAssertTrue(auto.waitForExistence(timeout: 5))
                    XCTAssertTrue(auto.isHittable, "The inline model popup must stay within the workflow card viewport.")
                    XCTAssertGreaterThanOrEqual(auto.frame.minX, scroll.frame.minX - 1)
                    XCTAssertLessThanOrEqual(auto.frame.maxX, scroll.frame.maxX + 1)
                    attachScreenshot("Workflow Ask AI inline model popup")
                    auto.tap()
                    XCTAssertEqual(models.value as? String, "collapsed")
                }
            }
            attachScreenshot("Workflow expanded \(name) rendered field composition")
            let close = app.buttons["workflow-node-close"]
            for _ in 0..<12 where !close.isHittable { scroll.swipeDown() }
            XCTAssertTrue(close.isHittable); close.tap()
            XCTAssertTrue(summary.exists, "Close must restore \(name)'s compact node.")
        }
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.actions.skill-contract,workflows-ui.template.centered-in-place-editor
    func testAppActionShowsOneEditableRequestWithoutTransportArrayHeading() throws {
        let app = launchWorkflowFixture("editor")
        let scroll = app.scrollViews["workflow-management"]
        XCTAssertTrue(scroll.waitForExistence(timeout: 8))
        let news = app.buttons.matching(identifier: "workflow-node-summary")
            .matching(NSPredicate(format: "label CONTAINS[c] %@", "News")).firstMatch
        XCTAssertTrue(news.exists)
        for _ in 0..<12 where !news.isHittable { scroll.swipeUp() }
        XCTAssertTrue(news.isHittable)
        news.tap()

        let query = app.textFields["workflow-input-news-request-0-query"]
        XCTAssertTrue(query.waitForExistence(timeout: 5))
        for _ in 0..<8 where !query.isHittable { scroll.swipeUp() }
        XCTAssertTrue(query.isHittable, "The request's real Query field must be visible and editable.")
        XCTAssertEqual(query.value as? String, "Germany news")
        XCTAssertEqual(app.textFields.matching(NSPredicate(format: "identifier CONTAINS %@ AND identifier ENDSWITH %@", "-request-", "-query")).count, 1)
        XCTAssertFalse(app.staticTexts.matching(NSPredicate(format: "label MATCHES[c] %@", "Requests ?\\*?")).firstMatch.exists)
        XCTAssertFalse(app.staticTexts["Request 1"].exists,
                       "A single request must expose its fields without a batch heading.")
        XCTAssertFalse(app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH %@", "workflows.builder.output_type_")).firstMatch.exists)
        query.tap()
        query.typeText(" updated")
        XCTAssertEqual(query.value as? String, "Germany news updated")
        XCTAssertTrue(app.buttons["workflow-node-save"].isEnabled)
        attachScreenshot("Workflow app action single request fields")
    }

    // contract-test: supporting surface=gui.apple assertions=workflows-ui.template.centered-in-place-editor,workflows-ui.template.explicit-guarded-save
    func testMessageDestinationBackPreservesExistingEditorDraft() throws {
        let app = launchWorkflowFixture("editor")
        let messageNode = app.buttons.matching(identifier: "workflow-node-summary")
            .matching(NSPredicate(format: "label CONTAINS[c] %@", "Send message")).firstMatch
        XCTAssertTrue(messageNode.waitForExistence(timeout: 8))
        for _ in 0..<8 where !messageNode.isHittable { app.swipeUp() }
        XCTAssertTrue(messageNode.isHittable)
        messageNode.tap()

        let title = app.textFields["workflow-message-title"]
        XCTAssertTrue(title.waitForExistence(timeout: 5))
        for _ in 0..<3 where !title.isHittable { app.swipeUp() }
        XCTAssertTrue(title.isHittable)
        let originalTitle = try XCTUnwrap(title.value as? String)
        title.tap()
        title.typeText(" unsaved draft")
        let draftTitle = try XCTUnwrap(title.value as? String)
        XCTAssertNotEqual(draftTitle, originalTitle, "The regression guard must contain a real unsaved edit.")

        let destination = app.buttons["workflow-message-destination"]
        XCTAssertTrue(destination.exists)
        for _ in 0..<3 where !destination.isHittable { app.swipeDown() }
        XCTAssertTrue(destination.isHittable)
        destination.tap()
        XCTAssertTrue(app.descendants(matching: .any)["workflow-chat-destination-picker"].waitForExistence(timeout: 5))
        XCTAssertFalse(title.exists, "The chooser replaces message fields until Back is used.")
        let back = app.buttons["workflow-node-back"]
        for _ in 0..<3 where !back.isHittable { app.swipeDown() }
        XCTAssertTrue(back.isHittable)
        back.tap()

        XCTAssertTrue(title.waitForExistence(timeout: 5), "Back must return to the existing message editor.")
        XCTAssertEqual(title.value as? String, draftTitle, "Back must retain the unsubmitted title draft.")
        XCTAssertFalse(app.descendants(matching: .any)["workflow-chat-destination-picker"].exists)
        XCTAssertTrue(app.buttons["workflow-node-save"].exists)
        XCTAssertFalse(messageNode.exists, "The message editor must remain expanded.")
        attachScreenshot("Workflow message draft retained after destination Back")
    }

    // contract-test: supporting surface=gui.apple assertions=workflows-ui.runs.timeline-execution-detail,workflows-ui.detail.stable-visual-header
    func testWorkflowRunTabShowsEmptyHistoryWithoutRetainedContent() throws {
        let app = launchWorkflowFixture("no-runs")
        let header = app.descendants(matching: .any)["workspace-detail-header"]
        XCTAssertTrue(header.waitForExistence(timeout: 8))
        let templateHeight = header.frame.height
        XCTAssertGreaterThanOrEqual(templateHeight, 304)
        XCTAssertLessThan(templateHeight, 420, "The fixture identity has a bounded intrinsic banner height.")
        for _ in 0..<2 {
            app.descendants(matching: .any)["workflow-tab-runs"].tap()
            assertVisible("workflow-runs", in: app, message: "The run tab must show owner-scoped history.")
            assertVisible("workflow-runs-empty", in: app, message: "No-run fixture must show empty history.")
            XCTAssertEqual(header.frame.height, templateHeight, accuracy: 2,
                           "A short run panel must not expand the category banner to fill the viewport.")
            app.descendants(matching: .any)["workflow-tab-template"].tap()
        }
        attachScreenshot("Workflow banner retains intrinsic height for empty Runs")
    }

    // contract-test: supporting surface=gui.apple assertions=workflows-ui.runs.timeline-execution-detail,workflows.execution.lifecycle-visible
    func testWorkflowRunTabShowsPinnedGraphForCompletedRun() throws {
        let app = launchWorkflowFixture("runs")
        app.descendants(matching: .any)["workflow-tab-runs"].tap()
        assertVisible("workflow-run-marker", in: app, message: "The completed run must appear on the timeline.")
        assertVisible("workflow-run-graph", in: app, message: "The selected run must show its pinned graph.")
        let timeline = app.descendants(matching: .any)["workflow-run-timeline"]
        XCTAssertEqual(timeline.frame.height, 100, accuracy: 2)
        let scroll = app.scrollViews["workflow-management"]
        let panel = app.descendants(matching: .any)["workflow-runs"]
        XCTAssertGreaterThan(panel.frame.minX, scroll.frame.minX)
        XCTAssertLessThan(panel.frame.maxX, scroll.frame.maxX)
        let next = app.buttons["workflow-next-run-marker"]
        for _ in 0..<3 where !next.isHittable { scroll.swipeUp() }
        XCTAssertTrue(next.isHittable); next.tap()
        XCTAssertTrue(app.buttons["workflow-run-select"].exists,
                      "Upcoming selection must retain the menu to select historical runs.")
        XCTAssertFalse(app.buttons["workflow-delete-run"].exists,
                       "The upcoming schedule has no persisted run to delete.")
        let completed = app.buttons["workflow-run-marker"]
        completed.tap()
        assertVisible("workflow-run-graph", in: app, message: "Returning to history restores the pinned run graph.")
        attachScreenshot("Workflow Runs panel and selected history timeline")
    }

    // contract-test: supporting surface=gui.apple assertions=workflows.control.typed-data,workflows.actions.skill-contract
    func testWorkflowOutputExamplesShowTypedFieldsAndDeclaredListDetails() throws {
        let app = launchWorkflowFixture("editor")
        let scroll = app.scrollViews["workflow-management"]
        let weather = app.buttons.matching(identifier: "workflow-node-summary")
            .matching(NSPredicate(format: "label CONTAINS[c] %@", "Weather")).firstMatch
        XCTAssertTrue(weather.waitForExistence(timeout: 8))
        for _ in 0..<10 where !weather.isHittable { scroll.swipeUp() }
        XCTAssertTrue(weather.isHittable); weather.tap()
        let toggle = app.buttons["workflow-show-output-fields"]
        for _ in 0..<12 where !toggle.isHittable { scroll.swipeUp() }
        XCTAssertTrue(toggle.isHittable); toggle.tap()
        let fields = app.descendants(matching: .any)["workflow-output-fields"]
        XCTAssertTrue(fields.waitForExistence(timeout: 5))
        XCTAssertEqual(app.staticTexts["workflow-output-example-heading"].label, "Example")
        XCTAssertEqual(app.descendants(matching: .any).matching(identifier: "workflow-output-field").count, 4)
        let types = app.staticTexts.matching(identifier: "workflow-output-type").allElementsBoundByIndex.map(\.label)
        XCTAssertTrue(types.contains("Number")); XCTAssertTrue(types.contains("Bool")); XCTAssertTrue(types.contains("List"))
        let disclosure = app.buttons["workflow-output-list-disclosure"]
        for _ in 0..<6 where !disclosure.isHittable { scroll.swipeUp() }
        XCTAssertTrue(disclosure.isHittable); disclosure.tap()
        XCTAssertTrue(app.descendants(matching: .any)["workflow-output-list-details"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["09:00"].exists, "The list uses its declared first-item example.")
        disclosure.tap()
        XCTAssertFalse(app.descendants(matching: .any)["workflow-output-list-details"].exists)
        attachScreenshot("Workflow typed output examples")
    }

    // Rendering fixture only; accepted Test decoding is covered separately with actual response bytes.
    // contract-test: supporting surface=gui.apple assertions=workflows.results.selective-embeds,workflows.control.typed-data
    func testWorkflowCompletedOutputUsesRealPreviewCarousel() throws {
        let app = launchWorkflowFixture("editor", extraArguments: ["--ui-test-workflow-output-fixture"])
        let scroll = app.scrollViews["workflow-management"]
        let news = app.buttons.matching(identifier: "workflow-node-summary")
            .matching(NSPredicate(format: "label CONTAINS[c] %@", "News")).firstMatch
        XCTAssertTrue(news.waitForExistence(timeout: 8))
        for _ in 0..<12 where !news.isHittable { scroll.swipeUp() }
        XCTAssertTrue(news.isHittable); news.tap()
        let toggle = app.buttons["workflow-show-output-fields"]
        for _ in 0..<12 where !toggle.isHittable { scroll.swipeUp() }
        XCTAssertTrue(toggle.isHittable); toggle.tap()
        let position = app.staticTexts["workflow-result-position"]
        XCTAssertTrue(position.waitForExistence(timeout: 5))
        XCTAssertEqual(position.label, "1 of 2")
        XCTAssertEqual(app.staticTexts["workflow-output-example-heading"].label, "Test output")
        XCTAssertTrue(app.descendants(matching: .any)["workflow-result-card"].exists)
        XCTAssertTrue(app.staticTexts["First synthetic article"].exists)
        let next = app.buttons["workflow-result-next"]
        for _ in 0..<8 where !next.isHittable { scroll.swipeUp() }
        XCTAssertTrue(next.isHittable); next.tap()
        XCTAssertEqual(position.label, "2 of 2")
        XCTAssertTrue(app.staticTexts["Second synthetic article"].exists)
        XCTAssertFalse(next.isEnabled)
        XCTAssertTrue(app.buttons["workflow-result-previous"].isEnabled)
        attachScreenshot("Workflow completed output news result carousel")
    }

    // contract-test: supporting surface=gui.apple assertions=workflows-ui.mvp.ask-ai
    func testAskAIAppInvocationHintBlocksStepSave() throws {
        let app = launchWorkflowFixture("ask-ai-blocked")
        let askNode = app.descendants(matching: .any)["workflow-ask-ai-node"]
        XCTAssertTrue(askNode.waitForExistence(timeout: 8))
        app.swipeUp()
        askNode.tap()
        XCTAssertFalse(askNode.exists, "The editable expanded panel replaces the summary card.")
        assertVisible("workflow-ai-app-warning", in: app,
                      message: "Ask AI must explain when the instruction would invoke an app skill.")
        attachScreenshot("Workflow Ask AI blocked hint")
        let save = app.descendants(matching: .any)["workflow-node-save"]
        XCTAssertTrue(save.exists)
        XCTAssertFalse(save.isEnabled, "A blocked Ask AI verdict must prevent the step from being saved.")
    }

    // Uses synthetic local ciphertext and no account.
    // contract-test: supporting surface=gui.apple assertions=workflows.content.encrypted-retained,workflows.access.boundaries
    func testEncryptedShortTemplateOpensRecipientPreviewAndBindingSteps() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "workflows", "--dev-preview-variant", "short-template",
                               "--dev-preview-theme", "light", "-AppleLanguages", "(en)",
                               "-AppleLocale", "en_US"]
        app.launch()

        let title = app.descendants(matching: .any)["workflow-template-title"]
        XCTAssertTrue(title.waitForExistence(timeout: 25),
                      "A locally decrypted short link must open the recipient's template preview.")
        XCTAssertEqual(title.label, "Weekly AI events")
        XCTAssertTrue(app.staticTexts["3 steps. Imported workflows start disabled."].exists)
        XCTAssertFalse(app.descendants(matching: .any)["workflow-short-template-error"].exists)

        let importButton = app.descendants(matching: .any)["workflow-template-import"]
        XCTAssertTrue(importButton.exists)
        importButton.tap()
        XCTAssertTrue(app.descendants(matching: .any)["workflow-template-bindings"].waitForExistence(timeout: 5))
        attachScreenshot("Workflow encrypted short recipient bindings")
        XCTAssertTrue(app.descendants(matching: .any)["workflow-template-binding-schedule-schedule"].exists)
        XCTAssertTrue(app.staticTexts["Choose your schedule and timezone"].exists)
        XCTAssertTrue(app.descendants(matching: .any)["workflow-template-binding-app_skill-forecast"].exists)
        XCTAssertTrue(app.staticTexts["Connect weather forecast"].exists)
        XCTAssertEqual(app.buttons.matching(identifier: "workflow-template-complete-binding").count, 2)
        let enable = app.descendants(matching: .any)["workflow-template-enable"]
        XCTAssertTrue(enable.exists)
        XCTAssertFalse(enable.isEnabled, "A recipient copy stays disabled until bindings are completed.")
    }

    // contract-test: supporting surface=gui.apple assertions=workflows-ui.workspace.recommendation-led-composition
    func testWorkflowSidebarShowsWorkflowRowsInsteadOfChatHistory() throws {
        let app = launchWorkflowFixture("sidebar")

        assertVisible("workflows-sidebar", in: app, message: "The Workflows workspace must render its own sidebar.")
        assertVisible("workflow-sidebar-row", in: app, message: "The Workflows sidebar must list workflow rows.")
        assertVisible("workflows-sidebar-heading", in: app,
                      message: "The sidebar must retain its single Workflows owner-list heading.")
        XCTAssertFalse(app.descendants(matching: .any)["workflow-sidebar-template"].exists,
                       "Template browsing belongs to workflow home rather than the owner sidebar")
        attachScreenshot("Workflow sidebar owner list")
        XCTAssertFalse(
            app.descendants(matching: .any)["chat-history-panel"].exists,
            "The Workflows sidebar must not render the chats history panel."
        )
    }

    private func launchWorkflowFixture(_ fixture: String, extraArguments: [String] = []) -> XCUIApplication {
        #if os(iOS)
        let wide = UIDevice.current.userInterfaceIdiom == .pad
        if wide { XCUIDevice.shared.orientation = .landscapeLeft }
        #endif
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-workflows-fixture", fixture] + extraArguments
        app.launchEnvironment["UI_TEST_WORKFLOWS_FIXTURE"] = fixture
        app.launch()

        #if os(iOS)
        if wide { XCUIDevice.shared.orientation = .landscapeLeft }
        #endif

        XCTAssertTrue(app.wait(for: .runningForeground, timeout: 12))
        return app
    }

    private func assertVisible(_ identifier: String, in app: XCUIApplication, message: String) {
        XCTAssertTrue(
            app.descendants(matching: .any)[identifier].waitForExistence(timeout: 8),
            message
        )
    }

    private func attachScreenshot(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
