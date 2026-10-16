// Signed-out main-app welcome after the marketing landing page separation.
// Specification: specifications/features/landing-onboarding/specification.yml
// The normal Daily Inspiration and existing topic controls remain in the real shell.
import XCTest

@MainActor
final class LandingOnboardingParityUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: direct surface=gui.apple assertions=landing-onboarding.apple-web-parity
    func testSignedOutAppStartsWithNormalDailyInspirationTopicsAndWorkingLogin() {
        let app = launchWelcome()
        let inspiration = element(app, "daily-inspiration-card")
        XCTAssertTrue(inspiration.waitForExistence(timeout: 15)); XCTAssertTrue(inspiration.isHittable)
        XCTAssertTrue(element(app, "guest-interest-rail").exists)
        XCTAssertTrue(app.buttons["guest-interest-skip"].isHittable)
        XCTAssertTrue(element(app, "message-editor").exists)
        XCTAssertFalse(element(app, "landing-intro-expanded").exists)
        XCTAssertFalse(element(app, "landing-story-id").exists)
        XCTAssertFalse(element(app, "landing-signup-benefits").exists)
        let login = app.buttons["header-login-signup-btn"]
        XCTAssertTrue(login.isHittable)
        attachScreenshot("Signed-out app with normal Daily Inspiration and topic selection")
        login.tap()
        XCTAssertTrue(app.buttons["auth-login-tab"].waitForExistence(timeout: 8) || app.buttons["auth-signup-tab"].exists)
    }

    // contract-test: direct surface=gui.apple assertions=landing-onboarding.apple-web-parity
    func testTopicSelectionNarrowsExamplesAndSkipRestoresCatalog() {
        let app = launchWelcome()
        let skip = app.buttons["guest-interest-skip"]
        XCTAssertTrue(skip.waitForExistence(timeout: 15)); skip.tap()
        XCTAssertTrue(element(app, "welcome-chat-cards-carousel").waitForExistence(timeout: 5))
        let all = exampleIDs(app)
        XCTAssertFalse(all.isEmpty)
        app.buttons["guest-interest-select-interests"].tap()
        let rail = element(app, "guest-interest-rail")
        XCTAssertTrue(rail.waitForExistence(timeout: 3))
        XCTAssertFalse(app.buttons["interest-tag-privacy"].exists,
            "Do not offer a topic whose examples are absent from the native catalog")
        let events = app.buttons["interest-tag-find_events"]
        XCTAssertTrue(events.isHittable); events.tap()
        let confirm = app.buttons["guest-interest-continue"]
        XCTAssertTrue(confirm.waitForExistence(timeout: 3)); XCTAssertTrue(confirm.isHittable); confirm.tap()
        let narrowed = exampleIDs(app)
        XCTAssertEqual(narrowed, Set(all.filter { $0.contains("example-creativity-drawing-meetups-berlin") }))
        XCTAssertFalse(narrowed.isEmpty); XCTAssertNotEqual(narrowed, all)
        attachScreenshot("Selected topics narrow the public example catalog")
        app.buttons["guest-interest-select-interests"].tap()
        XCTAssertTrue(skip.waitForExistence(timeout: 3)); skip.tap()
        XCTAssertEqual(exampleIDs(app), all)
        XCTAssertTrue(app.buttons["header-login-signup-btn"].isHittable)
    }

    private func launchWelcome() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-disable-auth-cache", "--ui-test-start-new-chat", "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        return app
    }
    private func element(_ app: XCUIApplication, _ id: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: id).firstMatch
    }
    private func exampleIDs(_ app: XCUIApplication) -> Set<String> {
        let elements = app.descendants(matching: .any).matching(NSPredicate(format:
            "identifier BEGINSWITH %@ OR identifier BEGINSWITH %@", "welcome-chat-card-example-", "welcome-chat-compact-card-example-"))
        return Set(elements.allElementsBoundByIndex.map(\.identifier))
    }
    private func attachScreenshot(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
    }
}
