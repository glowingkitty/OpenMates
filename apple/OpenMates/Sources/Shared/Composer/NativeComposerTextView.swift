// Long-lived TextKit 2 platform adapter for the native composer controller.
// The adapter projects attributed content, UTF-16 selection, and accessibility.
// Localized labels and action names are injected by the product host.
// Ordered embed descriptors follow the canonical ComposerDocument node order.
// Platform view and controller identities remain stable during synchronization.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/enter_message/MessageInput.svelte
// CSS:     frontend/packages/ui/src/styles/fields.css
// ────────────────────────────────────────────────────────────────────

import Foundation

#if canImport(UIKit)
import UIKit
#elseif canImport(AppKit)
import AppKit
#endif

struct NativeComposerEmbedAccessibilityDescriptor: Equatable {
    let nodeID: String
    let label: String
    let actionNames: [String]
}

@MainActor
final class NativeComposerTextView {
    typealias AccessibilityAction = (name: String, handler: @MainActor @Sendable () -> Bool)

    let controller: NativeComposerController
    private(set) var embedAccessibilityElements: [NativeComposerEmbedAccessibilityDescriptor] = []

    private let accessibilityLabel: String
    private let accessibilityHint: String
    private let embedAccessibilityLabel: (ComposerNodeV1) -> String
    private let embedAccessibilityActions: (ComposerNodeV1) -> [AccessibilityAction]
    private var actionsByEmbedID: [String: [AccessibilityAction]] = [:]

    init(
        controller: NativeComposerController,
        accessibilityLabel: String,
        accessibilityHint: String,
        embedAccessibilityLabel: @escaping (ComposerNodeV1) -> String,
        embedAccessibilityActions: @escaping (ComposerNodeV1) -> [AccessibilityAction]
    ) {
        self.controller = controller
        self.accessibilityLabel = accessibilityLabel
        self.accessibilityHint = accessibilityHint
        self.embedAccessibilityLabel = embedAccessibilityLabel
        self.embedAccessibilityActions = embedAccessibilityActions
        rebuildEmbedAccessibilityElements()
    }

    #if canImport(UIKit)
    func makePlatformView() -> UITextView {
        let textView = UITextView(usingTextLayoutManager: true)
        synchronize(textView)
        return textView
    }

    func synchronize(_ textView: UITextView) {
        textView.attributedText = controller.attributedString
        textView.selectedRange = controller.selection
        textView.accessibilityIdentifier = "message-editor"
        textView.accessibilityLabel = accessibilityLabel
        textView.accessibilityHint = accessibilityHint
        rebuildEmbedAccessibilityElements()
        textView.accessibilityElements = embedAccessibilityElements.map { descriptor in
            let element = UIAccessibilityElement(accessibilityContainer: textView)
            element.accessibilityIdentifier = descriptor.nodeID
            element.accessibilityLabel = descriptor.label
            element.accessibilityTraits = .button
            element.accessibilityCustomActions = (actionsByEmbedID[descriptor.nodeID] ?? []).map { action in
                UIAccessibilityCustomAction(name: action.name) { _ in action.handler() }
            }
            return element
        }
    }
    #elseif canImport(AppKit)
    func makePlatformView() -> NSTextView {
        let textView = NSTextView(usingTextLayoutManager: true)
        synchronize(textView)
        return textView
    }

    func synchronize(_ textView: NSTextView) {
        textView.textStorage?.setAttributedString(controller.attributedString)
        textView.setSelectedRange(controller.selection)
        textView.setAccessibilityIdentifier("message-editor")
        textView.setAccessibilityLabel(accessibilityLabel)
        textView.setAccessibilityHelp(accessibilityHint)
        rebuildEmbedAccessibilityElements()
    }
    #endif

    func performAccessibilityAction(named name: String, forEmbedID nodeID: String) -> Bool {
        guard let action = actionsByEmbedID[nodeID]?.first(where: { $0.name == name }) else {
            return false
        }
        return action.handler()
    }

    private func rebuildEmbedAccessibilityElements() {
        let embeds = controller.document.nodes.filter { $0.kind == "embed" }
        actionsByEmbedID = Dictionary(uniqueKeysWithValues: embeds.map { node in
            (node.id, embedAccessibilityActions(node))
        })
        embedAccessibilityElements = embeds.map { node in
            NativeComposerEmbedAccessibilityDescriptor(
                nodeID: node.id,
                label: embedAccessibilityLabel(node),
                actionNames: actionsByEmbedID[node.id]?.map { $0.name } ?? []
            )
        }
    }
}
