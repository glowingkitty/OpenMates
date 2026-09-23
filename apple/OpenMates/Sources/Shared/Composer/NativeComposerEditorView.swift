// SwiftUI bridge for the production TextKit 2 composer surface.
// The host supplies one long-lived NativeComposerSession as document authority.
// A coordinator retains stable adapter and platform-view identities across redraws.
// Focus and canonical changes flow through the session without reparsing on edits.
// Localized accessibility and host submit behavior remain explicit inputs.
// Specification: specifications/features/message-input/specification.yml
// Assertion: message-input.layout.responsive-parity

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/enter_message/MessageInput.svelte
// CSS:     frontend/packages/ui/src/components/enter_message/MessageInput.styles.css
//          Classes: .message-field, .message-field-editor
// Tokens:  ColorTokens.generated.swift, TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

#if canImport(UIKit)
import UIKit

struct NativeComposerEditorView: UIViewRepresentable {
    @ObservedObject var session: NativeComposerSession
    let isFocused: Binding<Bool>
    let isEditable: Bool
    let accessibilityHint: String
    var measuredHeight: Binding<CGFloat> = .constant(0)
    var piiDecorations: [NativeComposerPIIDecoration] = []
    var onExcludePII: (String) -> Void = { _ in }
    let onSubmit: () -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(session: session, accessibilityHint: accessibilityHint)
    }

    func makeUIView(context: Context) -> UITextView {
        let textView = context.coordinator.adapter.makePlatformView()
        textView.backgroundColor = .clear
        textView.isScrollEnabled = true
        textView.showsVerticalScrollIndicator = false
        textView.textContainerInset = UIEdgeInsets(
            top: MessageComposerMetric.editorVerticalInset,
            left: .spacing6,
            bottom: MessageComposerMetric.editorVerticalInset,
            right: .spacing6
        )
        return textView
    }

    func sizeThatFits(_ proposal: ProposedViewSize, uiView: UITextView, context: Context) -> CGSize? {
        guard let width = proposal.width else { return nil }
        return CGSize(width: width, height: resolvedHeight(for: uiView, width: width))
    }

    func updateUIView(_ textView: UITextView, context: Context) {
        context.coordinator.onFocusChange = { isFocused.wrappedValue = $0 }
        context.coordinator.onSubmit = onSubmit
        context.coordinator.adapter.updatePIIDecorations(piiDecorations, onExclude: onExcludePII)
        context.coordinator.adapter.synchronize(textView)
        textView.isEditable = isEditable
        if textView.bounds.width > 0 {
            publishMeasuredHeight(resolvedHeight(for: textView, width: textView.bounds.width))
        }
        if isFocused.wrappedValue, !textView.isFirstResponder {
            textView.becomeFirstResponder()
        } else if !isFocused.wrappedValue, textView.isFirstResponder {
            textView.resignFirstResponder()
        }
    }

    private func resolvedHeight(for textView: UITextView, width: CGFloat) -> CGFloat {
        let contentSize = textView.sizeThatFits(
            CGSize(width: width, height: .greatestFiniteMagnitude)
        )
        let containsEmbed = session.controller.document.nodes.contains(where: { $0.kind == "embed" })
        return MessageComposerMetric.editorHeight(
            for: contentSize.height,
            containsEmbed: containsEmbed
        )
    }

    private func publishMeasuredHeight(_ height: CGFloat) {
        guard abs(measuredHeight.wrappedValue - height) > 0.5 else { return }
        DispatchQueue.main.async {
            measuredHeight.wrappedValue = height
        }
    }

    @MainActor
    final class Coordinator {
        let adapter: NativeComposerTextView
        var onFocusChange: (Bool) -> Void = { _ in }
        var onSubmit: () -> Void = { }

        init(session: NativeComposerSession, accessibilityHint: String) {
            adapter = NativeComposerTextView(
                controller: session.controller,
                accessibilityLabel: AppStrings.chatMessageInput,
                accessibilityHint: accessibilityHint,
                embedAccessibilityLabel: { node in node.display?.title ?? node.embedType ?? "" },
                embedAccessibilityActions: { _ in [] },
                onCanonicalMarkdownChange: { [weak session] markdown in
                    session?.publishControllerState(canonicalMarkdown: markdown)
                },
                onFocusChange: { _ in },
                onSubmit: { }
            )
            adapter.onFocusChange = { [weak self] focused in self?.onFocusChange(focused) }
            adapter.onSubmit = { [weak self] in self?.onSubmit() }
        }
    }
}
#elseif canImport(AppKit)
import AppKit

struct NativeComposerEditorView: NSViewRepresentable {
    @ObservedObject var session: NativeComposerSession
    let isFocused: Binding<Bool>
    let isEditable: Bool
    let accessibilityHint: String
    var measuredHeight: Binding<CGFloat> = .constant(0)
    var piiDecorations: [NativeComposerPIIDecoration] = []
    var onExcludePII: (String) -> Void = { _ in }
    let onSubmit: () -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(session: session, accessibilityHint: accessibilityHint)
    }

    func makeNSView(context: Context) -> NSScrollView {
        let textView = context.coordinator.adapter.makePlatformView()
        textView.drawsBackground = false
        textView.textContainerInset = NSSize(
            width: .spacing6,
            height: MessageComposerMetric.editorVerticalInset
        )
        let scrollView = NSScrollView()
        scrollView.drawsBackground = false
        scrollView.hasVerticalScroller = false
        scrollView.documentView = textView
        return scrollView
    }

    func updateNSView(_ scrollView: NSScrollView, context: Context) {
        guard let textView = scrollView.documentView as? NSTextView else { return }
        context.coordinator.onFocusChange = { isFocused.wrappedValue = $0 }
        context.coordinator.onSubmit = onSubmit
        context.coordinator.adapter.synchronize(textView)
        textView.isEditable = isEditable
        if isFocused.wrappedValue {
            textView.window?.makeFirstResponder(textView)
        }
    }

    @MainActor
    final class Coordinator {
        let adapter: NativeComposerTextView
        var onFocusChange: (Bool) -> Void = { _ in }
        var onSubmit: () -> Void = { }

        init(session: NativeComposerSession, accessibilityHint: String) {
            adapter = NativeComposerTextView(
                controller: session.controller,
                accessibilityLabel: AppStrings.chatMessageInput,
                accessibilityHint: accessibilityHint,
                embedAccessibilityLabel: { node in node.display?.title ?? node.embedType ?? "" },
                embedAccessibilityActions: { _ in [] },
                onCanonicalMarkdownChange: { [weak session] markdown in
                    session?.publishControllerState(canonicalMarkdown: markdown)
                },
                onFocusChange: { _ in },
                onSubmit: { }
            )
            adapter.onFocusChange = { [weak self] focused in self?.onFocusChange(focused) }
            adapter.onSubmit = { [weak self] in self?.onSubmit() }
        }
    }
}
#endif
