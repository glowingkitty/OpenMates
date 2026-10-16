// Production interactive-question controls exercised in the isolated message host.
// Web: InteractiveQuestionContainer.svelte and renderers/ChoiceQuestion.svelte.
import XCTest

@MainActor
final class InteractiveQuestionCardParityUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    private var choiceContent: String {
        """
        ```interactive_question
        {"type":"choice","id":"golden-ratio-followup","question":"What would you like to explore?","options":[{"id":"math","text":"Explore the mathematics"},{"id":"design","text":"Explore design examples"}]}
        ```
        """
    }

    private func launchChoice(interactiveResponse: String? = nil) throws -> XCUIApplication {
        var props = ["content": choiceContent]
        if let interactiveResponse { props["interactiveResponse"] = interactiveResponse }
        let data = try JSONSerialization.data(withJSONObject: props)
        let app = XCUIApplication()
        app.launchArguments = ["--dev-preview", "message", "--dev-preview-variant", "assistant",
            "--dev-preview-width", "390", "--dev-preview-theme", "light",
            "--dev-preview-props", try XCTUnwrap(String(data: data, encoding: .utf8)),
            "-AppleLanguages", "(en)"]
        app.launch()
        return app
    }

    private func assertAnsweredChoice(_ app: XCUIApplication, selectedIndex: Int,
                                      file: StaticString = #filePath, line: UInt = #line) {
        let card = app.descendants(matching: .any).matching(identifier: "interactive-question-card").firstMatch
        XCTAssertTrue(card.waitForExistence(timeout: 10), file: file, line: line)
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "value == %@", "answered"), object: card)], timeout: 5), .completed,
                       file: file, line: line)
        let send = app.buttons["interactive-question-submit"]
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "exists == false"), object: send)], timeout: 3), .completed,
                       file: file, line: line)
        XCTAssertFalse(app.buttons["interactive-question-clear"].exists, file: file, line: line)
        let options = app.buttons.matching(identifier: "interactive-question-option")
        XCTAssertEqual(options.count, 2, file: file, line: line)
        for (index, option) in options.allElementsBoundByIndex.enumerated() {
            XCTAssertFalse(option.isEnabled, "Submitted choices must remain locked", file: file, line: line)
            XCTAssertEqual(option.isSelected, index == selectedIndex, file: file, line: line)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testSendingChoiceImmediatelyHidesFooterAndLocksSelection() throws {
        let app = try launchChoice()
        let send = app.buttons["interactive-question-submit"]
        XCTAssertTrue(send.waitForExistence(timeout: 10))
        let option = app.buttons.matching(identifier: "interactive-question-option").element(boundBy: 0)
        XCTAssertTrue(option.isHittable)
        option.tap()
        XCTAssertEqual(XCTWaiter.wait(for: [XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "enabled == true"), object: send)], timeout: 5), .completed)
        XCTAssertEqual(send.value as? String, "cta", "An enabled Send uses the production primary action state")
        send.tap()
        assertAnsweredChoice(app, selectedIndex: 0)
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshot.name = "Submitted interactive question locks choices and removes footer immediately"
        screenshot.lifetime = .keepAlways
        add(screenshot)
    }

    // Synthetic persisted-response props prove production card restoration;
    // this fixture does not claim real-account history synchronization evidence.
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testReopenedPersistedAnswerRestoresSelectionAndKeepsFooterHidden() throws {
        let app = try launchChoice(interactiveResponse:
            "{\"id\":\"golden-ratio-followup\",\"type\":\"choice\",\"selection\":[\"design\"]}")
        assertAnsweredChoice(app, selectedIndex: 1)
        app.terminate()
        app.launch()
        assertAnsweredChoice(app, selectedIndex: 1)
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshot.name = "Reopened persisted interactive answer retains locked selected choice"
        screenshot.lifetime = .keepAlways
        add(screenshot)
    }

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
