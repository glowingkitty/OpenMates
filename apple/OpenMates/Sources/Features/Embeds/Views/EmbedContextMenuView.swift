// Product-owned embed context actions. Share enters the common Settings shell.
// Specification: specifications/features/settings-ui/specification.yml
// Assertions: settings-ui.shell.lifecycle-and-routing
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/embeds/EmbedContextMenu.svelte
// CSS: .menu-item, .menu-item:hover
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

struct EmbedContextMenuView: View {
    let embed: EmbedRecord
    let chatId: String
    let onFullscreen: () -> Void
    let onShare: () -> Void
    var onClose: () -> Void = {}
    @Environment(\.openURL) private var openURL

    var body: some View {
        VStack(spacing: 0) {
            action(AppStrings.localized("common.view"), icon: "fullscreen", identifier: "embed-context-view", onFullscreen)
            action(AppStrings.share, icon: "share", identifier: "embed-context-share", onShare)
            if let url = embedURL {
                action(AppStrings.copy, icon: "copy", identifier: "embed-context-copy") {
                    #if os(iOS)
                    UIPasteboard.general.string = url.absoluteString
                    #elseif os(macOS)
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(url.absoluteString, forType: .string)
                    #endif
                    onClose()
                }
                action(AppStrings.openInBrowser, icon: "open", identifier: "embed-context-open-browser") { openURL(url); onClose() }
                if embed.type.contains("image") || embed.type.contains("video") || embed.type.contains("pdf") {
                    action(AppStrings.download, icon: "download", identifier: "embed-context-download") { openURL(url); onClose() }
                }
            }
            action(AppStrings.close, icon: "close", identifier: "embed-context-close", onClose)
        }
        // Web .menu-container: min-width 120px, spacing-4, grey-blue, radius-5.
        .frame(minWidth: 120)
        .fixedSize(horizontal: true, vertical: true)
        .padding(.spacing4)
        .background(Color.greyBlue)
        .clipShape(RoundedRectangle(cornerRadius: .radius5))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("embed-context-menu")
    }

    private func action(_ title: String, icon: String, identifier: String, _ perform: @escaping () -> Void) -> some View {
        Button(action: perform) {
            HStack(spacing: .spacing4) {
                Icon(icon, size: 18)
                Text(title).font(.omSmall)
                Spacer(minLength: .spacing2)
            }
            .foregroundStyle(Color.fontPrimary)
            .padding(.horizontal, .spacing8)
            .padding(.vertical, .spacing6)
            .contentShape(Rectangle())
        }
        .buttonStyle(EmbedContextActionStyle())
        .accessibilityIdentifier(identifier)
    }

    private struct EmbedContextActionStyle: ButtonStyle {
        @State private var hovered = false
        func makeBody(configuration: Configuration) -> some View {
            configuration.label
                .background(hovered || configuration.isPressed ? Color.grey20 : Color.clear)
                .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
                .scaleEffect(configuration.isPressed ? 0.98 : 1)
                .onHover { hovered = $0 }
        }
    }

    private var embedURL: URL? {
        guard let value = embed.rawData?["url"]?.value as? String
            ?? embed.rawData?["source_url"]?.value as? String,
            let url = URL(string: value), ["http", "https"].contains(url.scheme?.lowercased() ?? "") else { return nil }
        return url
    }
}

#if os(macOS)
/// Observe only a secondary click inside the mounted card. The transparent
/// view preserves normal card hit testing and unregisters its window monitor.
struct EmbedSecondaryClickSurface: NSViewRepresentable {
    let onClick: () -> Void
    func makeNSView(context: Context) -> Surface { Surface(onClick: onClick) }
    func updateNSView(_ view: Surface, context: Context) { view.onClick = onClick }
    static func dismantleNSView(_ view: Surface, coordinator: ()) { view.stopMonitoring() }

    final class Surface: NSView {
        var onClick: () -> Void
        private var monitor: Any?
        init(onClick: @escaping () -> Void) { self.onClick = onClick; super.init(frame: .zero) }
        required init?(coder: NSCoder) { nil }
        override func hitTest(_ point: NSPoint) -> NSView? { nil }
        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            stopMonitoring()
            guard window != nil else { return }
            monitor = NSEvent.addLocalMonitorForEvents(matching: .rightMouseDown) { [weak self] event in
                guard let self, event.window === self.window, !self.isHiddenOrHasHiddenAncestor,
                      self.bounds.contains(self.convert(event.locationInWindow, from: nil)) else { return event }
                self.onClick()
                return nil
            }
        }
        func stopMonitoring() { if let monitor { NSEvent.removeMonitor(monitor) }; monitor = nil }
    }
}
#endif
