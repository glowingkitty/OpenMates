// Native news search preview and regular article cards.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/embeds/news/NewsSearchEmbedPreview.svelte
//         frontend/packages/ui/src/components/embeds/news/NewsSearchEmbedFullscreen.svelte
//         frontend/packages/ui/src/components/embeds/SearchResultsTemplate.svelte
// Tokens: ColorTokens.generated.swift, SpacingTokens.generated.swift, TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity

import SwiftUI

struct NewsSearchEmbedRenderer: View {
    let model: SearchSkillPreviewModel
    let mode: EmbedDisplayMode
    let onOpenEmbed: (EmbedRecord) -> Void

    var body: some View {
        switch mode {
        case .preview:
            VStack(alignment: .leading, spacing: .spacing2) {
                if model.status == .finished {
                    WebSearchThumbnailStrip(results: model.websiteResults)
                }
                Text(model.query)
                    .font(.omP).fontWeight(.semibold).foregroundStyle(Color.grey100)
                    .lineLimit(3).fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .accessibilityIdentifier("news-search-query")
                Text("\(AppStrings.via) \(model.provider)")
                    .font(.omSmall).foregroundStyle(Color.grey70).lineLimit(1)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("news-search-provider")
                if model.status == .error {
                    Text(AppStrings.searchFailed).font(.omXs).foregroundStyle(Color.error)
                } else if model.status == .finished {
                    if model.previewResultCount == 0 {
                        Text(AppStrings.localized(EmbedFieldReader.int(model.embed.rawData ?? [:], keys: ["result_count"]) == 0
                            ? "embeds.search_no_results" : "embeds.search_preview_open_to_view_results"))
                            .font(.omXs).italic().foregroundStyle(Color.grey60)
                    } else {
                        SearchResultSourceSummary(favicons: model.websiteResults.compactMap(\.previewFaviconURL),
                                                  totalCount: model.previewResultCount)
                    }
                }
            }
            // .news-search-details:not(.mobile): justify-content:center.
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("news-search-preview-details")
        case .fullscreen:
            SearchResultsGrid(status: model.status, query: model.query, results: model.websiteResults,
                              emptyText: AppStrings.searchNoResults(for: model.query), webLayout: true) { result in
                let article = Self.articleRecord(for: result)
                EmbedPreviewCard(embed: article, variant: .compact) { onOpenEmbed(article) }
                    .accessibilityIdentifier("embed-preview-\(article.id)")
            }
            .accessibilityIdentifier("news-search-results")
        }
    }

    static func articleRecord(for result: WebsiteResultModel) -> EmbedRecord {
        let source = result.cardEmbed
        return EmbedRecord(
            id: source.id, type: EmbedType.webWebsite.rawValue, status: source.status,
            data: source.data, encryptedContent: source.encryptedContent,
            encryptedType: source.encryptedType, encryptedTextPreview: source.encryptedTextPreview,
            parentEmbedId: source.parentEmbedId, appId: "news", skillId: source.skillId,
            embedIds: source.embedIds, hashedChatId: source.hashedChatId,
            hashedMessageId: source.hashedMessageId, hashedUserId: source.hashedUserId,
            versionNumber: source.versionNumber, contentHash: source.contentHash,
            versionHistory: source.versionHistory, versionHistoryReadonly: source.versionHistoryReadonly,
            createdAt: source.createdAt
        )
    }

}
