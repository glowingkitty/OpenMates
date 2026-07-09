// Local WebView-backed message editor bridge for the Apple composer.
// The host shell remains native, while the editable document surface runs the
// same browser editing model that the web composer depends on. Bridge events are
// text-only so diagnostics and Swift state never log raw private message bodies.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/enter_message/MessageInput.svelte
//          frontend/packages/ui/src/components/enter_message/editorConfig.ts
// CSS:     frontend/packages/ui/src/components/enter_message/MessageInput.styles.css
//          Classes: .ProseMirror, .message-input-editor, .message-field
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
import WebKit
#if os(iOS)
import UIKit
#endif

enum TiptapComposerResource {
    static let subdirectory = "TiptapComposer"
    static let indexResource = "index"
    static let indexExtension = "html"

    static func indexURL(in bundle: Bundle = .main) -> URL? {
        bundle.url(forResource: indexResource, withExtension: indexExtension, subdirectory: subdirectory)
    }
}

struct TiptapComposerTheme: Equatable {
    var fontPrimary = "#1f2933"
    var fontTertiary = "rgba(31, 41, 51, 0.58)"
    var buttonPrimary = "#ff553b"

    var dictionary: [String: String] {
        [
            "fontPrimary": fontPrimary,
            "fontTertiary": fontTertiary,
            "buttonPrimary": buttonPrimary,
        ]
    }
}

struct TiptapComposerEmbedCommand: Equatable {
    var id: String
    var type: String
    var status: String = "finished"
    var contentRef: String? = nil
    var uploadEmbedId: String? = nil
    var filename: String? = nil
    var duration: String? = nil
    var transcript: String? = nil
    var mimeType: String? = nil
    var uploadError: String? = nil
    var referenceType: String? = nil

    var dictionary: [String: Any] {
        var attrs: [String: Any] = [
            "id": id,
            "type": type,
            "status": status
        ]
        if let contentRef { attrs["contentRef"] = contentRef }
        if let uploadEmbedId { attrs["uploadEmbedId"] = uploadEmbedId }
        if let filename { attrs["filename"] = filename }
        if let duration { attrs["duration"] = duration }
        if let transcript { attrs["transcript"] = transcript }
        if let mimeType { attrs["mimeType"] = mimeType }
        if let uploadError { attrs["uploadError"] = uploadError }
        if let referenceType { attrs["referenceType"] = referenceType }
        return attrs
    }
}

enum TiptapComposerCommand: Equatable {
    case focus
    case blur
    case clear
    case setContent(String)
    case setPlaceholder(String)
    case setTheme(TiptapComposerTheme)
    case setCompact(Bool)
    case setDisabled(Bool)
    case insertEmbed(TiptapComposerEmbedCommand)
    case updateEmbed(id: String, attrs: TiptapComposerEmbedCommand)
    case removeEmbed(String)
    case serializeMarkdown
    case getDiagnostics

    var payload: [String: Any] {
        switch self {
        case .focus:
            return ["type": "focus"]
        case .blur:
            return ["type": "blur"]
        case .clear:
            return ["type": "clear"]
        case .setContent(let text):
            return ["type": "setContent", "text": text]
        case .setPlaceholder(let placeholder):
            return ["type": "setPlaceholder", "placeholder": placeholder]
        case .setTheme(let theme):
            return ["type": "setTheme", "theme": theme.dictionary]
        case .setCompact(let compact):
            return ["type": "setCompact", "compact": compact]
        case .setDisabled(let disabled):
            return ["type": "setDisabled", "disabled": disabled]
        case .insertEmbed(let embed):
            return ["type": "insertEmbed", "attrs": embed.dictionary]
        case .updateEmbed(let id, let attrs):
            return ["type": "updateEmbed", "id": id, "attrs": attrs.dictionary]
        case .removeEmbed(let id):
            return ["type": "removeEmbed", "id": id]
        case .serializeMarkdown:
            return ["type": "serializeMarkdown"]
        case .getDiagnostics:
            return ["type": "getDiagnostics"]
        }
    }

    var script: String? {
        guard JSONSerialization.isValidJSONObject(payload),
              let data = try? JSONSerialization.data(withJSONObject: payload),
              let json = String(data: data, encoding: .utf8) else {
            return nil
        }
        return "window.OpenMatesComposer && window.OpenMatesComposer.receive(\(json));"
    }
}

struct TiptapComposerBridgeMessage: Decodable, Equatable {
    let type: String
    let text: String?
    let height: Double?
    let message: String?
    let embedCount: Int?
    let blockingEmbedCount: Int?
    let embedId: String?
    let embedType: String?
    let embedStatus: String?
    let extensions: [String]?
    let embedCommandNames: [String]?

    static func decode(_ body: Any) -> TiptapComposerBridgeMessage? {
        guard JSONSerialization.isValidJSONObject(body),
              let data = try? JSONSerialization.data(withJSONObject: body) else {
            return nil
        }
        return try? JSONDecoder().decode(TiptapComposerBridgeMessage.self, from: data)
    }
}

struct TiptapComposerWebView: View {
    @Binding var text: String
    let isFocused: FocusState<Bool>.Binding
    var compact: Bool
    var placeholder: String
    var minHeight: CGFloat
    var accessibilityHint: String
    var onSubmit: () -> Void

    @State private var measuredHeight: CGFloat = 40
    @State private var diagnosticEmbedCount: Int?

    private var editorHeight: CGFloat {
        compact ? minHeight : max(minHeight, measuredHeight)
    }

    var body: some View {
        PlatformTiptapComposerWebView(
            text: $text,
            isFocused: isFocused,
            compact: compact,
            placeholder: placeholder,
            accessibilityHint: accessibilityHint,
            embedCount: $diagnosticEmbedCount,
            measuredHeight: $measuredHeight,
            onSubmit: onSubmit
        )
        .frame(maxWidth: .infinity, minHeight: editorHeight, maxHeight: compact ? minHeight : nil)
        .accessibilityLabel(AppStrings.chatMessageInput)
        .accessibilityHint(accessibilityHint)
        .accessibilityIdentifier("message-editor")
        .accessibilityValue(accessibilityValue)
        .simultaneousGesture(
            TapGesture().onEnded {
                isFocused.wrappedValue = true
            }
        )
    }

    private var accessibilityValue: String {
        guard let diagnosticEmbedCount else { return text }
        return "\(text)\nembedCount=\(diagnosticEmbedCount)"
    }
}

#if os(iOS)
private typealias PlatformViewRepresentable = UIViewRepresentable
private typealias PlatformView = UIView
#elseif os(macOS)
private typealias PlatformViewRepresentable = NSViewRepresentable
private typealias PlatformView = NSView
#endif

private struct PlatformTiptapComposerWebView: PlatformViewRepresentable {
    @Binding var text: String
    let isFocused: FocusState<Bool>.Binding
    var compact: Bool
    var placeholder: String
    var accessibilityHint: String
    @Binding var embedCount: Int?
    @Binding var measuredHeight: CGFloat
    var onSubmit: () -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(parent: self)
    }

    #if os(iOS)
    func makeUIView(context: Context) -> WKWebView { makeWebView(context: context) }

    func updateUIView(_ webView: WKWebView, context: Context) {
        updateWebView(webView, context: context)
    }
    #elseif os(macOS)
    func makeNSView(context: Context) -> WKWebView { makeWebView(context: context) }

    func updateNSView(_ webView: WKWebView, context: Context) {
        updateWebView(webView, context: context)
    }
    #endif

    private func makeWebView(context: Context) -> WKWebView {
        let contentController = WKUserContentController()
        contentController.add(context.coordinator, name: Coordinator.messageHandlerName)

        let configuration = WKWebViewConfiguration()
        configuration.userContentController = contentController
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        configuration.suppressesIncrementalRendering = false

        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.isOpaque = false
        #if os(iOS)
        webView.backgroundColor = .clear
        webView.scrollView.backgroundColor = .clear
        webView.scrollView.isScrollEnabled = false
        webView.scrollView.bounces = false
        webView.accessibilityIdentifier = "message-editor"
        webView.accessibilityLabel = AppStrings.chatMessageInput
        webView.accessibilityHint = accessibilityHint
        webView.accessibilityValue = text
        let tapRecognizer = UITapGestureRecognizer(target: context.coordinator, action: #selector(Coordinator.handleWebViewTap))
        tapRecognizer.cancelsTouchesInView = false
        webView.addGestureRecognizer(tapRecognizer)
        #elseif os(macOS)
        webView.setValue(false, forKey: "drawsBackground")
        webView.setAccessibilityIdentifier("message-editor")
        webView.setAccessibilityLabel(AppStrings.chatMessageInput)
        webView.setAccessibilityHelp(accessibilityHint)
        webView.setAccessibilityValue(text)
        #endif
        context.coordinator.webView = webView

        if let url = TiptapComposerResource.indexURL() {
            webView.loadFileURL(url, allowingReadAccessTo: url.deletingLastPathComponent())
        } else {
            context.coordinator.reportMissingResource()
        }

        return webView
    }

    private func updateWebView(_ webView: WKWebView, context: Context) {
        context.coordinator.parent = self
        #if os(iOS)
        webView.accessibilityHint = accessibilityHint
        #elseif os(macOS)
        webView.setAccessibilityHelp(accessibilityHint)
        #endif
        context.coordinator.updateAccessibilityValue(text: text)
        context.coordinator.sync(webView: webView)
    }

    final class Coordinator: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
        static let messageHandlerName = "openmatesComposer"

        var parent: PlatformTiptapComposerWebView
        weak var webView: WKWebView?
        private var ready = false
        private var lastSentText: String?
        private var lastSentPlaceholder = ""
        private var lastSentCompact: Bool?
        private var lastFocusRequest: Bool?
        private var lastEmbedCount: Int?

        init(parent: PlatformTiptapComposerWebView) {
            self.parent = parent
            super.init()
        }

        func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
            guard let bridgeMessage = TiptapComposerBridgeMessage.decode(message.body) else { return }
            switch bridgeMessage.type {
            case "ready":
                ready = true
                sync(webView: webView)
            case "contentChanged":
                guard let text = bridgeMessage.text else { return }
                lastSentText = text
                if parent.text != text {
                    parent.text = text
                }
                updateAccessibilityValue(text: text, embedCount: bridgeMessage.embedCount)
            case "submit":
                parent.onSubmit()
            case "heightChanged":
                if let height = bridgeMessage.height {
                    parent.measuredHeight = CGFloat(height)
                }
            case "focus":
                if !parent.isFocused.wrappedValue {
                    parent.isFocused.wrappedValue = true
                }
            case "blur":
                if parent.isFocused.wrappedValue {
                    parent.isFocused.wrappedValue = false
                }
            case "error":
                NativeDiagnostics.warning("Tiptap composer bridge error", category: "apple_composer")
            case "diagnostics", "serializedMarkdown", "embedInserted", "embedUpdated", "embedRemoved", "blockingEmbedsChanged":
                if let text = bridgeMessage.text {
                    updateAccessibilityValue(text: text, embedCount: bridgeMessage.embedCount)
                }
            default:
                break
            }
        }

        func updateAccessibilityValue(text: String, embedCount: Int? = nil) {
            if let embedCount {
                lastEmbedCount = embedCount
                parent.embedCount = embedCount
            }
            let value = accessibilityValue(text: text, embedCount: lastEmbedCount)
            #if os(iOS)
            webView?.accessibilityValue = value
            #elseif os(macOS)
            webView?.setAccessibilityValue(value)
            #endif
        }

        private func accessibilityValue(text: String, embedCount: Int?) -> String {
            guard let embedCount else { return text }
            return "\(text)\nembedCount=\(embedCount)"
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            ready = true
            sync(webView: webView)
        }

        #if os(iOS)
        @objc func handleWebViewTap() {
            if !parent.isFocused.wrappedValue {
                parent.isFocused.wrappedValue = true
            }
            if let webView {
                send(.focus, to: webView)
            }
        }
        #endif

        func webView(
            _ webView: WKWebView,
            decidePolicyFor navigationAction: WKNavigationAction,
            decisionHandler: @escaping @MainActor @Sendable (WKNavigationActionPolicy) -> Void
        ) {
            guard let url = navigationAction.request.url else {
                decisionHandler(.cancel)
                return
            }
            if url.isFileURL || url.scheme == "about" {
                decisionHandler(.allow)
            } else {
                NativeDiagnostics.warning("Tiptap composer blocked non-local navigation", category: "apple_composer")
                decisionHandler(.cancel)
            }
        }

        func sync(webView: WKWebView?) {
            guard ready, let webView else { return }

            if lastSentPlaceholder != parent.placeholder {
                lastSentPlaceholder = parent.placeholder
                send(.setPlaceholder(parent.placeholder), to: webView)
            }

            if lastSentText != parent.text {
                lastSentText = parent.text
                send(.setContent(parent.text), to: webView)
            }

            if lastSentCompact != parent.compact {
                lastSentCompact = parent.compact
                send(.setCompact(parent.compact), to: webView)
            }

            let focused = parent.isFocused.wrappedValue
            if lastFocusRequest != focused {
                lastFocusRequest = focused
                send(focused ? .focus : .blur, to: webView)
            }

            send(.setTheme(TiptapComposerTheme()), to: webView)
        }

        func reportMissingResource() {
            NativeDiagnostics.warning("Tiptap composer resource missing", category: "apple_composer")
        }

        private func send(_ command: TiptapComposerCommand, to webView: WKWebView) {
            guard let script = command.script else { return }
            webView.evaluateJavaScript(script) { _, error in
                if error != nil {
                    NativeDiagnostics.warning("Tiptap composer command failed", category: "apple_composer")
                }
            }
        }
    }
}
