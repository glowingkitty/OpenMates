// Production interactive-question controls exercised in the isolated message host.
// Web: InteractiveQuestionContainer.svelte and renderers/ChoiceQuestion.svelte.
import XCTest

@MainActor
final class InteractiveQuestionCardParityUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testChoiceSelectionEnablesSendAndClearResetsSelectionWithVisibleActionBadge() throws {
        let content = """
        ```interactive_question
        {"type":"choice","id":"golden-ratio-followup","question":"What would you like to explore?","options":[{"id":"math","text":"Explore the mathematics"},{"id":"design","text":"Explore design examples"}]}
        ```

        [Follow the next step](/#message=Explain%20the%20golden%20ratio)
        """
        let props = try JSONSerialization.data(withJSONObject: ["content": content])
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "message", "--dev-preview-variant", "assistant",
            "--dev-preview-width", "390", "--dev-preview-theme", "light",
            "--dev-preview-props", try XCTUnwrap(String(data: props, encoding: .utf8)),
            "-AppleLanguages", "(en)"]
        app.launch()

        let send = app.buttons["interactive-question-submit"]
        XCTAssertTrue(send.waitForExistence(timeout: 10))
        XCTAssertFalse(send.isEnabled, "A choice must be selected before sending")
        let option = app.buttons["interactive-question-option"].firstMatch
        XCTAssertTrue(option.isHittable)
        option.tap()
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "enabled == true"), object: send)], timeout: 5), .completed)
        XCTAssertTrue(option.isSelected, "The selected choice must expose its actual selected state")

        let clear = app.buttons["interactive-question-clear"]
        XCTAssertTrue(clear.exists && clear.isHittable)
        XCTAssertGreaterThan(clear.frame.minX, option.frame.minX, "Footer controls align to the card's right edge")
        clear.tap()
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "enabled == false"), object: send)], timeout: 5), .completed)
        XCTAssertFalse(option.isSelected, "Clear must reset the choice indicator")

        let link = app.buttons["Follow the next step"]
        XCTAssertTrue(link.waitForExistence(timeout: 5))
        XCTAssertEqual(link.value as? String, "ai", "The badge must use the glyph asset instead of the opaque branded square")
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshot.name = "Interactive question cleared and visible AI follow-up badge"
        screenshot.lifetime = .keepAlways
        add(screenshot)
    }
}
