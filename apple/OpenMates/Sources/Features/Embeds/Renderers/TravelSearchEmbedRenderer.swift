// TravelSearchEmbedRenderer — native counterpart for travel search embeds.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/travel/TravelSearchEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/travel/TravelSearchEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/travel/TravelConnectionEmbedPreview.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct TravelSearchEmbedRenderer: View {
    let embed: EmbedRecord
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode
    let allEmbedRecords: [String: EmbedRecord]
    let onOpenEmbed: (EmbedRecord) -> Void

    private var childEmbeds: [EmbedRecord] {
        embed.childEmbedIds.compactMap { allEmbedRecords[$0] }
    }

    private var connections: [TravelConnectionSummary] {
        let children = childEmbeds.map { TravelConnectionSummary(embedId: $0.id, data: $0.rawData ?? [:]) }
        if !children.isEmpty { return children }
        return TravelConnectionSummary.list(from: data)
    }

    var body: some View {
        switch mode {
        case .preview:
            TravelSearchPreview(data: data, connections: connections)
        case .fullscreen:
            TravelSearchFullscreen(
                data: data,
                connections: connections,
                childEmbeds: childEmbeds,
                onOpenEmbed: onOpenEmbed
            )
        }
    }
}

private struct TravelSearchPreview: View {
    let data: [String: AnyCodable]?
    let connections: [TravelConnectionSummary]

    private var first: TravelConnectionSummary? { connections.first }
    private var route: String {
        first?.routeFull ?? TravelValue.string(data, ["query"]) ?? "Connections"
    }
    private var provider: String? {
        TravelValue.string(data, ["provider"]).map { $0 == "Google" ? "Google" : $0 }
    }
    private var minimumPrice: String? {
        let priced = connections.compactMap(\.priceNumber)
        guard let min = priced.min() else { return nil }
        return "\(first?.currency ?? "EUR") \(String(format: "%.0f", min))"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            Text(route)
                .font(.omP)
                .fontWeight(.bold)
                .foregroundStyle(Color.fontPrimary)
                .lineLimit(2)

            if let departure = first?.departureDateText {
                Text(departure)
                    .font(.omSmall)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.grey70)
            }

            if let provider {
                Text("via \(provider)")
                    .font(.omSmall)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.grey70)
            }

            HStack(spacing: .spacing2) {
                if !connections.isEmpty {
                    Text("\(connections.count) \(connections.count == 1 ? "connection" : "connections")")
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
    }
}

private struct TravelSearchFullscreen: View {
    let data: [String: AnyCodable]?
    let connections: [TravelConnectionSummary]
    let childEmbeds: [EmbedRecord]
    let onOpenEmbed: (EmbedRecord) -> Void

    var body: some View {
        LazyVStack(spacing: .spacing8) {
            if connections.isEmpty {
                Text(LocalizationManager.shared.text("embed.no_results"))
                    .font(.omP)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.fontSecondary)
                    .frame(maxWidth: .infinity, minHeight: 200)
            } else {
                ForEach(Array(connections.enumerated()), id: \.element.id) { index, connection in
                    if let child = childEmbeds.first(where: { $0.id == connection.embedId }) {
                        Button {
                            onOpenEmbed(child)
                        } label: {
                            TravelConnectionResultCard(connection: connection)
                        }
                        .buttonStyle(.plain)
                    } else {
                        TravelConnectionResultCard(connection: connection)
                    }
                    if index < connections.count - 1 {
                        Color.clear.frame(height: .spacing1)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity)
    }
}

