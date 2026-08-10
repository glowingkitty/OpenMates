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

@MainActor
final class WorkflowsParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testWorkflowHomeRendersComposerAndRecommendations() throws {
        let app = launchWorkflowFixture("home")

        assertVisible("workflows-home", in: app, message: "Workflow home must replace WorkspacePlaceholderView.")
        assertVisible("workflow-input-composer", in: app, message: "Workflow home must provide the title-only composer.")
        assertVisible("workflow-recommendations", in: app, message: "Workflow home must show workflow recommendations.")
        XCTAssertFalse(
            app.descendants(matching: .any)["workspace-placeholder-workflows"].exists,
            "Workflow home must not fall back to WorkspacePlaceholderView."
        )
    }

    func testWorkflowEditorRendersFocusedNodeEditingControls() throws {
        let app = launchWorkflowFixture("editor")

        assertVisible("workflow-editor", in: app, message: "Selecting a workflow must open the focused editor.")
        assertVisible("workflow-title-input", in: app, message: "The focused editor must expose a workflow title field.")
        assertVisible("workflow-node-stack", in: app, message: "The focused editor must render its vertical node stack.")
        assertVisible("workflow-node-summary", in: app, message: "The focused editor must expose expandable node summaries.")
        assertVisible("workflow-editor-undo", in: app, message: "Dirty workflow edits must expose Undo.")
        assertVisible("save-workflow", in: app, message: "Dirty workflow edits must expose Save.")
    }

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
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-workflows-fixture", fixture]
        app.launchEnvironment["UI_TEST_WORKFLOWS_FIXTURE"] = fixture
        app.launch()

        XCTAssertTrue(app.wait(for: .runningForeground, timeout: 12))
        return app
    }

    private func assertVisible(_ identifier: String, in app: XCUIApplication, message: String) {
        XCTAssertTrue(
            app.descendants(matching: .any)[identifier].waitForExistence(timeout: 8),
            message
        )
    }
}
