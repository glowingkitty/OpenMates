// Unit coverage for Apple interactive-question markdown parity.
// These tests keep native chat rendering aligned with the web protocol:
// valid questions become native render blocks, malformed questions show a
// visible fallback, and hidden response protocol never appears as user text.

import XCTest
@testable import OpenMates

final class InteractiveQuestionsParityTests: XCTestCase {
    func testValidChoiceQuestionParsesAsInteractiveQuestionBlock() {
        let markdown = """
        ```interactive_question
        {
          "type": "choice",
          "id": "python_slicing",
          "question": "Which expression returns every second item?",
          "options": [
            { "id": "step_2", "text": "items[::2]" }
          ]
        }
        ```
        """

        let blocks = MarkdownParser.parse(markdown)

        guard case .interactiveQuestion(let payload) = blocks.first else {
            XCTFail("Expected valid interactive question block")
            return
        }
        XCTAssertEqual(payload.id, "python_slicing")
        XCTAssertEqual(payload.type, "choice")
        XCTAssertEqual(payload.question, "Which expression returns every second item?")
        XCTAssertEqual(payload.options?.first?.text, "items[::2]")
    }

    func testInputQuestionWithoutTitleParsesAsInteractiveQuestionBlock() {
        let markdown = """
        ```interactive_question
        {
          "type": "input",
          "id": "experience",
          "fields": [
            { "id": "topic", "label": "Topic" }
          ]
        }
        ```
        """

        let blocks = MarkdownParser.parse(markdown)

        guard case .interactiveQuestion(let payload) = blocks.first else {
            XCTFail("Expected valid input question without top-level question")
            return
        }
        XCTAssertEqual(payload.id, "experience")
        XCTAssertEqual(payload.type, "input")
        XCTAssertEqual(payload.fields?.first?.label, "Topic")
    }

    func testMalformedQuestionParsesAsFallbackBlock() {
        let markdown = """
        ```interactive_question
        {
          "type": "choice",
          "id": "broken",
          "options": [
        }
        ```
        """

        let blocks = MarkdownParser.parse(markdown)

        guard case .interactiveQuestionFallback = blocks.first else {
            XCTFail("Expected malformed interactive question fallback")
            return
        }
    }

    func testInteractiveResponseProtocolParsesAsHiddenBlock() {
        let markdown = """
        items[::2]

        ```interactive_response
        {
          "id": "python_slicing",
          "selection": ["step_2"]
        }
        ```
        """

        let blocks = MarkdownParser.parse(markdown)

        XCTAssertEqual(blocks.count, 2)
        guard case .paragraph(let text) = blocks.first else {
            XCTFail("Expected visible answer paragraph")
            return
        }
        XCTAssertEqual(text, "items[::2]")
        guard case .hiddenProtocol = blocks.last else {
            XCTFail("Expected hidden protocol block")
            return
        }
    }

    @MainActor
    func testChoiceResponseFormatsAnswerTextAndHiddenProtocol() throws {
        let json = """
        {
          "type": "choice",
          "id": "python_slicing",
          "multiple": false,
          "question": "Which expression returns every second item?",
          "options": [
            { "id": "step_2", "text": "items[::2]" },
            { "id": "reverse", "text": "items[::-1]" }
          ]
        }
        """
        let payload = try JSONDecoder().decode(
            AppleInteractiveQuestionPayload.self,
            from: XCTUnwrap(json.data(using: .utf8))
        )

        let content = payload.responseContent(response: [
            "id": "python_slicing",
            "selection": ["step_2"]
        ])

        XCTAssertTrue(content.hasPrefix("items[::2]\n\n```interactive_response"))
        XCTAssertTrue(content.contains("\"id\" : \"python_slicing\""))
        XCTAssertTrue(content.contains("\"selection\" : ["))
    }

    @MainActor
    func testCustomChoiceResponseFormatsTypedAnswerTextAndHiddenProtocol() throws {
        let json = """
        {
          "type": "choice",
          "id": "project_direction",
          "multiple": false,
          "question": "What should we work on next?",
          "custom_option_id": "own_answer",
          "custom_placeholder": "Type your own answer",
          "options": [
            { "id": "ship_fix", "text": "Ship the bug fix" },
            { "id": "own_answer", "text": "I give you my own answer" }
          ]
        }
        """
        let payload = try JSONDecoder().decode(
            AppleInteractiveQuestionPayload.self,
            from: XCTUnwrap(json.data(using: .utf8))
        )

        let content = payload.responseContent(response: [
            "id": "project_direction",
            "selection": ["own_answer"],
            "custom_answer": "Let users type a custom response"
        ])

        XCTAssertTrue(content.hasPrefix("Let users type a custom response\n\n```interactive_response"))
        XCTAssertTrue(content.contains("\"custom_answer\" : \"Let users type a custom response\""))
    }
}
