import XCTest

/// Screenshot proof for the agentic coding surfaces (test-result embed,
/// assistant-created Project card with Undo, application card in a Project folder).
/// All data is synthetic; no account or network is used.
@MainActor
final class AgenticCodingPreviewUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
        XCUIDevice.shared.orientation = .portrait
    }

    // contract-test: supporting surface=gui.apple assertions=code-run.tests.recorded-evidence
    func testTestResultPreviewCardsRender() {
        let app = launchCards("test-result-previews")
        for (kind, status) in [("browser", "passed"), ("cli", "failed"), ("unit", "stale")] {
            let card = element("dev-test-result-card-\(kind)", in: app)
            scrollUntilVisible(app: app, element: card)
            XCTAssertTrue(card.waitForExistence(timeout: 8), "Missing \(kind) test-result card")
            XCTAssertTrue(card.descendants(matching: .any)["test-result-preview"].firstMatch.exists)
            XCTAssertTrue(card.descendants(matching: .any)["test-result-preview-counts"].firstMatch.exists)
            XCTAssertTrue(card.descendants(matching: .any)["test-result-preview-title"].firstMatch.exists)
            XCTAssertTrue(card.descendants(matching: .any)["test-result-preview-status"].firstMatch.exists)
            if status == "stale" {
                XCTAssertTrue(card.descendants(matching: .any)["test-result-preview-stale"].firstMatch.exists)
            }
            attachScreenshot(name: "Test result preview|\(kind) \(status)")
        }
    }

    // contract-test: supporting surface=gui.apple assertions=code-run.tests.recorded-evidence
    func testBrowserTestResultFullscreenShowsStepTimeline() {
        let app = launchCards("test-result-fullscreen")
        XCTAssertTrue(element("test-result-fullscreen-body", in: app).waitForExistence(timeout: 8))
        XCTAssertTrue(element("test-result-status", in: app).exists)
        XCTAssertTrue(element("test-result-count-passed", in: app).exists)
        let timeline = element("test-result-timeline", in: app)
        scrollUntilVisible(app: app, element: timeline)
        XCTAssertTrue(timeline.exists)
        XCTAssertTrue(element("test-result-step-0", in: app).exists)
        XCTAssertTrue(element("test-result-step-2", in: app).exists)
        attachScreenshot(name: "Test result fullscreen|browser run with step timeline")
    }

    // contract-test: supporting surface=gui.apple assertions=projects.creation.assistant-inferred
    func testProjectCreatedCardUndoAndUndoneState() {
        let app = launchCards("project-created-undo")
        XCTAssertTrue(element("project-created-card", in: app).waitForExistence(timeout: 8))
        // `app.buttons`: the fixture marker's value is also "project-created-undo",
        // and an untyped identifier lookup matches values too.
        let undo = app.buttons["project-created-undo"]
        XCTAssertTrue(undo.waitForExistence(timeout: 5))
        XCTAssertTrue(undo.isHittable)
        XCTAssertEqual(element("project-created-row", in: app).value as? String, "created")
        attachScreenshot(name: "Project created card|Undo visible")

        undo.tap()
        let row = element("project-created-row", in: app)
        let undone = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", "undone"), object: row)
        XCTAssertEqual(XCTWaiter.wait(for: [undone], timeout: 5), .completed,
                       "fixture undo \(element("dev-project-undo-calls", in: app).value as? String ?? "missing")")
        XCTAssertFalse(app.buttons["project-created-undo"].exists)
        XCTAssertTrue(element("project-created-status", in: app).exists)
        XCTAssertEqual(element("project-focus-row", in: app).value as? String, "inactive")
        attachScreenshot(name: "Project created card|Undone")
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.application-single-source
    func testApplicationCardLeadsItsProjectFolder() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "projects", "--dev-preview-variant", "applicationFolder",
            "--dev-preview-theme", "dark", "--dev-preview-width", "390", "--dev-preview-height", "844",
            "--ui-test-embed-presentation", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        XCTAssertTrue(element("dev-preview-root", in: app).waitForExistence(timeout: 10))
        let filesTab = element("project-tab-files", in: app)
        XCTAssertTrue(filesTab.waitForExistence(timeout: 8))
        filesTab.tap()
        let folder = app.buttons["project-virtual-folder-kitchen-app"]
        XCTAssertTrue(folder.waitForExistence(timeout: 8))
        for _ in 0..<12 where !folder.exists || !folder.isHittable { app.swipeUp() }
        XCTAssertTrue(folder.isHittable)
        attachScreenshot(name: "Projects workspace|folder containing the application")
        folder.tap()

        let application = element("project-item-kitchen-app-card", in: app)
        let file = element("project-item-kitchen-app-file", in: app)
        XCTAssertTrue(application.waitForExistence(timeout: 8))
        XCTAssertTrue(file.waitForExistence(timeout: 8))
        XCTAssertLessThan(application.frame.minY, file.frame.minY,
                          "The application card stays ahead of files in its folder")
        attachScreenshot(name: "Projects workspace|application card ahead of files")
    }

    private func launchCards(_ fixture: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embeds", "--dev-chat-cards-fixture", fixture,
                               "--dev-preview-theme", "light", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launchEnvironment["DEV_PREVIEW"] = "embeds"
        app.launch()
        XCTAssertTrue(element("dev-chat-cards-fixture", in: app).waitForExistence(timeout: 10))
        return app
    }

    private func element(_ identifier: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any)[identifier].firstMatch
    }

    private func attachScreenshot(name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func scrollUntilVisible(app: XCUIApplication, element: XCUIElement) {
        for _ in 0..<8 where !element.exists || !element.isHittable { app.swipeUp() }
    }
}
