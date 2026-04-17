// Embed context menu — long-press/right-click actions on embed previews and fullscreen.
// Mirrors the web app's EmbedContextMenu.svelte: share, copy link, open in browser,
// download, fullscreen toggle, and report actions.

import SwiftUI

struct EmbedContextMenuView: View {
    let embed: EmbedRecord
    let chatId: String
    let onFullscreen: () -> Void
    let onShare: () -> Void

    var body: some View {
        Group {
            Button { onFullscreen() } label: {
                Label("Open Fullscreen", systemImage: "arrow.up.left.and.arrow.down.right")
            }

            Button { onShare() } label: {
                Label("Share Embed", systemImage: "square.and.arrow.up")
            }

            if let url = embedURL {
                Button { copyToClipboard(url) } label: {
                    Label("Copy Link", systemImage: "link")
                }

                Button { openInBrowser(url) } label: {
                    Label("Open in Browser", systemImage: "safari")
                }
            }

            if embed.embedType.contains("image") || embed.embedType.contains("video") || embed.embedType.contains("pdf") {
                Button { downloadEmbed() } label: {
                    Label("Download", systemImage: "arrow.down.circle")
                }
            }

            Divider()

            Button(role: .destructive) { reportEmbed() } label: {
                Label("Report Issue", systemImage: "exclamationmark.triangle")
            }
        }
    }

    private var embedURL: String? {
        embed.data?["url"]?.value as? String ??
        embed.data?["source_url"]?.value as? String
    }

    private func copyToClipboard(_ text: String) {
        #if os(iOS)
        UIPasteboard.general.string = text
        #elseif os(macOS)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
        #endif
        ToastManager.shared.show("Link copied", type: .success)
    }

    private func openInBrowser(_ urlString: String) {
        guard let url = URL(string: urlString) else { return }
        #if os(iOS)
        UIApplication.shared.open(url)
        #elseif os(macOS)
        NSWorkspace.shared.open(url)
        #endif
    }

    private func downloadEmbed() {
        guard let url = embedURL, let downloadURL = URL(string: url) else { return }
        #if os(iOS)
        UIApplication.shared.open(downloadURL)
        #elseif os(macOS)
        NSWorkspace.shared.open(downloadURL)
        #endif
    }

    private func reportEmbed() {
        Task {
            try? await APIClient.shared.request(
                .post, path: "/v1/embeds/\(embed.id)/report",
                body: ["chat_id": chatId]
            ) as Data
            ToastManager.shared.show("Reported", type: .success)
        }
    }
}
