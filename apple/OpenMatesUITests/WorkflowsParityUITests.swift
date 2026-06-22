// UI smoke target for Workflows V1 parity verification.
// The detailed workflow contract is covered by WorkflowsParityTests; this test
// keeps a targeted UI class available for remote Apple verification commands.
// No credentials, workflow IDs, private chat content, or screenshots are stored.

import XCTest

@MainActor
final class WorkflowsParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testNativeShellLaunchesForWorkflowParityRun() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-shell-metrics"]
        app.launchEnvironment["UI_TEST_SHELL_METRICS"] = "1"
        app.launch()

        XCTAssertTrue(app.wait(for: .runningForeground, timeout: 12))
        XCTAssertFalse(app.tables.firstMatch.exists, "Workflow parity shell must not use default List/table chrome")
    }
}
