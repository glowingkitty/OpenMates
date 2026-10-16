// Supporting production-intent proof in isolated preview; no auth or inference.
import XCTest

@MainActor
final class OpenMatesControlsUITests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=apple-controls.quick-actions,apple-controls.workflow
    func testEveryControlQueuesItsExactQuickActionAndWorkflowUsesIssuedCapability() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embed-share", "--dev-workflows-widget-fixture", "--dev-controls-fixture", "--ui-test-disable-auth-cache"]
        app.launchEnvironment["DEV_PREVIEW"] = "embed-share"
        app.launch()
        let result = app.staticTexts["control-fixture-result"]
        XCTAssertTrue(result.waitForExistence(timeout: 10))
        for action in ["ask", "newTask", "recordRequest", "askAboutPhoto", "search", "incognitoAsk"] {
            let button = app.buttons["control-fixture-" + action]
            XCTAssertTrue(button.isHittable)
            button.tap()
            expectation(for: NSPredicate(format: "label == %@", action), evaluatedWith: result)
            waitForExpectations(timeout: 5)
        }
        app.buttons["control-fixture-workflow"].tap()
        let route = app.staticTexts["workflows-fixture-route"]
        expectation(for: NSPredicate(format: "label == %@", "run:fixture-workflow;issued=true"), evaluatedWith: route)
        waitForExpectations(timeout: 5)
        app.buttons["workflows-fixture-invalidate"].tap()
        app.buttons["control-fixture-workflow"].tap()
        expectation(for: NSPredicate(format: "label == %@", "unavailable"), evaluatedWith: result)
        waitForExpectations(timeout: 5)
        let proof = XCTAttachment(screenshot: app.screenshot())
        proof.name = "controls-production-intent-routing"; proof.lifetime = .keepAlways
        add(proof)
    }
}
