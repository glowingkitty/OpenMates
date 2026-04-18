// Generic search results renderer — used by all composite embed types.
// Shows query, result count, and provider info.

import SwiftUI

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
