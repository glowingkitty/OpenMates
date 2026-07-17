// Unit coverage for the Watch embed preview contract.
// These tests lock down the small watchOS card mapping without rendering the
// iOS/macOS embed stack or storing private chat content in fixtures.

import XCTest
@testable import OpenMates

final class WatchEmbedPreviewTests: XCTestCase {
    func testWatchPairLoginUIContractIdentifiersAreStable() {
        XCTAssertEqual(Set(WatchUIContract.pairLoginIdentifiers), [
            "watch-pair-login",
            "watch-pair-confirm-iphone-title",
            "watch-pair-confirm-iphone-description",
            "watch-pair-manual-fallback",
            "watch-pair-token",
            "watch-pair-url",
            "watch-pair-show-qr-button",
            "watch-pair-qr-code",
            "watch-pair-qr-fullscreen",
            "watch-pair-qr-close-button",
            "watch-pair-waiting-label",
            "watch-pair-pin-input",
            "watch-pair-refresh-button",
            "watch-pair-self-host-button",
            "watch-pair-self-host-input",
            "watch-pair-self-host-connect-button",
            "watch-pair-self-host-cancel-button",
            "watch-pair-self-host-error",
            "watch-pair-use-production-button",
        ])
        XCTAssertNoDuplicates(WatchUIContract.pairLoginIdentifiers)
        XCTAssertFalse(WatchUIContract.pairLoginIdentifiers.contains("watch-pair-server-production-button"))
        XCTAssertFalse(WatchUIContract.pairLoginIdentifiers.contains("watch-pair-server-development-button"))
        XCTAssertFalse(WatchUIContract.pairLoginIdentifiers.contains("watch-pair-server-selector"))
    }

    func testWatchChatAndAudioComposerUIContractIdentifiersAreStable() {
        XCTAssertTrue(WatchUIContract.chatFlowIdentifiers.contains("watch-chat-shell"))
        XCTAssertTrue(WatchUIContract.chatFlowIdentifiers.contains("watch-chat-list"))
        XCTAssertTrue(WatchUIContract.chatFlowIdentifiers.contains("watch-chat-thread"))
        XCTAssertTrue(WatchUIContract.chatFlowIdentifiers.contains("watch-message-input"))
        XCTAssertTrue(WatchUIContract.chatFlowIdentifiers.contains("watch-message-send"))
        XCTAssertTrue(WatchUIContract.chatFlowIdentifiers.contains("watch-audio-record-button"))
        XCTAssertTrue(WatchUIContract.chatFlowIdentifiers.contains("watch-pending-audio-embed"))

        XCTAssertEqual(Set(WatchUIContract.audioComposerIdentifiers), [
            "watch-audio-record-button",
            "watch-audio-stop-button",
            "watch-audio-transcribing",
            "watch-pending-audio-embed",
            "watch-audio-error",
        ])
        XCTAssertNoDuplicates(WatchUIContract.chatFlowIdentifiers)
        XCTAssertNoDuplicates(WatchUIContract.audioComposerIdentifiers)
    }

    func testWatchEmbedPreviewUIContractIdentifiersAreStable() {
        XCTAssertEqual(Set(WatchUIContract.embedPreviewIdentifiers), [
            "watch-embed-preview",
            "watch-embed-continuation",
            "watch-embed-open-device",
            "watch-embed-qr-payload",
            "watch-embed-notification-request",
        ])
        XCTAssertNoDuplicates(WatchUIContract.embedPreviewIdentifiers)
    }

    func testWatchDesignReviewContractRejectsStockProductChrome() {
        XCTAssertEqual(Set(WatchUIContract.forbiddenProductChrome), [
            "List",
            "Form",
            "NavigationStack",
            "navigationTitle",
            "toolbar",
        ])
        XCTAssertTrue(WatchUIContract.designEvidence.contains { $0.contains("Color.grey100") })
        XCTAssertTrue(WatchUIContract.designEvidence.contains { $0.contains("ScrollView/LazyVStack") })
        XCTAssertTrue(WatchUIContract.designEvidence.contains { $0.contains("pending audio-recording embed") })
    }

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

        let model = WatchEmbedPreviewMapper.makeModel(for: embed, chatId: "chat-secure")

        XCTAssertEqual(model.family, .audioRecording)
        XCTAssertEqual(model.title, "private title")
        XCTAssertFalse(model.continuation.universalLink?.contains("private title") == true)
        XCTAssertFalse(model.continuation.universalLink?.contains("private dictated text") == true)
        XCTAssertEqual(model.continuation.qrPayload, model.continuation.universalLink)
    }

    func testWatchEmbedOpenRequestPayloadContainsOnlyRoutingIds() throws {
        let request = try XCTUnwrap(WatchEmbedOpenRequest(chatId: "chat-secure", embedId: "embed-secure"))

        let payload = WatchEmbedOpenConnectivityPayload.requestMessage(request)
        let parsed = WatchEmbedOpenConnectivityPayload.parseRequest(payload)

        XCTAssertEqual(parsed, request)
        XCTAssertEqual(payload[WatchEmbedOpenConnectivityPayload.kindKey] as? String, WatchEmbedOpenConnectivityPayload.watchEmbedOpenRequestKind)
        XCTAssertEqual(payload[WatchEmbedOpenConnectivityPayload.chatIdKey] as? String, "chat-secure")
        XCTAssertEqual(payload[WatchEmbedOpenConnectivityPayload.embedIdKey] as? String, "embed-secure")
        XCTAssertFalse(payload.keys.contains("title"))
        XCTAssertFalse(payload.keys.contains("subtitle"))
        XCTAssertFalse(payload.keys.contains("content"))
    }

    func testWatchMessageDisplayTextRemovesEmbedOnlyBlocks() throws {
        let refs = [WatchEmbedRef(id: "embed-a", type: EmbedType.webWebsite.rawValue, status: "finished", data: nil)]
        let content = """
        Here is the result.

        ```json
        {"type":"web-website","embed_id":"embed-a"}
        ```
        """

        let displayText = WatchMessageContentSanitizer.displayText(content: content, embedRefs: refs)

        XCTAssertEqual(displayText, "Here is the result.")
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

    private func XCTAssertNoDuplicates(
        _ values: [String],
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        XCTAssertEqual(values.count, Set(values).count, file: file, line: line)
    }
}
