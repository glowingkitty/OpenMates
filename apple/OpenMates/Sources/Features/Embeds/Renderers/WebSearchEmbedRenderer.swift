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
// Specification: specifications/features/app-skills/web-search/specification.yml
// Assertions: web-search.surface-parity

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
                .fixedSize(horizontal: false, vertical: true)
                .layoutPriority(1)
                .frame(maxWidth: .infinity, alignment: .leading)
                .accessibilityIdentifier("web-search-query")

            Text(viaProvider)
                .font(.omSmall)
                .foregroundStyle(Color.grey70)
                .lineLimit(1)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier("web-search-provider")

            if model.status == .error {
                Text(AppStrings.searchFailed)
                    .font(.omXs)
                    .foregroundStyle(Color.error)
                    .padding(.top, .spacing1)
            } else if model.status == .finished {
                if explicitZeroResults {
                    Text(AppStrings.localized("embeds.search_no_results"))
                        .font(.omXs)
                        .fontWeight(.medium)
                        .italic()
                        .foregroundStyle(Color.grey60)
                        .accessibilityIdentifier("search-no-results-message")
                } else if model.previewResultCount == 0 && model.websiteResults.isEmpty {
                    Text(AppStrings.localized("embeds.search_preview_open_to_view_results"))
                        .font(.omXs)
                        .fontWeight(.medium)
                        .italic()
                        .foregroundStyle(Color.grey60)
                        .accessibilityIdentifier("search-preview-metadata-missing-message")
                } else {
                    SearchResultSourceSummary(
                        favicons: model.websiteResults.compactMap(\.previewFaviconURL),
                        totalCount: model.previewResultCount
                    )
                    .padding(.top, .spacing2)
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }

    private var viaProvider: String {
        "\(AppStrings.via) \(model.provider)"
    }

    private var explicitZeroResults: Bool {
        EmbedFieldReader.int(model.embed.rawData ?? [:], keys: ["result_count"]) == 0
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
            let presentedEmbed = result.videoEmbed ?? result.cardEmbed
            EmbedPreviewCard(embed: presentedEmbed, variant: .compact) {
                onOpenEmbed(presentedEmbed)
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
    @State private var failedURLs = Set<String>()
    @State private var loadedURLs = Set<String>()
    static func selectedURLs(_ values: [String?]) -> [String] {
        var seen = Set<String>()
        return Array(values.compactMap { $0 }.filter { seen.insert($0).inserted }.prefix(10))
    }
    var body: some View {
        let urls = Self.selectedURLs(results.map(\.thumbnailStripURL))
        if !urls.isEmpty {
            HStack(spacing: 2) {
                ForEach(urls, id: \.self) { value in
                    if failedURLs.contains(value) {
                        Color.clear.frame(width: 40, height: 30)
                    } else if let url = URL(string: value) {
                        CachedRemoteImage(url: url, onFailure: {
                            _ = loadedURLs.remove(value)
                            _ = failedURLs.insert(value)
                        }, onSuccess: { _ = loadedURLs.insert(value) }, svgContentMode: .fill) { image in
                            image.resizable().aspectRatio(contentMode: .fill)
                        } placeholder: { Color.clear }
                        .frame(width: 40, height: 30).clipped()
                        .accessibilityIdentifier("web-search-thumbnail")
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .frame(height: 30).clipped()
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("web-search-thumbnail-strip")
            .accessibilityValue(loadedURLs.isEmpty ? (failedURLs.count == urls.count ? "failed" : "loading") : "loaded")
            .task(id: urls) {
                loadedURLs.removeAll()
                failedURLs.removeAll()
            }
        }
    }
}
