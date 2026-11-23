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
        XCTAssertFalse(app.descendants(matching: .any)["apps-daily-inspiration-area"].exists,
            "The Apps start screen no longer shows a daily inspiration banner")
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

    // contract-test: supporting surface=gui.apple assertions=daily-inspiration.start-row-cards,daily-inspiration.start-row-actions
    func testAppsStartScreenHasNoBannerAndActionsTileIsLastRowItem() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-apps-workspace"]
        app.launch()
        let actions = app.descendants(matching: .any)["apps-row-actions"]
        XCTAssertTrue(actions.waitForExistence(timeout: 15))
        XCTAssertFalse(app.descendants(matching: .any)["apps-daily-inspiration-area"].exists)
        XCTAssertFalse(app.descendants(matching: .any)["daily-inspiration-card"].exists)
        XCTAssertFalse(app.staticTexts["Daily inspiration"].exists)
        let cards = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'apps-app-card-'"))
        XCTAssertGreaterThan(cards.count, 0); XCTAssertLessThanOrEqual(cards.count, 10)
        for card in cards.allElementsBoundByIndex {
            XCTAssertLessThan(card.frame.minX, actions.frame.minX, "The actions tile is the last item of the row")
            XCTAssertEqual(card.frame.height, 200, accuracy: 1, "Apps use the same 200pt large cards as Chats")
        }
        XCTAssertTrue(app.buttons["apps-show-all"].exists)
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = "apple-apps-start"; attachment.lifetime = .keepAlways; add(attachment)
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
