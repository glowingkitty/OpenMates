// Focused coverage for the backend event-child contract and native events
// preview/fullscreen data model.

import XCTest
@testable import OpenMates

final class EventsEmbedParityTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=events-search.surface-parity
    func testBackendEventChildTypeNormalizesToEventsRenderer() throws {
        let record = try JSONDecoder().decode(EmbedRecord.self, from: Data(#"{
          "embed_id": "event-child-1",
          "type": "event",
          "status": "finished",
          "data": {
            "title": "Swift meetup",
            "date_start": "2026-09-24T18:00:00Z",
            "event_type": "PHYSICAL",
            "venue_city": "Berlin",
            "venue_country": "Germany"
          }
        }"#.utf8))

        XCTAssertEqual(record.type, EmbedType.eventsEvent.rawValue)
        XCTAssertEqual(EmbedType.normalized(rawValue: "event"), .eventsEvent)
        let summary = EventResultSummary(embedId: record.id, data: try XCTUnwrap(record.rawData))
        XCTAssertEqual(summary.title, "Swift meetup")
        XCTAssertEqual(summary.shortLocation, "Berlin, Germany")
    }

    // contract-test: supporting surface=gui.apple assertions=events-search.surface-parity
    func testEventSearchOnlyUsesExplicitOrParentLinkedChildren() throws {
        let parent = try decodeRecord(#"{
          "embed_id": "event-search-1",
          "type": "app:events:search",
          "status": "finished",
          "embed_ids": ["event-child-1"],
          "data": {"query": "Events in Berlin"}
        }"#)
        let linked = try decodeRecord(#"{
          "embed_id": "event-child-1", "type": "event", "status": "finished",
          "parent_embed_id": "event-search-1", "data": {"title": "Linked event"}
        }"#)
        let unrelated = try decodeRecord(#"{
          "embed_id": "event-child-2", "type": "event", "status": "finished",
          "parent_embed_id": "another-search", "data": {"title": "Unrelated event"}
        }"#)

        let children = EventsSearchEmbedModel.childEmbeds(
            for: parent,
            in: [linked.id: linked, unrelated.id: unrelated]
        )

        XCTAssertEqual(children.map(\.id), [linked.id])
        let summaries = children.map {
            EventResultSummary(embedId: $0.id, data: $0.rawData ?? [:])
        }
        XCTAssertEqual(EventsSearchEmbedModel.query(from: parent.rawData, events: summaries), "Events in Berlin")
        XCTAssertEqual(summaries.map(\.title), ["Linked event"])
    }

    // contract-test: supporting surface=gui.apple assertions=events-search.surface-parity
    func testLegacyResultsToonAndMarkdownDescriptionRenderAsEventContent() throws {
        let data: [String: AnyCodable] = [
            "results_toon": AnyCodable("""
            results[1]{title,date_start,event_type,venue_city,venue_country}:
              Community workshop,2026-09-24T18:00:00Z,PHYSICAL,Berlin,Germany
            """)
        ]

        let event = try XCTUnwrap(EventResultSummary.list(from: data).first)
        XCTAssertEqual(event.title, "Community workshop")
        XCTAssertEqual(event.shortLocation, "Berlin, Germany")
        XCTAssertEqual(String(EventValue.markdown("Meet **local builders**").characters), "Meet local builders")
    }

    private func decodeRecord(_ json: String) throws -> EmbedRecord {
        try JSONDecoder().decode(EmbedRecord.self, from: Data(json.utf8))
    }
}
