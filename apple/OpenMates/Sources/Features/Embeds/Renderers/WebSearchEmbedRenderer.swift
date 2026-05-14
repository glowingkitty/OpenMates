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
                    totalCount: model.websiteResults.count
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
