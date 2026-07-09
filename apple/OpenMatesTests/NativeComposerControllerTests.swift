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

final class NativeComposerControllerTests: XCTestCase {
    func testInsertEmbedPreservesDocumentOrderAndSelection() throws {
        let controller = NativeComposerController(
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
        let controller = NativeComposerController(
            document: try ComposerMarkdownAdapter.parse("Composing"),
            selection: NSRange(location: 9, length: 0)
        )

        controller.setMarkedTextRange(NSRange(location: 4, length: 5))
        XCTAssertFalse(controller.canSubmit)

        controller.setMarkedTextRange(nil)
        XCTAssertTrue(controller.canSubmit)
    }

    func testTextKit2SurfaceContainsOneAttachmentAtom() throws {
        let controller = try makeEmbeddedController()

        #if canImport(UIKit)
        let textView = UITextView(usingTextLayoutManager: true)
        textView.attributedText = controller.attributedString
        XCTAssertNotNil(textView.textLayoutManager)
        XCTAssertEqual(textView.attributedText.string.utf16.count, 12)
        #elseif canImport(AppKit)
        let textView = NSTextView(usingTextLayoutManager: true)
        textView.textStorage?.setAttributedString(controller.attributedString)
        XCTAssertNotNil(textView.textLayoutManager)
        XCTAssertEqual(textView.string.utf16.count, 12)
        #endif
    }

    private func makeEmbeddedController() throws -> NativeComposerController {
        let controller = NativeComposerController(
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
}
