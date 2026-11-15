import XCTest

/// Screenshot proof for the Project Timeline tab on the Rust core's data
/// shape. All data is the synthetic "Recipe Manager" history of the web
/// preview; no account or network is used.
@MainActor
final class ProjectTimelineUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    private func element(_ app: XCUIApplication, _ identifier: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }

    // contract-test: supporting surface=gui.apple assertions=projects.surface.semantic-parity
    func testTimelineListsEntriesExpandsCommitAndAsksBeforeRestore() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "projects", "--dev-preview-variant", "timeline",
                               "--dev-preview-theme", "light", "--ui-test-embed-presentation",
                               "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        XCTAssertTrue(element(app, "dev-preview-root").waitForExistence(timeout: 10))
        XCTAssertFalse(element(app, "dev-preview-error").exists)

        let tab = app.buttons["project-tab-timeline"]
        XCTAssertTrue(tab.waitForExistence(timeout: 10))
        tab.tap()
        XCTAssertTrue(element(app, "project-timeline").waitForExistence(timeout: 5))
        XCTAssertTrue(element(app, "project-timeline-entry-commit-2").waitForExistence(timeout: 5))
        XCTAssertTrue(element(app, "project-timeline-entry-version-1").exists)
        XCTAssertTrue(element(app, "project-timeline-entry-op-1").exists)
        XCTAssertTrue(app.staticTexts["Removed file"].exists, "A file operation without a known path reads Removed file")
        XCTAssertTrue(app.staticTexts["web-app/styles.css"].exists)
        XCTAssertFalse(element(app, "project-timeline-empty").exists)
        attachScreenshot("Project Timeline")

        let toggle = app.buttons["project-timeline-commit-toggle-commit-2"]
        XCTAssertTrue(toggle.exists)
        toggle.tap()
        let restore = app.buttons["project-timeline-restore-commit-2"]
        XCTAssertTrue(restore.waitForExistence(timeout: 3))
        XCTAssertTrue(app.staticTexts["web-app/index.html"].exists)
        attachScreenshot("Project Timeline commit expanded")

        restore.tap()
        let confirm = app.buttons["project-timeline-restore-confirm"]
        XCTAssertTrue(confirm.waitForExistence(timeout: 3))
        XCTAssertTrue(app.staticTexts["Restore all files to this commit? This creates new versions; later history is kept."].exists)
        attachScreenshot("Project Timeline restore confirm")

        confirm.tap()
        let status = element(app, "project-timeline-restore-status")
        XCTAssertTrue(status.waitForExistence(timeout: 3))
        let done = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", "done"), object: status)
        XCTAssertEqual(XCTWaiter.wait(for: [done], timeout: 8), .completed)
    }

    nonisolated private func attachScreenshot(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
