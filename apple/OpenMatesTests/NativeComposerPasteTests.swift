// Contract tests for native composer paste classification.
// OpenMates embed payloads outrank HTML, files, URLs, and plain text.
// Tables, code, documents, and standalone URLs request explicit conversion.
// Unsupported clipboard content falls back to lossless sanitized text.
// Decisions retain source content so conversion failure remains recoverable.

import XCTest
#if os(iOS)
import UIKit
#endif
@testable import OpenMates

final class NativeComposerPasteTests: XCTestCase {
    private let service = ComposerPasteService()

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send
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

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send
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

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send
    func testLongProseAndHTMLStructureBecomeDocuments() {
        let prose = Array(repeating: "synthetic", count: 180).joined(separator: " ")
        XCTAssertEqual(service.classify(.init(plainText: prose)), .convert(.document, source: prose))
        XCTAssertEqual(
            service.classify(.init(plainText: "Visible", html: "<article><h1>Title</h1></article>")),
            .convert(.document, source: "Visible")
        )
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send
    func testPlainTextFallbackPreservesUnicodeAndLineOrder() {
        let source = "Hello 👋🏽\nمرحبا\n世界"
        XCTAssertEqual(service.classify(.init(plainText: source)), .insertText(source))
    }
}

#if os(iOS)
@MainActor
final class AttachmentDocumentPickerTests: XCTestCase {
    // contract-test: direct surface=gui.apple assertions=message-input.embeds.gated-send
    func testReadableLocalDocumentReachesComposerWithoutSecurityScope() throws {
        let fileURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("attachment-picker-regression-\(UUID().uuidString).pdf")
        let content = Data("synthetic PDF fixture".utf8)
        try content.write(to: fileURL)
        defer { try? FileManager.default.removeItem(at: fileURL) }

        var selected: (Data, String)?
        let coordinator = AttachmentDocumentPickerView.Coordinator(
            onFileSelected: { data, filename in selected = (data, filename) },
            startAccessing: { _ in false }
        )
        let picker = UIDocumentPickerViewController(forOpeningContentTypes: [.pdf])
        coordinator.documentPicker(picker, didPickDocumentsAt: [fileURL])

        XCTAssertEqual(selected?.0, content)
        XCTAssertEqual(selected?.1, fileURL.lastPathComponent)
    }
}
#endif
