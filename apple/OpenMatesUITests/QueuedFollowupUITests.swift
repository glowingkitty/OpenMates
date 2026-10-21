// Production queue controls/composer flow using disposable Debug-only receipts.
// No account, inference, server mutation or production queue is involved.
import XCTest

@MainActor
final class QueuedFollowupUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
        #if os(iOS)
        XCUIDevice.shared.orientation = .portrait
        #endif
    }
    // contract-test: supporting surface=gui.apple assertions=chat-queued-followups.editing.cancel
    func testCancelQueuedEditRestoresOwnedPreviousDraft() {
        let app = launchFixture()
        let editor = app.textViews["message-editor"].firstMatch
        editor.tap(); editor.typeText("Previous unsent draft")
        let save = app.buttons["chat-composer-cancel"].firstMatch
        if save.isHittable { save.tap() }
        let edit = app.buttons["queued-followup-edit"].firstMatch
        XCTAssertTrue(edit.waitForExistence(timeout: 5)); edit.tap()
        XCTAssertEqual(editor.value as? String, "Synthetic queued follow-up")
        app.buttons["queued-followup-cancel-edit"].tap()
        XCTAssertEqual(editor.value as? String, "Previous unsent draft")
        XCTAssertFalse(app.buttons["queued-followup-cancel-edit"].exists)
        assertReceipt(app, contains: "mutations=0")
    }
    // contract-test: supporting surface=gui.apple assertions=chat-queued-followups.editing.stable-revision
    func testUnchangedQueuedEditDoesNotCreateARevisionOrAnotherMessage() {
        let app = launchFixture()
        app.buttons["queued-followup-edit"].firstMatch.tap()
        app.buttons["send-button"].tap()
        let cancelled = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: app.buttons["queued-followup-cancel-edit"])
        XCTAssertEqual(XCTWaiter.wait(for: [cancelled], timeout: 8), .completed)
        assertReceipt(app, contains: "mutations=0;revision=1;mode=follow_up;rows=1")
    }
    // contract-test: supporting surface=gui.apple assertions=chat-queued-followups.editing.stable-revision
    func testChangedQueuedEditUpdatesTheSameRowOnce() {
        let app = launchFixture()
        app.buttons["queued-followup-edit"].firstMatch.tap()
        let editor = app.textViews["message-editor"].firstMatch
        editor.tap(); editor.typeText(" revised")
        app.buttons["send-button"].tap()
        assertReceipt(app, contains: "mutations=1;revision=2;mode=follow_up;rows=1")
        XCTAssertFalse(app.buttons["queued-followup-cancel-edit"].exists)
    }
    // contract-test: supporting surface=gui.apple assertions=chat-queued-followups.editing.stable-revision
    func testRejectedQueuedEditKeepsLocalInputAndServerRevision() {
        let app = launchFixture(conflict: true)
        app.buttons["queued-followup-edit"].firstMatch.tap()
        let editor = app.textViews["message-editor"].firstMatch
        editor.tap(); editor.typeText(" local edit")
        let submitted = editor.value as? String
        app.buttons["send-button"].tap()
        let outcome = app.descendants(matching: .any)["queued-followup-fixture-outcome"].firstMatch
        let rejected = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "conflict"), object: outcome)
        XCTAssertEqual(XCTWaiter.wait(for: [rejected], timeout: 8), .completed)
        XCTAssertEqual(editor.value as? String, submitted)
        XCTAssertTrue(app.buttons["queued-followup-cancel-edit"].exists)
        assertReceipt(app, contains: "mutations=0;revision=1;mode=follow_up;rows=1")
    }
    // contract-test: supporting surface=gui.apple assertions=chat-queued-followups.steering.safe-boundary
    func testSteerUsesTheSameQueuedIdentityAndShowsAcceptedIntent() {
        let app = launchFixture()
        app.buttons["queued-followup-steer"].firstMatch.tap()
        assertReceipt(app, contains: "mutations=1;revision=2;mode=steer;rows=1")
        XCTAssertFalse(app.buttons["queued-followup-steer"].exists)
        XCTAssertTrue(app.buttons["queued-followup-edit"].exists)
    }
    private func launchFixture(conflict: Bool = false) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "chat-opening", "--ui-test-composer-send", "accepted", "--ui-test-queued-followups"]
        if conflict { app.launchArguments.append("--ui-test-queued-conflict") }
        app.launchEnvironment["DEV_PREVIEW"] = "chat-opening"
        app.launch()
        XCTAssertTrue(app.textViews["message-editor"].firstMatch.waitForExistence(timeout: 12))
        XCTAssertTrue(app.buttons["queued-followup-edit"].firstMatch.waitForExistence(timeout: 5))
        return app
    }
    private func assertReceipt(_ app: XCUIApplication, contains value: String) {
        let outcome = app.descendants(matching: .any)["queued-followup-fixture-outcome"].firstMatch
        let matches = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value CONTAINS %@", value), object: outcome)
        XCTAssertEqual(XCTWaiter.wait(for: [matches], timeout: 8), .completed)
    }
}
