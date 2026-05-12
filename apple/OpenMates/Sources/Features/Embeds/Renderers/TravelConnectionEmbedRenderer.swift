// TravelConnectionEmbedRenderer — native counterpart for travel connection embeds.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/travel/TravelConnectionEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/travel/TravelConnectionEmbedFullscreen.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
#if canImport(MapKit)
import MapKit
#endif

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
        EmbedMapDetailTemplate(mapConfiguration: connection.mapConfiguration) {
            VStack(alignment: .leading, spacing: .spacing6) {
                if let route = connection.routeHeader {
                    Text(route)
                        .font(.omP)
                        .fontWeight(.bold)
                        .foregroundStyle(Color.fontPrimary)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: .infinity)
                        .padding(.horizontal, .spacing6)
                        .padding(.vertical, .spacing4)
                        .background(Color.grey10)
                        .clipShape(RoundedRectangle(cornerRadius: 11))
                }

                if let travelClass = connection.travelClassLabel {
                    Text(travelClass)
                        .font(.omP)
                        .fontWeight(.bold)
                        .foregroundStyle(Color.fontPrimary)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: .infinity)
                }

                if let startAirport = connection.startAirportName {
                    HStack(spacing: .spacing2) {
                        Text("Start:")
                            .foregroundStyle(Color.grey50)
                        Text(startAirport)
                            .foregroundStyle(Color.grey50)
                    }
                    .font(.omSmall)
                    .fontWeight(.bold)
                    .frame(maxWidth: .infinity)
                }

                ForEach(Array(connection.legs.enumerated()), id: \.offset) { _, leg in
                    ForEach(Array(leg.segments.enumerated()), id: \.offset) { index, segment in
                        TravelSegmentCard(segment: segment)
                        if index < leg.segments.count - 1 {
                            TravelLayoverView(layover: index < leg.layovers.count ? leg.layovers[index] : nil)
                        }
                    }
                }

                if connection.legs.isEmpty {
                    VStack(spacing: .spacing2) {
                        if let route = connection.routeFull {
                            Text(route)
                        }
                        Text(connection.metaLine)
                    }
                    .font(.omP)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.fontPrimary)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, .spacing8)
                }

                if !connection.bookingInfoLines.isEmpty {
                    VStack(alignment: .leading, spacing: .spacing3) {
                        ForEach(connection.bookingInfoLines, id: \.self) { line in
                            Text(line)
                                .font(.omXs)
                                .foregroundStyle(Color.grey60)
                        }
                    }
                }
            }
        }
    }
}

private struct TravelSegmentCard: View {
    let segment: TravelSegmentSummary

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(alignment: .leading, spacing: .spacing3) {
                TravelTimeBadge(time: segment.departureTime, isDaytime: segment.departureIsDaytime)
                if let delay = segment.departureDelayText {
                    TravelDelayBadge(text: delay, isLate: segment.departureDelayMinutes ?? 0 > 0)
                }
                if let duration = segment.duration, !duration.isEmpty {
                    Text(duration)
                        .font(.omH3)
                        .fontWeight(.bold)
                        .foregroundStyle(LinearGradient(colors: [Color(hex: 0x4867CD), Color(hex: 0x5A85EB)], startPoint: .topLeading, endPoint: .bottomTrailing))
                }
                TravelTimeBadge(time: segment.arrivalTime, isDaytime: segment.arrivalIsDaytime)
                if let delay = segment.arrivalDelayText {
                    TravelDelayBadge(text: delay, isLate: segment.arrivalDelayMinutes ?? 0 > 0)
                }
            }
            .frame(minWidth: 96, alignment: .leading)

            VStack(alignment: .leading, spacing: .spacing4) {
                TravelAirportCodeView(
                    code: segment.departureStation,
                    countryCode: segment.departureCountryCode,
                    platform: segment.departurePlatform,
                    platformChanged: segment.departurePlatformChanged
                )

                HStack(alignment: .center, spacing: .spacing4) {
                    if let logoURL = segment.airlineLogoURL {
                        CachedRemoteImage(url: logoURL) { image in
                            image.resizable().aspectRatio(contentMode: .fill)
                        } placeholder: {
                            Circle().fill(Color.grey20)
                        }
                        .frame(width: 28, height: 28)
                        .background(Color.white)
                        .clipShape(Circle())
                        .overlay(Circle().stroke(Color.grey20, lineWidth: 1.5))
                    } else {
                        AirlineLogoStack(carrierCodes: segment.carrierCode.map { [$0] } ?? [])
                    }

                    VStack(alignment: .leading, spacing: 1) {
                        Text(segment.carrierFlightText)
                            .font(.omSmall)
                            .fontWeight(.bold)
                            .foregroundStyle(Color.fontPrimary)
                            .lineLimit(2)

                        if let airplane = segment.airplane {
                            Text("via \(airplane)")
                                .font(.omSmall)
                                .fontWeight(.bold)
                                .foregroundStyle(Color.fontPrimary)
                                .lineLimit(2)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

                TravelAirportCodeView(
                    code: segment.arrivalStation,
                    countryCode: segment.arrivalCountryCode,
                    platform: segment.arrivalPlatform,
                    platformChanged: segment.arrivalPlatformChanged
                )
            }
        }
        .padding(14)
        .background(Color.grey10)
        .clipShape(RoundedRectangle(cornerRadius: 15))
    }
}

private struct TravelTimeBadge: View {
    let time: String
    let isDaytime: Bool

    var body: some View {
        HStack(spacing: .spacing2) {
            Text(isDaytime ? "☀" : "🌙")
                .font(.omTiny)
            Text(time)
                .font(.omSmall)
                .fontWeight(.bold)
        }
        .foregroundStyle(.white)
        .padding(.horizontal, .spacing5)
        .padding(.vertical, .spacing2)
        .background(isDaytime ? LinearGradient(colors: [Color(hex: 0xF5BB12), Color(hex: 0xE79600)], startPoint: .leading, endPoint: .trailing) : LinearGradient(colors: [Color(hex: 0x365DAD), Color(hex: 0x1745A1)], startPoint: .leading, endPoint: .trailing))
        .clipShape(Capsule())
    }
}

private struct TravelDelayBadge: View {
    let text: String
    let isLate: Bool

    var body: some View {
        Text(text)
            .font(.omMicro)
            .fontWeight(.bold)
            .foregroundStyle(isLate ? Color(hex: 0x991B1B) : Color(hex: 0x166534))
            .padding(.horizontal, .spacing4)
            .padding(.vertical, .spacing1)
            .background(isLate ? Color(hex: 0xFEE2E2) : Color(hex: 0xDCFCE7))
            .clipShape(Capsule())
    }
}

private struct TravelAirportCodeView: View {
    let code: String
    let countryCode: String?
    let platform: String?
    let platformChanged: Bool

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: .spacing2) {
            Text([countryCode.flatMap(TravelValue.countryFlag), code].compactMap { $0 }.joined(separator: " "))
                .font(.omP)
                .fontWeight(.bold)
                .foregroundStyle(Color.fontPrimary)

            if let platform, !platform.isEmpty {
                Text("Platform \(platform)")
                    .font(.omMicro)
                    .fontWeight(.bold)
                    .foregroundStyle(platformChanged ? Color(hex: 0x92400E) : Color.grey70)
                    .padding(.horizontal, .spacing3)
                    .padding(.vertical, .spacing1)
                    .background(platformChanged ? Color(hex: 0xFEF3C7) : Color.grey20)
                    .clipShape(Capsule())
            }
        }
    }
}

private struct TravelLayoverView: View {
    let layover: TravelLayoverSummary?

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            if layover?.overnight == true {
                HStack(spacing: .spacing2) {
                    Text("🌙")
                        .font(.omSmall)
                    Text("Overnight")
                        .font(.omP)
                        .fontWeight(.bold)
                }
                .foregroundStyle(.white)
                .padding(.horizontal, .spacing6)
                .padding(.vertical, .spacing2)
                .background(LinearGradient(colors: [Color(hex: 0x365DAD), Color(hex: 0x1745A1)], startPoint: .leading, endPoint: .trailing))
                .clipShape(Capsule())
            }

            Text(layover?.duration ?? "Connection")
                .font(.omH3)
                .fontWeight(.bold)
                .foregroundStyle(LinearGradient(colors: [Color(hex: 0x4867CD), Color(hex: 0x5A85EB)], startPoint: .topLeading, endPoint: .bottomTrailing))

            if let airport = layover?.airport, !airport.isEmpty {
                Text("Layover in\n\(airport)")
                    .font(.omSmall)
                    .fontWeight(.bold)
                    .foregroundStyle(Color.fontPrimary)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, .spacing4)
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
    let originCountryCode: String?
    let destinationCountryCode: String?
    let departure: String?
    let duration: String?
    let stops: Int
    let carrierCodes: [String]
    let bookingURL: String?
    let bookingProvider: String?
    let bookingToken: String?
    fileprivate let legs: [TravelLegSummary]

    init(embedId: String?, data: [String: AnyCodable]) {
        self.embedId = embedId
        self.priceRaw = TravelValue.string(data, ["total_price", "price"])
        self.currency = TravelValue.string(data, ["currency"]) ?? "EUR"
        self.tripType = TravelValue.string(data, ["trip_type"]) ?? "one_way"
        self.origin = TravelValue.string(data, ["origin"])
        self.destination = TravelValue.string(data, ["destination"])
        self.originCountryCode = TravelValue.string(data, ["origin_country_code"])
        self.destinationCountryCode = TravelValue.string(data, ["destination_country_code"])
        self.departure = TravelValue.string(data, ["departure"])
        self.duration = TravelValue.string(data, ["duration"])
        self.stops = TravelValue.int(data, ["stops", "transfers"]) ?? 0
        self.carrierCodes = TravelValue.stringArray(data, "carrier_codes")
        self.bookingURL = TravelValue.string(data, ["booking_url"])
        self.bookingProvider = TravelValue.string(data, ["booking_provider"])
        self.bookingToken = TravelValue.string(data, ["booking_token"])
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

    var priceHeader: String? {
        guard let priceText else { return nil }
        return "\(priceText) | \(tripTypeLabel)"
    }

    var routeFull: String? {
        guard let origin, let destination else { return nil }
        return "\(origin) → \(destination)"
    }

    var routeHeader: String? {
        guard let origin, let destination else { return nil }
        let originCity = origin.replacingOccurrences(of: #" \([A-Z]{3}\)"#, with: "", options: .regularExpression)
        let destinationCity = destination.replacingOccurrences(of: #" \([A-Z]{3}\)"#, with: "", options: .regularExpression)
        let originPrefix = TravelValue.countryFlag(originCountryCode).map { "\($0) " } ?? ""
        let destinationPrefix = TravelValue.countryFlag(destinationCountryCode).map { "\($0) " } ?? ""
        return "\(originPrefix)\(originCity) → \(destinationPrefix)\(destinationCity)"
    }

    var travelClassLabel: String? {
        guard let travelClass = legs.first?.segments.first?.travelClass, !travelClass.isEmpty else { return nil }
        return "\(travelClass) class"
    }

    var startAirportName: String? {
        if let origin = legs.first?.origin, !origin.isEmpty { return origin }
        guard let station = legs.first?.segments.first?.departureStation, !station.isEmpty else { return nil }
        return station
    }

    var bookingInfoLines: [String] {
        []
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

    var googleFlightsURL: String? {
        let originCode = TravelValue.iataCode(from: origin)
        let destinationCode = TravelValue.iataCode(from: destination)
        var parts = ["Flights"]
        if let originCode { parts.append("from \(originCode)") }
        if let destinationCode { parts.append("to \(destinationCode)") }
        if let date = departure?.split(separator: "T").first ?? departure?.split(separator: " ").first {
            parts.append("on \(date)")
        }
        guard parts.count > 1 else { return nil }
        let query = parts.joined(separator: " ").addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? parts.joined(separator: "+")
        return "https://www.google.com/travel/flights?q=\(query)"
    }

    #if canImport(MapKit)
    var routeCoordinates: [CLLocationCoordinate2D] {
        var coordinates: [CLLocationCoordinate2D] = []
        for leg in legs {
            for segment in leg.segments {
                if let departureCoordinate = segment.departureCoordinate,
                   coordinates.last?.latitude != departureCoordinate.latitude || coordinates.last?.longitude != departureCoordinate.longitude {
                    coordinates.append(departureCoordinate)
                }
                if let arrivalCoordinate = segment.arrivalCoordinate {
                    coordinates.append(arrivalCoordinate)
                }
            }
        }
        return coordinates
    }

    var mapConfiguration: EmbedMapConfiguration? {
        let coordinates = routeCoordinates
        guard coordinates.count >= 2 else { return nil }
        let lats = coordinates.map(\.latitude)
        let lons = coordinates.map(\.longitude)
        let center = CLLocationCoordinate2D(
            latitude: ((lats.min() ?? 0) + (lats.max() ?? 0)) / 2,
            longitude: ((lons.min() ?? 0) + (lons.max() ?? 0)) / 2
        )
        return EmbedMapConfiguration(
            center: center,
            markers: [
                EmbedMapMarker(coordinate: coordinates[0], title: origin ?? "Origin"),
                EmbedMapMarker(coordinate: coordinates[coordinates.count - 1], title: destination ?? "Destination")
            ],
            route: coordinates,
            latitudeDelta: 10,
            longitudeDelta: 10
        )
    }
    #else
    var mapConfiguration: Never? { nil }
    #endif

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
    let layovers: [TravelLayoverSummary]
    let segments: [TravelSegmentSummary]

    static func list(from data: [String: AnyCodable]) -> [TravelLegSummary] {
        if let legs = data["legs"]?.value as? [[String: Any]] {
            return legs.map { dict in
                let wrapped = dict.mapValues(AnyCodable.init)
                return TravelLegSummary(
                    origin: TravelValue.string(wrapped, ["origin"]) ?? "",
                    destination: TravelValue.string(wrapped, ["destination"]) ?? "",
                    duration: TravelValue.string(wrapped, ["duration"]) ?? "",
                    layovers: TravelLayoverSummary.list(from: wrapped),
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
    let scheduledDepartureTime: String?
    let actualDepartureTime: String?
    let departureDelayMinutes: Int?
    let departurePlatform: String?
    let departurePlatformChanged: Bool
    let departureCountryCode: String?
    let departureIsDaytime: Bool
    let departureLatitude: Double?
    let departureLongitude: Double?
    let arrivalStation: String
    let arrivalTime: String
    let scheduledArrivalTime: String?
    let actualArrivalTime: String?
    let arrivalDelayMinutes: Int?
    let arrivalPlatform: String?
    let arrivalPlatformChanged: Bool
    let arrivalCountryCode: String?
    let arrivalIsDaytime: Bool
    let arrivalLatitude: Double?
    let arrivalLongitude: Double?
    let duration: String?
    let airlineLogo: String?
    let airplane: String?
    let travelClass: String?

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
                scheduledDepartureTime: TravelValue.string(wrapped, ["scheduled_departure_time"]),
                actualDepartureTime: TravelValue.string(wrapped, ["actual_departure_time"]),
                departureDelayMinutes: TravelValue.int(wrapped, ["departure_delay_minutes"]),
                departurePlatform: TravelValue.string(wrapped, ["departure_platform"]),
                departurePlatformChanged: TravelValue.bool(wrapped, ["departure_platform_changed"]) ?? false,
                departureCountryCode: TravelValue.string(wrapped, ["departure_country_code"]),
                departureIsDaytime: TravelValue.bool(wrapped, ["departure_is_daytime"]) ?? false,
                departureLatitude: TravelValue.double(wrapped, ["departure_latitude"]),
                departureLongitude: TravelValue.double(wrapped, ["departure_longitude"]),
                arrivalStation: TravelValue.string(wrapped, ["arrival_station"]) ?? "",
                arrivalTime: TravelValue.formatTime(TravelValue.string(wrapped, ["arrival_time"]) ?? ""),
                scheduledArrivalTime: TravelValue.string(wrapped, ["scheduled_arrival_time"]),
                actualArrivalTime: TravelValue.string(wrapped, ["actual_arrival_time"]),
                arrivalDelayMinutes: TravelValue.int(wrapped, ["arrival_delay_minutes"]),
                arrivalPlatform: TravelValue.string(wrapped, ["arrival_platform"]),
                arrivalPlatformChanged: TravelValue.bool(wrapped, ["arrival_platform_changed"]) ?? false,
                arrivalCountryCode: TravelValue.string(wrapped, ["arrival_country_code"]),
                arrivalIsDaytime: TravelValue.bool(wrapped, ["arrival_is_daytime"]) ?? false,
                arrivalLatitude: TravelValue.double(wrapped, ["arrival_latitude"]),
                arrivalLongitude: TravelValue.double(wrapped, ["arrival_longitude"]),
                duration: TravelValue.string(wrapped, ["duration"]),
                airlineLogo: TravelValue.string(wrapped, ["airline_logo"]),
                airplane: TravelValue.string(wrapped, ["airplane"]),
                travelClass: TravelValue.string(wrapped, ["travel_class"])
            )
        }
    }

    var carrierFlightText: String {
        [carrier, number].compactMap { value in
            guard let value, !value.isEmpty else { return nil }
            return value
        }.joined(separator: " | ")
    }

    var airlineLogoURL: URL? {
        guard let airlineLogo, !airlineLogo.isEmpty else { return nil }
        return URL(string: airlineLogo)
    }

    var departureDelayText: String? {
        TravelValue.delayText(departureDelayMinutes)
    }

    var arrivalDelayText: String? {
        TravelValue.delayText(arrivalDelayMinutes)
    }

    #if canImport(MapKit)
    var departureCoordinate: CLLocationCoordinate2D? {
        guard let departureLatitude, let departureLongitude else { return nil }
        let coordinate = CLLocationCoordinate2D(latitude: departureLatitude, longitude: departureLongitude)
        return CLLocationCoordinate2DIsValid(coordinate) ? coordinate : nil
    }

    var arrivalCoordinate: CLLocationCoordinate2D? {
        guard let arrivalLatitude, let arrivalLongitude else { return nil }
        let coordinate = CLLocationCoordinate2D(latitude: arrivalLatitude, longitude: arrivalLongitude)
        return CLLocationCoordinate2DIsValid(coordinate) ? coordinate : nil
    }
    #endif
}

private struct TravelLayoverSummary {
    let airport: String?
    let duration: String?
    let overnight: Bool

    static func list(from data: [String: AnyCodable]) -> [TravelLayoverSummary] {
        guard let layovers = data["layovers"]?.value as? [[String: Any]] else { return [] }
        return layovers.map { dict in
            let wrapped = dict.mapValues(AnyCodable.init)
            return TravelLayoverSummary(
                airport: TravelValue.string(wrapped, ["airport"]),
                duration: TravelValue.string(wrapped, ["duration"]),
                overnight: TravelValue.bool(wrapped, ["overnight"]) ?? false
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

    static func bool(_ data: [String: AnyCodable]?, _ keys: [String]) -> Bool? {
        for key in keys {
            if let bool = data?[key]?.value as? Bool { return bool }
            if let string = data?[key]?.value as? String {
                if string == "true" { return true }
                if string == "false" { return false }
            }
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
        if let value = data?[key]?.value as? String, !value.isEmpty, value != "null" {
            return value
                .split { separator in
                    separator == "|" || separator == ","
                }
                .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                .filter { !$0.isEmpty }
        }
        var output: [String] = []
        for index in 0..<20 {
            if let value = data?["\(key)_\(index)"]?.value as? String {
                output.append(value)
            }
        }
        return output
    }

    static func iataCode(from value: String?) -> String? {
        guard let value else { return nil }
        if let match = value.range(of: #"\(([A-Z]{3})\)"#, options: .regularExpression) {
            return String(value[match]).trimmingCharacters(in: CharacterSet(charactersIn: "()"))
        }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.count == 3 ? trimmed.uppercased() : nil
    }

    static func delayText(_ minutes: Int?) -> String? {
        guard let minutes else { return nil }
        if minutes == 0 { return "On time" }
        if minutes > 0 { return "+\(minutes) min" }
        return "\(minutes) min"
    }

    static func countryFlag(_ code: String?) -> String? {
        guard let code else { return nil }
        let scalars = code.uppercased().unicodeScalars.compactMap { scalar -> UnicodeScalar? in
            guard scalar.value >= 65, scalar.value <= 90 else { return nil }
            return UnicodeScalar(127397 + scalar.value)
        }
        guard scalars.count == 2 else { return nil }
        return String(String.UnicodeScalarView(scalars))
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

        for format in ["yyyy-MM-dd'T'HH:mm:ssXXXXX", "yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd HH:mm", "yyyy-MM-dd"] {
            formatter.dateFormat = format
            if let date = formatter.date(from: value) { return date }
        }

        return nil
    }
}
