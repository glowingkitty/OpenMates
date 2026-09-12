// Red contract tests for the native TextKit 2 composer view adapter.
// UIKit and AppKit must expose the same controller-driven editing semantics.
// Accessibility labels and actions are injected synthetic fixture values.
// Embed accessibility order follows the canonical composer document order.
// Adapter synchronization must retain controller and attachment identities.

import Foundation
import SwiftUI
import XCTest
@testable import OpenMates

#if canImport(UIKit)
import UIKit
#elseif canImport(AppKit)
import AppKit
#endif

@MainActor
final class NativeComposerTextViewAdapterTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=message-input.focus.parent-state
    func testCreatesTextKit2PlatformViewAndSynchronizesContentAndSelection() throws {
        let controller = try makeController()
        let adapter = makeAdapter(controller: controller)
        let textView = adapter.makePlatformView()

        #if canImport(UIKit)
        XCTAssertNotNil(textView.textLayoutManager)
        XCTAssertEqual(textView.attributedText.string, controller.attributedString.string)
        XCTAssertEqual(textView.selectedRange, controller.selection)
        XCTAssertEqual(textView.accessibilityIdentifier, "message-editor")
        XCTAssertEqual(textView.accessibilityLabel, "Synthetic message input")
        XCTAssertEqual(textView.accessibilityHint, "Synthetic editing hint")
        #elseif canImport(AppKit)
        XCTAssertNotNil(textView.textLayoutManager)
        XCTAssertEqual(try XCTUnwrap(textView.textStorage).string, controller.attributedString.string)
        XCTAssertEqual(textView.selectedRange(), controller.selection)
        XCTAssertEqual(textView.accessibilityIdentifier(), "message-editor")
        XCTAssertEqual(textView.accessibilityLabel(), "Synthetic message input")
        XCTAssertEqual(textView.accessibilityHelp(), "Synthetic editing hint")
        #endif

        try controller.setSelection(NSRange(location: 1, length: 2))
        adapter.synchronize(textView)

        #if canImport(UIKit)
        XCTAssertEqual(textView.selectedRange, NSRange(location: 1, length: 2))
        #elseif canImport(AppKit)
        XCTAssertEqual(textView.selectedRange(), NSRange(location: 1, length: 2))
        #endif
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send
    func testExposesEmbedAccessibilityInDocumentOrderWithInjectedCustomActions() throws {
        let controller = try makeController()
        let recorder = AccessibilityActionRecorder()
        let adapter = makeAdapter(controller: controller, recorder: recorder)
        let textView = adapter.makePlatformView()

        XCTAssertEqual(
            adapter.embedAccessibilityElements.map(\.nodeID),
            ["composer:embed:first", "composer:embed:second"]
        )
        XCTAssertEqual(
            adapter.embedAccessibilityElements.map(\.label),
            ["Synthetic image, finished", "Synthetic PDF, finished"]
        )
        XCTAssertEqual(
            adapter.embedAccessibilityElements.map(\.actionNames),
            [["Synthetic remove"], ["Synthetic remove"]]
        )

        #if canImport(UIKit)
        let platformElements = try XCTUnwrap(
            textView.accessibilityElements as? [UIAccessibilityElement]
        )
        XCTAssertEqual(
            platformElements.compactMap(\.accessibilityLabel),
            ["Synthetic image, finished", "Synthetic PDF, finished"]
        )
        XCTAssertEqual(
            platformElements.map { $0.accessibilityCustomActions?.map(\.name) ?? [] },
            [["Synthetic remove"], ["Synthetic remove"]]
        )
        #endif

        XCTAssertTrue(adapter.performAccessibilityAction(
            named: "Synthetic remove",
            forEmbedID: "composer:embed:second"
        ))
        XCTAssertEqual(recorder.nodeIDs, ["composer:embed:second"])
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send
    func testEmbedStatusSynchronizationRetainsControllerAndPlatformViewIdentity() throws {
        let controller = try makeController()
        let adapter = makeAdapter(controller: controller)
        let textView = adapter.makePlatformView()
        let platformViewIdentity = ObjectIdentifier(textView)

        try controller.updateEmbed(id: "composer:embed:first", status: "processing")
        adapter.synchronize(textView)

        XCTAssertTrue(adapter.controller === controller)
        XCTAssertEqual(ObjectIdentifier(textView), platformViewIdentity)
        XCTAssertEqual(
            adapter.embedAccessibilityElements.map(\.label),
            ["Synthetic image, processing", "Synthetic PDF, finished"]
        )
        #if canImport(UIKit)
        XCTAssertEqual(textView.attributedText.string, controller.attributedString.string)
        #elseif canImport(AppKit)
        XCTAssertEqual(try XCTUnwrap(textView.textStorage).string, controller.attributedString.string)
        #endif
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.focus.parent-state
    func testPlatformEditsAndSelectionChangesSynchronizeBackToController() throws {
        let controller = try makeController()
        let adapter = makeAdapter(controller: controller)
        let textView = adapter.makePlatformView()

        #if canImport(UIKit)
        commitUIKitEdit(adapter, textView: textView, range: NSRange(location: 0, length: 1), replacement: "Z")
        XCTAssertEqual(textView.attributedText.string, "Z\u{FFFC}B\u{FFFC}C")
        textView.selectedRange = NSRange(location: 2, length: 1)
        adapter.textViewDidChangeSelection(textView)
        #elseif canImport(AppKit)
        XCTAssertFalse(adapter.textView(
            textView,
            shouldChangeTextIn: NSRange(location: 0, length: 1),
            replacementString: "Z"
        ))
        XCTAssertEqual(textView.string, "Z\u{FFFC}B\u{FFFC}C")
        textView.setSelectedRange(NSRange(location: 2, length: 1))
        adapter.textViewDidChangeSelection(Notification(name: NSTextView.didChangeSelectionNotification, object: textView))
        #endif

        XCTAssertEqual(controller.attributedString.string, "Z\u{FFFC}B\u{FFFC}C")
        XCTAssertEqual(controller.selection, NSRange(location: 2, length: 1))
        XCTAssertNil(adapter.lastControllerError)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.layout.responsive-parity
    func testTypedTextRetainsWebTypographyAndSemanticForegroundColor() throws {
        FontRegistration.registerFonts()
        let controller = try makeController()
        let adapter = makeAdapter(controller: controller)
        let textView = adapter.makePlatformView()

        #if canImport(UIKit)
        commitUIKitEdit(adapter, textView: textView, range: NSRange(location: 0, length: 1), replacement: "Z")
        let attributes = textView.attributedText.attributes(at: 0, effectiveRange: nil)
        let font = try XCTUnwrap(attributes[.font] as? UIFont)
        let foregroundColor = try XCTUnwrap(attributes[.foregroundColor] as? UIColor)
        let paragraphStyle = try XCTUnwrap(attributes[.paragraphStyle] as? NSParagraphStyle)
        let expectedColor = UIColor(Color.fontPrimary)
        let darkTraits = UITraitCollection(userInterfaceStyle: .dark)

        XCTAssertEqual(font.fontName, "LexendDeca-Medium")
        XCTAssertEqual(font.pointSize, 16, accuracy: 0.01)
        XCTAssertEqual(paragraphStyle.minimumLineHeight, 25.6, accuracy: 0.01)
        XCTAssertEqual(paragraphStyle.maximumLineHeight, 25.6, accuracy: 0.01)
        XCTAssertEqual(
            foregroundColor.resolvedColor(with: darkTraits),
            expectedColor.resolvedColor(with: darkTraits)
        )
        XCTAssertEqual((textView.typingAttributes[.font] as? UIFont)?.fontName, "LexendDeca-Medium")
        #elseif canImport(AppKit)
        XCTAssertFalse(adapter.textView(
            textView,
            shouldChangeTextIn: NSRange(location: 0, length: 1),
            replacementString: "Z"
        ))
        let attributes = try XCTUnwrap(textView.textStorage).attributes(at: 0, effectiveRange: nil)
        let font = try XCTUnwrap(attributes[.font] as? NSFont)
        let paragraphStyle = try XCTUnwrap(attributes[.paragraphStyle] as? NSParagraphStyle)

        XCTAssertEqual(font.fontName, "LexendDeca-Medium")
        XCTAssertEqual(font.pointSize, 16, accuracy: 0.01)
        XCTAssertEqual(paragraphStyle.minimumLineHeight, 25.6, accuracy: 0.01)
        XCTAssertEqual(paragraphStyle.maximumLineHeight, 25.6, accuracy: 0.01)
        XCTAssertNotNil(attributes[.foregroundColor] as? NSColor)
        #endif
    }

    #if canImport(UIKit)
    // contract-test: supporting surface=gui.apple assertions=message-input.focus.parent-state
    func testUIKitAccessibilityTracksNativeTextWithoutStaleOverride() throws {
        let controller = try NativeComposerController(
            document: ComposerDocumentV1(version: 1, nodes: [.text(id: "text-1", source: "Prefix")]),
            selection: NSRange(location: 6, length: 0)
        )
        let adapter = makeAdapter(controller: controller)
        let textView = adapter.makePlatformView()
        let nativeTextView = UITextView(usingTextLayoutManager: true)
        nativeTextView.text = "Prefix and suffix"
        // Native storage can finish a keyboard edit before the next adapter refresh.
        textView.textStorage.append(NSAttributedString(string: " and suffix"))
        XCTAssertEqual(textView.text, nativeTextView.text)
        XCTAssertEqual(textView.accessibilityValue, nativeTextView.accessibilityValue,
                       "Adapter must retain standard UITextView dynamic accessibility")
    }

    // UIKit must commit replacement ranges itself before canonical text is published.
    // This models keyboard correction followed by continued typing, without a second
    // adapter mutation of the native storage or selection during shouldChange.
    // contract-test: supporting surface=gui.apple assertions=message-input.focus.parent-state
    func testUIKitCommitsCorrectionAndContinuedTypingExactlyOnce() throws {
        let controller = try NativeComposerController(
            document: ComposerDocumentV1(version: 1, nodes: [.text(id: "text-1", source: "Reply with one short sentnce")]),
            selection: NSRange(location: 28, length: 0)
        )
        let adapter = makeAdapter(controller: controller)
        let textView = adapter.makePlatformView()
        var published: [String] = []
        adapter.onCanonicalMarkdownChange = { published.append($0) }

        commitUIKitEdit(adapter, textView: textView, range: NSRange(location: 21, length: 7), replacement: "sentence")
        commitUIKitEdit(adapter, textView: textView, range: textView.selectedRange, replacement: ": Hello from Osaka.")

        let expected = "Reply with one short sentence: Hello from Osaka."
        XCTAssertEqual(textView.text, expected)
        XCTAssertEqual(controller.attributedString.string, expected)
        XCTAssertEqual(published, ["Reply with one short sentence", expected])
        XCTAssertEqual(textView.selectedRange, NSRange(location: expected.utf16.count, length: 0))
    }

    private func commitUIKitEdit(
        _ adapter: NativeComposerTextView,
        textView: UITextView,
        range: NSRange,
        replacement: String,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        let originalText = textView.text
        let originalSelection = textView.selectedRange
        XCTAssertTrue(adapter.textView(textView, shouldChangeTextIn: range, replacementText: replacement), file: file, line: line)
        XCTAssertEqual(textView.text, originalText, "Delegate must leave the native transaction to UIKit", file: file, line: line)
        XCTAssertEqual(textView.selectedRange, originalSelection, file: file, line: line)
        // A SwiftUI refresh during the transaction must not pre-apply the edit.
        adapter.synchronize(textView)
        XCTAssertEqual(textView.text, originalText, file: file, line: line)
        textView.textStorage.replaceCharacters(in: range, with: NSAttributedString(string: replacement, attributes: textView.typingAttributes))
        textView.selectedRange = NSRange(location: range.location + replacement.utf16.count, length: 0)
        adapter.textViewDidChange(textView)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.focus.parent-state
    func testEquivalentSynchronizationPreservesAttributedTextWithoutAutoCapitalization() throws {
        let controller = try NativeComposerController(
            document: ComposerDocumentV1(version: 1, nodes: [.text(id: "text-1", source: "Hello")]),
            selection: NSRange(location: 5, length: 0)
        )
        let adapter = makeAdapter(controller: controller)
        let textView = adapter.makePlatformView()
        let sentinel = NSAttributedString.Key("synthetic-input-trait-sentinel")
        textView.textStorage.addAttribute(sentinel, value: true, range: NSRange(location: 0, length: 1))

        XCTAssertEqual(textView.autocapitalizationType, .none)
        try controller.loadDocument(ComposerDocumentV1(version: 1, nodes: [.text(id: "text-2", source: "Hello")]))
        adapter.synchronize(textView)

        XCTAssertEqual(textView.attributedText.attribute(sentinel, at: 0, effectiveRange: nil) as? Bool, true)
        XCTAssertEqual(textView.autocapitalizationType, .none)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.privacy-context
    func testPIIDecorationsUseWarningBackgroundAndExcludeOnlyTappedIdentity() throws {
        let controller = try NativeComposerController(
            document: ComposerDocumentV1(version: 1, nodes: [.text(id: "text-1", source: "alice@example.com and +49 170 1234567")]),
            selection: NSRange(location: 0, length: 0)
        )
        let adapter = makeAdapter(controller: controller)
        let textView = adapter.makePlatformView()
        let matches = PIIDetector.detect(in: controller.attributedString.string)
        var excludedIDs: [String] = []

        adapter.updatePIIDecorations(
            matches.map { .init(id: $0.id, range: $0.range) },
            onExclude: { excludedIDs.append($0) }
        )
        adapter.synchronize(textView)

        let first = try XCTUnwrap(matches.first)
        XCTAssertEqual(
            textView.attributedText.attribute(.backgroundColor, at: first.range.location, effectiveRange: nil) as? UIColor,
            UIColor(Color.warning).withAlphaComponent(0.35)
        )
        XCTAssertTrue(adapter.excludePII(atUTF16Offset: first.range.location))
        XCTAssertEqual(excludedIDs, [first.id])
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testPIITapHandlingDoesNotCompeteWithEditorFocusAndSelection() throws {
        let controller = try NativeComposerController(
            document: ComposerDocumentV1(version: 1, nodes: [.text(id: "text-1", source: "alice@example.com")]),
            selection: NSRange(location: 0, length: 0)
        )
        let adapter = makeAdapter(controller: controller)
        let textView = adapter.makePlatformView()
        let exclusionTap = try XCTUnwrap(textView.gestureRecognizers?.first { $0.delegate === adapter })
        XCTAssertFalse(exclusionTap.isEnabled, "Ordinary editor taps must not enter highlight handling")
        adapter.updatePIIDecorations([.init(id: "email", range: NSRange(location: 0, length: 17))], onExclude: { _ in })
        XCTAssertTrue(exclusionTap.isEnabled)
        XCTAssertTrue(adapter.gestureRecognizer(exclusionTap, shouldRecognizeSimultaneouslyWith: UITapGestureRecognizer()))
        adapter.updatePIIDecorations([], onExclude: { _ in })
        XCTAssertFalse(exclusionTap.isEnabled)
    }
    #endif

    private func makeAdapter(
        controller: NativeComposerController,
        recorder: AccessibilityActionRecorder = AccessibilityActionRecorder()
    ) -> NativeComposerTextView {
        NativeComposerTextView(
            controller: controller,
            accessibilityLabel: "Synthetic message input",
            accessibilityHint: "Synthetic editing hint",
            embedAccessibilityLabel: { node in
                "\(node.display?.title ?? "Synthetic attachment"), \(node.status ?? "unknown")"
            },
            embedAccessibilityActions: { node in
                [(
                    name: "Synthetic remove",
                    handler: {
                        recorder.nodeIDs.append(node.id)
                        return true
                    }
                    )]
            },
            onCanonicalMarkdownChange: { _ in },
            onFocusChange: { _ in },
            onSubmit: { }
        )
    }

    private func makeController() throws -> NativeComposerController {
        try NativeComposerController(
            document: ComposerDocumentV1(version: 1, nodes: [
                .text(id: "composer:text:before", source: "A"),
                fixtureEmbed(
                    id: "composer:embed:first",
                    title: "Synthetic image",
                    embedType: "image"
                ),
                .text(id: "composer:text:middle", source: "B"),
                fixtureEmbed(
                    id: "composer:embed:second",
                    title: "Synthetic PDF",
                    embedType: "pdf"
                ),
                .text(id: "composer:text:after", source: "C"),
            ]),
            selection: NSRange(location: 3, length: 0)
        )
    }

    private func fixtureEmbed(
        id: String,
        title: String,
        embedType: String
    ) -> ComposerNodeV1 {
        ComposerNodeV1.embed(
            id: id,
            embedType: embedType,
            canonicalSource: "```json\n{\"type\":\"\(embedType)\",\"embed_id\":\"\(id)\"}\n```",
            referenceOnly: false,
            display: ComposerEmbedDisplayV1(title: title, mediaKind: embedType),
            contentRef: "embed:\(id)"
        )
    }
}

@MainActor
private final class AccessibilityActionRecorder {
    var nodeIDs: [String] = []
}
