// Unit coverage for the Watch embed preview contract.
// These tests lock down the small watchOS card mapping without rendering the
// iOS/macOS embed stack or storing private chat content in fixtures.

import XCTest
@testable import OpenMates

final class WatchEmbedPreviewTests: XCTestCase {
    func testMapsSupportedV1EmbedFamiliesToCompactPreviewModels() throws {
        let cases: [(EmbedType, WatchEmbedPreviewFamily, [String: AnyCodable])] = [
            (.webWebsite, .website, ["title": AnyCodable("Example article"), "url": AnyCodable("https://example.com/post")]),
            (.videosVideo, .webVideo, ["title": AnyCodable("Launch demo"), "provider": AnyCodable("Video")]),
            (.image, .image, ["title": AnyCodable("OpenMates diagram"), "url": AnyCodable("https://example.com/image.png")]),
            (.recording, .audioRecording, ["transcript": AnyCodable("Audio note transcript"), "duration": AnyCodable("12s")]),
            (.codeCode, .code, ["filename": AnyCodable("Sources/App.swift"), "language": AnyCodable("swift"), "line_count": AnyCodable(12)]),
            (.pdf, .pdf, ["filename": AnyCodable("brief.pdf"), "page_count": AnyCodable(4)]),
            (.mapsPlace, .mapPlace, ["name": AnyCodable("Cafe"), "address": AnyCodable("Main Street")]),
            (.webSearch, .searchResults, ["query": AnyCodable("privacy search"), "result_count": AnyCodable(3)]),
            (.travelStays, .searchResults, ["query": AnyCodable("hotels in Lisbon"), "result_count": AnyCodable(5)]),
            (.travelConnections, .searchResults, ["query": AnyCodable("Berlin to Paris"), "result_count": AnyCodable(2)]),
            (.travelStay, .travelStay, ["name": AnyCodable("Quiet Hotel"), "city": AnyCodable("Lisbon")]),
            (.travelConnection, .travelConnection, ["origin_code": AnyCodable("BER"), "destination_code": AnyCodable("CDG"), "carrier": AnyCodable("Rail")]),
            (.shoppingProduct, .shoppingProduct, ["name": AnyCodable("Keyboard"), "price": AnyCodable("79 EUR")]),
            (.weatherForecast, .weather, ["location": AnyCodable("Berlin"), "summary": AnyCodable("Cloudy")]),
            (.reminderSet, .reminder, ["title": AnyCodable("Water plants"), "due": AnyCodable("Tomorrow")]),
        ]

        for (embedType, expectedFamily, raw) in cases {
            let embed = Self.embed(type: embedType.rawValue, raw: raw)

            let model = WatchEmbedPreviewMapper.makeModel(for: embed, chatId: "chat-123")

            XCTAssertEqual(model.family, expectedFamily, "Unexpected family for \(embedType.rawValue)")
            XCTAssertEqual(model.state, .ready)
            XCTAssertEqual(model.continuation.handoffActivityType, WatchEmbedContinuation.handoffActivityType)
            XCTAssertEqual(model.continuation.embedId, embed.id)
            XCTAssertEqual(model.continuation.chatId, "chat-123")
            XCTAssertTrue(model.continuation.universalLink?.contains("chat-id=chat-123") == true)
            XCTAssertTrue(model.continuation.universalLink?.contains("embed-id=embed-1") == true)
            XCTAssertFalse(model.title.isEmpty)
            XCTAssertFalse(model.title.hasPrefix("{"), "Raw JSON leaked into title for \(embedType.rawValue)")
        }
    }

    func testPreviewStateReflectsProcessingErrorsAndUnsupportedTypes() throws {
        let processing = Self.embed(type: EmbedType.webWebsite.rawValue, status: .processing, raw: ["title": AnyCodable("Loading")])
        let failed = Self.embed(type: EmbedType.webWebsite.rawValue, status: .error, raw: ["title": AnyCodable("Private title")])
        let unsupported = Self.embed(type: "internal-secret-payload", raw: ["secret": AnyCodable("never display this")])

        let processingModel = WatchEmbedPreviewMapper.makeModel(for: processing, chatId: nil)
        let failedModel = WatchEmbedPreviewMapper.makeModel(for: failed, chatId: nil)
        let unsupportedModel = WatchEmbedPreviewMapper.makeModel(for: unsupported, chatId: nil)

        XCTAssertEqual(processingModel.state, .processing)
        XCTAssertEqual(failedModel.state, .error)
        XCTAssertEqual(unsupportedModel.state, .error)
        XCTAssertEqual(unsupportedModel.family, .unsupported)
        XCTAssertNil(processingModel.continuation.universalLink)
        XCTAssertFalse(unsupportedModel.title.contains("never display this"))
    }

    func testContinuationPayloadDoesNotIncludePrivatePreviewContent() throws {
        let embed = Self.embed(
            type: EmbedType.recording.rawValue,
            raw: [
                "transcript": AnyCodable("private dictated text"),
                "title": AnyCodable("private title"),
            ]
        )

        let model = WatchEmbedPreviewMapper.makeModel(for: embed, chatId: "chat-private")

        XCTAssertEqual(model.family, .audioRecording)
        XCTAssertEqual(model.title, "private dictated text")
        XCTAssertFalse(model.continuation.universalLink?.contains("private") == true)
        XCTAssertEqual(model.continuation.qrPayload, model.continuation.universalLink)
    }

    private static func embed(
        id: String = "embed-1",
        type: String,
        status: EmbedStatus = .finished,
        raw: [String: AnyCodable]
    ) -> EmbedRecord {
        EmbedRecord(
            id: id,
            type: type,
            status: status,
            data: .raw(raw),
            parentEmbedId: nil,
            appId: EmbedType(rawValue: type)?.appId,
            skillId: nil,
            embedIds: nil,
            createdAt: "2026-07-07T00:00:00Z"
        )
    }
}
