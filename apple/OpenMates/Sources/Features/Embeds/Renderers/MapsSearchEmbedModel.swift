// Maps search presentation uses the existing decrypted child graph and inline fallback.
// Web: frontend/packages/ui/src/components/embeds/maps/MapsSearchEmbedPreview.svelte
//      frontend/packages/ui/src/components/embeds/maps/MapsSearchEmbedFullscreen.svelte
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity, chats.rendering.assistant-document-convergence
import Foundation
#if canImport(MapKit)
import MapKit
#endif

enum MapsSearchEmbedKind {
    static func isSearch(_ embed: EmbedRecord) -> Bool {
        if EmbedType.normalized(rawValue: embed.type) == .mapsSearch { return true }
        return embed.isAppSkillUse
            && (embed.appId ?? embed.rawData?["app_id"]?.value as? String) == "maps"
            && (embed.skillId ?? embed.rawData?["skill_id"]?.value as? String) == "search"
    }
}

@MainActor
struct MapsSearchEmbedModel {
    enum State: Equatable { case loading, results, empty, filtered, error }
    let query: String
    let provider: String
    let resultCount: Int
    let results: [EmbedRecord]
    let warnings: [String]
    let requiredAmenities: [String]
    let filterStatus: String?
    let candidateCount: Int?
    let verifiedCount: Int?
    let coverage: String?
    let searchContext: [String: AnyCodable]
    let searchStatus: String?
    let error: String?
    let state: State

    init(embed: EmbedRecord, allEmbedRecords: [String: EmbedRecord]) {
        let raw = embed.rawData ?? [:]
        let decoded = (raw["results_toon"]?.value as? String).map(EmbedRecord.parseContent) ?? [:]
        let encoded = decoded.mapValues(AnyCodable.init)
        let group = EmbedFieldReader.dictionaryArray(raw, key: "results").first
            ?? EmbedFieldReader.dictionaryArray(encoded, key: "results").first ?? [:]
        // Root fields win, while group/TOON metadata survives compacted payloads.
        let fields = encoded.merging(group.mapValues(AnyCodable.init)) { _, group in group }
            .merging(raw) { _, root in root }
        query = EmbedFieldReader.string(fields, keys: ["query", "title"]) ?? AppStrings.search
        let rawProvider = EmbedFieldReader.string(fields, keys: ["provider"]) ?? "Google"
        provider = rawProvider.lowercased() == "geoapify" ? "Geoapify"
            : rawProvider.lowercased() == "google" ? "Google" : rawProvider
        let refs = embed.childEmbedIds.isEmpty
            ? EmbedFieldReader.stringArray(fields, keys: ["embed_ids"]) : embed.childEmbedIds
        let rows = SearchDomainParentModel.flattenedRows(from: raw).filter(Self.isPlaceRow)
        let inline = rows.enumerated().map { index, row in
            EmbedRecord(id: row["embed_id"] as? String
                ?? (refs.indices.contains(index) ? refs[index] : nil) ?? "\(embed.id)-place-\(index)",
                type: "maps-place", status: .finished, data: .raw(row.mapValues(AnyCodable.init)),
                parentEmbedId: embed.id, appId: "maps", skillId: nil, embedIds: nil,
                createdAt: embed.createdAt)
        }
        let fallback = rows.isEmpty ? SearchSkillPreviewModel(embed: embed, allEmbedRecords: [:]).childEmbeds.filter { Self.isPlaceRow(($0.rawData ?? [:]).mapValues(\.value)) }.map {
            EmbedRecord(id: $0.id, type: "maps-place", status: $0.status, data: $0.data,
                parentEmbedId: embed.id, appId: "maps", skillId: nil, embedIds: nil, createdAt: $0.createdAt)
        } : []
        let hydrated = refs.compactMap { allEmbedRecords[$0] }
            + allEmbedRecords.values.filter { $0.parentEmbedId == embed.id }
                .sorted { ($0.createdAt ?? $0.id) < ($1.createdAt ?? $1.id) }
        results = SearchSkillPreviewModel.mergedRecords(parentOrder: refs,
            inlineRecords: inline + fallback, hydratedRecords: hydrated)
        resultCount = max(0, EmbedFieldReader.int(fields, keys: ["result_count", "total_results"])
            ?? max(refs.count, results.count))
        warnings = EmbedFieldReader.stringArray(fields, keys: ["warnings"])
        let filters = Self.record(fields["filter_summary"]?.value)
        requiredAmenities = EmbedFieldReader.stringArray(filters, keys: ["required"]).isEmpty
            ? EmbedFieldReader.stringArray(fields, keys: ["filter_summary_required"])
            : EmbedFieldReader.stringArray(filters, keys: ["required"])
        filterStatus = EmbedFieldReader.string(filters, keys: ["status"])
            ?? EmbedFieldReader.string(fields, keys: ["filter_summary_status"])
        candidateCount = EmbedFieldReader.int(filters, keys: ["candidate_count"])
            ?? EmbedFieldReader.int(fields, keys: ["filter_summary_candidate_count"])
        verifiedCount = EmbedFieldReader.int(filters, keys: ["verified_count"])
            ?? EmbedFieldReader.int(fields, keys: ["filter_summary_verified_count"])
        coverage = EmbedFieldReader.string(fields, keys: ["coverage"])
        searchContext = Self.record(fields["search_context"]?.value).merging(
            Dictionary(uniqueKeysWithValues: fields.compactMap { key, value in
                key.hasPrefix("search_context_") ? (String(key.dropFirst("search_context_".count)), value) : nil
            })) { nested, _ in nested }
        searchStatus = EmbedFieldReader.string(fields, keys: ["search_status"])
            ?? EmbedFieldReader.string(group.mapValues(AnyCodable.init), keys: ["status"])
            ?? EmbedFieldReader.string(encoded, keys: ["status"])
        let payloadError = EmbedFieldReader.string(fields, keys: ["error"])
        let quotaFailure = ["quota_exhausted", "quota_unavailable", "rate_limited"].contains(searchStatus ?? "")
        error = payloadError ?? (quotaFailure || embed.status == .error ? AppStrings.searchFailed : nil)
        if error != nil { state = .error }
        else if embed.status != .finished { state = .loading }
        else if resultCount > 0 { state = .results }
        else if filterStatus == "no_verified_results" { state = .filtered }
        else { state = .empty }
    }

    func child(forMarkerID id: String) -> EmbedRecord? {
        results.first { $0.id == id && MapsEmbedModel($0.rawData).hasCoordinates }
    }

    private static func isPlaceRow(_ row: [String: Any]) -> Bool {
        ["place_id", "placeId", "name", "displayName", "formatted_address", "location", "location_latitude", "latitude"].contains { row[$0] != nil }
    }

    private static func record(_ value: Any?) -> [String: AnyCodable] {
        if let value = value as? [String: AnyCodable] { return value }
        return (value as? [String: Any])?.mapValues(AnyCodable.init) ?? [:]
    }

    #if canImport(MapKit)
    // Reset map camera only when the resolved coordinate set changes during hydration.
    var mapIdentity: String {
        results.compactMap { record -> String? in
            let place = MapsEmbedModel(record.rawData)
            guard let lat = place.latitude, let lon = place.longitude else { return nil }
            return "\(record.id):\(lat),\(lon)"
        }.joined(separator: "|")
    }

    var mapConfiguration: EmbedMapConfiguration? {
        let markers = results.compactMap { record -> EmbedMapMarker? in
            let place = MapsEmbedModel(record.rawData)
            guard let latitude = place.latitude, let longitude = place.longitude else { return nil }
            return EmbedMapMarker(resultID: record.id, coordinate: CLLocationCoordinate2D(latitude: latitude, longitude: longitude),
                title: place.name ?? place.address ?? AppStrings.domainLocation)
        }
        guard let first = markers.first else { return nil }
        let latitudes = markers.map { $0.coordinate.latitude }
        let longitudes = markers.map { $0.coordinate.longitude }
        let minLat = latitudes.min() ?? first.coordinate.latitude
        let maxLat = latitudes.max() ?? first.coordinate.latitude
        let minLon = longitudes.min() ?? first.coordinate.longitude
        let maxLon = longitudes.max() ?? first.coordinate.longitude
        return EmbedMapConfiguration(center: CLLocationCoordinate2D(latitude: (minLat + maxLat) / 2,
            longitude: (minLon + maxLon) / 2), markers: markers,
            latitudeDelta: max(0.005, (maxLat - minLat) * 1.4),
            longitudeDelta: max(0.005, (maxLon - minLon) * 1.4))
    }
    #else
    var mapConfiguration: Never? { nil }
    #endif
}
