import XCTest

@MainActor
final class WelcomeContinueUITests: XCTestCase {
    // contract-test: direct surface=gui.apple assertions=continue-carousel.saved-item.start-time-gated
    func testUpcomingSavedEventComesBeforeRecentChatsAndOpensRealFullscreen() {
        checkCarousel(large: false)
    }
    // contract-test: direct surface=gui.apple assertions=continue-carousel.saved-item.start-time-gated
    func testExpandedSavedEventPreviewOpensRealFullscreen() {
        checkCarousel(large: true)
    }
    private func checkCarousel(large: Bool) {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embed-share", "--dev-welcome-continue-fixture", "--ui-test-disable-auth-cache"]
        if large { app.launchArguments.append("--dev-welcome-continue-large") }
        app.launch()
        let order = app.staticTexts["continue-fixture-order"]
        XCTAssertTrue(order.waitForExistence(timeout: 10))
        XCTAssertEqual(order.label, "embed:near,embed:later,recent")
        let savedIdentity = app.descendants(matching: .any).matching(identifier: "welcome-priority-embed-near").firstMatch
        XCTAssertTrue(savedIdentity.exists)
        let card = large
            ? app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "Public near event")).firstMatch
            : savedIdentity
        XCTAssertTrue(card.exists); XCTAssertTrue(card.isHittable)
        if large { XCTAssertEqual(card.frame.height, 200, accuracy: 2) }
        else { XCTAssertLessThan(card.frame.height, 100) }
        XCTAssertFalse(app.descendants(matching: .any).matching(identifier: "welcome-priority-embed-outside").firstMatch.exists)
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "Upcoming event before recent chats"
        shot.lifetime = .keepAlways; add(shot)
        card.tap()
        XCTAssertTrue(app.descendants(matching: .any).matching(identifier: "embed-fullscreen-header").firstMatch.waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Public near event"].exists)
    }
}
