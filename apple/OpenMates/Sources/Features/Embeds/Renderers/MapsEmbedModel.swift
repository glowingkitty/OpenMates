// Maps payload normalization shared by preview, fullscreen, header and actions.
// Web: maps/MapsLocationEmbedPreview.svelte, maps/MapsLocationEmbedFullscreen.svelte,
//      maps/MapLocationEmbedFullscreen.svelte.
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity

import Foundation
import CoreFoundation
#if canImport(MapKit)
import MapKit
#endif

@MainActor
struct MapsEmbedModel {
    let name: String?
    let address: String?
    let placeType: String?
    let locationType: String?
    let latitude: Double?
    let longitude: Double?
    let zoom: Double
    let rating: Double?
    let reviewCount: Int?
    let mapImageURL: URL?
    let imageURL: URL?
    let websiteURL: URL?
    let placeID: String?

    init(_ payload: [String: AnyCodable]?) {
        let data = payload ?? [:]
        name = Self.string(data, ["displayName", "display_name", "name", "title"])
        address = Self.string(data, ["formattedAddress", "formatted_address", "address"])
        placeType = Self.string(data, ["placeType", "place_type", "category"])
            ?? (data["types"]?.value as? [String])?.first
        locationType = Self.string(data, ["location_type", "locationType"])
        let location = Self.record(data["location"]?.value)
        latitude = Self.number(location, ["latitude", "lat"], range: -90...90)
            ?? Self.number(data, ["location_latitude", "location_lat", "latitude", "lat"], range: -90...90)
        longitude = Self.number(location, ["longitude", "lon", "lng"], range: -180...180)
            ?? Self.number(data, ["location_longitude", "location_lon", "location_lng", "longitude", "lon", "lng"], range: -180...180)
        zoom = min(20, max(2, Self.number(data, ["zoom"]) ?? 15))
        rating = Self.number(data, ["rating"], range: 0...5)
        if let reviews = Self.number(data, ["userRatingCount", "user_rating_count", "reviews"], range: 0...Double(Int32.max)) {
            reviewCount = Int(reviews)
        } else { reviewCount = nil }
        mapImageURL = Self.imageURL(Self.string(data, ["map_image_url", "mapImageUrl"]))
        imageURL = Self.imageURL(Self.string(data, ["imageUrl", "image_url", "photo_url"]))
        websiteURL = Self.httpURL(Self.string(data, ["websiteUri", "website_uri", "website", "website_url"]))
        placeID = Self.string(data, ["placeId", "place_id"])
    }

    var primaryName: String? {
        name?.components(separatedBy: .newlines).first?.trimmingCharacters(in: .whitespacesAndNewlines)
    }
    var isNearby: Bool { locationType == "area" }
    var isTransit: Bool {
        ["railway", "airport", "subway", "s-bahn", "tram", "bus", "ferry"].contains(placeType?.lowercased() ?? "")
    }
    var hasCoordinates: Bool { latitude != nil && longitude != nil }
    var ratingText: String? { rating.map { String(format: "%.1f", $0) } }
    var websiteLabel: String? {
        guard let websiteURL else { return nil }
        var label = websiteURL.absoluteString
        for prefix in ["https://", "http://", "www."] where label.hasPrefix(prefix) { label.removeFirst(prefix.count) }
        if label.hasSuffix("/") { label.removeLast() }
        return label
    }

    func googleMapsURL(isPlace: Bool) -> URL? {
        if isPlace, let placeID {
            return Self.url("https://www.google.com/maps/place/", query: [("q", "place_id:\(placeID)")])
        }
        if let latitude, let longitude {
            return Self.url("https://www.google.com/maps/search/", query: [("api", "1"), ("query", "\(latitude),\(longitude)")])
        }
        if isPlace, let address {
            return Self.url("https://www.google.com/maps/search/", query: [("api", "1"), ("query", address)])
        }
        return nil
    }
    var osmURL: URL? {
        guard let latitude, let longitude else { return nil }
        return Self.url("https://www.openstreetmap.org/", query: [("mlat", "\(latitude)"), ("mlon", "\(longitude)"), ("zoom", "\(zoom)")])
    }

    #if canImport(MapKit)
    var mapConfiguration: EmbedMapConfiguration? {
        guard let latitude, let longitude else { return nil }
        let coordinate = CLLocationCoordinate2D(latitude: latitude, longitude: longitude)
        // Same zoom meaning as Leaflet, with a bounded span for MapKit.
        let span = max(0.0003, min(120, 360 / pow(2, zoom)))
        return EmbedMapConfiguration(center: coordinate,
            markers: [EmbedMapMarker(coordinate: coordinate, title: name ?? address ?? AppStrings.domainLocation)],
            latitudeDelta: span, longitudeDelta: span)
    }
    #else
    var mapConfiguration: Never? { nil }
    #endif

    private static func string(_ data: [String: AnyCodable], _ keys: [String]) -> String? {
        keys.lazy.compactMap { key -> String? in
            guard let value = data[key]?.value as? String else { return nil }
            let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
            return trimmed.isEmpty || trimmed == "null" ? nil : trimmed
        }.first
    }
    private static func number(_ data: [String: AnyCodable], _ keys: [String], range: ClosedRange<Double>? = nil) -> Double? {
        for key in keys {
            guard let raw = data[key]?.value else { continue }
            // JSON booleans bridge through NSNumber; they are never coordinates.
            if let value = raw as? NSNumber, CFGetTypeID(value) == CFBooleanGetTypeID() { continue }
            let value: Double?
            if let string = raw as? String { value = Double(string.trimmingCharacters(in: .whitespacesAndNewlines)) }
            else if let number = raw as? NSNumber { value = number.doubleValue }
            else { value = nil }
            if let value, value.isFinite, range?.contains(value) != false { return value }
        }
        return nil
    }
    private static func record(_ raw: Any?) -> [String: AnyCodable] {
        if let data = raw as? [String: AnyCodable] { return data }
        return (raw as? [String: Any])?.mapValues(AnyCodable.init) ?? [:]
    }
    private static func httpURL(_ value: String?) -> URL? {
        guard let value, let url = URL(string: value),
              ["https", "http"].contains(url.scheme?.lowercased() ?? ""),
              url.host?.isEmpty == false, url.user == nil, url.password == nil else { return nil }
        return url
    }
    private static func imageURL(_ value: String?) -> URL? {
        guard let value else { return nil }
        if let url = httpURL(value) { return url }
        // Static SVGs are validated by the shared cached image loader before paint.
        if value.hasPrefix("data:image/"), value.utf8.count <= 3_000_000 { return URL(string: value) }
        if value.hasPrefix("/"), !value.hasPrefix("//"),
           let proxied = EmbedFieldReader.proxiedImageURL(value, maxWidth: 640) { return httpURL(proxied) }
        return nil
    }
    private static func url(_ base: String, query: [(String, String)]) -> URL? {
        var components = URLComponents(string: base)
        components?.queryItems = query.map { URLQueryItem(name: $0.0, value: $0.1) }
        return components?.url
    }
}
