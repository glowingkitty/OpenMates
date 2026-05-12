// TravelStayEmbedRenderer — native counterpart for travel stay embeds.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/travel/TravelStayEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/travel/TravelStayEmbedFullscreen.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
#if canImport(MapKit)
import MapKit
#endif

struct TravelStayEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var name: String { data?["name"]?.value as? String ?? "Stay" }
    private var location: String? { TravelValue.string(data, ["location", "address"]) }
    private var pricePerNight: Double? { TravelValue.double(data, ["price_per_night", "extracted_rate_per_night", "rate_per_night"]) }
    private var totalRate: Double? { TravelValue.double(data, ["extracted_total_rate", "total_rate"]) }
    private var currency: String { TravelValue.string(data, ["currency"]) ?? "EUR" }
    private var rating: Double? { TravelValue.double(data, ["overall_rating", "rating"]) }
    private var reviews: Int? { TravelValue.int(data, ["reviews"]) }
    private var propertyType: String? { TravelValue.string(data, ["property_type"]) }
    private var hotelClass: Int? { TravelValue.int(data, ["hotel_class"]) }
    private var description: String? { TravelValue.string(data, ["description"]) }
    private var amenities: [String] { TravelValue.stringArray(data, "amenities") }
    private var freeCancellation: Bool { (data?["free_cancellation"]?.value as? Bool) == true }
    private var ecoCertified: Bool { (data?["eco_certified"]?.value as? Bool) == true }
    private var imageUrl: String? {
        if let url = TravelValue.string(data, ["image_url", "thumbnail"]) { return url }
        if let images = data?["images"]?.value as? [[String: Any]],
           let first = images.first {
            let wrapped = first.mapValues(AnyCodable.init)
            return TravelValue.string(wrapped, ["original_image", "thumbnail"])
        }
        return nil
    }

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
                            Text("\(currency)\(String(format: "%.0f", pricePerNight))\(AppStrings.perNight)")
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
            EmbedMapDetailTemplate(mapConfiguration: mapConfiguration) {
                VStack(alignment: .leading, spacing: .spacing8) {
                    VStack(alignment: .center, spacing: .spacing3) {
                        Text(name)
                            .font(.omH3)
                            .fontWeight(.bold)
                            .foregroundStyle(Color.fontPrimary)
                            .multilineTextAlignment(.center)
                            .lineLimit(3)

                        HStack(spacing: .spacing4) {
                            if let hotelClass, hotelClass > 0 {
                                Text(String(repeating: "★", count: min(hotelClass, 5)))
                                    .font(.omSmall)
                                    .foregroundStyle(Color(hex: 0xF5A623))
                            }
                            if let propertyType {
                                Text(propertyType)
                                    .font(.omTiny)
                                    .fontWeight(.medium)
                                    .foregroundStyle(Color.grey80)
                                    .padding(.horizontal, .spacing5)
                                    .padding(.vertical, .spacing1)
                                    .background(Color.grey20)
                                    .clipShape(Capsule())
                            }
                        }

                        if let rating {
                            HStack(spacing: .spacing3) {
                                Text(String(format: "%.1f", rating))
                                    .font(.omP)
                                    .fontWeight(.bold)
                                    .foregroundStyle(Color.fontPrimary)
                                if let reviews {
                                    Text("(\(reviews.formatted()) \(AppStrings.reviews))")
                                        .font(.omSmall)
                                        .foregroundStyle(Color.fontSecondary)
                                }
                            }
                        }
                    }

                if let imageUrl, let imgURL = URL(string: imageUrl) {
                    CachedRemoteImage(url: imgURL) { image in
                        image.resizable().aspectRatio(contentMode: .fill)
                    } placeholder: { Color.grey20 }
                    .frame(height: 180)
                    .clipShape(RoundedRectangle(cornerRadius: .radius5))
                    .clipped()
                }

                VStack(alignment: .center, spacing: .spacing2) {
                if let pricePerNight {
                        HStack(alignment: .firstTextBaseline, spacing: .spacing2) {
                            Text("\(currency) \(String(format: "%.0f", pricePerNight))")
                                .font(.omH3)
                                .fontWeight(.bold)
                                .foregroundStyle(Color.fontPrimary)
                            Text(AppStrings.perNight)
                                .font(.omSmall)
                                .foregroundStyle(Color.fontSecondary)
                        }
                }
                    if let totalRate {
                        Text("\(currency) \(String(format: "%.0f", totalRate)) \(AppStrings.total)")
                            .font(.omSmall)
                            .foregroundStyle(Color.fontSecondary)
                    }
                }
                .frame(maxWidth: .infinity)

                if freeCancellation || ecoCertified {
                    HStack(spacing: .spacing3) {
                        if freeCancellation {
                            TravelStayBadge(label: AppStrings.freeCancellation, foreground: Color.fontPrimary, background: Color.grey10)
                        }
                        if ecoCertified {
                            TravelStayBadge(label: AppStrings.ecoCertified, foreground: Color.fontPrimary, background: Color.grey10)
                        }
                    }
                    .frame(maxWidth: .infinity)
                }

                if let location {
                    HStack(spacing: .spacing3) {
                        Icon("maps", size: 14)
                        Text(location)
                            .font(.omSmall)
                    }
                    .foregroundStyle(Color.fontSecondary)
                }

                if let description {
                    Text(description)
                        .font(.omXs)
                        .foregroundStyle(Color.fontSecondary)
                        .lineSpacing(4)
                        .padding(.spacing6)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color.grey10)
                        .clipShape(RoundedRectangle(cornerRadius: .radius4))
                }

                if !amenities.isEmpty {
                    FlowLayout(spacing: .spacing3) {
                        ForEach(amenities.prefix(10), id: \.self) { amenity in
                            Text(amenity)
                                .font(.omTiny)
                                .foregroundStyle(Color.grey80)
                                .padding(.horizontal, .spacing5)
                                .padding(.vertical, .spacing2)
                                .background(Color.grey10)
                                .overlay(Capsule().stroke(Color.grey20, lineWidth: 1))
                                .clipShape(Capsule())
                        }
                    }
                }
            }
        }
    }
    }

    #if canImport(MapKit)
    private var coordinate: CLLocationCoordinate2D? {
        if let gps = data?["gps_coordinates"]?.value as? [String: Any] {
            let wrapped = gps.mapValues(AnyCodable.init)
            if let latitude = TravelValue.double(wrapped, ["latitude", "lat"]),
               let longitude = TravelValue.double(wrapped, ["longitude", "lng", "lon"]) {
                let coordinate = CLLocationCoordinate2D(latitude: latitude, longitude: longitude)
                return CLLocationCoordinate2DIsValid(coordinate) ? coordinate : nil
            }
        }
        guard let latitude = TravelValue.double(data, ["latitude", "lat"]),
              let longitude = TravelValue.double(data, ["longitude", "lng", "lon"])
        else { return nil }
        let coordinate = CLLocationCoordinate2D(latitude: latitude, longitude: longitude)
        return CLLocationCoordinate2DIsValid(coordinate) ? coordinate : nil
    }

    private var mapConfiguration: EmbedMapConfiguration? {
        guard let coordinate else { return nil }
        return EmbedMapConfiguration(
            center: coordinate,
            markers: [EmbedMapMarker(coordinate: coordinate, title: name)],
            latitudeDelta: 0.025,
            longitudeDelta: 0.025
        )
    }
    #else
    private var mapConfiguration: Never? { nil }
    #endif
}

private struct TravelStayBadge: View {
    let label: String
    let foreground: Color
    let background: Color

    var body: some View {
        Text(label)
            .font(.omTiny)
            .fontWeight(.medium)
            .foregroundStyle(foreground)
            .padding(.horizontal, .spacing5)
            .padding(.vertical, .spacing2)
            .background(background)
            .clipShape(Capsule())
    }
}

private struct FlowLayout: Layout {
    var spacing: CGFloat

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let rows = rows(proposal: proposal, subviews: subviews)
        return CGSize(
            width: proposal.width ?? rows.map(\.width).max() ?? 0,
            height: rows.map(\.height).reduce(0, +) + spacing * CGFloat(max(rows.count - 1, 0))
        )
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var y = bounds.minY
        for row in rows(proposal: ProposedViewSize(width: bounds.width, height: proposal.height), subviews: subviews) {
            var x = bounds.minX
            for item in row.items {
                item.subview.place(
                    at: CGPoint(x: x, y: y),
                    anchor: .topLeading,
                    proposal: ProposedViewSize(item.size)
                )
                x += item.size.width + spacing
            }
            y += row.height + spacing
        }
    }

    private func rows(proposal: ProposedViewSize, subviews: Subviews) -> [Row] {
        let maxWidth = proposal.width ?? .infinity
        var rows: [Row] = []
        var current = Row()

        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if current.width + size.width + (current.items.isEmpty ? 0 : spacing) > maxWidth, !current.items.isEmpty {
                rows.append(current)
                current = Row()
            }
            current.add(subview: subview, size: size, spacing: spacing)
        }
        if !current.items.isEmpty {
            rows.append(current)
        }
        return rows
    }

    private struct Row {
        var items: [Item] = []
        var width: CGFloat = 0
        var height: CGFloat = 0

        mutating func add(subview: LayoutSubview, size: CGSize, spacing: CGFloat) {
            if !items.isEmpty { width += spacing }
            items.append(Item(subview: subview, size: size))
            width += size.width
            height = max(height, size.height)
        }
    }

    private struct Item {
        let subview: LayoutSubview
        let size: CGSize
    }
}
