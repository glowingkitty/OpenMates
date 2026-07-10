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
final class NativeComposerTextView: NSObject {
    typealias AccessibilityAction = (name: String, handler: @MainActor @Sendable () -> Bool)

    let controller: NativeComposerController
    private(set) var embedAccessibilityElements: [NativeComposerEmbedAccessibilityDescriptor] = []
    private(set) var lastControllerError: NativeComposerControllerError?

    private let editorAccessibilityLabel: String
    private let editorAccessibilityHint: String
    private let embedAccessibilityLabel: (ComposerNodeV1) -> String
    private let embedAccessibilityActions: (ComposerNodeV1) -> [AccessibilityAction]
    private var actionsByEmbedID: [String: [AccessibilityAction]] = [:]
    private var isSynchronizing = false

    init(
        controller: NativeComposerController,
        accessibilityLabel: String,
        accessibilityHint: String,
        embedAccessibilityLabel: @escaping (ComposerNodeV1) -> String,
        embedAccessibilityActions: @escaping (ComposerNodeV1) -> [AccessibilityAction]
    ) {
        self.controller = controller
        self.editorAccessibilityLabel = accessibilityLabel
        self.editorAccessibilityHint = accessibilityHint
        self.embedAccessibilityLabel = embedAccessibilityLabel
        self.embedAccessibilityActions = embedAccessibilityActions
        super.init()
        rebuildEmbedAccessibilityElements()
    }

    #if canImport(UIKit)
    func makePlatformView() -> UITextView {
        let textView = UITextView(usingTextLayoutManager: true)
        textView.delegate = self
        synchronize(textView)
        return textView
    }

    func synchronize(_ textView: UITextView) {
        isSynchronizing = true
        defer { isSynchronizing = false }
        textView.attributedText = controller.attributedString
        textView.selectedRange = controller.selection
        textView.accessibilityIdentifier = "message-editor"
        textView.accessibilityLabel = editorAccessibilityLabel
        textView.accessibilityHint = editorAccessibilityHint
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
        textView.delegate = self
        synchronize(textView)
        return textView
    }

    func synchronize(_ textView: NSTextView) {
        isSynchronizing = true
        defer { isSynchronizing = false }
        textView.textStorage?.setAttributedString(controller.attributedString)
        textView.setSelectedRange(controller.selection)
        textView.setAccessibilityIdentifier("message-editor")
        textView.setAccessibilityLabel(editorAccessibilityLabel)
        textView.setAccessibilityHelp(editorAccessibilityHint)
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

    private func applyPlatformEdit(
        range: NSRange,
        replacement: String
    ) -> Bool {
        do {
            try controller.setSelection(range)
            try controller.replaceSelection(with: replacement)
            lastControllerError = nil
        } catch let error as NativeComposerControllerError {
            lastControllerError = error
        } catch {
            lastControllerError = .platformSynchronizationFailed
        }
        return false
    }

    private func applyPlatformSelection(_ range: NSRange) {
        do {
            try controller.setSelection(range)
            lastControllerError = nil
        } catch let error as NativeComposerControllerError {
            lastControllerError = error
        } catch {
            lastControllerError = .platformSynchronizationFailed
        }
    }
}

#if canImport(UIKit)
extension NativeComposerTextView: UITextViewDelegate {
    func textView(
        _ textView: UITextView,
        shouldChangeTextIn range: NSRange,
        replacementText text: String
    ) -> Bool {
        let shouldApplyPlatformEdit = applyPlatformEdit(range: range, replacement: text)
        synchronize(textView)
        return shouldApplyPlatformEdit
    }

    func textViewDidChangeSelection(_ textView: UITextView) {
        guard !isSynchronizing else { return }
        applyPlatformSelection(textView.selectedRange)
    }
}
#elseif canImport(AppKit)
extension NativeComposerTextView: NSTextViewDelegate {
    func textView(
        _ textView: NSTextView,
        shouldChangeTextIn affectedCharRange: NSRange,
        replacementString: String?
    ) -> Bool {
        let shouldApplyPlatformEdit = applyPlatformEdit(
            range: affectedCharRange,
            replacement: replacementString ?? ""
        )
        synchronize(textView)
        return shouldApplyPlatformEdit
    }

    func textViewDidChangeSelection(_ notification: Notification) {
        guard !isSynchronizing else { return }
        guard let textView = notification.object as? NSTextView else { return }
        applyPlatformSelection(textView.selectedRange())
    }
}
#endif
