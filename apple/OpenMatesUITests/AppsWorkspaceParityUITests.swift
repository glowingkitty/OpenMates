// Web source: frontend/apps/web_app/tests/apps-workspace.spec.ts
// Synthetic provider-free fixture; real execution uses separate disposable dev state.
import XCTest

@MainActor
final class AppsWorkspaceParityUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=apps.discovery.public-catalog,apps.forms.metadata-driven,apps.execution.direct-shared-contract,apps.presentation.shared-detail-and-recency
    func testCatalogSkillFormRequiresExplicitRunAndOpensSharedResult() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-apps-workspace"]
        app.launch()
        XCTAssertTrue(app.descendants(matching: .any)["apps-daily-inspiration-area"].waitForExistence(timeout: 15))
        let next = app.buttons["apps-inspiration-next"]
        let previous = app.buttons["apps-inspiration-previous"]
        XCTAssertTrue(next.waitForExistence(timeout: 5)); XCTAssertTrue(next.isHittable)
        XCTAssertTrue(previous.exists); XCTAssertTrue(previous.isHittable)
        let inspiration = app.descendants(matching: .any)["daily-inspiration-card"].firstMatch
        XCTAssertTrue(inspiration.waitForExistence(timeout: 5))
        let searchInspiration = inspiration.value as? String
        XCTAssertNotNil(searchInspiration)
        XCTAssertFalse(searchInspiration?.isEmpty ?? true)
        next.tap()
        XCTAssertTrue(app.descendants(matching: .any)["apps-daily-inspiration-area"].exists,
            "Arrow navigation must keep the inspiration banner on the home screen")
        XCTAssertFalse(app.descendants(matching: .any)["apps-detail-fullscreen"].exists,
            "The arrow hit area must not open the underlying inspiration skill")
        let changed = NSPredicate { _, _ in
            guard inspiration.exists, let value = inspiration.value as? String else { return false }
            return !value.isEmpty && value != searchInspiration
        }
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: changed, object: nil)], timeout: 5), .completed,
            "Next must change the real inspiration content")
        previous.tap()
        XCTAssertTrue(app.descendants(matching: .any)["apps-daily-inspiration-area"].exists)
        XCTAssertFalse(app.descendants(matching: .any)["apps-detail-fullscreen"].exists)
        let restored = NSPredicate { _, _ in
            inspiration.exists && inspiration.value as? String == searchInspiration
        }
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: restored, object: nil)], timeout: 5), .completed,
            "Previous must restore the original inspiration content")
        let card = app.buttons["apps-app-card-web"]
        XCTAssertTrue(card.waitForExistence(timeout: 15)); XCTAssertTrue(card.isHittable); card.tap()
        XCTAssertTrue(app.descendants(matching: .any)["apps-detail-fullscreen"].waitForExistence(timeout: 8))
        XCTAssertTrue(app.buttons["apps-tab-overview"].exists,
            "Detail containers must retain independently accessible tab buttons")
        let skill = app.buttons["apps-skill-card-search"]
        XCTAssertTrue(skill.waitForExistence(timeout: 8)); revealDetailControl(skill, in: app); skill.tap()
        XCTAssertTrue(app.descendants(matching: .any)["apps-skill-form"].waitForExistence(timeout: 8))
        XCTAssertFalse(app.descendants(matching: .any)["apps-inline-results"].exists)
        XCTAssertTrue(app.descendants(matching: .any)["apps-skill-primary-fields"].exists)
        let query = app.textFields["workflow-input-apps-primary-request-0-query"]
        XCTAssertTrue(query.waitForExistence(timeout: 8)); revealDetailControl(query, in: app); query.tap(); query.typeText("Berlin")
        let settings = app.buttons["apps-skill-settings-toggle"]
        revealDetailControl(settings, in: app); settings.tap()
        XCTAssertTrue(app.descendants(matching: .any)["apps-skill-settings"].exists)
        let run = app.buttons["apps-skill-submit"]
        revealDetailControl(run, in: app)
        XCTAssertTrue(run.isEnabled); XCTAssertTrue(run.isHittable); run.tap()
        let results = app.descendants(matching: .any)["apps-inline-results"]
        XCTAssertTrue(results.waitForExistence(timeout: 8))
        let open = app.buttons["apps-inline-result-open"]
        revealDetailControl(open, in: app)
        XCTAssertTrue(open.isHittable); open.tap()
        XCTAssertTrue(app.descendants(matching: .any)["apps-result-fullscreen"].waitForExistence(timeout: 8))
        XCTAssertFalse(app.webViews.firstMatch.exists); XCTAssertFalse(app.tables.firstMatch.exists)
    }

    private func revealDetailControl(_ control: XCUIElement, in app: XCUIApplication) {
        let scroll = app.scrollViews["apps-detail-fullscreen"].firstMatch
        XCTAssertTrue(scroll.waitForExistence(timeout: 5), "Use the actual Apps detail scroll view")
        for _ in 0..<6 {
            if control.isHittable { break }
            scroll.swipeUp()
        }
        XCTAssertTrue(control.isHittable, "The real detail control must be reachable after bounded scrolling")
    }

}
