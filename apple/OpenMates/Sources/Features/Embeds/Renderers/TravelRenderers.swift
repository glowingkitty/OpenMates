// Travel embed renderers — connections, stays, price calendar, flights.
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/travel/TravelSearchEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/travel/TravelSearchEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/travel/TravelConnectionEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/travel/TravelConnectionEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/travel/TravelStaysEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/travel/TravelStaysEmbedFullscreen.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift, GradientTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct TravelSearchRenderer: View {
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

struct TravelConnectionRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var connection: TravelConnectionSummary {
        TravelConnectionSummary(embedId: nil, data: data ?? [:])
    }

    var body: some View {
        switch mode {
        case .preview:
            TravelConnectionPreviewDetails(connection: connection)
        case .fullscreen:
            TravelConnectionFullscreenDetails(connection: connection)
        }
    }
}

private struct TravelConnectionPreviewDetails: View {
    let connection: TravelConnectionSummary

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            HStack(alignment: .firstTextBaseline, spacing: .spacing3) {
                if let price = connection.priceText {
                    Text(price)
                        .font(.omP)
                        .fontWeight(.bold)
                        .foregroundStyle(Color(hex: 0x10B981))
                }
                Text("|")
                    .font(.omP)
                    .fontWeight(.bold)
                    .foregroundStyle(Color.fontPrimary)
                Text(connection.tripTypeLabel)
                    .font(.omP)
                    .fontWeight(.bold)
                    .foregroundStyle(Color.fontPrimary)
            }

            AirlineLogoStack(carrierCodes: connection.carrierCodes)

            if let route = connection.routeFull {
                Text(route)
                    .font(.omXs)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(1)
            }

            Text(connection.metaLine)
                .font(.omXs)
                .fontWeight(.semibold)
                .foregroundStyle(Color.grey60)
                .lineLimit(1)
        }
        .padding(.spacing6)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
    }
}

private struct TravelConnectionResultCard: View {
    let connection: TravelConnectionSummary

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            TravelConnectionPreviewDetails(connection: connection)
                .padding(.spacing3)
                .frame(minHeight: 132)
        }
        .background(Color.grey25)
        .clipShape(RoundedRectangle(cornerRadius: 30))
        .shadow(color: .black.opacity(0.12), radius: 20, x: 0, y: 8)
    }
}

private struct TravelConnectionFullscreenDetails: View {
    let connection: TravelConnectionSummary

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing8) {
            VStack(alignment: .leading, spacing: .spacing2) {
                HStack(alignment: .firstTextBaseline, spacing: .spacing3) {
                    if let price = connection.priceText {
                        Text(price)
                            .font(.omH3)
                            .fontWeight(.bold)
                            .foregroundStyle(Color(hex: 0x10B981))
                    }
                    Text("| \(connection.tripTypeLabel)")
                        .font(.omH3)
                        .fontWeight(.bold)
                        .foregroundStyle(Color.fontPrimary)
                }

                if let route = connection.routeFull {
                    Text(route)
                        .font(.omP)
                        .fontWeight(.bold)
                        .foregroundStyle(Color.fontPrimary)
                }

                Text(connection.metaLine)
                    .font(.omSmall)
                    .fontWeight(.bold)
                    .foregroundStyle(Color.grey60)
            }
            .padding(.spacing8)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.grey25)
            .clipShape(RoundedRectangle(cornerRadius: 30))

            VStack(alignment: .leading, spacing: .spacing5) {
                ForEach(Array(connection.legs.enumerated()), id: \.offset) { _, leg in
                    TravelLegCard(leg: leg)
                }
            }
        }
    }
}

private struct TravelLegCard: View {
    let leg: TravelLegSummary

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            HStack {
                Text("\(leg.origin) → \(leg.destination)")
                    .font(.omP)
                    .fontWeight(.bold)
                    .foregroundStyle(Color.fontPrimary)
                Spacer()
                Text(leg.duration)
                    .font(.omSmall)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.grey60)
            }

            ForEach(Array(leg.segments.enumerated()), id: \.offset) { index, segment in
                VStack(alignment: .leading, spacing: .spacing2) {
                    HStack(alignment: .top) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(segment.departureTime)
                                .font(.omP)
                                .fontWeight(.bold)
                            Text(segment.departureStation)
                                .font(.omSmall)
                                .foregroundStyle(Color.grey70)
                        }
                        Spacer()
                        VStack(alignment: .trailing, spacing: 2) {
                            Text(segment.arrivalTime)
                                .font(.omP)
                                .fontWeight(.bold)
                            Text(segment.arrivalStation)
                                .font(.omSmall)
                                .foregroundStyle(Color.grey70)
                        }
                    }
                    .foregroundStyle(Color.fontPrimary)

                    HStack(spacing: .spacing3) {
                        AirlineLogoStack(carrierCodes: segment.carrierCode.map { [$0] } ?? [])
                        Text([segment.carrier, segment.number, segment.duration].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · "))
                            .font(.omXs)
                            .fontWeight(.semibold)
                            .foregroundStyle(Color.grey60)
                            .lineLimit(2)
                    }
                }
                if index < leg.segments.count - 1 {
                    Divider().overlay(Color.grey30)
                }
            }
        }
        .padding(.spacing8)
        .background(Color.grey25)
        .clipShape(RoundedRectangle(cornerRadius: 24))
    }
}

private struct AirlineLogoStack: View {
    let carrierCodes: [String]

    var body: some View {
        HStack(spacing: -6) {
            ForEach(carrierCodes.prefix(3), id: \.self) { code in
                if let url = URL(string: "https://images.kiwi.com/airlines/64/\(code).png") {
                    AsyncImage(url: url) { phase in
                        switch phase {
                        case .success(let image):
                            image.resizable().aspectRatio(contentMode: .fill)
                        default:
                            Circle().fill(Color.grey10)
                                .overlay(Text(String(code.prefix(1))).font(.omMicro).foregroundStyle(Color.grey70))
                        }
                    }
                    .frame(width: 24, height: 24)
                    .background(Color.white)
                    .clipShape(Circle())
                    .overlay(Circle().stroke(Color.grey20, lineWidth: 1.5))
                }
            }
        }
        .frame(height: carrierCodes.isEmpty ? 0 : 24)
    }
}

struct TravelConnectionSummary: Identifiable {
    let id = UUID()
    let embedId: String?
    let priceRaw: String?
    let currency: String
    let tripType: String
    let origin: String?
    let destination: String?
    let departure: String?
    let duration: String?
    let stops: Int
    let carrierCodes: [String]
    fileprivate let legs: [TravelLegSummary]

    init(embedId: String?, data: [String: AnyCodable]) {
        self.embedId = embedId
        self.priceRaw = TravelValue.string(data, ["total_price", "price"])
        self.currency = TravelValue.string(data, ["currency"]) ?? "EUR"
        self.tripType = TravelValue.string(data, ["trip_type"]) ?? "one_way"
        self.origin = TravelValue.string(data, ["origin"])
        self.destination = TravelValue.string(data, ["destination"])
        self.departure = TravelValue.string(data, ["departure"])
        self.duration = TravelValue.string(data, ["duration"])
        self.stops = TravelValue.int(data, ["stops", "transfers"]) ?? 0
        self.carrierCodes = TravelValue.stringArray(data, "carrier_codes")
        self.legs = TravelLegSummary.list(from: data)
    }

    var priceNumber: Double? {
        guard let priceRaw else { return nil }
        return Double(priceRaw) ?? Double(priceRaw.replacingOccurrences(of: ",", with: "."))
    }

    var priceText: String? {
        guard let priceNumber else { return nil }
        return "\(currency) \(String(format: "%.0f", priceNumber))"
    }

    var routeFull: String? {
        guard let origin, let destination else { return nil }
        return "\(origin) → \(destination)"
    }

    var departureDateText: String? {
        guard let departure else { return nil }
        return TravelValue.formatDate(departure)
    }

    var stopsLabel: String {
        if stops == 0 { return "Direct" }
        if stops == 1 { return "1 stop" }
        return "\(stops) stops"
    }

    var tripTypeLabel: String {
        switch tripType {
        case "round_trip": return "Round trip"
        case "multi_city": return "Multi-city"
        default: return "One way"
        }
    }

    var metaLine: String {
        [departureDateText, duration, stopsLabel].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · ")
    }

    static func list(from data: [String: AnyCodable]?) -> [TravelConnectionSummary] {
        guard let raw = data?["results"]?.value as? [[String: Any]] else { return [] }
        return raw.enumerated().map { index, dict in
            TravelConnectionSummary(embedId: "legacy-\(index)", data: dict.mapValues(AnyCodable.init))
        }
    }
}

private struct TravelLegSummary {
    let origin: String
    let destination: String
    let duration: String
    let segments: [TravelSegmentSummary]

    static func list(from data: [String: AnyCodable]) -> [TravelLegSummary] {
        if let legs = data["legs"]?.value as? [[String: Any]] {
            return legs.map { dict in
                let wrapped = dict.mapValues(AnyCodable.init)
                return TravelLegSummary(
                    origin: TravelValue.string(wrapped, ["origin"]) ?? "",
                    destination: TravelValue.string(wrapped, ["destination"]) ?? "",
                    duration: TravelValue.string(wrapped, ["duration"]) ?? "",
                    segments: TravelSegmentSummary.list(from: wrapped)
                )
            }
        }
        return []
    }
}

private struct TravelSegmentSummary {
    let carrier: String?
    let carrierCode: String?
    let number: String?
    let departureStation: String
    let departureTime: String
    let arrivalStation: String
    let arrivalTime: String
    let duration: String?

    static func list(from data: [String: AnyCodable]) -> [TravelSegmentSummary] {
        guard let segments = data["segments"]?.value as? [[String: Any]]
            ?? data["legs_0_segments"]?.value as? [[String: Any]]
        else { return [] }
        return segments.map { dict in
            let wrapped = dict.mapValues(AnyCodable.init)
            return TravelSegmentSummary(
                carrier: TravelValue.string(wrapped, ["carrier"]),
                carrierCode: TravelValue.string(wrapped, ["carrier_code"]),
                number: TravelValue.string(wrapped, ["number"]),
                departureStation: TravelValue.string(wrapped, ["departure_station"]) ?? "",
                departureTime: TravelValue.formatTime(TravelValue.string(wrapped, ["departure_time"]) ?? ""),
                arrivalStation: TravelValue.string(wrapped, ["arrival_station"]) ?? "",
                arrivalTime: TravelValue.formatTime(TravelValue.string(wrapped, ["arrival_time"]) ?? ""),
                duration: TravelValue.string(wrapped, ["duration"])
            )
        }
    }
}

private enum TravelValue {
    static func string(_ data: [String: AnyCodable]?, _ keys: [String]) -> String? {
        for key in keys {
            if let string = data?[key]?.value as? String, !string.isEmpty { return string }
            if let number = data?[key]?.value as? Double { return String(number) }
            if let number = data?[key]?.value as? Int { return String(number) }
        }
        return nil
    }

    static func int(_ data: [String: AnyCodable]?, _ keys: [String]) -> Int? {
        for key in keys {
            if let int = data?[key]?.value as? Int { return int }
            if let double = data?[key]?.value as? Double { return Int(double) }
            if let string = data?[key]?.value as? String, let int = Int(string) { return int }
        }
        return nil
    }

    static func stringArray(_ data: [String: AnyCodable]?, _ key: String) -> [String] {
        if let values = data?[key]?.value as? [String] { return values }
        if let values = data?[key]?.value as? [Any] {
            return values.compactMap { $0 as? String }
        }
        var output: [String] = []
        for index in 0..<20 {
            if let value = data?["\(key)_\(index)"]?.value as? String {
                output.append(value)
            }
        }
        return output
    }

    static func formatDate(_ value: String) -> String {
        let formatter = ISO8601DateFormatter()
        if let date = formatter.date(from: value) {
            let out = DateFormatter()
            out.dateFormat = "EEE, MMM d"
            return out.string(from: date)
        }
        return value
    }

    static func formatTime(_ value: String) -> String {
        let formatter = ISO8601DateFormatter()
        if let date = formatter.date(from: value) {
            let out = DateFormatter()
            out.dateFormat = "HH:mm"
            return out.string(from: date)
        }
        return value
    }
}

struct TravelStayRenderer: View {
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
                    AsyncImage(url: imgURL) { image in
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
                    AsyncImage(url: imgURL) { image in
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

struct TravelPriceCalendarRenderer: View {
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

struct TravelFlightRenderer: View {
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
