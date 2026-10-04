// Production controls inside a detached preview host. Real AES-GCM key wrappers
// are seeded locally; tests never generate share links or write to a server.
import XCTest

@MainActor
final class EmbedShareSettingsParityUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: direct surface=gui.apple assertions=settings-ui.shell.lifecycle-and-routing,settings-ui.navigation.parent-return
    func testFullscreenShareUsesSettingsChildBackAndReturnsToSameEmbed() {
        let app = launch()
        card("first", in: app).tap()
        tapHeaderShare(in: app)
        assertShareSettings(title: "Share fixture first", in: app)
        let back = app.buttons["settings-destination-back"]
        XCTAssertTrue(back.isHittable)
        back.tap()
        XCTAssertTrue(element("settings-shared-page", in: app).waitForExistence(timeout: 5))
        XCTAssertFalse(element("settings-embed-share-content", in: app).exists)
        closeSettings(in: app)
        XCTAssertTrue(element("embed-share-fixture-fullscreen", in: app).waitForExistence(timeout: 5))
        tapHeaderShare(in: app)
        assertShareSettings(title: "Share fixture first", in: app)
        closeSettings(in: app)
        XCTAssertTrue(app.buttons["embed-close-button"].isHittable)
        app.buttons["embed-close-button"].tap()
        XCTAssertTrue(card("first", in: app).waitForExistence(timeout: 5))
    }

    // contract-test: direct surface=gui.apple assertions=settings-ui.shell.lifecycle-and-routing,chats.surface.semantic-parity
    func testFullscreenShareAfterSiblingNavigationUsesCurrentEmbed() {
        let app = launch()
        card("first", in: app).tap()
        let next = app.buttons["embed-next"]
        XCTAssertTrue(next.waitForExistence(timeout: 5))
        XCTAssertTrue(next.isHittable)
        next.tap()
        tapHeaderShare(in: app)
        assertShareSettings(title: "Share fixture second", in: app)
        closeSettings(in: app)
        tapHeaderShare(in: app)
        assertShareSettings(title: "Share fixture second", in: app)
    }

    // contract-test: direct surface=gui.apple assertions=settings-ui.shell.lifecycle-and-routing,settings-ui.navigation.parent-return
    func testPreviewContextShareUsesSelectedEmbedAndSettingsCloseRestoresCard() {
        let app = launch()
        let second = card("second", in: app)
        XCTAssertTrue(second.isHittable)
        second.press(forDuration: 0.8)
        let share = app.buttons["embed-context-share"]
        XCTAssertTrue(share.waitForExistence(timeout: 5))
        XCTAssertTrue(share.isHittable)
        share.tap()
        assertShareSettings(title: "Share fixture second", in: app)
        closeSettings(in: app)
        XCTAssertTrue(card("second", in: app).waitForExistence(timeout: 5))
        XCTAssertTrue(card("second", in: app).isHittable)
        XCTAssertFalse(element("embed-context-menu", in: app).exists)
    }

    // contract-test: supporting surface=gui.apple assertions=settings-ui.composition.canonical-and-accessible,chats.surface.semantic-parity
    func testEmbedSettingsKeepPasswordAndAllExpirationChoicesWithoutGeneratingLink() {
        let app = launch()
        card("first", in: app).press(forDuration: 0.8)
        let share = app.buttons["embed-context-share"]
        XCTAssertTrue(share.waitForExistence(timeout: 5))
        share.tap()
        assertShareSettings(title: "Share fixture first", in: app)
        let durations = app.buttons.matching(identifier: "duration-option")
        XCTAssertEqual(durations.count, 8)
        let oneMinute = durations.element(boundBy: 1)
        if !oneMinute.isHittable { app.swipeUp() }
        XCTAssertTrue(oneMinute.isHittable)
        oneMinute.tap()
        XCTAssertTrue(oneMinute.isSelected)
        app.swipeDown()
        let password = app.buttons["share-password-toggle"].firstMatch
        if !password.isHittable { app.swipeUp() }
        XCTAssertTrue(password.isHittable)
        password.tap()
        let field = app.secureTextFields["share-password-field"]
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["share-generate-link"].isEnabled)
        field.tap()
        field.typeText("password1")
        XCTAssertTrue(app.buttons["share-generate-link"].isEnabled)
        XCTAssertFalse(element("share-community-toggle", in: app).exists)
        XCTAssertFalse(element("share-highlights-toggle", in: app).exists)
        XCTAssertFalse(element("share-short-link-url", in: app).exists)
    }

    private func launch() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embed-share", "--dev-embed-share-settings-fixture", "--ui-test-disable-auth-cache"]
        app.launchEnvironment["DEV_PREVIEW"] = "embed-share"
        app.launch()
        let readiness = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", "ready"),
            object: element("embed-share-settings-fixture", in: app))
        XCTAssertEqual(XCTWaiter.wait(for: [readiness], timeout: 10), .completed)
        XCTAssertTrue(card("first", in: app).isHittable)
        return app
    }
    private func card(_ suffix: String, in app: XCUIApplication) -> XCUIElement {
        element("embed-share-fixture-embed-share-settings-\(suffix)", in: app)
    }
    private func element(_ id: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: id).firstMatch
    }
    private func tapHeaderShare(in app: XCUIApplication) {
        let share = app.buttons["embed-share-button"]
        if !share.waitForExistence(timeout: 3) {
            let more = app.buttons["embed-more-button"]
            XCTAssertTrue(more.isHittable)
            more.tap()
        }
        XCTAssertTrue(share.waitForExistence(timeout: 5))
        XCTAssertTrue(share.isHittable)
        share.tap()
    }
    private func assertShareSettings(title: String, in app: XCUIApplication) {
        XCTAssertTrue(element("settings-shared-share-settings", in: app).waitForExistence(timeout: 5))
        XCTAssertTrue(element("settings-embed-share-content", in: app).waitForExistence(timeout: 5))
        let contentTitle = app.staticTexts["share-content-title"]
        XCTAssertTrue(contentTitle.waitForExistence(timeout: 5))
        XCTAssertEqual(contentTitle.label, title)
        XCTAssertTrue(app.buttons["share-generate-link"].isHittable)
        XCTAssertTrue(app.buttons["settings-destination-back"].isHittable)
        XCTAssertFalse(element("embed-share-panel", in: app).exists)
        XCTAssertFalse(app.tables.firstMatch.exists)
    }
    private func closeSettings(in app: XCUIApplication) {
        let close = app.buttons["settings-backdrop-dismiss"]
        XCTAssertTrue(close.waitForExistence(timeout: 5))
        close.coordinate(withNormalizedOffset: CGVector(dx: 0.02, dy: 0.5)).tap()
    }
}
