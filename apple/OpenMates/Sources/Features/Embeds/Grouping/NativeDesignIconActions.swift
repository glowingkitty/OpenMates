// Public icon exports use validated inert SVG data, never remote WebKit content.
// Web: embeds/design/DesignIconResultEmbedFullscreen.svelte
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity, chats.persistence.client-encrypted
import SwiftUI
import WebKit
#if os(iOS)
import UIKit
#else
import AppKit
#endif

@MainActor
final class NativeDesignIconExportState: ObservableObject {
    @Published var svg: Data?
    @Published var size = 256
    func clear() { svg = nil; size = 256 }
}
private struct NativeDesignIconExportStateKey: EnvironmentKey {
    static let defaultValue: NativeDesignIconExportState? = nil
}
extension EnvironmentValues {
    var nativeDesignIconExportState: NativeDesignIconExportState? {
        get { self[NativeDesignIconExportStateKey.self] }
        set { self[NativeDesignIconExportStateKey.self] = newValue }
    }
}

@MainActor
enum NativeDesignIconActions {
    static func filename(data: [String: AnyCodable]?, extension ext: String) -> String {
        let value = ["icon_id", "display_name", "name"].compactMap { data?[$0]?.value as? String }.first(where: { !$0.isEmpty }) ?? "icon"
        let base = value.lowercased().replacingOccurrences(of: "[^a-z0-9._-]+", with: "-", options: .regularExpression)
            .trimmingCharacters(in: CharacterSet(charactersIn: "-"))
        return (base.isEmpty ? "icon" : base) + "." + ext
    }
    static func url(_ path: String?, apiBase: URL) -> URL? {
        guard let path, !path.isEmpty, let url = URL(string: path, relativeTo: apiBase)?.absoluteURL,
              let safe = NativeEmbedActionURL.external(url.absoluteString), safe.scheme == "https" else { return nil }
        return safe
    }
    static func prepare(_ data: Data, color: String, palette: Bool) throws -> StaticSVGImageSource {
        guard StaticSVGImageSource(data: data) != nil, var text = String(data: data, encoding: .utf8) else { throw URLError(.cannotDecodeContentData) }
        if !palette {
            guard color.range(of: "^#[0-9a-fA-F]{6}$", options: .regularExpression) != nil else { throw URLError(.badURL) }
            text = text.replacingOccurrences(of: "\\bcurrentColor\\b", with: color, options: .regularExpression)
        }
        guard let source = StaticSVGImageSource(data: Data(text.utf8)) else { throw URLError(.cannotDecodeContentData) }
        return source
    }
    static func load(_ url: URL, recipient: RecipientMediaContext?, fetch: ((URL) async throws -> Data)? = nil) async throws -> Data {
        let file = try await NativeEmbedDownload.Source.remote(filename: "icon.svg", mime: "image/svg+xml", url: url)
            .load(scope: nil, recipient: recipient, fetch: fetch)
        guard StaticSVGImageSource(data: file.bytes) != nil else { throw URLError(.cannotDecodeContentData) }
        return file.bytes
    }
    #if DEBUG
    /// Where the last PNG render attached its web view (tests explain blank output with it).
    static var lastRenderHost = "none"
    #endif
    static func png(_ source: StaticSVGImageSource, size: Int) async throws -> Data {
        guard (16...4096).contains(size) else { throw URLError(.dataLengthExceedsMaximum) }
        let renderer = NativeSVGPNGRenderer()
        return try await withTaskCancellationHandler(operation: {
            try Task.checkCancellation()
            return try await renderer.render(source, size: size)
        }, onCancel: { Task { @MainActor in renderer.cancel() } })
    }
}

@MainActor
private final class NativeSVGPNGRenderer: NSObject, WKNavigationDelegate {
    private var webView: WKWebView?
    private var continuation: CheckedContinuation<Data, Error>?
    private var timeout: Task<Void, Never>?
    private var targetSize = 256
    func render(_ source: StaticSVGImageSource, size: Int) async throws -> Data {
        try await withCheckedThrowingContinuation { continuation in
            self.continuation = continuation; targetSize = size
            let configuration = WKWebViewConfiguration(); configuration.websiteDataStore = .nonPersistent()
            configuration.defaultWebpagePreferences.allowsContentJavaScript = false
            let view = WKWebView(frame: CGRect(x: 0, y: 0, width: size, height: size), configuration: configuration)
            view.navigationDelegate = self; webView = view
            #if os(iOS)
            view.isOpaque = false; view.backgroundColor = .clear; view.scrollView.backgroundColor = .clear
            view.isUserInteractionEnabled = false; view.alpha = 0
            // WebKit paints only inside a window; prefer the active key window, else any connected one.
            let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
            let scene = scenes.first(where: { $0.activationState == .foregroundActive }) ?? scenes.first
            let host = scene?.windows.first(where: \.isKeyWindow) ?? scene?.windows.first
            host?.addSubview(view)
            #if DEBUG
            NativeDesignIconActions.lastRenderHost = host == nil ? "no-window scenes=\(scenes.count)"
                : "window active=\(scene?.activationState == .foregroundActive) key=\(host?.isKeyWindow == true)"
            #endif
            #elseif os(macOS)
            view.alphaValue = 0
            NSApp.keyWindow?.contentView?.addSubview(view, positioned: .below, relativeTo: nil)
            #endif
            let dataURL = "data:image/svg+xml;base64," + source.data.base64EncodedString()
            let html = "<html><head><meta name='viewport' content='width=device-width,initial-scale=1'><meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; img-src data:; style-src 'unsafe-inline'\"><style>html,body{margin:0;width:100%;height:100%;background:transparent}img{display:block;width:100%;height:100%;object-fit:contain}</style></head><body><img src='\(dataURL)'></body></html>"
            view.loadHTMLString(html, baseURL: nil)
            timeout = Task { [weak self] in
                do { try await Task.sleep(for: .seconds(10)); self?.finish(.failure(URLError(.timedOut))) } catch { }
            }
        }
    }
    func cancel() { finish(.failure(CancellationError())) }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { snapshot(webView, attempt: 0) }
    /// WebKit lays the page out to PDF without depending on on-screen
    /// compositing (screen snapshots of the hidden helper view came back fully
    /// transparent). Navigation can still finish before the data image is
    /// decoded, so a blank page is retried a bounded number of times.
    private static let blankSnapshotRetries = 10
    private func snapshot(_ webView: WKWebView, attempt: Int) {
        let configuration = WKPDFConfiguration(); configuration.rect = webView.bounds
        webView.createPDF(configuration: configuration) { [weak self] result in
            Task { @MainActor in
                guard let self, self.continuation != nil, self.webView === webView else { return }
                let pdf: Data
                switch result {
                case .success(let data): pdf = data
                case .failure(let error): self.finish(.failure(error)); return
                }
                let size = self.targetSize
                guard let provider = CGDataProvider(data: pdf as CFData),
                      let page = CGPDFDocument(provider)?.page(at: 1),
                      let context = CGContext(data: nil, width: size, height: size,
                          bitsPerComponent: 8, bytesPerRow: size * 4, space: CGColorSpaceCreateDeviceRGB(),
                          bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else {
                    self.finish(.failure(URLError(.cannotDecodeContentData))); return
                }
                let box = page.getBoxRect(.mediaBox)
                guard box.width > 0, box.height > 0 else { self.finish(.failure(URLError(.cannotDecodeContentData))); return }
                context.scaleBy(x: CGFloat(size) / box.width, y: CGFloat(size) / box.height)
                context.translateBy(x: -box.minX, y: -box.minY)
                context.drawPDFPage(page)
                if attempt < Self.blankSnapshotRetries, Self.isFullyTransparent(context, size: size) {
                    try? await Task.sleep(for: .milliseconds(100))
                    if self.continuation != nil, self.webView === webView { self.snapshot(webView, attempt: attempt + 1) }
                    return
                }
                var bytes: Data?
                if let image = context.makeImage() {
                    #if os(iOS)
                    bytes = UIImage(cgImage: image).pngData()
                    #else
                    bytes = NSBitmapImageRep(cgImage: image).representation(using: .png, properties: [:])
                    #endif
                }
                if let bytes { self.finish(.success(bytes)) }
                else { self.finish(.failure(URLError(.cannotDecodeContentData))) }
            }
        }
    }
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { finish(.failure(error)) }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { finish(.failure(error)) }
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping @MainActor @Sendable (WKNavigationActionPolicy) -> Void) {
        decisionHandler(navigationAction.request.url?.absoluteString == "about:blank" ? .allow : .cancel)
    }
    private static func isFullyTransparent(_ context: CGContext, size: Int) -> Bool {
        guard let base = context.data else { return false }
        let bytes = base.bindMemory(to: UInt8.self, capacity: size * size * 4)
        for offset in stride(from: 3, to: size * size * 4, by: 4) where bytes[offset] != 0 { return false }
        return true
    }
    private func finish(_ result: Result<Data, Error>) {
        guard let continuation else { return }
        self.continuation = nil; timeout?.cancel(); timeout = nil
        webView?.stopLoading(); webView?.navigationDelegate = nil; webView?.removeFromSuperview(); webView = nil
        continuation.resume(with: result)
    }
}
