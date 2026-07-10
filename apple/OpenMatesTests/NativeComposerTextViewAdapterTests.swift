// Red contract tests for the native TextKit 2 composer view adapter.
// UIKit and AppKit must expose the same controller-driven editing semantics.
// Accessibility labels and actions are injected synthetic fixture values.
// Embed accessibility order follows the canonical composer document order.
// Adapter synchronization must retain controller and attachment identities.

import Foundation
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
        XCTAssertTrue(textView.attributedText.isEqual(to: controller.attributedString))
        XCTAssertEqual(textView.selectedRange, controller.selection)
        XCTAssertEqual(textView.accessibilityIdentifier, "message-editor")
        XCTAssertEqual(textView.accessibilityLabel, "Synthetic message input")
        XCTAssertEqual(textView.accessibilityHint, "Synthetic editing hint")
        #elseif canImport(AppKit)
        XCTAssertNotNil(textView.textLayoutManager)
        XCTAssertTrue(try XCTUnwrap(textView.textStorage).isEqual(to: controller.attributedString))
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
        XCTAssertTrue(textView.attributedText.isEqual(to: controller.attributedString))
        #elseif canImport(AppKit)
        XCTAssertTrue(try XCTUnwrap(textView.textStorage).isEqual(to: controller.attributedString))
        #endif
    }

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
            }
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
