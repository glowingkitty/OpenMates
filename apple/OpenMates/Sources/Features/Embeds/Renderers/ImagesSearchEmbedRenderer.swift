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
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
    }

    private var imageStrip: some View {
        HStack(spacing: .spacing1) {
            ForEach(model.imageResults.prefix(10)) { result in
                if let urlString = result.thumbnailURL, let url = URL(string: urlString) {
                    CachedRemoteImage(url: url) { image in
                        image.resizable().aspectRatio(contentMode: .fill)
                    } placeholder: {
                        Color.grey20
                    }
                    .frame(width: 44, height: 30)
                    .clipped()
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .frame(height: 30)
        .clipped()
    }

    private var footer: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            Text(model.query)
                .font(.omSmall)
                .fontWeight(.semibold)
                .foregroundStyle(Color.grey90)
                .lineLimit(2)

            Text(viaProvider)
                .font(.omXxs)
                .foregroundStyle(Color.grey70)
                .lineLimit(1)

            SearchResultSourceSummary(
                favicons: model.imageResults.compactMap(\.faviconURL),
                totalCount: model.imageResults.count
            )
            .padding(.top, .spacing1)
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
