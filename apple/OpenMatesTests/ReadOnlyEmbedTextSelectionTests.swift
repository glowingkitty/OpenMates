// Native TextKit range/copy evidence for read-only embed content.
// Web: UnifiedEmbedFullscreen.svelte, code/CodeEmbedFullscreen.svelte,
//      web/WebsiteEmbedFullscreen.svelte
import XCTest
@testable import OpenMates
import SwiftUI
#if os(iOS)
import UIKit

@MainActor
final class ReadOnlyEmbedTextSelectionTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testReadOnlyMarkdownPreservesStrikethroughInNativeText() throws {
        let markdown = try AttributedString(markdown: "Current ~~obsolete~~ guidance",
            options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))
        let rendered = ReadOnlySelectableText.attributed(markdown)
        let obsolete = (rendered.string as NSString).range(of: "obsolete")
        XCTAssertEqual(rendered.attribute(.strikethroughStyle, at: obsolete.location, effectiveRange: nil) as? Int,
                       NSUnderlineStyle.single.rawValue)
        XCTAssertNil(rendered.attribute(.strikethroughStyle, at: 0, effectiveRange: nil))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,code-run.surface-parity
    func testNativeCodeRangeCopiesMultipleLinesWithIndentationAndUnicodeWithoutGutter() async throws {
        let source = "def butterfly():\n    value = '🦋'\n    return value\n"
        let selected = "    value = '🦋'\n    return value\n"
        let rendered = CodeSelectableSource.attributed(code: source, language: "python", fontSize: 15, colorScheme: .dark)
        XCTAssertEqual(rendered.string, source)
        let view = PlatformMessageSelectableText.makeTextView()
        PlatformMessageSelectableText.update(rendered, in: view)
        let nativeRange = (source as NSString).range(of: selected)
        view.selectedRange = nativeRange
        var captured: MessageTextSelectionSnapshot?
        let delivered = expectation(description: "Native selected range delivered")
        let context = MessageTextSelectionContext(messageID: "code", preserveWhitespace: true,
            onSelection: { snapshot in captured = snapshot; delivered.fulfill() }, onContextMenu: { _ in })
        let coordinator = PlatformMessageSelectableText.Coordinator(context)
        coordinator.textViewDidChangeSelection(view)
        await fulfillment(of: [delivered], timeout: 1)
        let snapshot = try XCTUnwrap(captured)
        ReadOnlySelectableText.copy(snapshot)
        XCTAssertEqual(UIPasteboard.general.string, selected)
        XCTAssertNotEqual(UIPasteboard.general.string, source)
        XCTAssertEqual(view.selectedRange, nativeRange)
        XCTAssertFalse(view.isEditable)
        XCTAssertFalse(view.isScrollEnabled)
        XCTAssertTrue(view.isSelectable)
        // Re-rendering identical syntax attributes preserves TextKit selection.
        PlatformMessageSelectableText.update(rendered, in: view)
        XCTAssertEqual(view.selectedRange, nativeRange)
        XCTAssertEqual(rendered.attribute(.font, at: 0, effectiveRange: nil) as? UIFont,
                       UIFont.monospacedSystemFont(ofSize: 15, weight: .regular))
        XCTAssertEqual((rendered.attribute(.paragraphStyle, at: 0, effectiveRange: nil) as? NSParagraphStyle)?.maximumLineHeight, 24)
        UIPasteboard.general.items = []
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testSourceQuoteStyleAndNativeSubstringCopySurviveUnchangedUpdate() async throws {
        let text = "Before 🦋 selected website words after"
        let quoteRange = (text as NSString).range(of: "selected website words")
        let rendered = ReadOnlySelectableText.attributed(SourceQuoteMatcher.attributed(text, range: quoteRange),
            color: .grey100, lineHeight: 24)
        XCTAssertNotNil(rendered.attribute(.backgroundColor, at: quoteRange.location, effectiveRange: nil))
        let view = PlatformMessageSelectableText.makeTextView()
        PlatformMessageSelectableText.update(rendered, in: view)
        view.selectedRange = (text as NSString).range(of: "website")
        var captured: MessageTextSelectionSnapshot?
        let delivered = expectation(description: "Website native selection delivered")
        let coordinator = PlatformMessageSelectableText.Coordinator(.init(messageID: "website",
            preserveWhitespace: true, onSelection: { captured = $0; delivered.fulfill() }, onContextMenu: { _ in }))
        coordinator.textViewDidChangeSelection(view)
        await fulfillment(of: [delivered], timeout: 1)
        ReadOnlySelectableText.copy(try XCTUnwrap(captured))
        XCTAssertEqual(UIPasteboard.general.string, "website")
        PlatformMessageSelectableText.update(rendered, in: view)
        XCTAssertEqual(view.selectedRange, (text as NSString).range(of: "website"))
        XCTAssertNotNil(view.attributedText.attribute(.backgroundColor, at: quoteRange.location, effectiveRange: nil))
        UIPasteboard.general.items = []
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,code-run.surface-parity
    func testWhitespaceOnlyNativeCodeSelectionRemainsCopyable() throws {
        let view = PlatformMessageSelectableText.makeTextView()
        PlatformMessageSelectableText.update(NSAttributedString(string: "first\n\t  second"), in: view)
        view.selectedRange = NSRange(location: 5, length: 4)
        let snapshot = try XCTUnwrap(MessageTextSelectionSnapshot.capture(messageID: "code", segmentID: "source",
            text: view.text, range: view.selectedRange, preserveWhitespace: true))
        ReadOnlySelectableText.copy(snapshot)
        XCTAssertEqual(UIPasteboard.general.string, "\n\t  ")
        UIPasteboard.general.items = []
    }
}
#elseif os(macOS)
import AppKit

@MainActor
final class ReadOnlyEmbedTextSelectionTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,code-run.surface-parity
    func testAppKitCodeNativeRangeCopiesExactSubstringAndKeepsSyntaxAttributes() async throws {
        let source = "let before = 1\n    let butterfly = \"🦋\"\nlet after = 2"
        let selected = "    let butterfly = \"🦋\"\n"
        let rendered = CodeSelectableSource.attributed(code: source, language: "swift", fontSize: 15, colorScheme: .dark)
        let view = PlatformMessageSelectableText.SelectionTextView()
        view.isEditable = false
        view.isSelectable = true
        view.textStorage?.setAttributedString(rendered)
        view.setSelectedRange((source as NSString).range(of: selected))
        var captured: MessageTextSelectionSnapshot?
        let delivered = expectation(description: "AppKit selection delivered")
        let coordinator = PlatformMessageSelectableText.Coordinator(.init(messageID: "code", preserveWhitespace: true,
            onSelection: { captured = $0; delivered.fulfill() }, onContextMenu: { _ in }))
        coordinator.textViewDidChangeSelection(Notification(name: NSTextView.didChangeSelectionNotification, object: view))
        await fulfillment(of: [delivered], timeout: 1)
        ReadOnlySelectableText.copy(try XCTUnwrap(captured))
        XCTAssertEqual(NSPasteboard.general.string(forType: .string), selected)
        XCTAssertEqual(view.string, source)
        XCTAssertFalse(view.isEditable)
        XCTAssertTrue(view.isSelectable)
        XCTAssertNotNil(view.textStorage?.attribute(.foregroundColor, at: 0, effectiveRange: nil))
        NSPasteboard.general.clearContents()
    }
}
#endif
