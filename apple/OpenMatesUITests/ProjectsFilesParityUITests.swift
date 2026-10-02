import XCTest

/// Focused production control checks with public, account-free Project data.
/// Actual connected-device reads remain a separate real parent-flow check.
@MainActor
final class ProjectsFilesParityUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=projects.files.connected-embed-previews,projects.surface.semantic-parity
    func testConnectedFolderUsesFilesEmbedFooterAndOpensItsContents() {
        let app = launch(variant: "connectedSource")
        waitForConnectedRoot(app, entry: "frontend")
        let folder = app.buttons["project-remote-entry-frontend"]
        reveal(folder, in: app)
        let preview = folder.descendants(matching: .any)["project-folder-embed-preview"].firstMatch
        XCTAssertTrue(preview.exists, "Connected folders must use the regular Files embed card")
        XCTAssertEqual(preview.frame.height, 200, accuracy: 1)
        XCTAssertLessThanOrEqual(preview.frame.width, 301)
        XCTAssertGreaterThan(preview.frame.width, 250)
        let title = folder.staticTexts["embed-basic-info-title"]
        XCTAssertTrue(title.exists)
        XCTAssertEqual(title.label, "frontend")
        XCTAssertTrue(folder.staticTexts["1 file, 1 folder · 2.0 KiB in files"].exists)
        XCTAssertTrue(folder.staticTexts["src"].exists)
        XCTAssertTrue(folder.staticTexts["app.ts"].exists)
        XCTAssertFalse(folder.staticTexts["project-folder-empty-summary"].exists,
                       "Available child rows must replace the empty summary")
        XCTAssertEqual(folder.staticTexts["src"].frame.minY, preview.frame.minY + 16, accuracy: 3)
        XCTAssertEqual(folder.staticTexts["src"].frame.minX, preview.frame.minX + 62.4, accuracy: 3)
        XCTAssertGreaterThan(title.frame.minY, preview.frame.minY + 130,
                             "The Files gradient icon and label belong in the shared bottom info bar")
        screenshot(app, "Connected folder Files embed preview")
        XCTAssertTrue(folder.isHittable)
        folder.tap()
        XCTAssertTrue(app.staticTexts["frontend"].firstMatch.waitForExistence(timeout: 5))
        let gone = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: folder)
        XCTAssertEqual(XCTWaiter.wait(for: [gone], timeout: 5), .completed,
                       "The root folder card must leave the current directory after opening")
        let root = app.buttons["OpenMates repository"]
        XCTAssertTrue(root.isHittable)
        root.tap()
        XCTAssertTrue(app.buttons["project-remote-entry-frontend"].waitForExistence(timeout: 5),
                      "The same folder card must remain operable after returning to the root")
    }

    // contract-test: supporting surface=gui.apple assertions=projects.surface.semantic-parity
    func testProjectHeaderActionsStayFixedAndOperableWhileFilesScroll() {
        let app = launch(variant: "largeConnectedSource")
        waitForConnectedRoot(app, entry: "needle-current.ts")
        let actions = element(app, "project-header-actions")
        let report = app.buttons["project-report-issue"]
        let more = app.buttons["project-more-button"]
        let close = app.buttons["project-close-button"]
        XCTAssertTrue(actions.waitForExistence(timeout: 5))
        let overlayStyle = XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "value == %@", "banner-overlay"), object: actions)
        XCTAssertEqual(XCTWaiter.wait(for: [overlayStyle], timeout: 5), .completed)
        let positions = [report.frame.midY, more.frame.midY, close.frame.midY]
        XCTAssertTrue(app.buttons["project-header-edit"].isHittable,
                      "The initial banner must remain visible before testing its scroll transition.")
        let scroll = element(app, "project-detail-scroll")
        for _ in 0..<6 where (actions.value as? String) != "standard" { scroll.swipeUp() }
        XCTAssertEqual(actions.value as? String, "standard")
        for (index, button) in [report, more, close].enumerated() {
            XCTAssertTrue(button.isHittable, "Project actions must remain visible above scrolled Files")
            XCTAssertEqual(button.frame.midY, positions[index], accuracy: 2)
            XCTAssertGreaterThanOrEqual(button.frame.minX, scroll.frame.minX)
            XCTAssertLessThanOrEqual(button.frame.maxX, scroll.frame.maxX)
        }
        report.tap()
        XCTAssertEqual(element(app, "dev-preview-local-action").label, "reported-project-preview-project")
        more.tap()
        let settings = app.buttons["project-menu-settings"]
        XCTAssertTrue(settings.waitForExistence(timeout: 3))
        XCTAssertTrue(settings.isHittable)
        settings.tap()
        XCTAssertEqual(element(app, "dev-preview-local-action").label, "opened-settings-preview-project")
        screenshot(app, "Fixed Project header actions after Files scroll")
        for _ in 0..<6 where (actions.value as? String) != "banner-overlay" { scroll.swipeDown() }
        XCTAssertEqual(actions.value as? String, "banner-overlay")
        XCTAssertTrue(close.isHittable)
        close.tap()
        XCTAssertTrue(app.buttons["project-card-preview-project"].waitForExistence(timeout: 5))
        XCTAssertFalse(actions.exists)
    }

    // contract-test: supporting surface=gui.apple assertions=projects.access.explicit-context,projects.files.connected-embed-previews
    func testOfflineConnectedSourceCannotOpenFileBrowser() {
        let app = launch(variant: "offlineConnectedSource")
        let source = app.buttons["project-source-source-preview"]
        XCTAssertTrue(source.waitForExistence(timeout: 5))
        reveal(source, in: app)
        XCTAssertFalse(source.isEnabled, "Offline source actions match the disabled web card")
        XCTAssertFalse(app.buttons["project-remote-entry-README.md"].exists)
        XCTAssertFalse(app.buttons["project-remote-entry-frontend"].exists)
        screenshot(app, "Offline connected source requires its source device")
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.connected-embed-previews
    func testRootConfigurationFilesOpenTextAndBinaryKeepsOriginalDownload() {
        let app = launch(variant: "rootFiles")
        waitForConnectedRoot(app, entry: "Dockerfile")
        for filename in ["Dockerfile", "Makefile", "config.toml", "notes.custom"] {
            let card = app.buttons["project-remote-entry-\(filename)"]
            reveal(card, in: app)
            card.tap()
            XCTAssertTrue(element(app, "code-source-panel").waitForExistence(timeout: 5))
            XCTAssertTrue(app.staticTexts["// Preview of \(filename)"].waitForExistence(timeout: 5),
                          "The opened root file must supply its own content")
            waitForPresentation(app)
            screenshot(app, "Root text file \(filename)")
            let close = app.buttons["embed-minimize"]
            XCTAssertTrue(close.isHittable)
            close.tap()
        }
        let binary = app.buttons["project-remote-entry-archive.pdf"]
        reveal(binary, in: app)
        binary.tap()
        XCTAssertTrue(element(app, "project-remote-file-detail").waitForExistence(timeout: 5))
        XCTAssertFalse(element(app, "code-source-panel").exists)
        XCTAssertTrue(app.buttons["project-remote-download"].isHittable)
        screenshot(app, "Original download offered for unsupported binary")
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.connected-embed-previews
    func testConnectedDirectoryPagesReachLaterRootFilesAndReturnToFirstPage() {
        let app = launch(variant: "largeConnectedSource")
        waitForConnectedRoot(app, entry: "needle-current.ts")
        XCTAssertTrue(app.buttons["project-remote-entry-nested"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["project-remote-entry-nested/needle-child.ts"].exists,
                       "Only immediate children belong in the root folder")
        let next = app.buttons["project-remote-page-next"]
        reveal(next, in: app)
        XCTAssertFalse(app.buttons["project-remote-page-previous"].isEnabled)
        next.tap()
        XCTAssertEqual(element(app, "project-remote-page-number").label, "2")
        reveal(next, in: app)
        next.tap()
        XCTAssertEqual(element(app, "project-remote-page-number").label, "3")
        XCTAssertFalse(next.isEnabled)
        let lastFile = app.buttons["project-remote-entry-remote-file-124.ts"]
        reveal(lastFile, in: app)
        lastFile.tap()
        XCTAssertTrue(element(app, "code-source-panel").waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["// Preview of remote-file-124.ts"].waitForExistence(timeout: 5))
        waitForPresentation(app)
        screenshot(app, "Opened connected root file beyond first 48 entries")
        app.buttons["embed-minimize"].tap()
        let previous = app.buttons["project-remote-page-previous"]
        reveal(previous, in: app)
        previous.tap()
        reveal(previous, in: app)
        previous.tap()
        XCTAssertEqual(element(app, "project-remote-page-number").label, "1")
        XCTAssertFalse(previous.isEnabled)
        screenshot(app, "Connected folder returns to first page")
    }

    // contract-test: supporting surface=gui.apple assertions=projects.files.connected-embed-previews,projects.access.explicit-context
    func testTruncatedTextKeepsWarningAndDownloadsOriginalWithoutUnsupportedShare() {
        let app = launch(variant: "truncatedConnectedSource")
        waitForConnectedRoot(app, entry: "large.txt")
        app.buttons["project-remote-entry-large.txt"].tap()
        XCTAssertTrue(element(app, "code-source-panel").waitForExistence(timeout: 5))
        waitForPresentation(app)
        let warning = element(app, "project-remote-preview-truncated")
        XCTAssertTrue(warning.exists)
        XCTAssertTrue(warning.isHittable, "The bounded-preview notice must be visible")
        XCTAssertFalse(app.staticTexts["ORIGINAL FILE END"].exists,
                       "The preview must not pretend to include the original's last line")
        app.buttons["embed-more-button"].tap()
        let download = app.buttons["project-remote-download"]
        XCTAssertTrue(download.waitForExistence(timeout: 5))
        XCTAssertTrue(download.isHittable)
        XCTAssertTrue(download.label.lowercased().contains("original"))
        XCTAssertFalse(app.buttons["embed-share-button"].exists,
                       "Transient connected files cannot create a chat embed share link")
        XCTAssertFalse(app.buttons["embed-run-button"].exists)
        download.tap()
        let ready = app.buttons["project-remote-share-download"]
        XCTAssertTrue(ready.waitForExistence(timeout: 5), "The original is available through the fenced store download")
        XCTAssertTrue(ready.isHittable)
        let progress = element(app, "project-remote-download-progress")
        XCTAssertTrue(progress.waitForExistence(timeout: 5))
        XCTAssertEqual(progress.value as? String, "240030/240030",
                       "The complete original is downloaded, rather than the 180 KiB bounded preview")
        XCTAssertTrue(warning.exists, "Downloading does not convert a bounded preview to complete text")
        screenshot(app, "Connected text truncation and complete original download")
        app.buttons["embed-minimize"].tap()
        XCTAssertTrue(app.buttons["project-remote-entry-large.txt"].waitForExistence(timeout: 5))
    }

    private func launch(variant: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "projects", "--dev-preview-variant", variant,
            "--dev-preview-theme", "dark", "--dev-preview-width", "390", "--dev-preview-height", "844",
            "--ui-test-embed-presentation", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let root = element(app, "dev-preview-root")
        XCTAssertTrue(root.waitForExistence(timeout: 10))
        XCTAssertEqual(root.value as? String, "auth=not-started;store=detached;socket=disconnected")
        XCTAssertFalse(element(app, "dev-preview-error").exists)
        return app
    }

    private func waitForConnectedRoot(_ app: XCUIApplication, entry: String) {
        XCTAssertTrue(app.buttons["project-remote-entry-\(entry)"].waitForExistence(timeout: 10),
                      "Files must automatically open the connected repository")
        XCTAssertFalse(app.buttons["project-source-source-preview"].exists)
    }

    private func waitForPresentation(_ app: XCUIApplication) {
        let state = element(app, "embed-presentation-state")
        XCTAssertTrue(state.waitForExistence(timeout: 5), "The real presentation-completion state must be exposed")
        let ready = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "ready"), object: state)
        XCTAssertEqual(XCTWaiter.wait(for: [ready], timeout: 5), .completed)
    }

    private func reveal(_ control: XCUIElement, in app: XCUIApplication) {
        let scroll = app.scrollViews.firstMatch
        for _ in 0..<24 where !control.isHittable { scroll.swipeUp() }
        if !control.isHittable {
            for _ in 0..<24 where !control.isHittable { scroll.swipeDown() }
        }
        XCTAssertTrue(control.isHittable)
    }

    private func element(_ app: XCUIApplication, _ id: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: id).firstMatch
    }

    private func screenshot(_ app: XCUIApplication, _ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
