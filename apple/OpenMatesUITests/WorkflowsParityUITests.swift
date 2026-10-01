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
                      message: "Workflow home must show recent and starter workflow cards.")
        XCTAssertGreaterThanOrEqual(app.buttons.matching(identifier: "workflow-landing-card").count, 4,
                                    "The owner workflow and three starters must be available.")
        attachScreenshot("Workflow home with inspiration and starter cards")

        app.descendants(matching: .any)["workflows-show-all"].tap()
        assertVisible("all-workflows-view", in: app,
                      message: "Show all must reveal the owner's workflow grid.")
        attachScreenshot("Workflow all workflows browse")
        app.descendants(matching: .any)["workflows-back-to-recent"].tap()
        assertVisible("workflow-mixed-row", in: app,
                      message: "Back to recent must restore the mixed landing cards.")
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
        assertVisible("workflow-node-title-input", in: app, message: "Tapping a step must expose its focused editor.")
        assertVisible("workflow-node-save", in: app, message: "A focused step must save independently.")
    }

    // contract-test: supporting surface=gui.apple assertions=workflows-ui.runs.timeline-execution-detail
    func testWorkflowRunTabShowsEmptyHistoryWithoutRetainedContent() throws {
        let app = launchWorkflowFixture("no-runs")
        app.descendants(matching: .any)["workflow-tab-runs"].tap()
        assertVisible("workflow-runs", in: app, message: "The run tab must show owner-scoped history.")
        assertVisible("workflow-runs-empty", in: app, message: "No-run fixture must show empty history.")
    }

    // contract-test: supporting surface=gui.apple assertions=workflows-ui.runs.timeline-execution-detail,workflows.execution.lifecycle-visible
    func testWorkflowRunTabShowsPinnedGraphForCompletedRun() throws {
        let app = launchWorkflowFixture("runs")
        app.descendants(matching: .any)["workflow-tab-runs"].tap()
        assertVisible("workflow-run-marker", in: app, message: "The completed run must appear on the timeline.")
        assertVisible("workflow-run-graph", in: app, message: "The selected run must show its pinned graph.")
    }

    // contract-test: supporting surface=gui.apple assertions=workflows-ui.mvp.ask-ai
    func testAskAIAppInvocationHintBlocksStepSave() throws {
        let app = launchWorkflowFixture("ask-ai-blocked")
        let askNode = app.descendants(matching: .any)["workflow-ask-ai-node"]
        XCTAssertTrue(askNode.waitForExistence(timeout: 8))
        app.swipeUp()
        askNode.tap()
        XCTAssertEqual(askNode.value as? String, "expanded")
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
        XCTAssertFalse(
            app.descendants(matching: .any)["chat-history-panel"].exists,
            "The Workflows sidebar must not render the chats history panel."
        )
    }

    private func launchWorkflowFixture(_ fixture: String) -> XCUIApplication {
        #if os(iOS)
        let wide = UIDevice.current.userInterfaceIdiom == .pad
        if wide { XCUIDevice.shared.orientation = .landscapeLeft }
        #endif
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-workflows-fixture", fixture]
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
