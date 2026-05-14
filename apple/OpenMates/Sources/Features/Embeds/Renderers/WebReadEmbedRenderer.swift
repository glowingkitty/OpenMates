// WebReadEmbedRenderer — native counterpart for web read skill embeds.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/web/WebReadEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/web/WebReadEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/UnifiedEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/BasicInfosBar.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct WebReadEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var title: String { data?["title"]?.value as? String ?? "Article" }
    private var url: String { data?["url"]?.value as? String ?? "" }
    private var content: String? { data?["content"]?.value as? String }
    private var wordCount: Int? { data?["word_count"]?.value as? Int }

    var body: some View {
        switch mode {
        case .preview:
            VStack(alignment: .leading, spacing: .spacing3) {
                Text(title)
                    .font(.omSmall)
                    .fontWeight(.medium)
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(2)

                if let wordCount {
                    Text("\(wordCount) words")
                        .font(.omXs)
                        .foregroundStyle(Color.fontTertiary)
                }

                if let content {
                    Text(content)
                        .font(.omXs)
                        .foregroundStyle(Color.fontSecondary)
                        .lineLimit(4)
                }
            }
            .padding(.spacing4)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)

        case .fullscreen:
            VStack(alignment: .leading, spacing: .spacing4) {
                Link(destination: URL(string: url) ?? URL(string: "https://openmates.org")!) {
                    Text(url).font(.omSmall).foregroundStyle(Color.buttonPrimary).lineLimit(1)
                }

                if let wordCount {
                    Text("\(wordCount) words")
                        .font(.omSmall)
                        .foregroundStyle(Color.fontTertiary)
                }

                if let content {
                    Text(content)
                        .font(.omP)
                        .foregroundStyle(Color.fontPrimary)
                }
            }
        }
    }
}
