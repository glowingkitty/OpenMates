// UI parity smoke coverage for the chat cards that closed the 2026-11-12 web
// parity audit gaps: image-generate card states, the Recommendations card and
// the assistant-created Project card. Uses the debug-only synthetic fixture
// (`--dev-preview embeds --dev-chat-cards-fixture <card>`), so no credentials,
// chat records, provider APIs or AI calls are needed. Each test asserts the
// web data-testid equivalents and attaches a screenshot for visual review.
// Plan: docs/plans/apple-client-core-migration/plan.yml (parity_audit_2026_11_12)

import XCTest

@MainActor
final class ChatCardsParityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
        // A timed-out rotated test must not leave later tests in landscape.
        XCUIDevice.shared.orientation = .portrait
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testImageGenerateCardStatesRender() {
        continueAfterFailure = true
        let app = launchFixture("image-generate")
        let expectedStates = [
            ("processing", "processing"), ("scripting", "draft-status"), ("svg-draft", "svg-draft"),
            ("modify", "modify"), ("error", "error"), ("cancelled", "processing"),
            ("draft-finished", "processing")
        ]
        for (fixture, state) in expectedStates {
            let container = element("dev-chat-card-image-\(fixture)", in: app)
            scrollUntilVisible(app: app, element: container)
            XCTAssertTrue(container.waitForExistence(timeout: 5), "Missing image card fixture \(fixture)")
            XCTAssertTrue(container.descendants(matching: .any)["embed-preview"].firstMatch.exists,
                          "Image card \(fixture) must render inside the shared embed preview card")
            let card = container.descendants(matching: .any)["image-generate-preview"].firstMatch
            XCTAssertTrue(card.waitForExistence(timeout: 5), "Image card \(fixture) must use the image-generate renderer")
            XCTAssertEqual(card.value as? String, state, "Image card \(fixture) shows the wrong state")
            switch fixture {
            case "scripting":
                XCTAssertTrue(card.descendants(matching: .any)["image-generate-draft-status"].firstMatch.exists)
            case "svg-draft":
                XCTAssertTrue(card.descendants(matching: .any)["image-generate-svg-draft"].firstMatch.exists)
                XCTAssertTrue(card.descendants(matching: .any)["image-generate-svg-draft-stage"].firstMatch.exists)
            case "modify":
                XCTAssertTrue(card.descendants(matching: .any)["image-modify-step"].firstMatch.exists)
            case "error":
                XCTAssertTrue(card.descendants(matching: .any)["image-generate-error-state"].firstMatch.exists)
                XCTAssertFalse(card.descendants(matching: .any)["image-generate-preview-prompt"].firstMatch.exists,
                               "A failed card hides the prompt like the web error box")
            default:
                XCTAssertTrue(card.descendants(matching: .any)["image-generate-preview-prompt"].firstMatch.exists)
            }
            attachScreenshot(name: "Image generate card|\(fixture)")
        }
    }

    // contract-test: supporting surface=gui.apple assertions=app-memories.suggestions.post-processor
    func testRecommendationsCardRendersAndPages() {
        let app = launchFixture("recommendations")
        let card = element("recommendations-card", in: app)
        XCTAssertTrue(card.waitForExistence(timeout: 8))
        XCTAssertEqual(card.value as? String, "1/3")
        XCTAssertTrue(element("recommendation-heading", in: app).exists)
        XCTAssertTrue(element("recommendation-embed", in: app).exists)
        XCTAssertTrue(element("recommendation-title", in: app).exists)
        XCTAssertTrue(element("recommendation-summary", in: app).exists)
        XCTAssertEqual(app.descendants(matching: .any).matching(identifier: "recommendation-dot").count, 3)
        XCTAssertEqual(element("recommendation-item", in: app).value as? String, "memory:create:rec-memory-1")
        attachScreenshot(name: "Recommendations card|first")

        let next = element("recommendation-next", in: app)
        XCTAssertTrue(next.isHittable)
        next.tap()
        XCTAssertEqual(element("recommendation-item", in: app).value as? String, "workflow:update:rec-workflow-1")
        XCTAssertEqual(card.value as? String, "2/3")
        attachScreenshot(name: "Recommendations card|second")

        let previous = element("recommendation-previous", in: app)
        previous.tap()
        previous.tap()
        XCTAssertEqual(card.value as? String, "3/3", "Previous wraps around to the last recommendation")

        let action = element("recommendation-action", in: app)
        XCTAssertTrue(action.isHittable)
        action.tap()
        XCTAssertEqual(element("dev-recommendation-last-action", in: app).value as? String, "rec-memory-2")
        attachScreenshot(name: "Recommendations card|after action")
    }

    // contract-test: supporting surface=gui.apple assertions=projects.focus.inferred-consent
    func testProjectCreatedCardRenders() {
        let app = launchFixture("project-created")
        let card = element("project-created-card", in: app)
        XCTAssertTrue(card.waitForExistence(timeout: 8))
        XCTAssertFalse(element("focus-mode-bar", in: app).exists,
                       "An assistant-created Project replaces the focus-mode bar")
        XCTAssertEqual(element("project-created-row", in: app).value as? String, "created")
        XCTAssertEqual(element("project-focus-row", in: app).value as? String, "activated")
        let createdName = element("project-created-name", in: app)
        XCTAssertTrue(createdName.exists)
        XCTAssertTrue(createdName.isHittable)
        XCTAssertTrue(element("project-focus-name", in: app).isHittable)
        XCTAssertTrue(element("focus-status-value", in: app).exists)
        XCTAssertFalse(element("project-created-undo", in: app).exists,
                       "Undo stays hidden until the client core exposes it, like the web")
        attachScreenshot(name: "Project created card")
    }

    // MARK: - Helpers

    private func launchFixture(_ card: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embeds", "--dev-chat-cards-fixture", card,
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
        for _ in 0..<8 where !element.exists || !element.isHittable {
            app.swipeUp()
        }
    }
}
