// Production signed-out routing and bundled examples. Pair transport alone is
// held at its existing deterministic waiting fixture; this is not live login proof.
import XCTest

@MainActor
final class WatchGuestWorkspaceUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }
    private func launch() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-watch-guest", "--ui-test-watch-guest-local-drafts"]
        app.launch()
        XCTAssertTrue(app.descendants(matching: .any)["watch-guest-workspace"].waitForExistence(timeout: 10))
        return app
    }
    private func reachable(_ element: XCUIElement, app: XCUIApplication) {
        for _ in 0..<6 where !element.isHittable { app.swipeUp() }
        XCTAssertTrue(element.isHittable)
    }
    private func retain(_ name: String) {
        let image = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        image.name = name; image.lifetime = .keepAlways; add(image)
    }


    // contract-test: supporting surface=gui.apple assertions=apple-watch.guest.public-inference,apple-watch.guest.account-isolation
    func testGuestDraftSurvivesBackAndReopenWithoutSendingOrPairing() {
        let app = launch()
        app.buttons["watch-new-chat-button"].tap()
        let field = app.textFields["watch-message-input"]
        XCTAssertTrue(field.waitForExistence(timeout: 5)); reachable(field, app: app); field.tap()
        let input = app.textViews.matching(NSPredicate(format: "placeholderValue == %@", field.placeholderValue ?? "")).firstMatch
        XCTAssertTrue(input.waitForExistence(timeout: 10)); input.typeText("Guest local draft")
        let done = app.buttons["Done"]
        XCTAssertTrue(done.waitForExistence(timeout: 5)); done.tap()
        XCTAssertFalse(app.descendants(matching: .any)["watch-pair-login"].exists)
        app.buttons["watch-public-back"].tap()
        let saved = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@ AND label CONTAINS %@", "watch-guest-local-", "Guest local draft")).firstMatch
        reachable(saved, app: app); saved.tap()
        XCTAssertEqual(app.textFields["watch-message-input"].value as? String, "Guest local draft")
        XCTAssertFalse(app.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH %@", "watch-guest-message-")).firstMatch.exists)
        retain("Watch guest encrypted local draft without submission")
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.guest.compact-workspace
    func testGuestStartsWithReachableActionsLoginAndBundledExamples() {
        let app = launch()
        let create = app.buttons["watch-new-chat-button"]
        let search = app.buttons["watch-chat-search-button"]
        let settings = app.buttons["watch-chat-settings-button"]
        let login = app.buttons["watch-guest-login"]
        for element in [create, search, settings, login] { XCTAssertTrue(element.isHittable) }
        XCTAssertLessThan(create.frame.maxY, login.frame.minY)
        XCTAssertFalse(app.descendants(matching: .any)["watch-pair-login"].exists)
        let example = app.buttons["watch-chat-row-example-artemis-ii-mission"]
        reachable(example, app: app)
        XCTAssertLessThan(login.frame.maxY, example.frame.minY)
        retain("Watch guest Chats action row Login and bundled example")
        for _ in 0..<4 where !create.isHittable { app.swipeDown() }
        XCTAssertTrue(create.isHittable)
        create.tap()
        XCTAssertTrue(app.descendants(matching: .any)["watch-guest-new-chat"].waitForExistence(timeout: 3))
        XCTAssertTrue(app.buttons["watch-send-button"].exists)
        XCTAssertFalse(app.buttons["watch-send-button"].isEnabled)
        XCTAssertTrue(app.textFields["watch-message-input"].exists)
        XCTAssertTrue(app.buttons["watch-guest-refresh-budget"].exists)
        XCTAssertFalse(app.descendants(matching: .any)["watch-pair-login"].exists)
        app.buttons["watch-public-back"].tap()
        settings.tap()
        XCTAssertTrue(app.descendants(matching: .any)["watch-guest-settings"].waitForExistence(timeout: 3))
        app.buttons["watch-public-back"].tap()
        XCTAssertTrue(login.isHittable)
    }

    // contract-test: direct surface=gui.apple assertions=apple-watch.guest.compact-workspace,apple-watch.guest.account-isolation
    func testSearchOpensRealPublicTranscriptAndPreviewsThenBackAndClearRestoreCatalog() {
        let app = launch()
        app.buttons["watch-chat-search-button"].tap()
        let field = app.textFields["watch-chat-search-input"]
        reachable(field, app: app)
        field.tap()
        // Use the existing Watch Quickboard path; the underlying SwiftUI field
        // cannot receive typeText while the system sheet owns keyboard focus.
        let input = app.textViews.matching(NSPredicate(format: "placeholderValue == %@", field.placeholderValue ?? "")).firstMatch
        XCTAssertTrue(input.waitForExistence(timeout: 10)); input.typeText("Artemis")
        let done = app.buttons["Done"]
        XCTAssertTrue(done.waitForExistence(timeout: 5)); done.tap()
        let example = app.buttons["watch-chat-row-example-artemis-ii-mission"]
        reachable(example, app: app); example.tap()
        XCTAssertTrue(app.descendants(matching: .any)["watch-public-transcript"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.textFields["watch-message-input"].exists)
        XCTAssertFalse(app.buttons["watch-chat-share-button"].exists)
        let preview = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "watch-embed-preview-")).firstMatch
        reachable(preview, app: app); preview.tap()
        XCTAssertTrue(app.buttons["watch-embed-continuation-close"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["watch-embed-open-device"].exists)
        retain("Watch public bundled embed detail without private handoff")
        app.buttons["watch-embed-continuation-close"].tap()
        for _ in 0..<10 where !app.buttons["watch-public-back"].isHittable { app.swipeDown() }
        app.buttons["watch-public-back"].tap()
        let clear = app.buttons["watch-public-search-clear"]
        reachable(clear, app: app); clear.tap()
        let another = app.buttons["watch-chat-row-example-beautiful-single-page-html"]
        reachable(another, app: app)
        XCTAssertTrue(another.exists)
        for _ in 0..<6 where !app.buttons["watch-guest-login"].isHittable { app.swipeDown() }
        XCTAssertTrue(app.buttons["watch-guest-login"].isHittable)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.explicit-entry-back
    func testOnlyExplicitLoginEntersPairingAndBackRestoresGuestForNextAttempt() {
        let app = launch()
        app.buttons["watch-guest-login"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["watch-pair-login"].waitForExistence(timeout: 5))
        let back = app.buttons["watch-pair-guest-back"]
        XCTAssertTrue(back.isHittable)
        retain("Watch explicit Login offers Back and iPhone-first approval")
        back.tap()
        XCTAssertTrue(app.buttons["watch-guest-login"].waitForExistence(timeout: 3))
        XCTAssertFalse(app.descendants(matching: .any)["watch-pair-login"].exists)
        app.buttons["watch-guest-login"].tap()
        XCTAssertTrue(back.waitForExistence(timeout: 3)); back.tap()
        XCTAssertTrue(app.buttons["watch-guest-login"].isHittable)
    }
}
