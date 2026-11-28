import XCTest

/// Project Overview Checks section on synthetic data (no account or network):
/// cards render with status and chips, the detail sheet opens, Run is available
/// and a pending human source can be confirmed.
@MainActor
final class ProjectChecksUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    private func element(_ app: XCUIApplication, _ identifier: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }

    // contract-test: direct surface=gui.apple assertions=checks.surface.semantic-parity,checks.human.waiting-for-confirmation
    func testChecksSectionOpensCheckAndConfirmsHumanSource() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "projects", "--dev-preview-variant", "readme",
                               "--ui-test-project-checks", "--dev-preview-theme", "light",
                               "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        XCTAssertTrue(element(app, "dev-preview-root").waitForExistence(timeout: 10))
        XCTAssertFalse(element(app, "dev-preview-error").exists)

        let section = element(app, "project-checks-section")
        XCTAssertTrue(section.waitForExistence(timeout: 10), "The Overview lists the Project's Checks")
        XCTAssertFalse(element(app, "project-checks-error").exists)
        let card = app.buttons["project-check-check-shopping"]
        XCTAssertTrue(card.waitForExistence(timeout: 5))
        XCTAssertTrue(element(app, "project-check-check-search").exists)
        XCTAssertTrue(app.staticTexts["Shopping list reads well on a phone"].exists)
        attachScreenshot("Project Checks section")

        if !card.isHittable { app.swipeUp() }
        card.tap()
        let sheet = element(app, "check-fullscreen")
        XCTAssertTrue(sheet.waitForExistence(timeout: 5), "Tapping a Check opens its detail")
        XCTAssertTrue(app.buttons["check-fullscreen-run"].exists)
        let confirm = app.buttons["check-source-confirm-src-human"]
        XCTAssertTrue(confirm.waitForExistence(timeout: 3), "A pending human source offers Confirm")
        XCTAssertTrue(app.buttons["check-source-reject-src-human"].exists)
        attachScreenshot("Project Check detail")

        confirm.tap()
        let gone = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: confirm)
        XCTAssertEqual(XCTWaiter.wait(for: [gone], timeout: 5), .completed, "Confirming records the decision")
        XCTAssertFalse(element(app, "project-checks-action-error").exists)
        attachScreenshot("Project Check confirmed")
    }

    nonisolated private func attachScreenshot(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
