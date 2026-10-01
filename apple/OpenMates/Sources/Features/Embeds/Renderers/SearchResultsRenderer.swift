// Generic and repository search result renderers.
//
// ─── Web source ─────────────────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/code/CodeRepoSearchEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/code/CodeRepoSearchEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/SearchResultsTemplate.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ──────────────────────────────────────────────────────────────────
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity

import SwiftUI

struct CodeRepoSearchEmbedRenderer: View {
    let model: CodeRepoSearchModel
    let mode: EmbedDisplayMode
    let onOpenEmbed: (EmbedRecord) -> Void

    var body: some View {
        switch mode {
        case .preview:
            preview
        case .fullscreen:
            fullscreen
        }
    }

    private var preview: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            Text(model.query)
                .font(.omSmall)
                .fontWeight(.semibold)
                .foregroundStyle(Color.fontPrimary)
                .lineLimit(1)

            if let provider = model.provider {
                Text("\(AppStrings.via) \(provider)")
                    .font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
                    .lineLimit(1)
            }

            if model.status == .finished {
                if model.resultCount == 0 {
                    Text(AppStrings.searchNoResults)
                        .accessibilityIdentifier("code-repo-search-count")
                } else {
                    Text(model.resultCountLabel)
                        .accessibilityIdentifier("code-repo-search-count")
                }
            } else if model.status == .error {
                Text(AppStrings.searchFailed)
                    .foregroundStyle(Color.error)
            }
        }
        .font(.omXs)
        .foregroundStyle(Color.fontSecondary)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
    }

    private var fullscreen: some View {
        SearchResultsGrid(
            status: model.status,
            query: model.query,
            results: model.repositoryEmbeds,
            emptyText: AppStrings.searchNoResults,
            webLayout: true
        ) { repository in
            EmbedPreviewCard(embed: repository, variant: .compact) {
                onOpenEmbed(repository)
            }
            .accessibilityIdentifier("embed-preview-\(repository.id)")
        }
    }
}

struct SearchResultsRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode
    let resultLabel: String

    private var query: String { data?["query"]?.value as? String ?? "" }
    private var resultCount: Int { data?["result_count"]?.value as? Int ?? 0 }
    private var provider: String? { data?["provider"]?.value as? String }

    var body: some View {
        switch mode {
        case .preview:
            previewContent
        case .fullscreen:
            fullscreenContent
        }
    }

    private var previewContent: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            Text(query)
                .font(.omP)
                .fontWeight(.semibold)
                .foregroundStyle(Color.fontPrimary)
                .lineLimit(2)

            HStack(spacing: .spacing2) {
                Text("\(resultCount) \(resultLabel)")
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
                if let provider {
                    Text("via \(provider)")
                        .font(.omXs)
                        .foregroundStyle(Color.fontTertiary)
                }
            }
        }
        .padding(.spacing4)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    private var fullscreenContent: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            Label("\(resultCount) \(resultLabel) found", systemImage: "magnifyingglass")
                .font(.omP)
                .foregroundStyle(Color.fontSecondary)

            if let provider {
                Text("\(LocalizationManager.shared.text("embed.provider")): \(provider)")
                    .font(.omSmall)
                    .foregroundStyle(Color.fontTertiary)
            }
        }
    }
}

/// The electronics parent uses the same compact result-card grid as the web
/// SearchResultsTemplate. Persisted parents can carry hydrated child records
/// or just inline WEBENCH rows while child sync is pending.
struct ElectronicsSearchParentRenderer: View {
    let embed: EmbedRecord
    let allEmbedRecords: [String: EmbedRecord]
    let mode: EmbedDisplayMode
    let onOpenEmbed: (EmbedRecord) -> Void

    private var raw: [String: AnyCodable] { embed.rawData ?? [:] }
    private var query: String { EmbedFieldReader.string(raw, keys: ["query"]) ?? "" }
    private var provider: String { EmbedFieldReader.string(raw, keys: ["provider"]) ?? "TI WEBENCH" }
    private var inlineRows: [[String: Any]] {
        let results = EmbedFieldReader.dictionaryArray(raw, key: "results")
        return results.isEmpty ? EmbedFieldReader.dictionaryArray(raw, key: "preview_results") : results
    }
    private var children: [EmbedRecord] {
        let inline = inlineRows.enumerated().map { index, row in
            EmbedRecord(
                id: row["embed_id"] as? String
                    ?? (embed.childEmbedIds.indices.contains(index) ? embed.childEmbedIds[index] : nil)
                    ?? "\(embed.id)-component-\(index)",
                type: EmbedType.electronicsComponent.rawValue, status: .finished,
                data: .raw(row.mapValues(AnyCodable.init)),
                parentEmbedId: embed.id, appId: "electronics", skillId: nil,
                embedIds: nil, createdAt: embed.createdAt
            )
        }
        let hydrated = embed.childEmbedIds.compactMap { allEmbedRecords[$0] }
        return SearchSkillPreviewModel.mergedRecords(
            parentOrder: embed.childEmbedIds, inlineRecords: inline,
            hydratedRecords: hydrated
        )
    }
    private var resultCount: Int {
        EmbedFieldReader.int(raw, keys: ["result_count"]) ?? children.count
    }
    private var topEfficiency: Double? {
        children.compactMap { EmbedFieldReader.double($0.rawData ?? [:], keys: ["efficiency_percent"]) }.max()
    }

    var body: some View {
        switch mode {
        case .preview:
            VStack(alignment: .leading, spacing: .spacing2) {
                Text(query).font(.omSmall).fontWeight(.semibold)
                    .foregroundStyle(Color.fontPrimary).lineLimit(2)
                Text("\(AppStrings.via) \(provider)")
                    .font(.omXs).foregroundStyle(Color.fontSecondary).lineLimit(1)
                HStack(spacing: .spacing2) {
                    Text("\(resultCount) components")
                        .font(.omXs).foregroundStyle(Color.fontSecondary)
                    if let topEfficiency {
                        Text(String(format: "%.1f%% Efficiency", topEfficiency))
                            .font(.omXs).fontWeight(.semibold)
                            .foregroundStyle(Color.fontPrimary)
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
            .accessibilityIdentifier("electronics-search-preview")
        case .fullscreen:
            SearchResultsGrid(status: embed.status, query: query, results: children,
                              emptyText: AppStrings.searchNoResults, webLayout: true) { child in
                EmbedPreviewCard(embed: child, allEmbedRecords: allEmbedRecords) {
                    onOpenEmbed(child)
                }
                .accessibilityIdentifier("embed-preview-\(child.id)")
            }
            .accessibilityIdentifier("electronics-search-fullscreen")
        }
    }
}
