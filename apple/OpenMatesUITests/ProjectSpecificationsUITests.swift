import XCTest

/// Project Overview Specifications on synthetic data (no account or network): the card
/// shows status, revision and proof; the reader shows the document, revision history and
/// a read-only older revision; Approve asks for confirmation and approves the current one.
@MainActor
final class ProjectSpecificationsUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    private func element(_ app: XCUIApplication, _ identifier: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }

    private func reveal(_ app: XCUIApplication, _ target: XCUIElement) {
        var attempts = 0
        while !target.isHittable && attempts < 6 { app.swipeUp(); attempts += 1 }
    }

    // contract-test: direct surface=gui.apple assertions=contracts.revision.exact-approval,contracts.surface.semantic-parity,contracts.ui.human-readable-default
    func testSpecificationOpensRevisionsAndApprovesCurrentRevision() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "projects", "--dev-preview-variant", "readme",
                               "--ui-test-project-specifications", "--dev-preview-theme", "light",
                               "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        XCTAssertTrue(element(app, "dev-preview-root").waitForExistence(timeout: 10))

        XCTAssertTrue(element(app, "project-specifications-section").waitForExistence(timeout: 10),
                      "The Overview lists the Project's Specifications")
        XCTAssertFalse(element(app, "project-specifications-error").exists)
        let card = app.buttons["project-specification-spec-recipes"]
        XCTAssertTrue(card.waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["1 proven · 1 open · 1 stale"].exists)
        reveal(app, card)
        attachScreenshot("Project Specifications section")

        card.tap()
        XCTAssertTrue(element(app, "specification-fullscreen").waitForExistence(timeout: 5),
                      "Tapping a card opens the reader")
        XCTAssertTrue(app.staticTexts["Changes since approval"].exists)
        XCTAssertTrue(app.staticTexts["Everyone finds a recipe by what is in the fridge and shops from one list."].exists)
        attachScreenshot("Specification reader")

        let older = app.buttons["specification-revision-rev-1"]
        XCTAssertTrue(older.waitForExistence(timeout: 3))
        older.tap()
        XCTAssertTrue(element(app, "specification-read-only").waitForExistence(timeout: 5),
                      "An older revision is read-only")
        XCTAssertFalse(app.buttons["specification-approve"].isEnabled)
        attachScreenshot("Older revision read-only")

        app.buttons["specification-revision-rev-2"].tap()
        let approve = app.buttons["specification-approve"]
        let enabled = XCTNSPredicateExpectation(predicate: NSPredicate(format: "enabled == true"), object: approve)
        XCTAssertEqual(XCTWaiter.wait(for: [enabled], timeout: 5), .completed)
        approve.tap()
        let confirm = app.buttons["specification-approve-confirm-button"]
        XCTAssertTrue(confirm.waitForExistence(timeout: 3), "Approval asks for confirmation")
        XCTAssertTrue(app.staticTexts["Approve revision 2?"].exists)
        attachScreenshot("Approve confirmation")
        confirm.tap()
        XCTAssertTrue(app.staticTexts["This revision is approved."].waitForExistence(timeout: 5))
        XCTAssertFalse(element(app, "project-specifications-action-error").exists)
        reveal(app, element(app, "spec-requirement"))
        attachScreenshot("Specification approved")
    }

    nonisolated private func attachScreenshot(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
