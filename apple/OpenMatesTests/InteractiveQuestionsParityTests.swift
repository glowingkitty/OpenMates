// Unit coverage for Apple interactive-question markdown parity.
// These tests keep native chat rendering aligned with the web protocol:
// valid questions become native render blocks, malformed questions show a
// visible fallback, and hidden response protocol never appears as user text.

import XCTest
@testable import OpenMates

final class InteractiveQuestionsParityTests: XCTestCase {
    private func historyMessage(_ id: String, role: MessageRole, content: String?) -> Message {
        Message(id: id, chatId: "synthetic-chat", role: role, content: content,
                encryptedContent: nil, createdAt: "2026-01-01T00:00:00Z", updatedAt: nil,
                appId: nil, isStreaming: false, embedRefs: nil, piiMappings: nil)
    }

    private func question(_ id: String = "followup") -> String {
        """
        ```interactive_question
        {"type":"choice","id":"\(id)","question":"Choose the next step","options":[{"id":"math","text":"Mathematics"},{"id":"design","text":"Design"}]}
        ```
        """
    }

    private func response(_ selection: String, id: String = "followup") -> String {
        """
        ```interactive_response
        {"id":"\(id)","selection":["\(selection)"]}
        ```
        """
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testAnswerHistoryLocksOnlyTheQuestionBeforeItsSubsequentUserResponse() {
        let prompt = historyMessage("question", role: .assistant, content: question())
        let answer = historyMessage("answer", role: .user, content: response("math"))
        XCTAssertNil(AppleInteractiveQuestionHistory.answers(in: [answer, prompt])["followup"],
                     "An earlier answer cannot lock a later question with the same ID")
        XCTAssertEqual(AppleInteractiveQuestionHistory.answers(in: [prompt, answer])["followup"]?.selection, ["math"])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testAnswerHistoryIgnoresResponsesAndQuestionsFromTheWrongRole() {
        let prompt = historyMessage("question", role: .assistant, content: question())
        for role in [MessageRole.assistant, .system] {
            let foreign = historyMessage("wrong-role", role: role, content: response("design"))
            XCTAssertNil(AppleInteractiveQuestionHistory.answers(in: [prompt, foreign])["followup"])
        }
        let answer = historyMessage("answer", role: .user, content: response("math"))
        let userQuotedQuestion = historyMessage("quoted-question", role: .user, content: question())
        XCTAssertEqual(AppleInteractiveQuestionHistory.answers(in: [prompt, answer, userQuotedQuestion])["followup"]?.selection,
                       ["math"], "A user quoting a question cannot reset the assistant's answered state")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testAnswerHistoryIgnoresMalformedAndEmptyResponsesWithoutErasingAnAnswer() {
        let valid = historyMessage("answer", role: .user, content: response("math"))
        let malformed = [
            "```interactive_response\n{\"id\":\"followup\",\"selection\":[\n```",
            "```interactive_response\n{\"selection\":[\"design\"]}\n```",
            "```interactive_response\n{\"id\":\"\",\"selection\":[\"design\"]}\n```",
            "```interactive_response\n{\"id\":\"followup\",\"selection\":\"design\"}\n```"
        ]
        for (index, content) in malformed.enumerated() {
            let invalid = historyMessage("invalid-\(index)", role: .user, content: content)
            XCTAssertTrue(AppleInteractiveQuestionHistory.answers(in: [invalid]).isEmpty)
            XCTAssertEqual(AppleInteractiveQuestionHistory.answers(in: [valid, invalid])["followup"]?.selection, ["math"])
        }
        let noContent = historyMessage("no-content", role: .user, content: nil)
        XCTAssertTrue(AppleInteractiveQuestionHistory.answers(in: [noContent]).isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testReusedQuestionIDStartsANewAnswerLifecycleAndKeepsOtherQuestionsAnswered() {
        let history = [
            historyMessage("question-1", role: .assistant, content: question()),
            historyMessage("answer-1", role: .user, content: response("math")),
            historyMessage("other-answer", role: .user, content: response("design", id: "other")),
            historyMessage("question-2", role: .assistant, content: question())
        ]
        let reopened = AppleInteractiveQuestionHistory.answers(in: history)
        XCTAssertNil(reopened["followup"])
        XCTAssertEqual(reopened["other"]?.selection, ["design"])
        let nextAnswer = historyMessage("answer-2", role: .user, content: response("design"))
        XCTAssertEqual(AppleInteractiveQuestionHistory.answers(in: history + [nextAnswer])["followup"]?.selection, ["design"])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testAnswerHistoryUsesTheLastValidResponseIncludingMultipleFencesInOneMessage() {
        let prompt = historyMessage("question", role: .assistant, content: question())
        let combined = historyMessage("answers", role: .user,
                                      content: response("math") + "\n\n" + response("design"))
        XCTAssertEqual(AppleInteractiveQuestionHistory.answers(in: [prompt, combined])["followup"]?.selection, ["design"])
        let malformedQuestion = historyMessage("bad-question", role: .assistant,
                                              content: "```interactive_question\n{\"id\":\"followup\"\n```")
        XCTAssertEqual(AppleInteractiveQuestionHistory.answers(in: [prompt, combined, malformedQuestion])["followup"]?.selection,
                       ["design"], "A malformed question cannot erase a valid submitted answer")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
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

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testChoiceQuestionParsesEmbedReferences() throws {
        let markdown = """
        ```interactive_question
        {
          "type": "choice",
          "id": "choose_snippet",
          "question": "Which implementation should we use?",
          "options": [
            { "id": "minimal", "text": "Minimal implementation", "embed_ids": ["embed-code-a"] }
          ]
        }
        ```
        """

        let blocks = MarkdownParser.parse(markdown)

        guard case .interactiveQuestion(let payload) = blocks.first else {
            XCTFail("Expected valid embed-backed interactive question block")
            return
        }
        XCTAssertEqual(payload.options?.first?.embedIds, ["embed-code-a"])
    }

    @MainActor
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testChoiceResponseIncludesSelectedEmbedReferences() throws {
        let json = """
        {
          "type": "choice",
          "id": "choose_snippet",
          "multiple": false,
          "question": "Which implementation should we use?",
          "options": [
            { "id": "minimal", "text": "Minimal implementation", "embed_ids": ["embed-code-a"] },
            { "id": "robust", "text": "More robust implementation", "embed_ids": ["embed-code-b"] }
          ]
        }
        """
        let payload = try JSONDecoder().decode(
            AppleInteractiveQuestionPayload.self,
            from: XCTUnwrap(json.data(using: .utf8))
        )

        let content = payload.responseContent(response: [
            "id": "choose_snippet",
            "selection": ["robust"]
        ])

        XCTAssertTrue(content.contains("\"embed_ids\" : ["))
        XCTAssertTrue(content.contains("\"embed-code-b\""))
        XCTAssertFalse(content.contains("function robustImplementation"))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
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

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
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

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
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
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
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
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
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

// Action links in assistant follow-ups must remain tappable inline links,
// including encoded question punctuation and non-Latin prompt content.
final class AssistantFollowUpLinkParityTests: XCTestCase {
    @MainActor
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testMessageActionLinksPreserveTheirPromptAndVisibleLabel() throws {
        let links = [
            ("Explain the golden ratio", "/#message=Explain%20the%20golden%20ratio%3F", "Explain the golden ratio?"),
            ("Show a visual example", "/#message=Show%20a%20visual%20example%20of%20%CF%86", "Show a visual example of φ"),
            ("Explore architecture", "/#message=Explore%20architecture%20%26%20design", "Explore architecture & design")
        ]
        let markdown = links.map { "[\($0.0)](\($0.1))" }.joined(separator: "\n")
        let tokens = InlineMarkdownTokenizer.parse(markdown)
        let parsed = tokens.compactMap { token -> (String, String, Bool)? in
            guard case .link(let label, let url, let internalLink, _, _) = token else { return nil }
            return (label, url, internalLink)
        }
        XCTAssertEqual(parsed.count, links.count)
        for (actual, expected) in zip(parsed, links) {
            XCTAssertEqual(actual.0, expected.0)
            // The tokenizer decodes its target once; compare against explicit
            // prompt text, then exercise the production draft-import handler.
            XCTAssertEqual(actual.1, "/#message=\(expected.2)")
            XCTAssertTrue(actual.2)
            let fragment = String(actual.1.dropFirst(2))
            let url = try XCTUnwrap(URL(string:
                "https://\(ServerConfiguration.current.selectedDomain)/#\(fragment)"))
            let handler = DeepLinkHandler()
            handler.handle(url: url)
            XCTAssertEqual(handler.pendingMessageText, expected.2,
                "Action-link prompts must retain punctuation, Unicode and ampersands when imported")
        }
    }
}
