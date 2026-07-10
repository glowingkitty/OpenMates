// Contract tests for native composer paste classification.
// OpenMates embed payloads outrank HTML, files, URLs, and plain text.
// Tables, code, documents, and standalone URLs request explicit conversion.
// Unsupported clipboard content falls back to lossless sanitized text.
// Decisions retain source content so conversion failure remains recoverable.

import XCTest
@testable import OpenMates

final class NativeComposerPasteTests: XCTestCase {
    private let service = ComposerPasteService()

    func testCustomEmbedPayloadHasHighestPriority() {
        let embed = ComposerNodeV1.embed(
            id: "embed-paste",
            embedType: "image",
            canonicalSource: "synthetic-reference",
            referenceOnly: true,
            display: .init(title: "Pasted image", mediaKind: "image")
        )
        let decision = service.classify(.init(
            plainText: "fallback",
            html: "<table><tr><td>fallback</td></tr></table>",
            customEmbed: embed,
            sourceCodeLanguage: "swift"
        ))
        XCTAssertEqual(decision, .insertEmbed(embed))
    }

    func testCodeTableDocumentAndURLClassification() {
        XCTAssertEqual(
            service.classify(.init(plainText: "let value = 42", sourceCodeLanguage: "swift")),
            .convert(.code, source: "let value = 42")
        )
        XCTAssertEqual(
            service.classify(.init(plainText: "name\tvalue\nalpha\t1")),
            .convert(.sheet, source: "name\tvalue\nalpha\t1")
        )
        XCTAssertEqual(
            service.classify(.init(plainText: "# Synthetic document\n\nBody")),
            .convert(.document, source: "# Synthetic document\n\nBody")
        )
        XCTAssertEqual(
            service.classify(.init(plainText: "https://composer-fixture.invalid/path")),
            .convert(.url, source: "https://composer-fixture.invalid/path")
        )

        let markdownTable = "| name | value |\n| --- | --- |\n| alpha | 1 |"
        XCTAssertEqual(
            service.classify(.init(plainText: markdownTable, sourceCodeLanguage: "markdown")),
            .convert(.sheet, source: markdownTable)
        )
        let commaTable = "name,value\nalpha,1\nbeta,2"
        XCTAssertEqual(
            service.classify(.init(plainText: commaTable, sourceCodeLanguage: "csv")),
            .convert(.sheet, source: commaTable)
        )
    }

    func testLongProseAndHTMLStructureBecomeDocuments() {
        let prose = Array(repeating: "synthetic", count: 180).joined(separator: " ")
        XCTAssertEqual(service.classify(.init(plainText: prose)), .convert(.document, source: prose))
        XCTAssertEqual(
            service.classify(.init(plainText: "Visible", html: "<article><h1>Title</h1></article>")),
            .convert(.document, source: "Visible")
        )
    }

    func testPlainTextFallbackPreservesUnicodeAndLineOrder() {
        let source = "Hello 👋🏽\nمرحبا\n世界"
        XCTAssertEqual(service.classify(.init(plainText: source)), .insertText(source))
    }
}
