// WebSearchEmbedRenderer — native counterpart for web search embeds.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/web/WebSearchEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/web/WebSearchEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/SearchResultsTemplate.svelte
//          frontend/packages/ui/src/components/embeds/UnifiedEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/BasicInfosBar.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct WebSearchEmbedRenderer: View {
    let model: SearchSkillPreviewModel
    let mode: EmbedDisplayMode
    let onOpenEmbed: (EmbedRecord) -> Void

    var body: some View {
        switch mode {
        case .preview:
            WebSearchEmbedPreviewDetails(model: model)
        case .fullscreen:
            WebSearchEmbedFullscreenContent(model: model, onOpenEmbed: onOpenEmbed)
        }
    }
}

struct WebSearchEmbedPreviewDetails: View {
    let model: SearchSkillPreviewModel

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            if model.status == .finished {
                WebSearchThumbnailStrip(results: model.websiteResults)
            }
            Text(model.query)
                .font(.omP)
                .fontWeight(.semibold)
                .foregroundStyle(Color.grey100)
                .lineLimit(3)
                .frame(maxWidth: .infinity, alignment: .leading)

            Text(viaProvider)
                .font(.omSmall)
                .fontWeight(.medium)
                .foregroundStyle(Color.grey70)
                .lineLimit(1)

            if model.status == .finished {
                SearchResultSourceSummary(
                    favicons: model.websiteResults.compactMap(\.faviconURL),
                    totalCount: model.previewResultCount
                )
                .padding(.top, .spacing1)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
    }

    private var viaProvider: String {
        "\(AppStrings.via) \(model.provider)"
    }
}

struct WebSearchEmbedFullscreenContent: View {
    let model: SearchSkillPreviewModel
    let onOpenEmbed: (EmbedRecord) -> Void

    var body: some View {
        SearchResultsGrid(
            status: model.status,
            query: model.query,
            results: model.websiteResults,
            emptyText: emptyText,
            webLayout: true
        ) { result in
            EmbedPreviewCard(embed: result.embed, variant: .compact) {
                onOpenEmbed(result.embed)
            }
            .accessibilityIdentifier("embed-preview-\(result.embed.id)")
        }
    }

    private var emptyText: String {
        AppStrings.searchNoResults(for: model.query)
    }
}

// SearchThumbnailStrip.svelte: at most ten unique images, 40x30 cells, 2pt gap.
// Resolves only already-hydrated metadata; never fetches private chat content.
struct WebSearchThumbnailStrip: View {
    let results: [WebsiteResultModel]
    static func selectedURLs(_ values: [String?]) -> [String] {
        var seen = Set<String>()
        return Array(values.compactMap { $0 }.filter { seen.insert($0).inserted }.prefix(10))
    }
    var body: some View {
        let urls = Self.selectedURLs(results.map(\.previewImageURL))
        if !urls.isEmpty {
            HStack(spacing: 2) {
                ForEach(urls, id: \.self) { value in
                    if let url = URL(string: value) {
                        CachedRemoteImage(url: url) { image in
                            image.resizable().aspectRatio(contentMode: .fill)
                        } placeholder: { Color.grey20 }
                        .frame(width: 40, height: 30).clipped()
                        .accessibilityIdentifier("web-search-thumbnail")
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .frame(height: 30).clipped()
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("web-search-thumbnail-strip")
        }
    }
}
