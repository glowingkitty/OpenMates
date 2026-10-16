// Maps normalized and raw payloads must render the same location and safe actions.
import XCTest
@testable import OpenMates

@MainActor
final class MapsEmbedModelTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testNormalizedAndRawPlaceAliasesPreserveDetailsAndCoordinates() {
        let normalized = MapsEmbedModel([
            "displayName": AnyCodable("Coffee Shop"), "formattedAddress": AnyCodable("A Street"),
            "location": AnyCodable(["latitude": "48.1321", "longitude": "11.5718"]),
            "userRatingCount": AnyCodable("1832"), "placeType": AnyCodable("Coffee Shop"),
            "rating": AnyCodable("4.7"), "websiteUri": AnyCodable("https://www.example.test/")
        ])
        let raw = MapsEmbedModel([
            "name": AnyCodable("Coffee Shop"), "formatted_address": AnyCodable("A Street"),
            "location_lat": AnyCodable(48.1321), "location_lng": AnyCodable(11.5718),
            "user_rating_count": AnyCodable(1832), "place_type": AnyCodable("Coffee Shop"),
            "rating": AnyCodable(4.7), "website_uri": AnyCodable("https://www.example.test/")
        ])
        XCTAssertEqual(normalized.name, raw.name)
        XCTAssertEqual(normalized.address, raw.address)
        XCTAssertEqual(normalized.latitude, raw.latitude)
        XCTAssertEqual(normalized.longitude, raw.longitude)
        XCTAssertEqual(normalized.ratingText, "4.7")
        XCTAssertEqual(normalized.reviewCount, 1832)
        XCTAssertEqual(normalized.placeType, raw.placeType)
        XCTAssertEqual(normalized.websiteLabel, "example.test")
        XCTAssertEqual(normalized.googleMapsURL(isPlace: true), raw.googleMapsURL(isPlace: true))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testLegacyTitleTransitAndAreaAliases() {
        let model = MapsEmbedModel(["title": AnyCodable("Berlin Hauptbahnhof\nBerlin"),
            "locationType": AnyCodable("area"), "placeType": AnyCodable("Railway"),
            "mapImageUrl": AnyCodable("data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%3E%3C/svg%3E")])
        XCTAssertEqual(model.primaryName, "Berlin Hauptbahnhof")
        XCTAssertTrue(model.isNearby)
        XCTAssertTrue(model.isTransit)
        XCTAssertNotNil(model.mapImageURL)
        XCTAssertNil(model.googleMapsURL(isPlace: false))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testCoordinatesAndZoomAreFiniteAndBoundedIncludingBooleanPayloads() {
        for value: Any in [Double.nan, Double.infinity, "NaN", "Infinity", true, 91, -91] {
            let model = MapsEmbedModel(["latitude": AnyCodable(value), "longitude": AnyCodable(13)])
            XCTAssertFalse(model.hasCoordinates)
            XCTAssertNil(model.osmURL)
            XCTAssertNil(model.mapConfiguration)
        }
        for value: Any in [181, -181, false, "Infinity"] {
            XCTAssertFalse(MapsEmbedModel(["lat": AnyCodable(48), "lon": AnyCodable(value)]).hasCoordinates)
        }
        let fallback = MapsEmbedModel(["latitude": AnyCodable(900), "lat": AnyCodable("0"),
            "longitude": AnyCodable(0), "zoom": AnyCodable(900)])
        XCTAssertTrue(fallback.hasCoordinates)
        XCTAssertEqual(fallback.zoom, 20)
        XCTAssertEqual(MapsEmbedModel(["zoom": AnyCodable(-900)]).zoom, 2)
        XCTAssertEqual(MapsEmbedModel(["zoom": AnyCodable(Double.nan)]).zoom, 15)
        XCTAssertNil(MapsEmbedModel(["rating": AnyCodable(6), "reviews": AnyCodable(-1)]).rating)
        XCTAssertNil(MapsEmbedModel(["reviews": AnyCodable(Double.infinity)]).reviewCount)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testMapActionsEscapeUntrustedQueryAndRejectUnsafeWebsiteSchemes() {
        let placeID = "place & x=# fragment + ü"
        let model = MapsEmbedModel(["place_id": AnyCodable(placeID)])
        let components = URLComponents(url: model.googleMapsURL(isPlace: true)!, resolvingAgainstBaseURL: false)!
        XCTAssertEqual(components.host, "www.google.com")
        XCTAssertEqual(components.queryItems, [URLQueryItem(name: "q", value: "place_id:\(placeID)")])
        XCTAssertNil(components.fragment)
        let address = "A & B #1, München"
        let byAddress = MapsEmbedModel(["address": AnyCodable(address)])
        XCTAssertEqual(URLComponents(url: byAddress.googleMapsURL(isPlace: true)!, resolvingAgainstBaseURL: false)?.queryItems?.last?.value, address)
        XCTAssertNil(byAddress.googleMapsURL(isPlace: false))
        for value in ["javascript:alert(1)", "file:///tmp/private", "https://user:password@example.test/", "//example.test/"] {
            XCTAssertNil(MapsEmbedModel(["websiteUri": AnyCodable(value)]).websiteURL)
        }
        XCTAssertNil(MapsEmbedModel(["map_image_url": AnyCodable("javascript:alert(1)")]).mapImageURL)
        let coordinates = MapsEmbedModel(["lat": AnyCodable(48.1321), "lon": AnyCodable(11.5718), "zoom": AnyCodable(16)])
        XCTAssertEqual(URLComponents(url: coordinates.osmURL!, resolvingAgainstBaseURL: false)?.queryItems?.map(\.name), ["mlat", "mlon", "zoom"])
        XCTAssertEqual(coordinates.mapConfiguration?.markers.count, 1)
        XCTAssertEqual(coordinates.mapConfiguration?.center.latitude ?? 0, 48.1321, accuracy: 0.00001)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.assistant-document-convergence
    func testDiscoveryIdentitySourceDistanceAndCoordinateGoogleAction() {
        for identity in [["provider": AnyCodable("Geoapify"), "place_id": AnyCodable("external-id")],
                         ["place_id": AnyCodable("geoapify:public-ruin")]] {
            let place = MapsEmbedModel(identity.merging([
                "name": AnyCodable("Ruine der Franziskaner-Klosterkirche"),
                "categories": AnyCodable("ruins|tourism"),
                "location_latitude": AnyCodable(52.5184314), "location_longitude": AnyCodable(13.4125411),
                "distance_meters": AnyCodable(539), "data_source": AnyCodable("OpenStreetMap via Geoapify"),
                "source_url": AnyCodable("https://www.openstreetmap.org/way/123")
            ]) { first, _ in first })
            XCTAssertTrue(place.isGeoapify)
            XCTAssertEqual(place.placeID, identity["place_id"]?.value as? String)
            XCTAssertEqual(place.name, "Ruine der Franziskaner-Klosterkirche")
            XCTAssertEqual(place.placeType, "ruins")
            XCTAssertEqual(place.distanceText, "539 m")
            XCTAssertEqual(place.dataSource, "OpenStreetMap via Geoapify")
            XCTAssertEqual(place.sourceURL?.host, "www.openstreetmap.org")
            XCTAssertNil(place.rating)
            XCTAssertNil(place.reviewCount)
            let action = URLComponents(url: place.googleMapsURL(isPlace: true)!, resolvingAgainstBaseURL: false)!
            XCTAssertEqual(action.queryItems, [URLQueryItem(name: "api", value: "1"),
                URLQueryItem(name: "query", value: "52.5184314,13.4125411")])
            XCTAssertFalse(action.url!.absoluteString.contains("geoapify"))
        }
        let noCoordinates = MapsEmbedModel(["place_id": AnyCodable("geoapify:123"), "address": AnyCodable("Berlin")])
        XCTAssertNil(noCoordinates.googleMapsURL(isPlace: true))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.assistant-document-convergence
    func testDiscoveryRejectsUnsafeSourcesAndNonFiniteDistance() {
        for url in ["javascript:alert(1)", "file:///private", "//example.test", "https://user:password@example.test"] {
            XCTAssertNil(MapsEmbedModel(["source_url": AnyCodable(url)]).sourceURL)
        }
        for value: Any in [Double.nan, Double.infinity, true, -1, "NaN"] {
            XCTAssertNil(MapsEmbedModel(["distance_meters": AnyCodable(value)]).distanceText)
        }
        XCTAssertEqual(MapsEmbedModel(["distance_meters": AnyCodable(1250)]).distanceText, "1.3 km")
        XCTAssertEqual(MapsEmbedModel(["distance_meters": AnyCodable(538.5)]).distanceText, "539 m")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.assistant-document-convergence
    func testRegularGoogleSearchRetainsIdentityActionAndRating() {
        let place = MapsEmbedModel(["provider": AnyCodable("Google"), "place_id": AnyCodable("google-public-id"),
            "rating": AnyCodable(4.7), "user_rating_count": AnyCodable(1832), "name": AnyCodable("Coffee Shop")])
        XCTAssertFalse(place.isGeoapify)
        XCTAssertEqual(place.ratingText, "4.7")
        XCTAssertEqual(place.reviewCount, 1832)
        XCTAssertEqual(URLComponents(url: place.googleMapsURL(isPlace: true)!, resolvingAgainstBaseURL: false)?.queryItems,
            [URLQueryItem(name: "q", value: "place_id:google-public-id")])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.assistant-document-convergence
    func testParentCountOrderAndMapSurvivePartialHydration() {
        let raw: [String: AnyCodable] = ["provider": AnyCodable("Geoapify"), "result_count": AnyCodable(2),
            "embed_ids": AnyCodable("second|first"), "results": AnyCodable([
                ["embed_id": "first", "name": "First", "latitude": 52.51, "longitude": 13.4] as [String: Any],
                ["embed_id": "second", "name": "Second", "latitude": 52.52, "longitude": 13.41] as [String: Any]])]
        let parent = EmbedRecord(id: "parent", type: "app:maps:search", status: .finished,
            data: .raw(raw), parentEmbedId: nil, appId: "maps", skillId: "search", embedIds: nil, createdAt: nil)
        let before = MapsSearchEmbedModel(embed: parent, allEmbedRecords: [:])
        XCTAssertEqual(before.resultCount, 2)
        XCTAssertEqual(before.results.map(\.id), ["second", "first"])
        XCTAssertEqual(before.mapConfiguration?.markers.count, 2)
        let hydrated = EmbedRecord(id: "first", type: "maps-place", status: .finished,
            data: .raw(["name": AnyCodable("First hydrated"), "lat": AnyCodable(52.51), "lon": AnyCodable(13.4)]),
            parentEmbedId: "parent", appId: "maps", skillId: nil, embedIds: nil, createdAt: nil)
        let partial = MapsSearchEmbedModel(embed: parent, allEmbedRecords: ["first": hydrated])
        XCTAssertEqual(partial.results.map(\.id), ["second", "first"])
        XCTAssertEqual(MapsEmbedModel(partial.results[1].rawData).name, "First hydrated")
        XCTAssertEqual(partial.resultCount, 2)
        XCTAssertEqual(partial.mapConfiguration?.markers.count, 2)
        XCTAssertEqual(partial.mapConfiguration?.markers.map(\.resultID), ["second", "first"])
        XCTAssertEqual(partial.child(forMarkerID: "first")?.id, "first")
        XCTAssertEqual(MapsEmbedModel(partial.child(forMarkerID: "first")?.rawData).name, "First hydrated")
        XCTAssertNil(partial.child(forMarkerID: "missing"))
        let pending = EmbedRecord(id: "pending", type: "app:maps:search", status: .finished,
            data: .raw(["result_count": AnyCodable(2), "embed_ids": AnyCodable("second|first")]), parentEmbedId: nil, appId: "maps", skillId: "search", embedIds: nil, createdAt: nil)
        XCTAssertEqual(MapsSearchEmbedModel(embed: pending, allEmbedRecords: [:]).resultCount, 2)
        XCTAssertEqual(MapsSearchEmbedModel(embed: pending, allEmbedRecords: [:]).state, .results)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.assistant-document-convergence
    func testFinishedParentDistinguishesQuotaFilteredEmptyAndWarnings() {
        func model(_ raw: [String: AnyCodable]) -> MapsSearchEmbedModel {
            MapsSearchEmbedModel(embed: EmbedRecord(id: "parent", type: "app:maps:search", status: .finished,
                data: .raw(raw), parentEmbedId: nil, appId: "maps", skillId: "search", embedIds: nil, createdAt: nil), allEmbedRecords: [:])
        }
        XCTAssertEqual(model([:]).state, .empty)
        for status in ["quota_exhausted", "quota_unavailable", "rate_limited"] {
            let quota = model(["provider": AnyCodable("Geoapify"), "search_status": AnyCodable(status),
                "result_count": AnyCodable(0), "error": AnyCodable("Discovery is unavailable. Try again later.")])
            XCTAssertEqual(quota.state, .error)
            XCTAssertEqual(quota.provider, "Geoapify")
            XCTAssertEqual(quota.error, "Discovery is unavailable. Try again later.")
        }
        let filtered = model(["filter_summary_status": AnyCodable("no_verified_results"),
            "filter_summary_required": AnyCodable("wheelchair|drinking_water"),
            "filter_summary_candidate_count": AnyCodable(6), "filter_summary_verified_count": AnyCodable(0)])
        XCTAssertEqual(filtered.state, .filtered)
        XCTAssertEqual(filtered.requiredAmenities, ["wheelchair", "drinking_water"])
        XCTAssertEqual(filtered.candidateCount, 6)
        XCTAssertEqual(filtered.verifiedCount, 0)
        let warning = model(["result_count": AnyCodable(2), "warnings": AnyCodable("Access unknown|OSM coverage varies"),
            "coverage": AnyCodable("OSM coverage varies"), "search_context_cache_hit": AnyCodable(true)])
        XCTAssertEqual(warning.state, .results)
        XCTAssertEqual(warning.warnings.count, 2)
        XCTAssertEqual(warning.coverage, "OSM coverage varies")
        XCTAssertEqual(warning.searchContext["cache_hit"]?.value as? Bool, true)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.assistant-document-convergence
    func testTOONParentRetainsPlaceRowsAndFlattenedMetadata() {
        let toon = """
        provider: Geoapify
        result_count: 1
        warnings: Access unknown|Coverage varies
        filter_summary_required: wheelchair|toilets
        results[1]{embed_id,name,place_id,location_latitude,location_longitude,distance_meters,data_source}:
          public-ruin,Unnamed ruins,geoapify:public-ruin,52.5184314,13.4125411,539,OpenStreetMap via Geoapify
        """
        let parent = EmbedRecord(id: "toon", type: "app:maps:search", status: .finished,
            data: .raw(["results_toon": AnyCodable(toon)]), parentEmbedId: nil, appId: "maps", skillId: "search", embedIds: nil, createdAt: nil)
        let parsed = MapsSearchEmbedModel(embed: parent, allEmbedRecords: [:])
        XCTAssertEqual(parsed.provider, "Geoapify")
        XCTAssertEqual(parsed.resultCount, 1)
        XCTAssertEqual(parsed.warnings, ["Access unknown", "Coverage varies"])
        XCTAssertEqual(parsed.requiredAmenities, ["wheelchair", "toilets"])
        XCTAssertEqual(parsed.results.count, 1)
        XCTAssertEqual(MapsEmbedModel(parsed.results.first?.rawData).distanceText, "539 m")
        XCTAssertEqual(parsed.mapConfiguration?.markers.count, 1)
    }

}
