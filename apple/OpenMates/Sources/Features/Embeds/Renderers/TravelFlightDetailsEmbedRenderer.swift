// TravelFlightDetailsEmbedRenderer — native counterpart for travel flight details embeds.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/travel/TravelFlightDetailsEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/travel/TravelFlightDetailsEmbedFullscreen.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct TravelFlightDetailsEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var airline: String? { data?["airline"]?.value as? String }
    private var flightNumber: String? { data?["flight_number"]?.value as? String }
    private var departure: String? { data?["departure"]?.value as? String }
    private var arrival: String? { data?["arrival"]?.value as? String }
    private var duration: String? { data?["duration"]?.value as? String }
    private var price: Double? { data?["price"]?.value as? Double }
    private var currency: String { data?["currency"]?.value as? String ?? "€" }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            if let airline {
                Text(airline).font(mode == .preview ? .omSmall : .omH4)
                    .fontWeight(.medium).foregroundStyle(Color.fontPrimary)
            }
            if let flightNumber {
                Text(flightNumber).font(.omXs).foregroundStyle(Color.fontTertiary)
            }
            if let departure, let arrival {
                HStack {
                    Text(departure)
                    Icon("back", size: 12).scaleEffect(x: -1, y: 1)
                    Text(arrival)
                }
                .font(.omSmall).foregroundStyle(Color.fontSecondary)
            }
            if let price {
                Text("\(currency)\(String(format: "%.0f", price))")
                    .font(.omP).fontWeight(.bold).foregroundStyle(Color.fontPrimary)
            }
        }
        .padding(.spacing4)
        .frame(maxWidth: .infinity, maxHeight: mode == .preview ? .infinity : nil, alignment: .topLeading)
    }
}
