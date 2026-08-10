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

    func testPlatformEditsAndSelectionChangesSynchronizeBackToController() throws {
        let controller = try makeController()
        let adapter = makeAdapter(controller: controller)
        let textView = adapter.makePlatformView()

        #if canImport(UIKit)
        XCTAssertFalse(adapter.textView(
            textView,
            shouldChangeTextIn: NSRange(location: 0, length: 1),
            replacementText: "Z"
        ))
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

    func testTypedTextRetainsWebTypographyAndSemanticForegroundColor() throws {
        FontRegistration.registerFonts()
        let controller = try makeController()
        let adapter = makeAdapter(controller: controller)
        let textView = adapter.makePlatformView()

        #if canImport(UIKit)
        XCTAssertFalse(adapter.textView(
            textView,
            shouldChangeTextIn: NSRange(location: 0, length: 1),
            replacementText: "Z"
        ))
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
