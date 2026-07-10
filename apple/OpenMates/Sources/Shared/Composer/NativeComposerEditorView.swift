// SwiftUI bridge for the production TextKit 2 composer surface.
// Canonical markdown bindings remain the host boundary during staged cutover.
// A coordinator owns stable controller, adapter, and platform-view identities.
// Parse failures preserve source as text and emit privacy-safe diagnostics.
// Focus and content changes flow back to existing Apple host state.

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
    @Binding var canonicalMarkdown: String
    let isFocused: FocusState<Bool>.Binding
    let accessibilityHint: String
    let onSubmit: () -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(canonicalMarkdown: canonicalMarkdown, accessibilityHint: accessibilityHint)
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
        context.coordinator.onCanonicalMarkdownChange = { canonicalMarkdown = $0 }
        context.coordinator.onFocusChange = { isFocused.wrappedValue = $0 }
        context.coordinator.onSubmit = onSubmit
        context.coordinator.loadExternalMarkdownIfNeeded(canonicalMarkdown)
        context.coordinator.adapter.synchronize(textView)
        if isFocused.wrappedValue, !textView.isFirstResponder {
            textView.becomeFirstResponder()
        } else if !isFocused.wrappedValue, textView.isFirstResponder {
            textView.resignFirstResponder()
        }
    }

    @MainActor
    final class Coordinator {
        let controller: NativeComposerController
        let adapter: NativeComposerTextView
        var onCanonicalMarkdownChange: (String) -> Void = { _ in }
        var onFocusChange: (Bool) -> Void = { _ in }
        var onSubmit: () -> Void = { }
        private var synchronizedMarkdown: String

        init(canonicalMarkdown: String, accessibilityHint: String) {
            controller = Self.makeController(canonicalMarkdown: canonicalMarkdown)
            synchronizedMarkdown = canonicalMarkdown
            adapter = NativeComposerTextView(
                controller: controller,
                accessibilityLabel: AppStrings.chatMessageInput,
                accessibilityHint: accessibilityHint,
                embedAccessibilityLabel: { node in node.display?.title ?? node.embedType ?? "" },
                embedAccessibilityActions: { _ in [] },
                onCanonicalMarkdownChange: { _ in },
                onFocusChange: { _ in },
                onSubmit: { }
            )
            adapter.onCanonicalMarkdownChange = { [weak self] markdown in
                self?.synchronizedMarkdown = markdown
                self?.onCanonicalMarkdownChange(markdown)
            }
            adapter.onFocusChange = { [weak self] focused in
                self?.onFocusChange(focused)
            }
            adapter.onSubmit = { [weak self] in self?.onSubmit() }
        }

        func loadExternalMarkdownIfNeeded(_ markdown: String) {
            guard markdown != synchronizedMarkdown else { return }
            do {
                try controller.loadDocument(ComposerMarkdownAdapter.parse(markdown))
                synchronizedMarkdown = markdown
            } catch {
                NativeDiagnostics.warning(
                    "Native composer external synchronization failed: \(type(of: error))",
                    category: "apple_composer"
                )
            }
        }

        private static func makeController(canonicalMarkdown: String) -> NativeComposerController {
            do {
                let document = try ComposerMarkdownAdapter.parse(canonicalMarkdown)
                return try NativeComposerController(
                    document: document,
                    selection: NSRange(location: canonicalMarkdown.utf16.count, length: 0)
                )
            } catch {
                NativeDiagnostics.warning(
                    "Native composer initial parse failed: \(type(of: error))",
                    category: "apple_composer"
                )
                let fallback = ComposerDocumentV1(
                    version: 1,
                    nodes: [.text(id: "composer:text:recovery", source: canonicalMarkdown)]
                )
                do {
                    return try NativeComposerController(
                        document: fallback,
                        selection: NSRange(location: canonicalMarkdown.utf16.count, length: 0)
                    )
                } catch {
                    preconditionFailure("Valid native composer recovery document was rejected")
                }
            }
        }
    }
}
#elseif canImport(AppKit)
import AppKit

struct NativeComposerEditorView: NSViewRepresentable {
    @Binding var canonicalMarkdown: String
    let isFocused: FocusState<Bool>.Binding
    let accessibilityHint: String
    let onSubmit: () -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(canonicalMarkdown: canonicalMarkdown, accessibilityHint: accessibilityHint)
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
        context.coordinator.onCanonicalMarkdownChange = { canonicalMarkdown = $0 }
        context.coordinator.onFocusChange = { isFocused.wrappedValue = $0 }
        context.coordinator.onSubmit = onSubmit
        context.coordinator.loadExternalMarkdownIfNeeded(canonicalMarkdown)
        context.coordinator.adapter.synchronize(textView)
        if isFocused.wrappedValue {
            textView.window?.makeFirstResponder(textView)
        }
    }

    @MainActor
    final class Coordinator {
        let controller: NativeComposerController
        let adapter: NativeComposerTextView
        var onCanonicalMarkdownChange: (String) -> Void = { _ in }
        var onFocusChange: (Bool) -> Void = { _ in }
        var onSubmit: () -> Void = { }
        private var synchronizedMarkdown: String

        init(canonicalMarkdown: String, accessibilityHint: String) {
            controller = Self.makeController(canonicalMarkdown: canonicalMarkdown)
            synchronizedMarkdown = canonicalMarkdown
            adapter = NativeComposerTextView(
                controller: controller,
                accessibilityLabel: AppStrings.chatMessageInput,
                accessibilityHint: accessibilityHint,
                embedAccessibilityLabel: { node in node.display?.title ?? node.embedType ?? "" },
                embedAccessibilityActions: { _ in [] },
                onCanonicalMarkdownChange: { _ in },
                onFocusChange: { _ in },
                onSubmit: { }
            )
            adapter.onCanonicalMarkdownChange = { [weak self] markdown in
                self?.synchronizedMarkdown = markdown
                self?.onCanonicalMarkdownChange(markdown)
            }
            adapter.onFocusChange = { [weak self] focused in self?.onFocusChange(focused) }
            adapter.onSubmit = { [weak self] in self?.onSubmit() }
        }

        func loadExternalMarkdownIfNeeded(_ markdown: String) {
            guard markdown != synchronizedMarkdown else { return }
            do {
                try controller.loadDocument(ComposerMarkdownAdapter.parse(markdown))
                synchronizedMarkdown = markdown
            } catch {
                NativeDiagnostics.warning(
                    "Native composer external synchronization failed: \(type(of: error))",
                    category: "apple_composer"
                )
            }
        }

        private static func makeController(canonicalMarkdown: String) -> NativeComposerController {
            do {
                let document = try ComposerMarkdownAdapter.parse(canonicalMarkdown)
                return try NativeComposerController(
                    document: document,
                    selection: NSRange(location: canonicalMarkdown.utf16.count, length: 0)
                )
            } catch {
                NativeDiagnostics.warning(
                    "Native composer initial parse failed: \(type(of: error))",
                    category: "apple_composer"
                )
                let fallback = ComposerDocumentV1(
                    version: 1,
                    nodes: [.text(id: "composer:text:recovery", source: canonicalMarkdown)]
                )
                do {
                    return try NativeComposerController(
                        document: fallback,
                        selection: NSRange(location: canonicalMarkdown.utf16.count, length: 0)
                    )
                } catch {
                    preconditionFailure("Valid native composer recovery document was rejected")
                }
            }
        }
    }
}
#endif
