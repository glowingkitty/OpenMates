// TravelPriceCalendarEmbedRenderer — native counterpart for travel price calendar embeds.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/travel/TravelPriceCalendarEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/travel/TravelPriceCalendarEmbedFullscreen.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct TravelPriceCalendarEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var origin: String? { data?["origin"]?.value as? String }
    private var destination: String? { data?["destination"]?.value as? String }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            Icon("calendar", size: mode == .preview ? 24 : 32)
                .foregroundStyle(Color.fontTertiary)
            if let origin, let destination {
                Text("\(origin) → \(destination)")
                    .font(mode == .preview ? .omSmall : .omP)
                    .foregroundStyle(Color.fontPrimary)
            }
            Text(LocalizationManager.shared.text("embed.travel.price_calendar"))
                .font(.omXs).foregroundStyle(Color.fontSecondary)
        }
        .padding(.spacing4)
        .frame(maxWidth: .infinity, maxHeight: mode == .preview ? .infinity : nil, alignment: .topLeading)
    }
}

