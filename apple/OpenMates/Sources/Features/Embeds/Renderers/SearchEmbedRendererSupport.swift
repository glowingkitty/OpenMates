// SearchEmbedRendererSupport — shared source summary/grid helpers.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/SearchResultsTemplate.svelte
//          frontend/packages/ui/src/components/embeds/BasicInfosBar.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct SearchResultSourceSummary: View {
    let favicons: [String]
    let totalCount: Int

    var body: some View {
        HStack(spacing: .spacing4) {
            if favicons.isEmpty {
                if totalCount > 0 {
                    Text(AppStrings.moreResults(totalCount))
                    .font(.omSmall)
                    .fontWeight(.medium)
                    .foregroundStyle(Color.grey70)
                    .lineLimit(1)
                }
            } else {
                HStack(spacing: -6) {
                    ForEach(Array(favicons.prefix(3).enumerated()), id: \.offset) { index, favicon in
                        FaviconCircle(urlString: favicon)
                            .zIndex(Double(favicons.count - index))
                    }
                }
                .frame(height: 19)

                let remaining = max(0, totalCount - min(3, favicons.count))
                if remaining > 0 {
                    Text(AppStrings.moreResults(remaining))
                    .font(.omSmall)
                    .fontWeight(.medium)
                    .foregroundStyle(Color.grey70)
                    .lineLimit(1)
                }
            }
        }
        .frame(height: 22, alignment: .leading)
    }
}

private struct FaviconCircle: View {
    let urlString: String

    var body: some View {
        ZStack {
            Circle().fill(Color.grey0)
            if let url = URL(string: urlString) {
                CachedRemoteImage(url: url) { image in
                    image.resizable().aspectRatio(contentMode: .fill)
                } placeholder: {
                    Icon("web", size: 11)
                        .foregroundStyle(Color.grey70)
                }
                .clipShape(Circle())
            } else {
                Icon("web", size: 11)
                    .foregroundStyle(Color.grey70)
            }
        }
        .frame(width: 19, height: 19)
        .overlay(Circle().stroke(Color.grey0, lineWidth: 1))
    }
}

struct SearchResultsGrid<Result: Identifiable, Content: View>: View {
    let status: EmbedStatus
    let query: String
    let results: [Result]
    let emptyText: String
    var webLayout: Bool = false
    @State private var viewportWidth: CGFloat = 390
    private var narrow: Bool { webLayout && viewportWidth <= 500 }
    @ViewBuilder let content: (Result) -> Content

    private var columns: [GridItem] {
        if narrow {
            return [GridItem(.flexible(minimum: 0), alignment: .top)]
        }
        // CSS minmax(280px, 1fr) lets the cell fill its column; the card
        // independently caps at 320pt, centered inside that column.
        return [GridItem(.adaptive(minimum: 280), spacing: .spacing8, alignment: .top)]
    }

    var body: some View {
        Group {
            if status == .error {
                errorState
            } else if results.isEmpty {
                emptyState
            } else {
                LazyVGrid(columns: columns, alignment: .center, spacing: narrow ? .spacing5 : .spacing8) {
                    ForEach(results) { result in
                        content(result)
                            .environment(\.embedPreviewFillsGridCell, true)
                            .frame(maxWidth: 320)
                            .frame(maxWidth: .infinity)
                    }
                }
                .frame(maxWidth: 1000)
                .padding(.horizontal, narrow ? .spacing3 : .spacing5)
                .padding(.top, narrow ? .spacing8 : .spacing12)
                .padding(.bottom, narrow ? 96 : 120)
            }
        }
        .frame(maxWidth: .infinity, alignment: .center)
        .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { viewportWidth = $0 }
    }

    private var emptyState: some View {
        Text(emptyText)
            .font(.omP)
            .fontWeight(.medium)
            .foregroundStyle(Color.fontSecondary)
            .multilineTextAlignment(.center)
            .frame(maxWidth: .infinity)
            .frame(height: 200)
    }

    private var errorState: some View {
        VStack(spacing: .spacing3) {
            Text(AppStrings.searchFailed)
                .font(.omH3)
                .fontWeight(.semibold)
                .foregroundStyle(Color.error)
            Text(AppStrings.genericProcessingError)
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
                .multilineTextAlignment(.center)
        }
        .padding(.horizontal, .spacing8)
        .padding(.vertical, .spacing12)
        .frame(maxWidth: .infinity)
    }
}
