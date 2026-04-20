// Wikipedia/wiki embed renderers — inline wiki links and fullscreen article view.
// Mirrors the web app's embeds/wiki/WikiInlineLink.svelte + WikipediaFullscreen.svelte.

import SwiftUI

struct WikiInlineLinkView: View {
    let title: String
    let summary: String?
    let url: String?

    var body: some View {
        HStack(spacing: .spacing3) {
            Icon("book", size: 20)
                .foregroundStyle(Color.fontTertiary)

            VStack(alignment: .leading, spacing: 0) {
                Text(title)
                    .font(.omSmall).fontWeight(.medium)
                    .foregroundStyle(Color.buttonPrimary)
                if let summary {
                    Text(summary)
                        .font(.omTiny).foregroundStyle(Color.fontTertiary)
                        .lineLimit(1)
                }
            }
        }
        .onTapGesture {
            if let url, let link = URL(string: url) {
                #if os(iOS)
                UIApplication.shared.open(link)
                #elseif os(macOS)
                NSWorkspace.shared.open(link)
                #endif
            }
        }
    }
}

struct WikiRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var title: String? { data?["title"]?.value as? String }
    private var summary: String? { data?["summary"]?.value as? String ?? data?["extract"]?.value as? String }
    private var thumbnail: String? { data?["thumbnail_url"]?.value as? String }
    private var url: String? { data?["url"]?.value as? String }
    private var content: String? { data?["content"]?.value as? String }

    var body: some View {
        if mode == .preview {
            previewLayout
        } else {
            fullscreenLayout
        }
    }

    private var previewLayout: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            HStack(spacing: .spacing3) {
                Icon("book", size: 16)
                    .foregroundStyle(Color.buttonPrimary)
                Text(LocalizationManager.shared.text("embed.wikipedia"))
                    .font(.omTiny).foregroundStyle(Color.fontTertiary)
            }

            if let title {
                Text(title)
                    .font(.omSmall).fontWeight(.medium)
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(2)
            }

            if let summary {
                Text(summary)
                    .font(.omXs).foregroundStyle(Color.fontSecondary)
                    .lineLimit(3)
            }
        }
        .padding(.spacing4)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    private var fullscreenLayout: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: .spacing6) {
                if let title {
                    Text(title)
                        .font(.omH2).fontWeight(.bold)
                }

                if let summary {
                    Text(summary)
                        .font(.omP).foregroundStyle(Color.fontSecondary)
                }

                if let content {
                    Divider()
                    Text(content)
                        .font(.omP).foregroundStyle(Color.fontPrimary)
                        .textSelection(.enabled)
                }

                if let url {
                    Divider()
                    Link("Read on Wikipedia", destination: URL(string: url)!)
                        .font(.omSmall)
                }
            }
            .padding(.spacing6)
        }
    }
}
