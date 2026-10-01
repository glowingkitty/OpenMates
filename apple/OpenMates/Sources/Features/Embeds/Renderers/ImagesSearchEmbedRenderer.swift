// ImagesSearchEmbedRenderer — native counterpart for image search embeds.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/images/ImagesSearchEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/images/ImagesSearchEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/SearchResultsTemplate.svelte
//          frontend/packages/ui/src/components/embeds/UnifiedEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/BasicInfosBar.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct ImagesSearchEmbedRenderer: View {
    let model: SearchSkillPreviewModel
    let mode: EmbedDisplayMode
    let onOpenEmbed: (EmbedRecord) -> Void

    var body: some View {
        switch mode {
        case .preview:
            ImagesSearchEmbedPreviewDetails(model: model)
        case .fullscreen:
            ImagesSearchEmbedFullscreenContent(model: model, onOpenEmbed: onOpenEmbed)
        }
    }
}

struct ImagesSearchEmbedPreviewDetails: View {
    let model: SearchSkillPreviewModel
    @State private var loadedThumbnailURLs = Set<String>()

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if !model.imageResults.isEmpty {
                imageStrip
                footer
            } else {
                textOnlyContent
            }
            Spacer(minLength: 61)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    private var imageStrip: some View {
        GeometryReader { viewport in
            HStack(spacing: .spacing1) {
                ForEach(model.imageResults.prefix(10)) { result in
                    if let urlString = result.thumbnailURL, let url = URL(string: urlString) {
                        CachedRemoteImage(url: url, onSuccess: { _ = loadedThumbnailURLs.insert(urlString) }) { image in
                            image.resizable().aspectRatio(contentMode: .fill)
                        } placeholder: {
                            Color.grey20
                        }
                        .frame(width: 40, height: 30)
                        .clipped()
                        .contentShape(Rectangle())
                        .accessibilityIdentifier("images-search-thumbnail")
                    }
                }
            }
            .frame(width: viewport.size.width, height: 30, alignment: .leading)
            .clipped()
        }
        .frame(height: 30)
        // Keep the accessible/hit region within the same painted viewport.
        .contentShape(Rectangle())
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("images-search-thumbnail-strip")
        .accessibilityValue(model.imageResults.contains {
            $0.thumbnailURL.map(loadedThumbnailURLs.contains) ?? false
        } ? "loaded" : "loading")
    }

    private var footer: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            Text(model.query)
                .font(.omSmall)
                .fontWeight(.semibold)
                .foregroundStyle(Color.grey90)
                .lineLimit(2)
                .accessibilityIdentifier("images-search-query")

            Text(viaProvider)
                .font(.omXxs)
                .foregroundStyle(Color.grey70)
                .lineLimit(1)
                .accessibilityIdentifier("images-search-provider")

            if !model.imageResults.compactMap(\.faviconURL).isEmpty {
                SearchResultSourceSummary(
                    favicons: model.imageResults.compactMap(\.faviconURL),
                    totalCount: model.previewResultCount
                )
                .padding(.top, .spacing1)
            }
        }
        .padding(.top, .spacing5)
        .padding(.horizontal, .spacing10)
        .padding(.bottom, .spacing4)
    }

    private var textOnlyContent: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            Text(model.query)
                .font(.omP)
                .fontWeight(.semibold)
                .foregroundStyle(Color.grey90)
                .lineLimit(3)
            Text(viaProvider)
                .font(.omSmall)
                .foregroundStyle(Color.grey70)
                .lineLimit(1)
        }
        .padding(.vertical, .spacing8)
        .padding(.horizontal, .spacing10)
    }

    private var viaProvider: String {
        "\(AppStrings.via) \(model.provider)"
    }
}

struct ImagesSearchEmbedFullscreenContent: View {
    let model: SearchSkillPreviewModel
    let onOpenEmbed: (EmbedRecord) -> Void

    var body: some View {
        SearchResultsGrid(
            status: model.status,
            query: model.query,
            results: model.imageResults,
            emptyText: emptyText
        ) { result in
            EmbedPreviewCard(embed: result.embed, variant: .compact) {
                onOpenEmbed(result.embed)
            }
        }
    }

    private var emptyText: String {
        AppStrings.searchNoResults(for: model.query)
    }
}
