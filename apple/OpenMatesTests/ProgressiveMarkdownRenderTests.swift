// Synthetic cumulative snapshots exercise the same parser and semantic document
// used by production history, without network/account fixtures or timing budgets.
import XCTest
@testable import OpenMates

@MainActor
final class ProgressiveMarkdownRenderTests: XCTestCase {
    private let identity = ProgressiveMarkdownIdentity(scopeID: "scope-A", chatID: "chat-A", messageID: "message-A")
    private func request(_ content: String, streaming: Bool = true, sequence: Int? = nil) -> ProgressiveMarkdownRequest {
        .init(identity: identity, content: content, isStreaming: streaming, sequence: sequence)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testFadePolicyMatchesWebAndNeverAnimatesRestoredOrReducedMotionContent() {
        XCTAssertEqual(ProgressiveMarkdownAnimationPolicy.duration, 0.22)
        XCTAssertEqual(ProgressiveMarkdownAnimationPolicy.initialOpacity, 0.5)
        XCTAssertTrue(ProgressiveMarkdownAnimationPolicy.animates(isStreaming: true, reduceMotion: false))
        XCTAssertFalse(ProgressiveMarkdownAnimationPolicy.animates(isStreaming: true, reduceMotion: true))
        XCTAssertFalse(ProgressiveMarkdownAnimationPolicy.animates(isStreaming: false, reduceMotion: false))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testCompletedParagraphPrefixReusesIdentityAndBoundsParsedWork() {
        var projection = ProgressiveMarkdownRenderProjection()
        var content = "First stable paragraph."
        projection.update(request(content))
        let firstID = projection.blocks[0].id
        let firstDocument = projection.blocks[0].document
        var maximumTail = 0
        for index in 1...180 {
            content += "\n\nParagraph \(index) is rendered before the response ends."
            projection.update(request(content))
            maximumTail = max(maximumTail, projection.lastParsedUTF8)
            XCTAssertEqual(projection.blocks[0].id, firstID)
            XCTAssertEqual(projection.blocks[0].document, firstDocument)
            XCTAssertEqual(projection.blocks.count, index + 1)
            XCTAssertTrue(projection.isStreaming)
            XCTAssertEqual(projection.fadeBlockID, projection.blocks.last?.id)
        }
        XCTAssertLessThan(maximumTail, 140, "Only the previous open paragraph plus the new paragraph is parsed")
        XCTAssertLessThan(projection.parsedUTF8, content.utf8.count * 3)
        let ids = projection.blocks.map(\.id)
        let revision = projection.fadeRevision
        projection.update(request(content, streaming: false))
        XCTAssertEqual(projection.blocks.map(\.id), ids)
        XCTAssertEqual(projection.fadeRevision, revision)
        XCTAssertNil(projection.fadeBlockID)
        XCTAssertEqual(projection.blocks.compactMap(\.markdown), MarkdownParser.parse(content))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testEveryCharacterConvergesForListsTablesFencesQuotesAndIncompleteHeading() {
        let fixtures = [
            "# Heading\n\nPlain text\n\n- First\n- Second\n\nAfter",
            "| Place | Choice |\n| --- | --- |\n| Berlin | Food |\n| Osaka | Tea |\n\nEnd",
            "Before\n\n```swift\nlet answer = 42\n\nprint(answer)\n```\n\nAfter",
            "> First quote\n> Second quote\n\n[Source](embed:source-1)",
            "#\n\n#not-a-header\n\n## Actual header\n\nUnicode café 🧭 is intact.",
            "1. One\n2. Two\n\n***\n\n[[embed:a]]\n\n[[embed:b]]\n\nAfter"
        ]
        for source in fixtures {
            var projection = ProgressiveMarkdownRenderProjection()
            var prefix = ""
            for character in source {
                prefix.append(character)
                projection.update(request(prefix))
                XCTAssertEqual(projection.blocks.compactMap(\.markdown),
                               MarkdownParser.parseSpans(prefix, isStreaming: true).map(\.block),
                               "Incremental grammar must equal a canonical parse at every boundary")
            }
            projection.update(request(source, streaming: false))
            XCTAssertEqual(projection.blocks.compactMap(\.markdown), MarkdownParser.parse(source))
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testAuthoritativeCorrectionKeepsUnaffectedSuffixAndDuplicateOccurrencesDistinct() {
        var projection = ProgressiveMarkdownRenderProjection()
        projection.update(request("First.\n\nRepeated.\n\nRepeated.\n\nLast."))
        let old = projection.blocks
        projection.update(request("First corrected.\n\nInserted.\n\nRepeated.\n\nRepeated.\n\nLast."))
        XCTAssertEqual(projection.blocks.suffix(3).map(\.id), old.suffix(3).map(\.id))
        XCTAssertEqual(Set(projection.blocks.map(\.id)).count, projection.blocks.count)
        XCTAssertEqual(projection.blocks.compactMap(\.markdown), MarkdownParser.parse(projection.source))
        projection.update(request("First corrected.\n\nLast."))
        XCTAssertEqual(projection.blocks.last?.id, old.last?.id)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testDuplicateOutOfOrderAndTerminalSnapshotsDoNotReplayAnimations() {
        var projection = ProgressiveMarkdownRenderProjection()
        projection.update(request("First paragraph.", sequence: 8))
        let count = projection.parseCount
        let revision = projection.fadeRevision
        XCTAssertFalse(projection.update(request("stale", sequence: 7)))
        XCTAssertFalse(projection.update(request("duplicate", sequence: 8)))
        XCTAssertEqual(projection.parseCount, count)
        XCTAssertEqual(projection.fadeRevision, revision)
        // The production lifecycle deliberately accepts terminal snapshots even
        // when their sequence is absent/zero. The terminal source is authoritative.
        XCTAssertTrue(projection.update(request("First paragraph.\n\nFinal.", streaming: false, sequence: 0)))
        let final = projection.blocks
        XCTAssertFalse(projection.update(request("late stream", sequence: 99)))
        XCTAssertFalse(projection.update(request("First paragraph.\n\nFinal.", streaming: false)))
        XCTAssertEqual(projection.blocks, final)
        XCTAssertNil(projection.fadeBlockID)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testInternalProtocolStaysHiddenUntilCanonicalFinalWithoutRemountingPrefix() {
        var projection = ProgressiveMarkdownRenderProjection()
        let prefix = "Visible introduction.\n\n"
        projection.update(request(prefix))
        let firstID = projection.blocks[0].id
        let fence = "```json\n{\"type\":\"app_skill_use\",\"embed_id\":\"source-1\"}\n```"
        projection.update(request(prefix + fence))
        XCTAssertEqual(projection.blocks.last?.document.kind, .hiddenProtocol)
        XCTAssertEqual(projection.blocks[0].id, firstID)
        projection.update(request(prefix + fence, streaming: false))
        XCTAssertEqual(projection.blocks[0].id, firstID)
        XCTAssertEqual(projection.blocks.last?.document.kind, .embedGroup)
        XCTAssertEqual(projection.blocks.compactMap(\.markdown), MarkdownParser.parse(prefix + fence))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testCitationBecomesInteractiveOnlyWhenItsTargetIsComplete() {
        let partial = "See [Berlin guide](embed:source-1"
        XCTAssertFalse(InlineMarkdownTokenizer.parse(partial).contains { token in
            if case .embed = token { return true }; return false
        })
        let complete = partial + ")."
        XCTAssertTrue(InlineMarkdownTokenizer.parse(complete).contains { token in
            if case .embed(_, let id, _) = token { return id == "source-1" }; return false
        })
        var projection = ProgressiveMarkdownRenderProjection()
        projection.update(request("Stable paragraph.\n\n" + partial))
        let ids = projection.blocks.map(\.id)
        projection.update(request("Stable paragraph.\n\n" + complete))
        XCTAssertEqual(projection.blocks.map(\.id), ids)
        XCTAssertEqual(projection.blocks.last?.document.inlineEntities.first?.target, "source-1")
        let count = projection.parseCount
        var hydrated = request(projection.source)
        hydrated.embedRefs = [EmbedRef(id: "source-1", type: "website", status: "finished", data: nil)]
        projection.update(hydrated)
        XCTAssertEqual(projection.parseCount, count, "Hydration changes resolution, not Markdown syntax")
        XCTAssertEqual(projection.blocks.map(\.id), ids)
        XCTAssertNil(projection.fadeBlockID)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testColdHistoryUsesCanonicalDocumentWithoutParsingOrFadeAndScopeChangeClearsState() throws {
        let source = "Stored paragraph.\n\n- One\n- Two"
        let message = Message(id: identity.messageID, chatId: identity.chatID, role: .assistant,
            content: source, encryptedContent: nil, createdAt: "2026-01-01T00:00:00Z", updatedAt: nil,
            appId: "code", isStreaming: false, embedRefs: nil)
        let document = try XCTUnwrap(ChatHistoryRenderDocument.build(for: message))
        var projection = ProgressiveMarkdownRenderProjection()
        var restored = request(source, streaming: false)
        restored.renderDocument = document
        projection.update(restored)
        XCTAssertEqual(projection.blocks.map(\.document), document.blocks)
        XCTAssertEqual(projection.parseCount, 0)
        XCTAssertEqual(projection.fadeRevision, 0)
        XCTAssertNil(projection.fadeBlockID)
        projection.update(.init(identity: .init(scopeID: "scope-B", chatID: "chat-B", messageID: "message-B"),
            content: "Other account.", isStreaming: true, sequence: 1))
        XCTAssertEqual(projection.source, "Other account.")
        XCTAssertEqual(projection.blocks.map(\.id), ["message-B:block:0"])
        XCTAssertEqual(projection.parseCount, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testLongParagraphKeepsReferencesAndMountedInlinePreparationDoesNoWorkForUnchangedSource() {
        let content = String(repeating: "An ordinary sentence with several words. ", count: 300)
            + "[Berlin guide](embed:source-1)."
        XCTAssertGreaterThan(content.count, 3_000)
        let input = InlineMarkdownPreparationInput(content: content, searchHighlightQuery: nil)
        let preparation = InlineMarkdownPreparationModel(input: input)
        XCTAssertTrue(preparation.value.customLayout)
        XCTAssertTrue(preparation.value.tokens.contains { token in
            if case .embed(_, let id, _) = token { return id == "source-1" }; return false
        })
        for _ in 0..<200 { preparation.update(input) }
        XCTAssertEqual(preparation.parseCount, 1)
        XCTAssertEqual(preparation.parsedUTF8, content.utf8.count)
        preparation.update(.init(content: content + " More text.", searchHighlightQuery: nil))
        XCTAssertEqual(preparation.parseCount, 2)
        XCTAssertEqual(preparation.parsedUTF8, content.utf8.count * 2 + " More text.".utf8.count)
    }

    // contract-test: direct surface=gui.apple assertions=chats.rendering.assistant-document-convergence,chats.surface.semantic-parity
    func testTeXFormulasBecomeSemanticMathTokensWithoutTreatingCurrencyAsMath() {
        let source = "Payment is $2,199 and energy is $E = mc^2$.\n\n$$\\frac{a}{b} \\times \\pi r^2$$"
        let tokens = InlineMarkdownTokenizer.parse(source)

        XCTAssertTrue(tokens.contains(.math("E = mc^2", display: false)))
        XCTAssertTrue(tokens.contains(.math("\\frac{a}{b} \\times \\pi r^2", display: true)))
        XCTAssertTrue(tokens.map(\.searchText).joined().contains("$2,199"))
        let renderedFormula = MarkdownMathParser.displayText(for: #"\frac{a}{b} \times \pi r^2"#)
        XCTAssertEqual(renderedFormula, "(a)⁄(b) × π r²")
        XCTAssertFalse(renderedFormula.contains("$"))
        XCTAssertFalse(renderedFormula.contains("\\frac"))
        XCTAssertFalse(renderedFormula.contains("\\times"))
        XCTAssertEqual(MarkdownMathParser.singleDisplayFormula(in: "  $$\\sqrt{x_2}$$  "), "\\sqrt{x_2}")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence,chats.surface.semantic-parity
    func testStreamingFormulaProjectionConvergesWithoutChangingStablePrefixIdentity() {
        var projection = ProgressiveMarkdownRenderProjection()
        projection.update(request("Stable introduction.\n\nThe result is $E = mc"))
        let stableID = projection.blocks.first?.id
        projection.update(request("Stable introduction.\n\nThe result is $E = mc^2$."))

        XCTAssertEqual(projection.blocks.first?.id, stableID)
        XCTAssertTrue(InlineMarkdownTokenizer.parse(projection.blocks.last?.document.text ?? "").contains(.math("E = mc^2", display: false)))
        projection.update(request(projection.source, streaming: false))
        XCTAssertEqual(projection.blocks.compactMap(\.markdown), MarkdownParser.parse(projection.source))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    func testShellEnvironmentVariablesAreNotParsedAsInlineMath() {
        let source = "Use $HOME and $PATH, then calculate $E = mc^2$."
        let tokens = InlineMarkdownTokenizer.parse(source)

        let formulas = tokens.compactMap { token -> String? in
            if case .math(let latex, _) = token { return latex }
            return nil
        }
        XCTAssertEqual(formulas, ["E = mc^2"])
        XCTAssertTrue(tokens.map(\.searchText).joined().contains("$HOME and $PATH"))
    }
}

final class CodeEmbedContentParityTests: XCTestCase {
    // contract-test: direct surface=gui.apple assertions=code-run.surface-parity
    func testFinishedIndexHTMLResolvesFromNestedDecodedPayload() {
        let data: [String: AnyCodable] = [
            "status": AnyCodable("finished"),
            "decodedContent": AnyCodable([
                "code": "<!doctype html><title>Ready</title>",
                "language": "html",
                "filename": "index.html",
                "line_count": 1
            ] as [String: Any])
        ]

        let content = AppleCodeEmbedContent(data: data)

        XCTAssertEqual(content.code, "<!doctype html><title>Ready</title>")
        XCTAssertEqual(content.language, "html")
        XCTAssertEqual(content.filename, "index.html")
        XCTAssertEqual(content.lineCount, 1)
    }

    // contract-test: direct surface=gui.apple assertions=code-run.surface-parity
    func testJSONStringContentAndLanguagePathHeaderMatchWebNormalization() {
        let json = #"{"type":"code-code","code":"html:index.html\n<!doctype html>\n<h1>Ready</h1>"}"#
        let content = AppleCodeEmbedContent(data: [
            "content": AnyCodable(json),
            "language": AnyCodable("text")
        ])

        XCTAssertEqual(content.code, "<!doctype html>\n<h1>Ready</h1>")
        XCTAssertEqual(content.language, "html")
        XCTAssertEqual(content.filename, "index.html")
        XCTAssertEqual(content.lineCount, 2)
    }

    // contract-test: supporting surface=gui.apple assertions=code-run.surface-parity
    func testPlainContentFallbackDoesNotStayInProcessingState() {
        let content = AppleCodeEmbedContent(data: [
            "content": AnyCodable("<!doctype html><p>Rendered</p>"),
            "filename": AnyCodable("index.html")
        ])

        XCTAssertFalse(content.code.isEmpty)
        XCTAssertEqual(content.filename, "index.html")
        XCTAssertEqual(content.lineCount, 1)
    }

    // contract-test: direct surface=gui.apple assertions=code-run.surface-parity
    func testBracePrefixedJSONAndJavaScriptRemainRawSource() {
        let json = #"{"name":"example","enabled":true}"#
        let javascript = "{\n  const ready = true;\n}"

        XCTAssertEqual(AppleCodeEmbedContent(data: ["content": AnyCodable(json)]).code, json)
        XCTAssertEqual(AppleCodeEmbedContent(data: ["content": AnyCodable(javascript)]).code, javascript)
    }

    // contract-test: direct surface=gui.apple assertions=code-run.surface-parity
    func testURLURIAndWindowsDriveFirstLinesAreNotLanguagePathHeaders() {
        let sources = [
            "https://example.com/source.js\nnext line",
            "file:///tmp/source.js\nnext line",
            "mailto:developer@example.com\nnext line",
            "C:\\Users\\Kitty\\index.js\nnext line"
        ]

        for source in sources {
            let content = AppleCodeEmbedContent(data: ["content": AnyCodable(source)])
            XCTAssertEqual(content.code, source)
            XCTAssertEqual(content.language, "")
            XCTAssertNil(content.filename)
        }
    }
}
