// SvgEmbedRenderer — the visual rendering of an SVG code embed (preview and
// fullscreen). Like the web, the source is never injected into a page: it goes
// through an <img> with a data: URL inside a web view with JavaScript off, a
// CSP of `default-src 'none'; img-src data:` and every navigation cancelled, so
// scripts and external resources cannot run or load. The web does not
// sanitise the SVG (the <img> context is the boundary), so there is no rule to
// share with the core. While the embed streams, the core's progressiveSvg
// (port of progressiveSvg.ts) closes the partial source; nil keeps the last
// good frame, like the web.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/code/SvgEmbedImage.svelte
//          frontend/packages/ui/src/components/embeds/code/CodeEmbedPreview.svelte (showSvgImage)
//          frontend/packages/ui/src/components/embeds/code/CodeEmbedFullscreen.svelte (previewKind svg)
//          frontend/packages/ui/src/components/embeds/code/progressiveSvg.ts (svgToDataUrl)
//          frontend/packages/ui/src/components/embeds/code/interactiveHtmlSandbox.ts (resolveCodePreviewKind)
// CSS:     SvgEmbedImage.svelte <style>: .svg-embed-image, img, .svg-embed-pending
// Tokens:  Color.grey0, SpacingTokens (spacing4), Font.omXs, Color.fontSecondary
// ────────────────────────────────────────────────────────────────────

import SwiftUI
import WebKit

/// Pure decisions for SVG code embeds.
enum SvgEmbedDocument {
    static let maxSourceBytes = 2_000_000

    /// `resolveCodePreviewKind(...) === 'svg'`.
    static func isSvg(language: String?, filename: String?, code: String) -> Bool {
        let lang = (language ?? "").lowercased()
        if lang == "svg" { return true }
        if (filename ?? "").lowercased().hasSuffix(".svg") { return true }
        return lang == "xml" && isStandaloneSvg(code)
    }

    static func isStandaloneSvg(_ code: String) -> Bool {
        let trimmed = code.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return trimmed.hasPrefix("<svg") || (trimmed.hasPrefix("<?xml") && trimmed.contains("<svg"))
    }

    /// `svgToDataUrl`: adds the SVG namespace when the root tag lacks it.
    static func prepared(_ source: String) -> String? {
        guard source.utf8.count <= maxSourceBytes else { return nil }
        guard let range = source.range(of: "<svg", options: [.caseInsensitive]) else { return nil }
        let tagEnd = source[range.upperBound...].firstIndex(of: ">") ?? source.endIndex
        let rootTag = source[range.lowerBound..<tagEnd]
        if rootTag.range(of: #"\sxmlns\s*="#, options: .regularExpression) != nil { return source }
        var result = source
        result.replaceSubrange(range, with: #"<svg xmlns="http://www.w3.org/2000/svg""#)
        return result
    }

    /// The page the web view loads: one <img>, nothing else.
    static func html(for source: String) -> String? {
        guard let svg = prepared(source), let data = svg.data(using: .utf8) else { return nil }
        let src = "data:image/svg+xml;base64,\(data.base64EncodedString())"
        return """
        <!doctype html><html><head><meta charset="utf-8">\
        <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'">\
        <meta name="viewport" content="width=device-width, initial-scale=1">\
        <style>html,body{margin:0;height:100%;background:transparent}\
        body{display:flex;align-items:center;justify-content:center}\
        img{max-width:100%;max-height:100%;object-fit:contain;-webkit-user-select:none}</style>\
        </head><body><img alt="" src="\(src)"></body></html>
        """
    }
}

struct SvgEmbedRenderer: View {
    let code: String
    let title: String
    let status: EmbedStatus
    @State private var frameHTML: String?

    var body: some View {
        ZStack {
            Color.grey0
            if let html = frameHTML {
                SvgImageWebView(html: html)
                    .padding(.spacing4)
                    .accessibilityElement(children: .ignore)
                    .accessibilityLabel(title)
                    .accessibilityIdentifier("svg-embed-image")
            } else if status == .processing {
                Text(LocalizationManager.shared.text("common.processing"))
                    .font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
                    .accessibilityIdentifier("svg-embed-pending")
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .clipped()
        .accessibilityIdentifier("svg-embed-visual")
        .onAppear { refreshFrame() }
        .onChange(of: code) { refreshFrame() }
        .onChange(of: status) { refreshFrame() }
    }

    /// Repairs the streaming source in the core; a nil document keeps the last frame.
    private func refreshFrame() {
        guard let document = progressiveSvg(source: code, complete: status != .processing),
              let html = SvgEmbedDocument.html(for: document) else { return }
        frameHTML = html
    }
}

@MainActor
private enum SvgWebViewFactory {
    final class Coordinator: NSObject, WKNavigationDelegate {
        var loadedHTML = ""
        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                     decisionHandler: @escaping @MainActor @Sendable (WKNavigationActionPolicy) -> Void) {
            // Only the initial load of our own HTML; every link is cancelled.
            let isInitial = action.navigationType == .other && action.request.url?.scheme == "about"
            decisionHandler(isInitial ? .allow : .cancel)
        }
    }

    static func make(coordinator: Coordinator) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        configuration.defaultWebpagePreferences.allowsContentJavaScript = false
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.navigationDelegate = coordinator
        #if os(iOS)
        view.isOpaque = false
        view.backgroundColor = .clear
        view.scrollView.isScrollEnabled = false
        #elseif os(macOS)
        view.setValue(false, forKey: "drawsBackground")
        #endif
        return view
    }

    static func load(_ html: String, in view: WKWebView, coordinator: Coordinator) {
        guard coordinator.loadedHTML != html else { return }
        coordinator.loadedHTML = html
        view.loadHTMLString(html, baseURL: nil)
    }
}

#if os(iOS)
private struct SvgImageWebView: UIViewRepresentable {
    let html: String
    func makeCoordinator() -> SvgWebViewFactory.Coordinator { SvgWebViewFactory.Coordinator() }
    func makeUIView(context: Context) -> WKWebView { SvgWebViewFactory.make(coordinator: context.coordinator) }
    func updateUIView(_ view: WKWebView, context: Context) {
        SvgWebViewFactory.load(html, in: view, coordinator: context.coordinator)
    }
}
#elseif os(macOS)
private struct SvgImageWebView: NSViewRepresentable {
    let html: String
    func makeCoordinator() -> SvgWebViewFactory.Coordinator { SvgWebViewFactory.Coordinator() }
    func makeNSView(context: Context) -> WKWebView { SvgWebViewFactory.make(coordinator: context.coordinator) }
    func updateNSView(_ view: WKWebView, context: Context) {
        SvgWebViewFactory.load(html, in: view, coordinator: context.coordinator)
    }
}
#endif
