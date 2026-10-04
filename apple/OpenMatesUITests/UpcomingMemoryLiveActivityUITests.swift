// Detached production Button(intent:) controls, intent and coordinator effects.
// This proves GUI navigation; real Lock Screen/OS presentation remains separate.
import XCTest

@MainActor
final class UpcomingMemoryLiveActivityUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }
    // contract-test: direct surface=gui.apple assertions=apple-live-activities.memories.upcoming,apple-live-activities.lifecycle.isolation
    func testTypedSavedMemoriesNavigateThroughRealIntentsRemoveAndExposeOverflowWithoutPrivateText() {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "embed-share", "--dev-upcoming-memory-live-activity-fixture", "--ui-test-disable-auth-cache"]
        app.launchEnvironment["DEV_PREVIEW"] = "embed-share"
        app.launch()
        let navigation = app.descendants(matching: .any).matching(identifier: "upcoming-live-activity-navigation").firstMatch
        XCTAssertTrue(navigation.waitForExistence(timeout: 10), app.debugDescription)
        assertValue("total=3;pages=3;selected=1", element: navigation)
        let next = app.buttons["upcoming-live-activity-next"], previous = app.buttons["upcoming-live-activity-previous"]
        XCTAssertTrue(next.isHittable)
        XCTAssertTrue(previous.isHittable)
        next.tap()
        assertValue("total=3;pages=3;selected=2", element: navigation)
        previous.tap()
        assertValue("total=3;pages=3;selected=1", element: navigation)
        previous.tap()
        assertValue("total=3;pages=3;selected=3", element: navigation)
        app.buttons["upcoming-live-fixture-remove"].tap()
        assertValue("total=2;pages=2;selected=2", element: navigation)
        next.tap()
        assertValue("total=2;pages=2;selected=1", element: navigation)
        app.buttons["upcoming-live-fixture-overflow"].tap()
        assertValue("total=30;pages=24;selected=2", element: navigation)
        let viewAll = app.descendants(matching: .any).matching(identifier: "upcoming-live-activity-view-all").firstMatch
        XCTAssertTrue(viewAll.isHittable); viewAll.tap()
        XCTAssertEqual(app.staticTexts["upcoming-live-fixture-route"].label, "memories")
        XCTAssertFalse(app.staticTexts["Private fixture medical title"].exists)
        XCTAssertFalse(app.staticTexts["Private fixture medical notes"].exists)
        XCTAssertFalse(app.staticTexts["Private fixture memory body"].exists)
        app.buttons["upcoming-live-fixture-switch-owner"].tap()
        next.tap()
        assertValue("total=30;pages=24;selected=2", element: navigation)
    }
    private func assertValue(_ value: String, element: XCUIElement, file: StaticString = #filePath, line: UInt = #line) {
        let predicate = NSPredicate(format: "value == %@", value)
        let result = XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: predicate, object: element)], timeout: 5)
        XCTAssertEqual(result, .completed, file: file, line: line)
    }
}
