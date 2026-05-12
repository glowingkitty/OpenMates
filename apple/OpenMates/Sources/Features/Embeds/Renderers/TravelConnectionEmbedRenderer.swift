// TravelConnectionEmbedRenderer — native counterpart for travel connection embeds.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/travel/TravelConnectionEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/travel/TravelConnectionEmbedFullscreen.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct TravelConnectionEmbedRenderer: View {
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

struct TravelConnectionResultCard: View {
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
                    CachedRemoteImage(url: url) { image in
                        image.resizable().aspectRatio(contentMode: .fill)
                    } placeholder: {
                        Circle().fill(Color.grey10)
                            .overlay(Text(String(code.prefix(1))).font(.omMicro).foregroundStyle(Color.grey70))
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

enum TravelValue {
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

    static func double(_ data: [String: AnyCodable]?, _ keys: [String]) -> Double? {
        for key in keys {
            if let double = data?[key]?.value as? Double { return double }
            if let int = data?[key]?.value as? Int { return Double(int) }
            if let string = data?[key]?.value as? String {
                return Double(string) ?? Double(string.replacingOccurrences(of: ",", with: "."))
            }
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
        if let date = parseDate(value) {
            let out = DateFormatter()
            out.locale = Locale(identifier: "en_US_POSIX")
            out.dateFormat = "EEE, MMM d"
            return out.string(from: date)
        }
        return value
    }

    static func formatTime(_ value: String) -> String {
        if let date = parseDate(value) {
            let out = DateFormatter()
            out.locale = Locale(identifier: "en_US_POSIX")
            out.dateFormat = "HH:mm"
            return out.string(from: date)
        }
        return value
    }

    private static func parseDate(_ value: String) -> Date? {
        let isoFormatter = ISO8601DateFormatter()
        if let date = isoFormatter.date(from: value) { return date }

        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)

        for format in ["yyyy-MM-dd'T'HH:mm:ssXXXXX", "yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd"] {
            formatter.dateFormat = format
            if let date = formatter.date(from: value) { return date }
        }

        return nil
    }
}

