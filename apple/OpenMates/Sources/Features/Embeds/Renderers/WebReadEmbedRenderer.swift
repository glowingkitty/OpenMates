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
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity

import SwiftUI

struct WebReadEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var title: String { data?["title"]?.value as? String ?? "Article" }
    private var url: String { Self.inputURL(in: data) ?? "" }

    static func inputURL(in data: [String: AnyCodable]?) -> String? {
        let raw = data ?? [:]
        if let input = EmbedFieldReader.string(raw, keys: ["url"]) { return input }
        let results = raw["results"]?.value as? [[String: Any]] ?? []
        return results.lazy.compactMap {
            EmbedFieldReader.string($0.mapValues(AnyCodable.init), keys: ["url"])
        }.first
    }
    private var content: String? {
        Self.sourceContent(in: data)
    }

    /// Read skills persist provider results under results[].markdown/content;
    /// the excerpt target must reach that text as well as legacy top-level data.
    static func sourceContent(in data: [String: AnyCodable]?) -> String? {
        let raw = data ?? [:]
        if let direct = EmbedFieldReader.string(raw, keys: ["content", "markdown", "text"]) { return direct }
        let results = raw["results"]?.value as? [[String: Any]] ?? []
        let contents = results.compactMap { result -> String? in
            let fields = result.mapValues(AnyCodable.init)
            return EmbedFieldReader.string(fields, keys: ["markdown", "content", "text"])
        }
        return contents.isEmpty ? nil : contents.joined(separator: "\n\n")
    }
    private var wordCount: Int? { data?["word_count"]?.value as? Int }

    var body: some View {
        switch mode {
        case .preview:
            SearchPreviewIdentityLayout(horizontalInset: .spacing4, summaryHeight: 44) {
                EmptyView()
            } inputs: {
                if !url.isEmpty {
                    Text(url).font(.omSmall).foregroundStyle(Color.fontPrimary).lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityIdentifier("web-read-input-url")
                }
            } summary: {
                VStack(alignment: .leading, spacing: 0) {
                    Text(title).font(.omXs).foregroundStyle(Color.fontSecondary).lineLimit(1)
                        .accessibilityIdentifier("web-read-result-title")
                    if let content {
                        Text(content).font(.omXs).foregroundStyle(Color.fontSecondary).lineLimit(1)
                            .accessibilityIdentifier("web-read-result-excerpt")
                    }
                    if let wordCount {
                        Text("\(wordCount) words").font(.omXs).foregroundStyle(Color.fontTertiary).lineLimit(1)
                    }
                }
            }

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
                    SourceQuoteTextDocument(text: content, locationPrefix: "web-read-paragraph", lineHeight: 27.2)
                        .font(.omP)
                        .foregroundStyle(Color.fontPrimary)
                }
            }
        }
    }
}
