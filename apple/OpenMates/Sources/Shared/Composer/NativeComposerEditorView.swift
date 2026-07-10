// SwiftUI bridge for the production TextKit 2 composer surface.
// The host supplies one long-lived NativeComposerSession as document authority.
// A coordinator retains stable adapter and platform-view identities across redraws.
// Focus and canonical changes flow through the session without reparsing on edits.
// Localized accessibility and host submit behavior remain explicit inputs.

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
    let isFocused: FocusState<Bool>.Binding
    let accessibilityHint: String
    let onSubmit: () -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(session: session, accessibilityHint: accessibilityHint)
    }

    func makeUIView(context: Context) -> UITextView {
        let textView = context.coordinator.adapter.makePlatformView()
        textView.backgroundColor = .clear
        textView.isScrollEnabled = true
        textView.textContainerInset = UIEdgeInsets(top: 14, left: 12, bottom: 14, right: 12)
        textView.font = UIFont(name: FontRegistration.fontFamily, size: 16)
        textView.textColor = UIColor(Color.fontPrimary)
        return textView
    }

    func updateUIView(_ textView: UITextView, context: Context) {
        context.coordinator.onFocusChange = { isFocused.wrappedValue = $0 }
        context.coordinator.onSubmit = onSubmit
        context.coordinator.adapter.synchronize(textView)
        if isFocused.wrappedValue, !textView.isFirstResponder {
            textView.becomeFirstResponder()
        } else if !isFocused.wrappedValue, textView.isFirstResponder {
            textView.resignFirstResponder()
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
                onCanonicalMarkdownChange: { [weak session] _ in session?.publishControllerState() },
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
    let isFocused: FocusState<Bool>.Binding
    let accessibilityHint: String
    let onSubmit: () -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(session: session, accessibilityHint: accessibilityHint)
    }

    func makeNSView(context: Context) -> NSScrollView {
        let textView = context.coordinator.adapter.makePlatformView()
        textView.drawsBackground = false
        textView.textContainerInset = NSSize(width: 12, height: 14)
        let scrollView = NSScrollView()
        scrollView.drawsBackground = false
        scrollView.hasVerticalScroller = true
        scrollView.documentView = textView
        return scrollView
    }

    func updateNSView(_ scrollView: NSScrollView, context: Context) {
        guard let textView = scrollView.documentView as? NSTextView else { return }
        context.coordinator.onFocusChange = { isFocused.wrappedValue = $0 }
        context.coordinator.onSubmit = onSubmit
        context.coordinator.adapter.synchronize(textView)
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
                onCanonicalMarkdownChange: { [weak session] _ in session?.publishControllerState() },
                onFocusChange: { _ in },
                onSubmit: { }
            )
            adapter.onFocusChange = { [weak self] focused in self?.onFocusChange(focused) }
            adapter.onSubmit = { [weak self] in self?.onSubmit() }
        }
    }
}
#endif
