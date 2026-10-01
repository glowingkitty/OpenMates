// Document page renderer for generated DOCX images and legacy HTML embeds.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/docs/DocsEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/docs/DocsEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/docs/docsEmbedContent.ts
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.rendering.assistant-document-convergence

import Foundation
// Specification: specifications/features/chat-share-settings/specification.yml
// Assertions: chat-share-settings.shared-link-open
import SwiftUI
import WebKit
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

/// Only already decrypted, inline page images enter this renderer. Encrypted
/// artifact keys are deliberately not interpreted as network URLs here.
struct DocumentCanvasSource {
    let pageURLs: [String]
    let encryptedPageKeys: [String]
    let aesKey: String?
    let html: String

    init(data: [String: AnyCodable]?) {
        let raw = data ?? [:]
        let pages = (raw["preview_page_urls"]?.value as? [String: String])
            ?? (raw["previewPageUrls"]?.value as? [String: String])
            ?? (raw["preview_page_urls"]?.value as? [String: Any])?.compactMapValues { $0 as? String }
            ?? [:]
        pageURLs = pages.keys
            .compactMap { key -> (Int, String)? in
                guard let number = Int(key), number > 0,
                      let value = pages[key],
                      Self.isAllowedPageURL(value) else { return nil }
                return (number, value)
            }
            .sorted { $0.0 < $1.0 }
            .map { $0.1 }
        let encrypted = (raw["screenshot_s3_keys"]?.value as? [String: String])
            ?? (raw["screenshot_s3_keys"]?.value as? [String: Any])?.compactMapValues { $0 as? String }
            ?? [:]
        encryptedPageKeys = encrypted.keys
            .compactMap { key -> (Int, String)? in
                guard let number = Int(key), number > 0,
                      let value = encrypted[key], !value.isEmpty,
                      value.count < 1024 else { return nil }
                return (number, value)
            }
            .sorted { $0.0 < $1.0 }
            .prefix(50)
            .map { $0.1 }
        aesKey = raw["aes_key"]?.value as? String
        html = (raw["html"]?.value as? String)
            ?? (raw["html_content"]?.value as? String)
            ?? (raw["content"]?.value as? String)
            ?? ""
    }

    /// Web previews use percent-encoded SVG; real decrypted pages use raster data.
    /// No remote URL or local file path may be loaded by the private web view.
    static func isAllowedPageURL(_ url: String) -> Bool {
        guard url.count <= 8_000_000 else { return false }
        if url.range(of: #"^data:image/(png|jpeg|webp|gif);base64,[A-Za-z0-9+/=]+$"#,
                     options: [.regularExpression, .caseInsensitive]) != nil {
            return true
        }
        guard url.lowercased().hasPrefix("data:image/svg+xml;charset=utf-8,"),
              !url.contains(where: { $0 == "\"" || $0 == "<" || $0 == ">" || $0.isWhitespace }),
              let svg = url.components(separatedBy: ",").dropFirst().joined(separator: ",").removingPercentEncoding,
              svg.utf8.count <= 2_000_000,
              svg.lowercased().contains("<svg"),
              svg.range(of: #"<\s*(script|style|foreignobject|iframe|image|use|a)\b|\bon[a-z]+\s*=|\b(?:href|src)\s*=|url\s*\("#,
                        options: [.regularExpression, .caseInsensitive]) == nil else { return false }
        return true
    }

    /// Semantic tags only. All document-owned attributes, styles and URLs are
    /// dropped; rendering is additionally confined by CSP and disabled JS.
    static func sanitizeHTML(_ html: String) -> String {
        let blocked = html.replacingOccurrences(
            of: #"(?is)<\s*(script|style|iframe|object|embed|form|svg|math|template)\b[^>]*>.*?<\s*/\s*\1\s*>"#,
            with: "", options: .regularExpression
        )
        let allowed: Set<String> = [
            "h1", "h2", "h3", "h4", "h5", "h6", "p", "blockquote", "pre", "code",
            "ul", "ol", "li", "table", "thead", "tbody", "tfoot", "tr", "th", "td",
            "caption", "strong", "em", "b", "i", "u", "s", "del", "ins", "mark",
            "sub", "sup", "small", "abbr", "cite", "dfn", "kbd", "samp", "var",
            "br", "hr", "img", "article", "section", "header", "footer", "main",
            "figure", "figcaption", "dl", "dt", "dd", "div", "span"
        ]
        let pattern = #"<[^>]*>"#
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return "" }
        let range = NSRange(blocked.startIndex..<blocked.endIndex, in: blocked)
        let matches = regex.matches(in: blocked, range: range)
        var output = ""
        var cursor = blocked.startIndex
        for match in matches {
            guard let tokenRange = Range(match.range, in: blocked) else { continue }
            output += blocked[cursor..<tokenRange.lowerBound]
            let token = String(blocked[tokenRange])
            if let name = token.range(of: #"^<\s*/?\s*([a-z][a-z0-9]*)"#,
                                      options: [.regularExpression, .caseInsensitive]) {
                let head = String(token[name])
                let tag = head.lowercased().replacingOccurrences(of: #"[^a-z0-9]"#, with: "",
                                                                   options: [.regularExpression])
                if allowed.contains(tag) {
                    if tag == "img" {
                        if let srcRange = token.range(of: #"\bsrc\s*=\s*["'][^"']+["']"#,
                                                      options: [.regularExpression, .caseInsensitive]) {
                            let assignment = String(token[srcRange])
                            if let quote = assignment.firstIndex(where: { $0 == "\"" || $0 == "'" }) {
                                let src = String(assignment[assignment.index(after: quote)..<assignment.index(before: assignment.endIndex)])
                                if Self.isAllowedPageURL(src) {
                                    output += "<img src=\"\(src)\">"
                                }
                            }
                        }
                    } else {
                        output += token.hasPrefix("</") ? "</\(tag)>" : "<\(tag)>"
                    }
                }
            }
            cursor = tokenRange.upperBound
        }
        output += blocked[cursor...]
        return output
    }

    func documentHTML(preview: Bool, scale: CGFloat, pageURLs renderedPageURLs: [String]? = nil,
                      artifactFit: CGFloat = 1) -> String {
        let boundedScale = min(max(scale, 0.2), 2.5)
        let urls = renderedPageURLs ?? pageURLs
        // The web artifact branch first constrains each image to the viewer
        // width, then applies its zoom transform. Legacy HTML uses full A4.
        let paperScale = !preview && !urls.isEmpty ? boundedScale * artifactFit : boundedScale
        let pageWidth = Int((794 * paperScale).rounded())
        let pageHeight = Int((1123 * paperScale).rounded())
        let pageMarkup: String
        if !urls.isEmpty {
            let visibleURLs = preview ? Array(urls.prefix(1)) : urls
            pageMarkup = visibleURLs.map { url in
                """
                <div class="slot" style="width:\(pageWidth)px;height:\(pageHeight)px">
                  <img class="paper" src="\(url)" alt="">
                </div>
                """
            }.joined()
        } else if !encryptedPageKeys.isEmpty {
            pageMarkup = """
                <div class="slot" style="width:\(pageWidth)px;height:\(pageHeight)px">
                  <div class="paper"></div>
                </div>
                """
        } else {
            pageMarkup = """
                <div class="slot legacy" style="width:\(pageWidth)px;min-height:\(pageHeight)px">
                  <div class="paper document"><div class="doc-content">\(Self.sanitizeHTML(html))</div></div>
                </div>
                """
        }
        let canvas = preview ? "#e8e8e8" : "#3c3c3c"
        let inset = preview ? "20px" : "12px 24px 32px"
        return """
        <!doctype html><html><head>
        <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
        <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; connect-src 'none'">
        <style>
          *{box-sizing:border-box}html,body{margin:0;min-height:100%;width:100%}
          body{background:\(canvas);padding:\(inset);overflow:\(preview ? "hidden" : "auto")}
          .slot{position:relative;margin:0 auto \(preview ? "0" : "8px");flex:none}
          .paper{display:block;width:794px;height:1123px;background:#fff;transform:scale(\(paperScale));transform-origin:top left;box-shadow:0 3px 12px rgba(0,0,0,.25)}
          .document{height:auto;min-height:1123px;padding:96px 72px}
          .doc-content{font:16px/1.65 Calibri,Cambria,Georgia,serif;color:#202020;overflow-wrap:anywhere}
          .doc-content h1{font-size:28px;line-height:1.25;border-bottom:2px solid #e8e8e8;padding-bottom:10px;margin:0 0 20px}
          .doc-content h2{font-size:22px;line-height:1.3;margin:32px 0 10px}
          .doc-content h3{font-size:18px;margin:24px 0 8px}
          .doc-content p{margin:0 0 10px}.doc-content ul,.doc-content ol{padding-left:24px}
          .doc-content table{border-collapse:collapse;width:100%}.doc-content th,.doc-content td{border:1px solid #d0d0d0;padding:7px 12px}
          .doc-content th{background:#f2f2f2}.doc-content blockquote{border-left:3px solid #c0c0c0;margin:16px 8px;padding:4px 16px}
          .doc-content pre{white-space:pre-wrap;background:#f8f8f8;padding:14px 18px}
          .doc-content a{color:#1155cc}
        </style></head><body><div class="pages">\(pageMarkup)</div></body></html>
        """
    }
}

struct DocumentCanvasView: View {
    let source: DocumentCanvasSource
    let mode: EmbedDisplayMode
    @Environment(\.recipientMediaContext) private var recipientMediaContext

    var body: some View {
        if let recipientMediaContext {
            DocumentCanvasContent(source: source, mode: mode, scope: recipientMediaContext.namespace,
                                  generation: recipientMediaContext.generation, recipientMediaContext: recipientMediaContext)
        } else { OwnerDocumentCanvas(source: source, mode: mode) }
    }
}

private struct OwnerDocumentCanvas: View {
    let source: DocumentCanvasSource
    let mode: EmbedDisplayMode
    @ObservedObject private var offlineStore = OfflineStore.shared
    var body: some View {
        DocumentCanvasContent(source: source, mode: mode, scope: offlineStore.activeScopeId,
                              generation: offlineStore.scopeGeneration, recipientMediaContext: nil)
    }
}

private struct DocumentCanvasContent: View {
    let source: DocumentCanvasSource
    let mode: EmbedDisplayMode
    let scope: String?
    let generation: UUID
    let recipientMediaContext: RecipientMediaContext?
    @State private var zoomMultiplier: CGFloat = 1
    @State private var hydratedPageURLs: [String] = []
    @State private var hydratedGeneration: UUID?
    @State private var loadedPageIdentity: Int?

    private var displayedPageURLs: [String] {
        if !source.pageURLs.isEmpty { return source.pageURLs }
        return hydratedGeneration == generation ? hydratedPageURLs : []
    }

    var body: some View {
        GeometryReader { geometry in
            let available = max(geometry.size.width - (mode == .preview ? 40 : 48), 1)
            let fit = min(available / 794, mode == .preview ? 0.85 : 1)
            let scale = fit * zoomMultiplier
            let document = source.documentHTML(preview: mode == .preview, scale: scale,
                                               pageURLs: displayedPageURLs, artifactFit: fit)
            ZStack(alignment: .bottom) {
                DocumentCanvasWebView(
                    html: document,
                    preview: mode == .preview,
                    loadedIdentity: $loadedPageIdentity
                )
                if mode == .fullscreen {
                    HStack {
                        Button { zoomMultiplier = max(0.5, zoomMultiplier - 0.25) } label: {
                            Icon("minus", size: 18).frame(maxWidth: .infinity)
                        }
                        .accessibilityLabel(AppStrings.zoomOut)
                        Text("\(Int((scale * 100).rounded()))%")
                            .font(.omSmall).fontWeight(.semibold)
                            .padding(.horizontal, .spacing5)
                            .padding(.vertical, .spacing3)
                            .background(Color.grey0)
                            .clipShape(Capsule())
                        Button { zoomMultiplier = min(2.5, zoomMultiplier + 0.25) } label: {
                            Icon("plus", size: 18).frame(maxWidth: .infinity)
                        }
                        .accessibilityLabel(AppStrings.zoomIn)
                    }
                    .foregroundStyle(Color.fontPrimary)
                    .buttonStyle(.plain)
                    .frame(height: 44)
                    .background(Color.grey0)
                    .clipShape(Capsule())
                    .padding(.horizontal, .spacing6)
                    .padding(.bottom, .spacing3)
                    .shadow(color: .black.opacity(0.24), radius: 10, y: 4)
                }
            }
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier(mode == .preview ? "docs-document-preview" : "docs-document-fullscreen")
            .accessibilityValue(
                loadedPageIdentity == document.hashValue
                    ? "ready:\(document.hashValue)"
                    : "loading:\(document.hashValue)"
            )
        }
        .frame(height: mode == .preview ? 200 : 650)
        .task(id: "\(generation)-\(source.encryptedPageKeys.hashValue)-\(source.aesKey?.hashValue ?? 0)") {
            await hydrateEncryptedPages()
        }
    }

    @MainActor
    private func hydrateEncryptedPages() async {
        hydratedPageURLs = []
        hydratedGeneration = nil
        guard source.pageURLs.isEmpty,
              let aesKey = source.aesKey, !aesKey.isEmpty,
              !source.encryptedPageKeys.isEmpty,
              let scope else { return }
        if let recipientMediaContext {
            let keys = mode == .preview ? Array(source.encryptedPageKeys.prefix(1)) : source.encryptedPageKeys
            var pages: [String] = []
            for key in keys {
                do {
                    let bytes = try await recipientMediaContext.fetchAndDecrypt(s3Url: "", aesKeyHex: aesKey,
                        aesNonceHex: nil, encryption: S3MediaClient.noncePrefixedEncryption, s3Key: key)
                    guard bytes.count <= 8_000_000,
                          bytes.prefix(8).elementsEqual([UInt8](arrayLiteral: 137, 80, 78, 71, 13, 10, 26, 10)) else { return }
                    try recipientMediaContext.checkCurrent()
                    pages.append("data:image/png;base64,\(bytes.base64EncodedString())")
                    hydratedPageURLs = pages
                    hydratedGeneration = generation
                } catch { return }
            }
            return
        }
        let offlineStore = OfflineStore.shared
        guard let owner = await AuthManager.currentUserId(),
              !Task.isCancelled,
              offlineStore.scopeGeneration == generation,
              offlineStore.activeScopeId == scope else { return }
        let keys = mode == .preview
            ? Array(source.encryptedPageKeys.prefix(1))
            : source.encryptedPageKeys
        var pages: [String] = []
        for key in keys {
            do {
                let bytes = try await S3MediaClient.shared.fetchAndDecrypt(
                    s3Url: "", aesKeyHex: aesKey, aesNonceHex: nil,
                    encryption: S3MediaClient.noncePrefixedEncryption,
                    s3Key: key, cacheNamespace: scope,
                    cachePolicy: .memoryOnly
                )
                guard !Task.isCancelled,
                      offlineStore.scopeGeneration == generation,
                      offlineStore.activeScopeId == scope,
                      await AuthManager.currentUserId() == owner else { return }
                // Owner resolution suspends; scope can change during that
                // suspension even after the checks immediately above.
                guard !Task.isCancelled,
                      offlineStore.scopeGeneration == generation,
                      offlineStore.activeScopeId == scope else { return }
                let pngSignature: [UInt8] = [137, 80, 78, 71, 13, 10, 26, 10]
                guard bytes.count <= 8_000_000,
                      bytes.prefix(8).elementsEqual(pngSignature) else { return }
                pages.append("data:image/png;base64,\(bytes.base64EncodedString())")
                hydratedPageURLs = pages
                hydratedGeneration = generation
            } catch {
                return
            }
        }
    }
}

@MainActor
private struct DocumentCanvasWebView {
    let html: String
    let preview: Bool
    @Binding var loadedIdentity: Int?

    final class Coordinator: NSObject, WKNavigationDelegate {
        var loadedHTML = ""
        var currentNavigation: WKNavigation?
        var loadedIdentity: Binding<Int?>?
        var active = true
        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                     decisionHandler: @escaping @MainActor @Sendable (WKNavigationActionPolicy) -> Void) {
            let isInitial = action.navigationType == .other && action.request.url?.scheme == "about"
            decisionHandler(isInitial ? .allow : .cancel)
        }
        func loadIfChanged(_ html: String, in view: WKWebView) {
            guard loadedHTML != html else { return }
            loadedHTML = html
            let identity = html.hashValue
            DispatchQueue.main.async { [weak self] in
                guard let self, self.active, self.loadedHTML.hashValue == identity else { return }
                self.loadedIdentity?.wrappedValue = nil
            }
            currentNavigation = view.loadHTMLString(html, baseURL: nil)
        }
        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            guard active, navigation === currentNavigation else { return }
            loadedIdentity?.wrappedValue = loadedHTML.hashValue
        }
        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            guard active, navigation === currentNavigation else { return }
            loadedIdentity?.wrappedValue = nil
        }
    }

    func makeView(coordinator: Coordinator) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        configuration.defaultWebpagePreferences.allowsContentJavaScript = false
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.navigationDelegate = coordinator
        #if os(iOS)
        view.isOpaque = false
        view.backgroundColor = .clear
        view.scrollView.isScrollEnabled = !preview
        view.scrollView.contentInsetAdjustmentBehavior = .never
        view.accessibilityIdentifier = preview ? "docs-page-preview" : "docs-page-fullscreen"
        #elseif os(macOS)
        view.setValue(false, forKey: "drawsBackground")
        view.setAccessibilityIdentifier(preview ? "docs-page-preview" : "docs-page-fullscreen")
        #endif
        coordinator.loadedIdentity = $loadedIdentity
        coordinator.loadIfChanged(html, in: view)
        return view
    }
}

#if os(iOS)
extension DocumentCanvasWebView: UIViewRepresentable {
    func makeCoordinator() -> Coordinator { Coordinator() }
    func makeUIView(context: Context) -> WKWebView { makeView(coordinator: context.coordinator) }
    func updateUIView(_ view: WKWebView, context: Context) {
        context.coordinator.loadedIdentity = $loadedIdentity
        context.coordinator.loadIfChanged(html, in: view)
    }
    static func dismantleUIView(_ view: WKWebView, coordinator: Coordinator) {
        coordinator.active = false
        view.stopLoading()
    }
}
#elseif os(macOS)
extension DocumentCanvasWebView: NSViewRepresentable {
    func makeCoordinator() -> Coordinator { Coordinator() }
    func makeNSView(context: Context) -> WKWebView { makeView(coordinator: context.coordinator) }
    func updateNSView(_ view: WKWebView, context: Context) {
        context.coordinator.loadedIdentity = $loadedIdentity
        context.coordinator.loadIfChanged(html, in: view)
    }
    static func dismantleNSView(_ view: WKWebView, coordinator: Coordinator) {
        coordinator.active = false
        view.stopLoading()
    }
}
#endif
