import XCTest
@testable import OpenMates

@MainActor
final class SearchDomainRenderersTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testNewsArticleKeepsNestedThumbnailIdentityAndNewsChrome() throws {
        let child = record(id: "article", type: "web-website", data: [
            "url": AnyCodable("https://example.com/news"),
            "thumbnail": AnyCodable(["original": "/images/og-image.jpg"]),
            "description": AnyCodable("Article summary")])
        let result = try XCTUnwrap(WebsiteResultModel(embed: child))
        let article = NewsSearchEmbedRenderer.articleRecord(for: result)
        XCTAssertEqual(article.id, child.id)
        XCTAssertEqual(article.appId, "news")
        XCTAssertEqual(article.rawData?["thumbnail_original"]?.value as? String, "/images/og-image.jpg")
        XCTAssertEqual(NewsPreviewLayout.descriptionWidth(containerWidth: 280, hasImage: true), 130)
        XCTAssertEqual(NewsPreviewLayout.descriptionWidth(containerWidth: 260, hasImage: false), 260)
        let generic = EmbedRecord(id: "parent", type: "app-skill-use", status: .finished,
                                 data: .raw([:]), parentEmbedId: nil, appId: "news", skillId: "search",
                                 embedIds: nil, createdAt: nil)
        XCTAssertEqual(EmbedVisualSkillIcon.name(for: generic), "search")
    }

    #if canImport(MapKit)
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testAppointmentLocationMapAcceptsNestedFlatAndProviderAliasCoordinates() {
        let shapes: [[String: AnyCodable]] = [
            ["gps_coordinates": AnyCodable(["latitude": 48.1397, "longitude": 11.5784])],
            ["gps_coordinates": AnyCodable(["lat": "48.1397", "lon": "11.5784"])],
            ["gps_coordinates_latitude": AnyCodable("48.1397"), "gps_coordinates_longitude": AnyCodable("11.5784")]
        ]
        for coordinates in shapes {
            var raw = coordinates
            raw["name"] = AnyCodable("Synthetic Doctor")
            raw["address"] = AnyCodable("Synthetic Practice Address")
            let model = HealthAppointmentModel(raw)
            let configuration = model.mapConfiguration
            XCTAssertNotNil(configuration)
            XCTAssertEqual(configuration?.center.latitude ?? 0, 48.1397, accuracy: 0.000001)
            XCTAssertEqual(configuration?.center.longitude ?? 0, 11.5784, accuracy: 0.000001)
            XCTAssertEqual(configuration?.markers.first?.title, "Synthetic Doctor")
            XCTAssertEqual(configuration?.markers.count, 1)
            XCTAssertEqual(configuration?.latitudeDelta, 0.005)
        }
        XCTAssertNil(HealthAppointmentModel(["gps_coordinates": AnyCodable(["latitude": 148.1, "longitude": 11.5])]).mapConfiguration)
        XCTAssertNil(HealthAppointmentModel(["address": AnyCodable("Synthetic Address")]).mapConfiguration)
    }
    #endif

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testHealthSearchSummaryUsesSpecialityAndCityWithoutInventingQuery() {
        let parent = record(id: "health-parent", type: "app:health:search_appointments", data: [
            "speciality": AnyCodable("ophthalmologist"), "city": AnyCodable("munich")])
        XCTAssertEqual(SearchDomainParentModel(kind: .health, embed: parent, allEmbedRecords: [:]).query,
                       "Ophthalmologist in Munich")
        XCTAssertEqual(HealthAppointmentModel.searchSummary(["query": AnyCodable("Explicit query"),
            "city": AnyCodable("munich")]), "Explicit query")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testHealthAppointmentKeepsProviderBookingSlotAndHydratedMetadata() {
        let fields: [String: AnyCodable] = [
            "name": AnyCodable("Synthetic Doctor"), "speciality": AnyCodable("Synthetic Specialty"),
            "slot_datetime": AnyCodable("2026-04-03T10:30:00"), "provider_platform": AnyCodable("Jameda"),
            "booking_url": AnyCodable("https://example.com/booking"),
            "practice_url": AnyCodable("https://example.com/practice"),
            "additional_slot_datetimes": AnyCodable(["2026-04-03T14:00:00"])]
        let model = HealthAppointmentModel(fields)
        XCTAssertEqual(model.bookingURL?.path, "/booking")
        XCTAssertEqual(model.provider, "Jameda")
        XCTAssertEqual(model.subtitle, "Synthetic Doctor · Synthetic Specialty")
        XCTAssertNotNil(model.fullSlotLabel)
        XCTAssertEqual(model.fields.stringArray("additional_slot_datetimes"), ["2026-04-03T14:00:00"])
        var unsafe = fields
        unsafe["booking_url"] = AnyCodable("javascript:alert(1)")
        XCTAssertEqual(HealthAppointmentModel(unsafe).bookingURL?.path, "/practice")
        unsafe["practice_url"] = AnyCodable("http://example.com/practice")
        XCTAssertNil(HealthAppointmentModel(unsafe).bookingURL)
        XCTAssertNil(HealthAppointmentModel([:]).fullSlotLabel)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testNestedAppointmentResultsKeepChildTypeAndDeclaredOrder() {
        let parent = record(
            id: "health-parent", type: "app:health:search_appointments",
            data: [
                "query": AnyCodable("Ophthalmologist in Munich"),
                "provider": AnyCodable("Doctolib, Jameda"),
                "results": AnyCodable([[
                    "id": "group",
                    "results": [
                        ["embed_id": "appointment-b", "name": "Dr. B", "slot_datetime": "2026-04-03T10:30:00"],
                        ["embed_id": "appointment-a", "name": "Dr. A", "slot_datetime": "2026-04-03T08:00:00"]
                    ]
                ]])
            ], childIDs: ["appointment-a", "appointment-b"]
        )
        let model = SearchDomainParentModel(kind: .health, embed: parent, allEmbedRecords: [:])
        XCTAssertEqual(model.query, "Ophthalmologist in Munich")
        XCTAssertEqual(model.provider, "Doctolib, Jameda")
        XCTAssertEqual(model.results.map(\.id), ["appointment-a", "appointment-b"])
        XCTAssertEqual(model.results.map(\.type), ["health-appointment", "health-appointment"])
        XCTAssertEqual(model.resultCount, 2)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testHydratedShoppingChildReplacesOnlyMatchingInlineResult() {
        let parent = record(
            id: "shopping-parent", type: "app:shopping:search_products",
            data: ["results": AnyCodable([
                ["embed_id": "milk", "title": "Inline milk"],
                ["embed_id": "yogurt", "title": "Inline yogurt"]
            ])], childIDs: ["milk", "yogurt"]
        )
        let hydrated = record(id: "milk", type: "shopping-product", data: ["title": AnyCodable("Decrypted milk")])
        let model = SearchDomainParentModel(kind: .shopping, embed: parent, allEmbedRecords: ["milk": hydrated])
        XCTAssertEqual(model.results.map(\.id), ["milk", "yogurt"])
        XCTAssertEqual(model.results[0].rawData?["title"]?.value as? String, "Decrypted milk")
        XCTAssertEqual(model.results[1].rawData?["title"]?.value as? String, "Inline yogurt")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testPersistedEncodedResultsBecomeTypedHomeChildren() {
        let parent = record(
            id: "home-parent", type: "app:home:search",
            data: ["results_toon": AnyCodable("""
                {"results":[{"embed_id":"listing-1","title":"Schöne Wohnung","price_label":"850 EUR/month"}]}
                """)]
        )
        let model = SearchDomainParentModel(kind: .home, embed: parent, allEmbedRecords: [:])
        XCTAssertEqual(model.results.map(\.type), ["home-listing"])
        XCTAssertEqual(model.results.first?.rawData?["price_label"]?.value as? String, "850 EUR/month")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testTypedDetailMetadataAndOutboundURLValidation() {
        let recipe = DomainFields([
            "total_time_minutes": AnyCodable(25),
            "difficulty": AnyCodable("einfach"),
            "recipe_url": AnyCodable("javascript:alert(1)")
        ])
        XCTAssertEqual(recipe.recipeMetadata, ["25 min", "Easy"])
        XCTAssertNil(recipe.secureURL("recipe_url"))

        let product = DomainFields([
            "price_cents": AnyCodable(139),
            "was_price_cents": AnyCodable(179),
            "attributes": AnyCodable(["is_organic": true, "is_vegetarian": true])
        ])
        XCTAssertNotNil(product.productPrice)
        XCTAssertNotEqual(product.productPrice, product.oldProductPrice)
        XCTAssertEqual(product.productTags, ["Bio", "Vegetarisch"])

        let home = DomainFields([
            "price_label": AnyCodable("850 EUR/month"),
            "size_sqm": AnyCodable(55),
            "rooms": AnyCodable(2),
            "url": AnyCodable("https://www.immobilienscout24.de/expose/12345")
        ])
        XCTAssertEqual(home.homeMetadata, ["55 m²", "2 rooms"])
        XCTAssertNotNil(home.secureURL("url"))
    }

    private func record(
        id: String, type: String, data: [String: AnyCodable], childIDs: [String] = []
    ) -> EmbedRecord {
        EmbedRecord(
            id: id, type: type, status: .finished, data: .raw(data),
            parentEmbedId: nil, appId: type.split(separator: ":").dropFirst().first.map(String.init),
            skillId: nil, embedIds: childIDs.isEmpty ? nil : childIDs.joined(separator: "|"), createdAt: nil
        )
    }
}
