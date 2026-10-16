// TravelPriceCalendarEmbedRenderer — native counterpart for travel price calendar embeds.
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity, chats.rendering.assistant-document-convergence
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/travel/TravelPriceCalendarEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/travel/TravelPriceCalendarEmbedFullscreen.svelte
// CSS:     TravelPriceCalendarEmbedPreview.svelte (.route-summary, .month-display)
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

@MainActor
struct TravelPriceCalendarInput {
    let route: String
    let dates: String?

    init(data: [String: AnyCodable]?) {
        let raw = data ?? [:]
        let request = EmbedFieldReader.dictionaryArray(raw, key: "requests").first?.mapValues(AnyCodable.init) ?? [:]
        let fields = request.merging(raw) { _, root in root }
        let firstResult = SearchDomainParentModel.flattenedRows(from: raw).first?.mapValues(AnyCodable.init) ?? [:]
        let origin = TravelValue.string(fields, ["origin"])
        let destination = TravelValue.string(fields, ["destination"])
        if let origin, let destination {
            route = "\(origin) → \(destination)"
        } else if let query = TravelValue.string(fields, ["query"]) {
            route = query
        } else if let origin = TravelValue.string(firstResult, ["origin_name", "origin"]),
                  let destination = TravelValue.string(firstResult, ["destination_name", "destination"]) {
            route = "\(origin) → \(destination)"
        } else {
            route = ""
        }
        let values = [TravelValue.string(fields, ["month", "start_date"]),
                      TravelValue.string(fields, ["end_date"])]
            .compactMap { $0 }
        dates = values.isEmpty ? TravelValue.string(firstResult, ["month"]) : values.joined(separator: " → ")
    }
}

struct TravelPriceCalendarEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var input: TravelPriceCalendarInput { TravelPriceCalendarInput(data: data) }

    var body: some View {
        if mode == .preview {
            SearchPreviewIdentityLayout(horizontalInset: .spacing4) {
                Color.clear
            } inputs: {
                identity
            } summary: {
                Text(AppStrings.localized("embed.travel.price_calendar"))
                    .font(.omXs).foregroundStyle(Color.fontSecondary).lineLimit(1)
            }
        } else {
            VStack(alignment: .leading, spacing: .spacing3) {
                Icon("calendar", size: 32).foregroundStyle(Color.fontTertiary)
                identity
                Text(AppStrings.localized("embed.travel.price_calendar"))
                    .font(.omXs).foregroundStyle(Color.fontSecondary)
            }
            .padding(.spacing4)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
    }

    private var identity: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            Text(input.route).font(mode == .preview ? .omSmall : .omP)
                .fontWeight(.semibold).foregroundStyle(Color.fontPrimary).lineLimit(2)
                .accessibilityIdentifier("travel-price-calendar-route")
            if let dates = input.dates {
                Text(dates).font(.omXs).foregroundStyle(Color.fontSecondary).lineLimit(1)
                    .accessibilityIdentifier("travel-price-calendar-dates")
            }
        }
    }
}
