// Native selection and the production annotation/Fork settings controls.
// Synthetic fixtures use local encrypted transports and never contact accounts.
import XCTest

@MainActor
final class MessageSelectionParityUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.inline-entity-interaction,chats.persistence.client-encrypted
    func testNativeSubstringSelectionHighlightsAndSavesComment() {
        let app = launch("selected-text")
        selectNativeWord(in: app)
        let selected = app.staticTexts["selection-fixture-selected"].label
        XCTAssertFalse(app.staticTexts["selection-fixture-context"].exists, "Touch selection must keep range handles available")
        XCTAssertFalse(selected.isEmpty)
        XCTAssertFalse(selected.contains("Select part of this sentence."), "Selection must use a substring")
        let action = app.buttons["message-selection-highlight-and-comment"]
        XCTAssertTrue(action.waitForExistence(timeout: 5)); XCTAssertTrue(action.isHittable)
        action.tap()
        let input = app.descendants(matching: .any)["message-highlight-comment-input"].firstMatch
        XCTAssertTrue(input.waitForExistence(timeout: 5)); XCTAssertTrue(input.isHittable)
        input.tap(); input.typeText("Synthetic comment")
        let save = app.buttons["message-highlight-comment-save"]
        XCTAssertTrue(save.isHittable); save.tap()
        let receipt = app.staticTexts["selection-fixture-transport"]
        XCTAssertTrue(NSPredicate(format: "label == %@", "update_message_highlight:encrypted").evaluate(with: receipt)
            || XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "update_message_highlight:encrypted"), object: receipt)], timeout: 5) == .completed)
        screenshot("Native substring highlight and encrypted comment")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.inline-entity-interaction
    func testExplainUsesOnlySelectedTextAndUserSelectionOmitsExplain() {
        let app = launch("selected-text")
        selectNativeWord(in: app)
        let selected = app.staticTexts["selection-fixture-selected"].label
        let explain = app.buttons["message-selection-explain-new-chat"]
        XCTAssertTrue(explain.waitForExistence(timeout: 5)); XCTAssertTrue(explain.isHittable)
        explain.tap()
        XCTAssertEqual(app.staticTexts["selection-fixture-route"].label, "Tell me more about: " + selected)
        app.terminate()
        let userApp = launch("selected-text-user")
        selectNativeWord(in: userApp)
        XCTAssertTrue(userApp.buttons["message-selection-highlight"].waitForExistence(timeout: 5))
        XCTAssertFalse(userApp.buttons["message-selection-explain-new-chat"].exists)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.inline-entity-interaction
    func testForkOpensSharedSettingsWithTitleCountAndEditableName() {
        let app = launch("fork-settings")
        let name = app.textFields["message-fork-name"]
        XCTAssertTrue(name.waitForExistence(timeout: 10)); XCTAssertTrue(name.isHittable)
        XCTAssertEqual(name.value as? String, "Synthetic source")
        let count = app.descendants(matching: .any)["message-fork-count"].firstMatch
        XCTAssertTrue(count.exists)
        screenshot("Shared Fork settings rendered message count")
        let hierarchy = XCTAttachment(string: app.debugDescription)
        hierarchy.name = "Shared Fork settings accessibility hierarchy"
        hierarchy.lifetime = .keepAlways; add(hierarchy)
        XCTAssertEqual(count.value as? String, "3", "The rendered Fork message count must exactly match the source boundary")
        name.tap(); name.typeText(" copy")
        let fork = app.buttons["message-fork-confirm"]
        XCTAssertTrue(fork.isHittable); XCTAssertTrue(fork.isEnabled)
        screenshot("Shared Fork settings title and message count")
        fork.tap()
        let receipt = app.staticTexts["message-fork-fixture-receipt"]
        let finished = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "Synthetic source copy"), object: receipt)
        XCTAssertEqual(XCTWaiter.wait(for: [finished], timeout: 5), .completed)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.inline-entity-interaction
    func testReadOnlySelectionCanCopyWithoutAnnotationActions() {
        let app = launch("selected-text-readonly")
        selectNativeWord(in: app)
        let selected = app.staticTexts["selection-fixture-selected"].label
        let copy = app.buttons["message-selection-copy"]
        XCTAssertTrue(copy.waitForExistence(timeout: 5)); XCTAssertTrue(copy.isHittable)
        XCTAssertFalse(app.buttons["message-selection-highlight"].exists)
        XCTAssertFalse(app.buttons["message-selection-explain-new-chat"].exists)
        copy.tap()
        XCTAssertEqual(app.staticTexts["selection-fixture-route"].label, selected)
        let more = app.buttons["message-selection-more"]
        XCTAssertTrue(more.isHittable); more.tap()
        XCTAssertTrue(app.staticTexts["selection-fixture-context"].waitForExistence(timeout: 5))
        screenshot("Read-only native selection Copy remains available")
    }

    private func selectNativeWord(in app: XCUIApplication) {
        let text = app.textViews.matching(NSPredicate(format: "label CONTAINS %@", "Svelte runes make state explicit")).firstMatch
        XCTAssertTrue(text.waitForExistence(timeout: 10)); XCTAssertTrue(text.isHittable)
        // Double-tap uses UIKit's word-selection gesture. A long press can
        // propose a paragraph-wide edit menu, which is a separate platform path.
        text.coordinate(withNormalizedOffset: CGVector(dx: 0.08, dy: 0.2)).doubleTap()
        XCTAssertTrue(app.staticTexts["selection-fixture-selected"].waitForExistence(timeout: 5))
        let selected = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label.length > 0"), object: app.staticTexts["selection-fixture-selected"])
        XCTAssertEqual(XCTWaiter.wait(for: [selected], timeout: 5), .completed)
    }

    private func launch(_ variant: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "message", "--dev-preview-variant", variant, "--dev-preview-width", "390",
            "-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        return app
    }

    private func screenshot(_ name: String) {
        let artifact = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        artifact.name = name; artifact.lifetime = .keepAlways; add(artifact)
    }
}
