// Feasibility coverage for the native TextKit composer controller.
// Tests use synthetic text and embed references with no private content.
// UIKit/AppKit adapters must expose the same document and selection behavior.
// The first red run proves these contracts before production host integration.
// TextKit attachment atoms remain one UTF-16 unit in the editable surface.

import Foundation
import XCTest
@testable import OpenMates

#if canImport(UIKit)
import UIKit
#elseif canImport(AppKit)
import AppKit
#endif

@MainActor
final class NativeComposerControllerTests: XCTestCase {
    func testInsertEmbedPreservesDocumentOrderAndSelection() throws {
        let controller = try NativeComposerController(
            document: try ComposerMarkdownAdapter.parse("BeforeAfter"),
            selection: NSRange(location: 6, length: 0)
        )
        let embed = ComposerNodeV1.embed(
            id: "composer:embed:fixture",
            embedType: "image",
            canonicalSource: "```json\n{\"type\":\"image\",\"embed_id\":\"fixture-1\"}\n```",
            referenceOnly: false,
            display: ComposerEmbedDisplayV1(title: "Image", mediaKind: "image"),
            contentRef: "embed:fixture-1"
        )

        try controller.insertEmbed(embed)

        XCTAssertEqual(controller.attributedString.string, "Before\u{FFFC}After")
        XCTAssertEqual(controller.selection, NSRange(location: 7, length: 0))
        XCTAssertEqual(controller.document.nodes.map(\.id), [
            "composer:text:0",
            "composer:embed:fixture",
            "composer:text:1",
        ])
    }

    func testEmbedUpdatePreservesAttachmentIdentityAndSelection() throws {
        let controller = try makeEmbeddedController()
        let selection = controller.selection
        let attachment = try XCTUnwrap(
            controller.attributedString.attribute(
                .attachment,
                at: 6,
                effectiveRange: nil
            ) as? ComposerTextAttachment
        )

        try controller.updateEmbed(
            id: "composer:embed:fixture",
            status: "processing"
        )

        let updatedAttachment = try XCTUnwrap(
            controller.attributedString.attribute(
                .attachment,
                at: 6,
                effectiveRange: nil
            ) as? ComposerTextAttachment
        )
        XCTAssertTrue(attachment === updatedAttachment)
        XCTAssertEqual(controller.selection, selection)
    }

    func testMarkedTextBlocksSubmitUntilCompositionCommits() throws {
        let controller = try NativeComposerController(
            document: try ComposerMarkdownAdapter.parse("Composing"),
            selection: NSRange(location: 9, length: 0)
        )

        try controller.setMarkedTextRange(NSRange(location: 4, length: 5))
        XCTAssertFalse(controller.canSubmit)

        try controller.setMarkedTextRange(nil)
        XCTAssertTrue(controller.canSubmit)
    }

    func testTextKit2SurfaceContainsOneAttachmentAtom() throws {
        let controller = try makeEmbeddedController()

        #if canImport(UIKit)
        let textView = UITextView(usingTextLayoutManager: true)
        textView.attributedText = controller.attributedString
        XCTAssertNotNil(textView.textLayoutManager)
        XCTAssertEqual(textView.attributedText.string.utf16.count, 12)
        let attachment = try XCTUnwrap(
            textView.attributedText.attribute(
                .attachment,
                at: 6,
                effectiveRange: nil
            ) as? ComposerTextAttachment
        )
        var activationCount = 0
        let layoutManager = try XCTUnwrap(textView.textLayoutManager)
        let provider = try XCTUnwrap(attachment.viewProvider(
            for: textView,
            location: layoutManager.documentRange.location,
            textContainer: textView.textContainer
        ) as? ComposerAttachmentViewProvider)
        provider.loadView()
        let button = try XCTUnwrap(provider.view as? UIButton)
        button.addAction(UIAction { _ in activationCount += 1 }, for: .touchUpInside)
        button.sendActions(for: .touchUpInside)
        XCTAssertEqual(activationCount, 1)
        XCTAssertEqual(
            provider.attachmentBounds(
                for: [:],
                location: layoutManager.documentRange.location,
                textContainer: textView.textContainer,
                proposedLineFragment: CGRect(x: 0, y: 0, width: 320, height: 20),
                position: .zero
            ).size,
            CGSize(width: 320, height: 60)
        )
        #elseif canImport(AppKit)
        let textView = NSTextView(usingTextLayoutManager: true)
        textView.textStorage?.setAttributedString(controller.attributedString)
        XCTAssertNotNil(textView.textLayoutManager)
        XCTAssertEqual(textView.string.utf16.count, 12)
        #endif
    }

    func testBoundaryInsertionPreservesOriginalTextNodeID() throws {
        let document = try ComposerMarkdownAdapter.parse("Before")
        let embed = fixtureEmbed(id: "composer:embed:boundary")

        let atStart = try NativeComposerController(
            document: document,
            selection: NSRange(location: 0, length: 0)
        )
        try atStart.insertEmbed(embed)
        XCTAssertEqual(atStart.document.nodes.map(\.id), [
            "composer:embed:boundary",
            "composer:text:0",
        ])

        let atEnd = try NativeComposerController(
            document: document,
            selection: NSRange(location: 6, length: 0)
        )
        try atEnd.insertEmbed(embed)
        XCTAssertEqual(atEnd.document.nodes.map(\.id), [
            "composer:text:0",
            "composer:embed:boundary",
        ])
    }

    func testGeneratedTextIDDoesNotCollideWithInsertedEmbedID() throws {
        let controller = try NativeComposerController(
            document: ComposerMarkdownAdapter.parse("BeforeAfter"),
            selection: NSRange(location: 6, length: 0)
        )

        try controller.insertEmbed(fixtureEmbed(id: "composer:text:1"))

        XCTAssertEqual(Set(controller.document.nodes.map(\.id)).count, 3)
        XCTAssertEqual(controller.document.nodes.last?.id, "composer:text:2")
    }

    func testInvalidAndSurrogateSplittingSelectionsAreRejected() throws {
        let document = try ComposerMarkdownAdapter.parse("A\u{1F44D}B")

        XCTAssertThrowsError(try NativeComposerController(
            document: document,
            selection: NSRange(location: 2, length: 0)
        ))
        XCTAssertThrowsError(try NativeComposerController(
            document: document,
            selection: NSRange(location: 5, length: 0)
        ))
    }

    func testDuplicateInitialNodeIDsAreRejected() {
        let document = ComposerDocumentV1(version: 1, nodes: [
            .text(id: "composer:text:0", source: "A"),
            .text(id: "composer:text:0", source: "B"),
        ])

        XCTAssertThrowsError(try NativeComposerController(
            document: document,
            selection: NSRange(location: 0, length: 0)
        )) { error in
            XCTAssertEqual(
                error as? NativeComposerControllerError,
                .duplicateNodeID("composer:text:0")
            )
        }
    }

    private func makeEmbeddedController() throws -> NativeComposerController {
        let controller = try NativeComposerController(
            document: try ComposerMarkdownAdapter.parse("BeforeAfter"),
            selection: NSRange(location: 6, length: 0)
        )
        try controller.insertEmbed(ComposerNodeV1.embed(
            id: "composer:embed:fixture",
            embedType: "image",
            canonicalSource: "```json\n{\"type\":\"image\",\"embed_id\":\"fixture-1\"}\n```",
            referenceOnly: false,
            display: ComposerEmbedDisplayV1(title: "Image", mediaKind: "image"),
            contentRef: "embed:fixture-1"
        ))
        return controller
    }

    private func fixtureEmbed(id: String) -> ComposerNodeV1 {
        ComposerNodeV1.embed(
            id: id,
            embedType: "image",
            canonicalSource: "```json\n{\"type\":\"image\",\"embed_id\":\"fixture-1\"}\n```",
            referenceOnly: false,
            display: ComposerEmbedDisplayV1(title: "Image", mediaKind: "image"),
            contentRef: "embed:fixture-1"
        )
    }
}
