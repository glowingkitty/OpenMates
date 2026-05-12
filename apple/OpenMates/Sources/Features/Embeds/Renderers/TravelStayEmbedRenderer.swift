// TravelStayEmbedRenderer — native counterpart for travel stay embeds.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/travel/TravelStayEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/travel/TravelStayEmbedFullscreen.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct TravelStayEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var name: String { data?["name"]?.value as? String ?? "Stay" }
    private var location: String? { data?["location"]?.value as? String }
    private var pricePerNight: Double? { data?["price_per_night"]?.value as? Double }
    private var currency: String { data?["currency"]?.value as? String ?? "€" }
    private var rating: Double? { data?["rating"]?.value as? Double }
    private var imageUrl: String? { data?["image_url"]?.value as? String }

    var body: some View {
        switch mode {
        case .preview:
            ZStack(alignment: .bottomLeading) {
                if let imageUrl, let imgURL = URL(string: imageUrl) {
                    CachedRemoteImage(url: imgURL) { image in
                        image.resizable().aspectRatio(contentMode: .fill)
                    } placeholder: {
                        Color.grey20
                    }
                } else {
                    Color.grey20.overlay(Icon("travel", size: 36).foregroundStyle(Color.fontTertiary))
                }

                VStack(alignment: .leading, spacing: 2) {
                    Text(name).font(.omSmall).fontWeight(.medium).foregroundStyle(.white).lineLimit(1)
                    HStack {
                        if let pricePerNight {
                            Text("\(currency)\(String(format: "%.0f", pricePerNight))/night")
                                .font(.omXs).foregroundStyle(.white)
                        }
                        if let rating {
                            Label { Text(String(format: "%.1f", rating)).font(.omTiny) } icon: { Icon("rating", size: 10) }
                                .foregroundStyle(.yellow)
                        }
                    }
                }
                .padding(.spacing3)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(.linearGradient(colors: [.clear, .black.opacity(0.7)], startPoint: .top, endPoint: .bottom))
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

        case .fullscreen:
            VStack(alignment: .leading, spacing: .spacing4) {
                if let imageUrl, let imgURL = URL(string: imageUrl) {
                    CachedRemoteImage(url: imgURL) { image in
                        image.resizable().aspectRatio(contentMode: .fit)
                    } placeholder: { ProgressView() }
                    .clipShape(RoundedRectangle(cornerRadius: .radius3))
                }
                if let location { Label { Text(location).font(.omSmall) } icon: { Icon("maps", size: 14) }.foregroundStyle(Color.fontSecondary) }
                if let pricePerNight {
                    Text("\(currency)\(String(format: "%.2f", pricePerNight)) per night")
                        .font(.omH4).fontWeight(.bold).foregroundStyle(Color.fontPrimary)
                }
                if let rating {
                    HStack {
                        ForEach(0..<Int(rating), id: \.self) { _ in
                            Icon("rating", size: 14).foregroundStyle(.yellow)
                        }
                        Text(String(format: "%.1f", rating)).font(.omSmall).foregroundStyle(Color.fontSecondary)
                    }
                }
            }
        }
    }
}

