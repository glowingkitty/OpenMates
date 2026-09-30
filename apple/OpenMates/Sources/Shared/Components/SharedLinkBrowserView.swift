// Opens a public short share in an in-app browser when its decrypted target is
// not a native Workflow template. The original fragment stays in the browser.

import SwiftUI

#if os(iOS)
import SafariServices
#elseif os(macOS)
import AppKit
import WebKit
#endif

@MainActor
struct SharedLinkBrowserView: View {
    let url: URL
    @State private var openingProfile: ServerProfile

    init(url: URL) {
        self.url = url
        _openingProfile = State(initialValue: ServerProfile.current())
    }

    var body: some View {
        Group {
            if let incomingHost = url.host?.lowercased(),
               Self.permitsInitialURL(url, selectedHost: openingProfile.displayDomain),
               ServerProfile.current() == openingProfile {
                #if os(iOS)
                SharedLinkSafariView(url: url)
                    .ignoresSafeArea()
                #elseif os(macOS)
                SharedLinkWebView(url: url, pinnedHost: incomingHost, openingProfile: openingProfile)
                #endif
            } else {
                Color.clear
                    .accessibilityIdentifier("shared-link-browser-invalid-url")
            }
        }
    }

    static func permitsInitialURL(_ url: URL, selectedHost: String) -> Bool {
        guard let incomingHost = url.host?.lowercased(),
              [selectedHost.lowercased(), "openmates.org", "app.openmates.org", "app.dev.openmates.org"].contains(incomingHost) else {
            return false
        }
        return ShortShareLink.parse(url, selectedDomain: incomingHost) != nil ||
            DeepLinkHandler.workflowTemplateLink(from: url, selectedDomain: incomingHost) != nil
    }

    static func permitsSharedNavigation(_ url: URL, selectedHost: String) -> Bool {
        guard url.scheme?.lowercased() == "https",
              url.host?.lowercased() == selectedHost.lowercased(),
              url.user == nil, url.password == nil, url.port == nil else { return false }

        if url.path == "/s" || url.path == "/s/" { return true }
        let path = url.pathComponents
        if path.count == 3, path[1] == "s" {
            return path[2].range(of: "^[A-Za-z0-9]{6,12}$", options: .regularExpression) != nil
        }
        if path.count == 4, path[1] == "share" {
            return ["chat", "embed", "workflow-template"].contains(path[2]) &&
                path[3].range(of: "^[A-Za-z0-9_-]{1,128}$", options: .regularExpression) != nil
        }
        // The public chat server route sends a first browser load through the
        // root SPA hash before client-side navigation to /share/chat/{id}.
        guard url.path == "/" || url.path.isEmpty,
              let fragment = url.fragment else { return false }
        let rawParts = fragment.split(separator: "&", omittingEmptySubsequences: false)
        let pairs = rawParts.compactMap { part -> (String, String)? in
            let pair = part.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false)
            guard pair.count == 2 else { return nil }
            return (String(pair[0]), String(pair[1]))
        }
        let chatIDs = pairs.filter { $0.0 == "share-chat-id" }.map { $0.1 }
        if chatIDs.count == 1,
           chatIDs[0].range(of: "^[A-Za-z0-9_-]{1,128}$", options: .regularExpression) != nil {
            return true
        }
        let embedIDs = pairs.filter { $0.0 == "embed-id" }.map { $0.1 }
        let fullscreen = pairs.filter { $0.0 == "fullscreen" }.map { $0.1 }
        let keys = pairs.filter { $0.0 == "key" }.map { $0.1 }
        return rawParts.count == 3 && pairs.count == 3 && embedIDs.count == 1 && fullscreen == ["true"] &&
            keys.count == 1 && !keys[0].isEmpty &&
            embedIDs[0].range(of: "^[A-Za-z0-9_-]{1,128}$", options: .regularExpression) != nil
    }

    static func permitsMediaSubframeNavigation(_ url: URL, trustedMainURL: URL?, pinnedHost: String) -> Bool {
        guard let trustedMainURL,
              permitsSharedNavigation(trustedMainURL, selectedHost: pinnedHost) else { return false }
        if url.absoluteString == "about:blank" || url.absoluteString == "about:srcdoc" { return true }
        if url.scheme?.lowercased() == "https" {
            return url.user == nil && url.password == nil
        }
        // Local object URLs created by the selected share page may back media.
        if url.scheme?.lowercased() == "blob",
           let originURL = URL(string: String(url.absoluteString.dropFirst("blob:".count))) {
            return originURL.scheme?.lowercased() == "https" &&
                originURL.host?.lowercased() == pinnedHost.lowercased() &&
                originURL.user == nil && originURL.password == nil
        }
        return false
    }
}

#if os(iOS)
private struct SharedLinkSafariView: UIViewControllerRepresentable {
    let url: URL
    @Environment(\.dismiss) private var dismiss

    final class Coordinator: NSObject, SFSafariViewControllerDelegate {
        let dismiss: DismissAction

        init(dismiss: DismissAction) {
            self.dismiss = dismiss
        }

        func safariViewControllerDidFinish(_ controller: SFSafariViewController) {
            let action = dismiss
            Task { @MainActor in action() }
        }
    }

    func makeCoordinator() -> Coordinator { Coordinator(dismiss: dismiss) }

    func makeUIViewController(context: Context) -> SFSafariViewController {
        let controller = SFSafariViewController(url: url)
        controller.delegate = context.coordinator
        return controller
    }

    func updateUIViewController(_ controller: SFSafariViewController, context: Context) {}
}
#elseif os(macOS)
@MainActor
private struct SharedLinkWebView: NSViewRepresentable {
    let url: URL
    let pinnedHost: String
    let openingProfile: ServerProfile

    final class Coordinator: NSObject, WKNavigationDelegate {
        let pinnedHost: String
        let openingProfile: ServerProfile
        var requestedURL: URL?

        init(pinnedHost: String, openingProfile: ServerProfile) {
            self.pinnedHost = pinnedHost
            self.openingProfile = openingProfile
        }

        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction) async -> WKNavigationActionPolicy {
            guard let destination = action.request.url,
                  ServerProfile.current() == openingProfile else {
                return .cancel
            }
            if let frame = action.targetFrame {
                if frame.isMainFrame {
                    if SharedLinkBrowserView.permitsSharedNavigation(destination, selectedHost: pinnedHost) {
                        return .allow
                    }
                } else if SharedLinkBrowserView.permitsMediaSubframeNavigation(destination,
                    trustedMainURL: webView.url ?? requestedURL, pinnedHost: pinnedHost) {
                    return .allow
                }
            } else {
                // A target=_blank or script window.open has no target frame.
                // Only a real user link may navigate or leave this sheet.
                guard action.navigationType == .linkActivated else { return .cancel }
                if SharedLinkBrowserView.permitsSharedNavigation(destination, selectedHost: pinnedHost) {
                    webView.load(URLRequest(url: destination))
                    return .cancel
                }
            }
            // A link explicitly clicked in shared web content can leave the
            // sheet in the default browser. Never system-open a claimed /s URL.
            if action.navigationType == .linkActivated,
               destination.host?.lowercased() != pinnedHost.lowercased(),
               ["https", "http"].contains(destination.scheme?.lowercased() ?? ""),
               destination.user == nil, destination.password == nil {
                NSWorkspace.shared.open(destination)
            }
            return .cancel
        }
    }

    func makeCoordinator() -> Coordinator { Coordinator(pinnedHost: pinnedHost, openingProfile: openingProfile) }

    func makeNSView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.navigationDelegate = context.coordinator
        context.coordinator.requestedURL = url
        view.load(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData))
        return view
    }

    func updateNSView(_ view: WKWebView, context: Context) {
        let coordinator = context.coordinator
        guard coordinator.requestedURL != url,
              url.host?.lowercased() == pinnedHost,
              SharedLinkBrowserView.permitsInitialURL(url, selectedHost: openingProfile.displayDomain) else { return }
        coordinator.requestedURL = url
        view.load(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData))
    }

    static func dismantleNSView(_ view: WKWebView, coordinator: Coordinator) {
        view.stopLoading()
        view.navigationDelegate = nil
        view.loadHTMLString("", baseURL: nil)
    }
}
#endif
