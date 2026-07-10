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
import SwiftUI

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
    var onCanonicalMarkdownChange: @MainActor (String) -> Void
    var onFocusChange: @MainActor (Bool) -> Void
    var onSubmit: @MainActor () -> Void
    private var actionsByEmbedID: [String: [AccessibilityAction]] = [:]
    private var isSynchronizing = false
    private var lastSynchronizedRevision: Int?
    private var lastAccessibilityNodes: [ComposerNodeV1] = []

    init(
        controller: NativeComposerController,
        accessibilityLabel: String,
        accessibilityHint: String,
        embedAccessibilityLabel: @escaping (ComposerNodeV1) -> String,
        embedAccessibilityActions: @escaping (ComposerNodeV1) -> [AccessibilityAction],
        onCanonicalMarkdownChange: @escaping @MainActor (String) -> Void,
        onFocusChange: @escaping @MainActor (Bool) -> Void,
        onSubmit: @escaping @MainActor () -> Void
    ) {
        self.controller = controller
        self.editorAccessibilityLabel = accessibilityLabel
        self.editorAccessibilityHint = accessibilityHint
        self.embedAccessibilityLabel = embedAccessibilityLabel
        self.embedAccessibilityActions = embedAccessibilityActions
        self.onCanonicalMarkdownChange = onCanonicalMarkdownChange
        self.onFocusChange = onFocusChange
        self.onSubmit = onSubmit
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
        if lastSynchronizedRevision != controller.revision {
            textView.attributedText = styledAttributedString(controller.attributedString)
            lastSynchronizedRevision = controller.revision
        }
        textView.selectedRange = controller.selection
        textView.typingAttributes = textAttributes
        textView.accessibilityIdentifier = "message-editor"
        textView.accessibilityLabel = editorAccessibilityLabel
        textView.accessibilityHint = editorAccessibilityHint
        if rebuildEmbedAccessibilityElementsIfNeeded() {
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
        if lastSynchronizedRevision != controller.revision {
            textView.textStorage?.setAttributedString(styledAttributedString(controller.attributedString))
            lastSynchronizedRevision = controller.revision
        }
        textView.setSelectedRange(controller.selection)
        textView.typingAttributes = textAttributes
        textView.setAccessibilityIdentifier("message-editor")
        textView.setAccessibilityLabel(editorAccessibilityLabel)
        textView.setAccessibilityHelp(editorAccessibilityHint)
        rebuildEmbedAccessibilityElementsIfNeeded()
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

    @discardableResult
    private func rebuildEmbedAccessibilityElementsIfNeeded() -> Bool {
        let embeds = controller.document.nodes.filter { $0.kind == "embed" }
        guard embeds != lastAccessibilityNodes else { return false }
        lastAccessibilityNodes = embeds
        rebuildEmbedAccessibilityElements()
        return true
    }

    private var textAttributes: [NSAttributedString.Key: Any] {
        let paragraphStyle = NSMutableParagraphStyle()
        paragraphStyle.minimumLineHeight = 25.6
        paragraphStyle.maximumLineHeight = 25.6
        // Web body typography supplies --font-weight-p: 500 to ProseMirror.
        #if canImport(UIKit)
        let font = UIFont(name: FontRegistration.mediumPostScriptName, size: 16)
            ?? UIFont.systemFont(ofSize: 16, weight: .medium)
        return [
            .font: font,
            .foregroundColor: UIColor(Color.fontPrimary),
            .paragraphStyle: paragraphStyle,
        ]
        #elseif canImport(AppKit)
        let font = NSFont(name: FontRegistration.mediumPostScriptName, size: 16)
            ?? NSFont.systemFont(ofSize: 16, weight: .medium)
        return [
            .font: font,
            .foregroundColor: NSColor(Color.fontPrimary),
            .paragraphStyle: paragraphStyle,
        ]
        #endif
    }

    private func styledAttributedString(_ source: NSAttributedString) -> NSAttributedString {
        let styled = NSMutableAttributedString(attributedString: source)
        styled.addAttributes(textAttributes, range: NSRange(location: 0, length: styled.length))
        return styled
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

    private func notifyCanonicalMarkdownChange() {
        do {
            onCanonicalMarkdownChange(try controller.canonicalMarkdown())
        } catch {
            NativeDiagnostics.warning(
                "Native composer serialization failed: \(type(of: error))",
                category: "apple_composer"
            )
        }
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

    #if canImport(UIKit)
    private func applyIncrementalEdit(
        to textView: UITextView,
        range: NSRange,
        replacement: String
    ) {
        isSynchronizing = true
        defer { isSynchronizing = false }
        textView.textStorage.beginEditing()
        textView.textStorage.replaceCharacters(
            in: range,
            with: NSAttributedString(string: replacement, attributes: textAttributes)
        )
        textView.textStorage.endEditing()
        if textView.textStorage.string != controller.attributedString.string {
            textView.attributedText = styledAttributedString(controller.attributedString)
        }
        lastSynchronizedRevision = controller.revision
        textView.selectedRange = controller.selection
        textView.typingAttributes = textAttributes
        if rebuildEmbedAccessibilityElementsIfNeeded() {
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
    }
    #elseif canImport(AppKit)
    private func applyIncrementalEdit(
        to textView: NSTextView,
        range: NSRange,
        replacement: String
    ) {
        isSynchronizing = true
        defer { isSynchronizing = false }
        textView.textStorage?.beginEditing()
        textView.textStorage?.replaceCharacters(
            in: range,
            with: NSAttributedString(string: replacement, attributes: textAttributes)
        )
        textView.textStorage?.endEditing()
        if textView.textStorage?.string != controller.attributedString.string {
            textView.textStorage?.setAttributedString(styledAttributedString(controller.attributedString))
        }
        lastSynchronizedRevision = controller.revision
        textView.setSelectedRange(controller.selection)
        textView.typingAttributes = textAttributes
        rebuildEmbedAccessibilityElementsIfNeeded()
    }
    #endif
}

#if canImport(UIKit)
extension NativeComposerTextView: UITextViewDelegate {
    func textView(
        _ textView: UITextView,
        shouldChangeTextIn range: NSRange,
        replacementText text: String
    ) -> Bool {
        let shouldApplyPlatformEdit = applyPlatformEdit(range: range, replacement: text)
        if lastControllerError == nil {
            applyIncrementalEdit(to: textView, range: range, replacement: text)
            notifyCanonicalMarkdownChange()
        }
        return shouldApplyPlatformEdit
    }

    func textViewDidChangeSelection(_ textView: UITextView) {
        guard !isSynchronizing else { return }
        applyPlatformSelection(textView.selectedRange)
    }

    func textViewDidBeginEditing(_ textView: UITextView) {
        onFocusChange(true)
    }

    func textViewDidEndEditing(_ textView: UITextView) {
        onFocusChange(false)
    }
}
#elseif canImport(AppKit)
extension NativeComposerTextView: NSTextViewDelegate {
    func textView(
        _ textView: NSTextView,
        shouldChangeTextIn affectedCharRange: NSRange,
        replacementString: String?
    ) -> Bool {
        if replacementString == "\n",
           NSApp.currentEvent?.modifierFlags.contains(.shift) != true,
           controller.canSubmit {
            onSubmit()
            return false
        }
        let shouldApplyPlatformEdit = applyPlatformEdit(
            range: affectedCharRange,
            replacement: replacementString ?? ""
        )
        if lastControllerError == nil {
            applyIncrementalEdit(
                to: textView,
                range: affectedCharRange,
                replacement: replacementString ?? ""
            )
            notifyCanonicalMarkdownChange()
        }
        return shouldApplyPlatformEdit
    }

    func textViewDidChangeSelection(_ notification: Notification) {
        guard !isSynchronizing else { return }
        guard let textView = notification.object as? NSTextView else { return }
        applyPlatformSelection(textView.selectedRange())
    }

    func textDidBeginEditing(_ notification: Notification) {
        onFocusChange(true)
    }

    func textDidEndEditing(_ notification: Notification) {
        onFocusChange(false)
    }
}
#endif
