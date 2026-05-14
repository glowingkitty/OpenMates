// TravelStaysEmbedRenderer — native counterpart for travel stays search embeds.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/travel/TravelStaysEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/travel/TravelStaysEmbedFullscreen.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct TravelStaysEmbedRenderer: View {
    let embed: EmbedRecord
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode
    let allEmbedRecords: [String: EmbedRecord]
    let onOpenEmbed: (EmbedRecord) -> Void

    private var childEmbeds: [EmbedRecord] {
        let explicit = embed.childEmbedIds.compactMap { allEmbedRecords[$0] }
        if !explicit.isEmpty { return explicit }
        return allEmbedRecords.values
            .filter { $0.parentEmbedId == embed.id }
            .sorted { ($0.createdAt ?? $0.id) < ($1.createdAt ?? $1.id) }
    }

    private var stays: [TravelStaySummary] {
        let children = childEmbeds.map { TravelStaySummary(embedId: $0.id, data: $0.rawData ?? [:]) }
        if !children.isEmpty { return children }
        return TravelStaySummary.list(from: data)
    }

    private var query: String {
        TravelValue.string(data, ["query", "title"]) ?? "Stays"
    }

    private var provider: String? {
        TravelValue.string(data, ["provider"])
    }

    var body: some View {
        switch mode {
        case .preview:
            VStack(alignment: .leading, spacing: .spacing3) {
                Text(query)
                    .font(.omP)
                    .fontWeight(.bold)
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(2)

                if let provider {
                    Text("\(AppStrings.via) \(provider)")
                        .font(.omSmall)
                        .fontWeight(.semibold)
                        .foregroundStyle(Color.grey70)
                        .lineLimit(1)
                }

                HStack(spacing: .spacing2) {
                    if !stays.isEmpty {
                        Text("\(stays.count) \(stays.count == 1 ? "stay" : "stays")")
                            .font(.omSmall)
                            .fontWeight(.bold)
                            .foregroundStyle(Color.grey70)
                    }
                    if let minimumPrice {
                        Text("from \(minimumPrice)")
                            .font(.omSmall)
                            .fontWeight(.bold)
                            .foregroundStyle(Color.fontPrimary)
                    }
                }
            }
            .padding(.spacing6)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)

        case .fullscreen:
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 280, maximum: 320), spacing: .spacing8)], spacing: .spacing8) {
                ForEach(childEmbeds) { child in
                    EmbedPreviewCard(embed: child, allEmbedRecords: allEmbedRecords, variant: .compact) {
                        onOpenEmbed(child)
                    }
                    .frame(maxWidth: 320)
                }
            }
            .frame(maxWidth: 1000)
            .padding(.horizontal, .spacing5)
            .padding(.vertical, .spacing12)
            .padding(.bottom, 120)
        }
    }

    private var minimumPrice: String? {
        let priced = stays.compactMap(\.ratePerNight)
        guard let min = priced.min() else { return nil }
        return "\(stays.first?.currency ?? "EUR") \(String(format: "%.0f", min))"
    }
}

private struct TravelStaySummary: Identifiable {
    let id = UUID()
    let embedId: String?
    let name: String
    let currency: String
    let ratePerNight: Double?

    init(embedId: String?, data: [String: AnyCodable]) {
        self.embedId = embedId
        self.name = TravelValue.string(data, ["name"]) ?? "Stay"
        self.currency = TravelValue.string(data, ["currency"]) ?? "EUR"
        self.ratePerNight = TravelValue.double(data, ["rate_per_night", "price_per_night"])
    }

    static func list(from data: [String: AnyCodable]?) -> [TravelStaySummary] {
        guard let raw = data?["results"]?.value as? [[String: Any]] else { return [] }
        return raw.enumerated().map { index, dict in
            TravelStaySummary(embedId: "legacy-stay-\(index)", data: dict.mapValues(AnyCodable.init))
        }
    }
}

