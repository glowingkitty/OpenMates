// Detached shared widget rendering and synthetic foreground intent; no workflow execution.
import XCTest

@MainActor
final class WorkflowsWidgetUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }
    // contract-test: supporting surface=gui.apple assertions=apple-workflow-widget.selection,apple-workflow-widget.run-current-scope,apple-workflow-widget.private-cache
    func testProductionWidgetRunIssuesTypedActionAndInvalidationRemovesRun() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embed-share", "--dev-workflows-widget-fixture", "--ui-test-disable-auth-cache"]
        app.launchEnvironment["DEV_PREVIEW"] = "embed-share"
        app.launch()
        let widget = app.descendants(matching: .any).matching(identifier: "workflows-widget").firstMatch
        XCTAssertTrue(widget.waitForExistence(timeout: 10))
        XCTAssertEqual(app.staticTexts["workflows-widget-title"].label, "Synthetic morning report")
        let button = app.buttons["workflows-widget-run"]
        XCTAssertTrue(button.isHittable); button.tap()
        let route = app.staticTexts["workflows-fixture-route"]
        let delivered = NSPredicate(format: "label == %@", "run:fixture-workflow;issued=true")
        expectation(for: delivered, evaluatedWith: route)
        waitForExpectations(timeout: 10)
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = "workflow-widget-detached-populated"
        screenshot.lifetime = .keepAlways
        add(screenshot)
        app.buttons["workflows-fixture-invalidate"].tap()
        XCTAssertFalse(button.exists)
        XCTAssertTrue(app.descendants(matching: .any).matching(identifier: "workflows-widget-unavailable").firstMatch.exists)
        let empty = XCTAttachment(screenshot: app.screenshot())
        empty.name = "workflow-widget-detached-unavailable"
        empty.lifetime = .keepAlways
        add(empty)
    }
}
