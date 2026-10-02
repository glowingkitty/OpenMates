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
}
