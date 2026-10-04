// Production widget content in a detached host; no account or remote writes.
import XCTest

@MainActor
final class ActiveChatsWidgetUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }
    // contract-test: direct surface=gui.apple assertions=apple-live-activities.processing.widget,apple-live-activities.lifecycle.isolation
    func testWidgetCensusWithoutLiveActivitiesKeepsRowsRoutesCompletionAndLogout() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embed-share", "--dev-active-chats-widget-fixture", "--ui-test-disable-auth-cache"]
        app.launchEnvironment["DEV_PREVIEW"] = "embed-share"
        app.launch()
        XCTAssertTrue(element("dev-preview-root", in: app).waitForExistence(timeout: 10))
        let widget = element("active-chats-widget", in: app)
        XCTAssertTrue(widget.waitForExistence(timeout: 10), app.debugDescription)
        XCTAssertEqual(widget.value as? String, "total=9;visible=3;overflow=6")
        let first = element("active-chats-widget-chat-fixture-1", in: app)
        XCTAssertTrue(first.isHittable); first.tap()
        XCTAssertEqual(app.staticTexts["active-chats-fixture-route"].label, "chat:fixture-1")
        element("active-chats-widget-view-all", in: app).tap()
        XCTAssertEqual(app.staticTexts["active-chats-fixture-route"].label, "all")
        app.buttons["active-chats-fixture-large"].tap()
        XCTAssertEqual(widget.value as? String, "total=9;visible=7;overflow=2")
        XCTAssertTrue(element("active-chats-widget-chat-fixture-7", in: app).isHittable)
        app.buttons["active-chats-fixture-complete"].tap()
        XCTAssertFalse(first.exists)
        XCTAssertEqual(widget.value as? String, "total=8;visible=7;overflow=1")
        app.buttons["active-chats-fixture-logout"].tap()
        XCTAssertEqual(widget.value as? String, "total=0;visible=0;overflow=0")
        XCTAssertFalse(element("active-chats-widget-view-all", in: app).exists)
        XCTAssertTrue(element("active-chats-widget-empty", in: app).isHittable)
    }
    // contract-test: direct surface=gui.apple assertions=apple-live-activities.processing.widget,apple-live-activities.lifecycle.isolation
    func testLockScreenAccessoryContentRoutesAndClearsAfterLogout() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embed-share", "--dev-active-chats-widget-fixture", "--ui-test-disable-auth-cache"]
        app.launchEnvironment["DEV_PREVIEW"] = "embed-share"
        app.launch()
        XCTAssertTrue(element("dev-preview-root", in: app).waitForExistence(timeout: 10))
        let widget = element("active-chats-widget", in: app)
        XCTAssertTrue(widget.waitForExistence(timeout: 10), app.debugDescription)
        app.buttons["active-chats-fixture-circular"].tap()
        XCTAssertEqual(widget.value as? String, "total=9;visible=0;overflow=9")
        let circular = element("active-chats-widget-circular", in: app)
        XCTAssertTrue(circular.isHittable); circular.tap()
        XCTAssertEqual(app.staticTexts["active-chats-fixture-route"].label, "all")
        app.buttons["active-chats-fixture-rectangular"].tap()
        XCTAssertEqual(widget.value as? String, "total=9;visible=1;overflow=8")
        let first = element("active-chats-widget-chat-fixture-1", in: app)
        XCTAssertTrue(first.isHittable); first.tap()
        XCTAssertEqual(app.staticTexts["active-chats-fixture-route"].label, "chat:fixture-1")
        element("active-chats-widget-view-all", in: app).tap()
        XCTAssertEqual(app.staticTexts["active-chats-fixture-route"].label, "all")
        app.buttons["active-chats-fixture-complete"].tap()
        XCTAssertFalse(first.exists)
        XCTAssertEqual(widget.value as? String, "total=8;visible=1;overflow=7")
        XCTAssertTrue(element("active-chats-widget-chat-fixture-2", in: app).isHittable)
        app.buttons["active-chats-fixture-logout"].tap()
        XCTAssertEqual(widget.value as? String, "total=0;visible=0;overflow=0")
        XCTAssertFalse(element("active-chats-widget-view-all", in: app).exists)
        XCTAssertTrue(element("active-chats-widget-empty", in: app).isHittable)
        app.buttons["active-chats-fixture-circular"].tap()
        XCTAssertTrue(element("active-chats-widget-circular", in: app).isHittable)
        element("active-chats-widget-circular", in: app).tap()
        XCTAssertEqual(app.staticTexts["active-chats-fixture-route"].label, "app")
    }
    private func element(_ id: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: id).firstMatch
    }
}
