import XCTest
@testable import OpenMates

@MainActor
final class CalledSkillSearchInputRetentionTests: XCTestCase {
    private func record(app: String, skill: String, status: EmbedStatus, raw: [String: Any]) -> EmbedRecord {
        EmbedRecord(id: "parent", type: "app:\(app):\(skill)", status: status,
            data: .raw(raw.mapValues(AnyCodable.init)), parentEmbedId: nil,
            appId: app, skillId: skill, embedIds: nil, createdAt: nil)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.assistant-document-convergence
    func testProjectReadRetainsActualPathInProcessingAndFinishedStates() {
        for status in [EmbedStatus.processing, .finished] {
            for field in ["path", "file_path"] {
                let embed = record(app: "projects", skill: "read", status: status, raw: [field: "docs/design.md"])
                XCTAssertEqual(ProjectReferenceEmbedModel(embed: embed).query, "docs/design.md")
            }
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.assistant-document-convergence
    func testTravelRequestRouteAndDateSurviveDifferentHydratedResult() {
        let raw: [String: Any] = ["requests": [["legs": [
            ["origin": "Berlin", "destination": "Paris", "date": "2026-11-10"]
        ]]], "results": [["origin": "BER", "destination": "CDG", "departure": "2026-11-11T10:00:00Z"]]]
        for status in [EmbedStatus.processing, .finished] {
            let model = TravelSearchPresentation(embed: record(app: "travel", skill: "search_connections", status: status, raw: raw),
                locale: Locale(identifier: "en_US"), timeZone: TimeZone(secondsFromGMT: 0)!)
            XCTAssertEqual(model.route, "Berlin → Paris")
            XCTAssertTrue(model.previewDate?.contains("10") == true)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.assistant-document-convergence
    func testCalendarUsesRequestRouteAndMonthBeforeAndAfterResults() {
        let request: [String: Any] = ["origin": "BER", "destination": "LIS", "month": "2026-11"]
        let initial = TravelPriceCalendarInput(data: ["requests": AnyCodable([request])])
        let finished = TravelPriceCalendarInput(data: ["requests": AnyCodable([request]),
            "results": AnyCodable([["origin_name": "Berlin", "destination_name": "Lisbon", "month": "2026-12"]])])
        XCTAssertEqual(initial.route, "BER → LIS")
        XCTAssertEqual(finished.route, initial.route)
        XCTAssertEqual(initial.dates, "2026-11")
        XCTAssertEqual(finished.dates, initial.dates)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.rendering.assistant-document-convergence
    func testCompletedSearchDomainsKeepRequestInputAlongsideResults() {
        for (kind, skill) in [(SearchDomainKind.health, "search_appointments"), (.home, "search"),
                              (.nutrition, "search_recipes"), (.shopping, "search_products")] {
            let embed = record(app: kind.rawValue, skill: skill, status: .finished,
                raw: ["query": "Actual request", "results": [["title": "Different result"]]])
            XCTAssertEqual(SearchDomainParentModel(kind: kind, embed: embed, allEmbedRecords: [:]).query, "Actual request")
        }
        let health = record(app: "health", skill: "search_appointments", status: .finished,
            raw: ["speciality": "dentist", "city": "Berlin"])
        let summary = SearchDomainParentModel(kind: .health, embed: health, allEmbedRecords: [:]).query
        XCTAssertTrue(summary.contains("dentist"))
        XCTAssertTrue(summary.contains("Berlin"))
    }
}
