import XCTest

@MainActor
final class ProjectReferenceEmbedParityUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testSearchAndReadReferencesUseTypedPreviewAndVisibleFullscreenRows() {
        for operation in ["search", "read"] {
            let app = XCUIApplication()
            app.launchArguments = ["--dev-preview", "embeds", "--dev-preview-app", "projects",
                "--embed-registry-key", "app:projects:\(operation)", "--embed-surface", "preview",
                "--ui-test-embed-presentation", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
            app.launch()
            XCTAssertTrue(app.descendants(matching: .any)["project-reference-preview"].waitForExistence(timeout: 10))
            let card = app.buttons["embed-preview"]
            XCTAssertTrue(card.isHittable)
            attach("Projects \(operation) typed preview")
            card.tap()
            let ready = app.descendants(matching: .any)["embed-presentation-state"].firstMatch
            XCTAssertTrue(ready.waitForExistence(timeout: 10))
            let settled = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "ready"), object: ready)
            XCTAssertEqual(XCTWaiter.wait(for: [settled], timeout: 10), .completed)
            let rows = app.buttons.matching(identifier: "project-reference-row")
            XCTAssertEqual(rows.count, 2)
            XCTAssertTrue(rows.element(boundBy: 0).isHittable)
            XCTAssertTrue(rows.element(boundBy: 1).isHittable)
            XCTAssertTrue(app.staticTexts["README.md"].exists)
            XCTAssertTrue(app.staticTexts["docs/architecture.md"].exists)
            attach("Projects \(operation) fullscreen reference rows")
            app.terminate()
        }
    }

    private func attach(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
    }
}
