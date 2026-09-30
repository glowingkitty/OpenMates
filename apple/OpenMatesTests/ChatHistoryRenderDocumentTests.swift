// Contract tests for stable native chat-history render documents.
// Covers web-equivalent mixed markdown and embed ordering without UI rendering.
// Verifies encrypted message identity survives SwiftData cold-boot restoration.
// Uses synthetic content and placeholder identifiers only.
// Guards message-scoped parsing from moving back into SwiftUI body evaluation.

import CryptoKit
import MapKit
import SwiftData
import XCTest
@testable import OpenMates

@MainActor
final class ChatHistoryRenderDocumentTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testResultsMapCameraFitsBerlinMarkersAtCityScaleAndRetainsSingleLocationScale() throws {
        let berlin = [CLLocationCoordinate2D(latitude: 52.5219, longitude: 13.4132),
                      CLLocationCoordinate2D(latitude: 52.5163, longitude: 13.3777),
                      CLLocationCoordinate2D(latitude: 52.5207, longitude: 13.4010)]
        let rect = try XCTUnwrap(AppleResultsMapCamera.fittedRect(coordinates: berlin))
        berlin.forEach { XCTAssertTrue(rect.contains(MKMapPoint($0)), "Every result must fit the initial camera") }
        let region = MKCoordinateRegion(rect)
        XCTAssertLessThan(region.span.longitudeDelta, 0.1, "Berlin events need city scale, never world zoom")
        XCTAssertEqual(region.center.latitude, 52.5191, accuracy: 0.003)
        XCTAssertEqual(region.center.longitude, 13.39545, accuracy: 0.001)

        let single = try XCTUnwrap(AppleResultsMapCamera.fittedRect(coordinates: [berlin[0], berlin[0]]))
        let meters = single.size.width / MKMapPointsPerMeterAtLatitude(berlin[0].latitude)
        XCTAssertEqual(meters, 1_200, accuracy: 1, "Shared venues must receive a useful nonzero neighborhood camera")
        XCTAssertNil(AppleResultsMapCamera.fittedRect(coordinates: []))
        XCTAssertNil(AppleResultsMapCamera.fittedRect(coordinates: [.init(latitude: 100, longitude: 200)]))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testResultsMapCameraFitsRoutesAcrossDateLineAndZoomsAboutCurrentCenter() throws {
        let rect = try XCTUnwrap(AppleResultsMapCamera.fittedRect(coordinates: [
            .init(latitude: 10, longitude: 179.5), .init(latitude: 10, longitude: -179.5),
        ]))
        XCTAssertLessThan(rect.size.width, MKMapRect.world.size.width / 100,
                          "A route crossing the date line must use the short longitude interval")
        let region = MKCoordinateRegion(center: .init(latitude: 52.52, longitude: 13.405),
                                        span: .init(latitudeDelta: 0.02, longitudeDelta: 0.04))
        let closer = AppleResultsMapCamera.zoomed(region, factor: 0.5)
        XCTAssertEqual(closer.center.latitude, region.center.latitude)
        XCTAssertEqual(closer.center.longitude, region.center.longitude)
        XCTAssertEqual(closer.span.longitudeDelta, 0.02, accuracy: 0.00001)
        let restored = AppleResultsMapCamera.zoomed(closer, factor: 2)
        XCTAssertEqual(restored.span.latitudeDelta, region.span.latitudeDelta, accuracy: 0.00001)
        XCTAssertEqual(restored.span.longitudeDelta, region.span.longitudeDelta, accuracy: 0.00001)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,pii.surface.semantic-parity
    func testTranscriptDisplayProjectionRestoresSharedEmbedsOnceAndKeepsUserMappingPrecedence() {
        let placeholder = "[PERSON_NAME_1]"
        let old = PIIMapping(placeholder: placeholder, original: "Earlier synthetic name", type: "person_name")
        let latest = PIIMapping(placeholder: placeholder, original: "Updated synthetic name", type: "person_name")
        let ignored = PIIMapping(placeholder: placeholder, original: "Assistant mapping must not override", type: "person_name")
        let source = EmbedRecord(id: "shared-source", type: "website", status: .finished,
                                 data: .raw(["title": AnyCodable(placeholder)]),
                                 parentEmbedId: nil, appId: "web", skillId: nil,
                                 embedIds: nil, createdAt: nil)
        let rows = (0..<120).map { index in
            Message(id: "projection-row-\(index)", chatId: "projection-chat",
                    role: index < 2 ? .user : .assistant, content: placeholder,
                    encryptedContent: nil, createdAt: "2026-01-01T00:00:00Z", updatedAt: nil,
                    appId: nil, isStreaming: false,
                    embedRefs: [EmbedRef(id: source.id, type: source.type, status: nil, data: nil)],
                    piiMappings: [index == 0 ? old : (index == 1 ? latest : ignored)])
        }
        var restoredIds: [String] = []
        let projection = ChatTranscriptDisplayProjection(messages: rows, embedRecords: [source.id: source],
                                                        isPIIRevealed: true) { embed, mappings in
            restoredIds.append(embed.id)
            return PIIDetector.restorePII(in: embed, mappings: mappings)
        }
        XCTAssertEqual(projection.piiMappings, [latest])
        for row in rows {
            XCTAssertEqual(projection.embeds(for: row).first?.rawData?["title"]?.value as? String, latest.original)
        }
        XCTAssertEqual(restoredIds, [source.id], "120 row lookups must reuse the one restored shared embed")
        XCTAssertEqual(source.rawData?["title"]?.value as? String, placeholder,
                       "Revealing PII must not mutate the canonical stored record")

        let hidden = ChatTranscriptDisplayProjection(messages: rows, embedRecords: [source.id: source],
                                                    isPIIRevealed: false) { embed, _ in
            XCTFail("Hidden mode must never restore embed content")
            return embed
        }
        XCTAssertEqual(hidden.embeds(for: rows[0]).first?.rawData?["title"]?.value as? String, placeholder)
        XCTAssertEqual(hidden.piiMappings, [latest], "Message rendering still receives the same mapping collection")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chat-navigation.open.local-first-coherent
    func testInlineFlowReusesMeasurementsAndPreservesWrapping() {
        var cache = InlineMarkdownFlowMeasurements(idealSizes: [
            CGSize(width: 40, height: 20),
            CGSize(width: 50, height: 20),
            CGSize(width: 30, height: 24)
        ])
        var constrainedMeasurements = 0
        let measure: (Int, CGFloat) -> CGSize = { _, width in
            constrainedMeasurements += 1
            return CGSize(width: width, height: 20)
        }

        let measured = cache.arrangement(width: 100, spacing: 0, lineSpacing: 2, measureConstrained: measure)
        let placed = cache.arrangement(width: 100, spacing: 0, lineSpacing: 2, measureConstrained: measure)

        XCTAssertEqual(measured, placed)
        XCTAssertEqual(measured.origins, [CGPoint(x: 0, y: 0), CGPoint(x: 40, y: 0), CGPoint(x: 0, y: 22)])
        XCTAssertEqual(measured.size, CGSize(width: 90, height: 46))
        XCTAssertEqual(constrainedMeasurements, 0, "Ordinary text/chips should use their intrinsic size without a second measurement")

        let resized = cache.arrangement(width: 130, spacing: 0, lineSpacing: 2, measureConstrained: measure)
        XCTAssertEqual(resized.origins, [CGPoint(x: 0, y: 0), CGPoint(x: 40, y: 0), CGPoint(x: 90, y: 0)])
        XCTAssertEqual(resized.size, CGSize(width: 120, height: 24))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chat-navigation.open.local-first-coherent
    func testInlineFlowConstrainsOversizedChipOncePerLayoutProposal() {
        var cache = InlineMarkdownFlowMeasurements(idealSizes: [
            CGSize(width: 200, height: 20),
            CGSize(width: 20, height: 20)
        ])
        var constrainedMeasurements = 0
        let measure: (Int, CGFloat) -> CGSize = { index, width in
            XCTAssertEqual(index, 0)
            constrainedMeasurements += 1
            return CGSize(width: width, height: 40)
        }

        let measured = cache.arrangement(width: 100, spacing: 0, lineSpacing: 2, measureConstrained: measure)
        let placed = cache.arrangement(width: 100, spacing: 0, lineSpacing: 2, measureConstrained: measure)
        XCTAssertEqual(measured, placed)
        XCTAssertEqual(measured.sizes.first, CGSize(width: 100, height: 40))
        XCTAssertEqual(measured.origins.last, CGPoint(x: 0, y: 42))
        XCTAssertEqual(constrainedMeasurements, 1)

        let resized = cache.arrangement(width: 80, spacing: 0, lineSpacing: 2, measureConstrained: measure)
        XCTAssertEqual(resized.sizes.first, CGSize(width: 80, height: 40))
        XCTAssertEqual(constrainedMeasurements, 2)
        let spaced = cache.arrangement(width: 80, spacing: 0, lineSpacing: 4, measureConstrained: measure)
        XCTAssertEqual(spaced.origins.last, CGPoint(x: 0, y: 44))
        XCTAssertEqual(constrainedMeasurements, 3)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chat-navigation.open.local-first-coherent
    func testInlineFlowPreservesOriginalProposalWhenChipHugsWrappedText() {
        var cache = InlineMarkdownFlowMeasurements(idealSizes: [
            CGSize(width: 200, height: 20),
            CGSize(width: 20, height: 20)
        ])
        let measure: (Int, CGFloat) -> CGSize = { _, width in
            // Multiline Text may return its longest wrapped line's width,
            // which is narrower than the width offered by its parent.
            CGSize(width: width - 10, height: width >= 100 ? 40 : 60)
        }

        let measured = cache.arrangement(width: 100, spacing: 0, lineSpacing: 2, measureConstrained: measure)
        XCTAssertEqual(measured.size, CGSize(width: 90, height: 62))
        XCTAssertEqual(measured.proposedWidths, [100, nil])
        XCTAssertEqual(measured.origins.last, CGPoint(x: 0, y: 42))

        // Placement must retain the original container and child proposals.
        // Reusing the returned 90-point width would incorrectly add a line.
        let placed = cache.arrangement(width: 100, spacing: 0, lineSpacing: 2, measureConstrained: measure)
        XCTAssertEqual(placed, measured)
        let incorrectlyRewrapped = cache.arrangement(width: measured.size.width, spacing: 0, lineSpacing: 2, measureConstrained: measure)
        XCTAssertEqual(incorrectlyRewrapped.size.height, 82)
        XCTAssertNotEqual(incorrectlyRewrapped.size.height, placed.size.height)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chat-navigation.open.local-first-coherent
    func testInlineMarkdownMakesProgressPastLiteralAndMalformedDelimiters() {
        let cases = [
            ("[literal] then [source](embed:source)", "[literal] then source"),
            ("An unmatched ` marker and [source](embed:source)", "An unmatched ` marker and source"),
            ("![alt](https://example.com/image.png) and [source](embed:source)", "![alt](https://example.com/image.png) and source"),
            ("[ [ [", "[ [ ["),
            ("Unicode 🪐 [plain] and `unfinished", "Unicode 🪐 [plain] and `unfinished")
        ]
        for (source, expected) in cases {
            XCTAssertEqual(InlineMarkdownTokenizer.parse(source).map(\.searchText).joined(), expected)
        }
        XCTAssertTrue(InlineMarkdownTokenizer.parse(cases[0].0).contains(
            .embed(displayText: "source", embedRef: "source", isBold: false)))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testImportedProviderMetadataDecryptsIntoRenderIdentity() async throws {
        let chatId = "chat-imported-provider"
        let key = SymmetricKey(data: Data(repeating: 7, count: 32))
        ChatKeyManager.shared.setKey(key, for: chatId)
        defer { ChatKeyManager.shared.removeKey(for: chatId) }

        let crypto = CryptoManager.shared
        let message = Message(
            id: "message-imported-provider",
            chatId: chatId,
            role: .assistant,
            content: nil,
            encryptedContent: try await crypto.encryptContent("Synthetic imported reply", key: key),
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: nil,
            appId: nil,
            isStreaming: false,
            embedRefs: nil,
            encryptedSenderName: try await crypto.encryptContent("Gemini", key: key),
            encryptedCategory: try await crypto.encryptContent("gemini", key: key),
            encryptedModelName: try await crypto.encryptContent("gemini-import", key: key)
        )

        let decryptedMessages = await ChatViewModel.decryptMessagesForDisplay([message], chatId: chatId)
        let decrypted = try XCTUnwrap(decryptedMessages.first)

        XCTAssertEqual(decrypted.content, "Synthetic imported reply")
        XCTAssertEqual(decrypted.senderName, "Gemini")
        XCTAssertEqual(decrypted.category, "gemini")
        XCTAssertEqual(decrypted.modelName, "gemini-import")
        XCTAssertEqual(decrypted.renderDocumentForDisplay?.identity.senderName, "Gemini")
        XCTAssertEqual(decrypted.renderDocumentForDisplay?.identity.category, "gemini")
        XCTAssertEqual(decrypted.renderDocumentForDisplay?.identity.modelName, "gemini-import")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testImportedProviderMappingMatchesWebContract() {
        XCTAssertEqual(ImportedAssistantProvider.resolve(category: "openmates")?.iconName, "openmates")
        XCTAssertEqual(ImportedAssistantProvider.resolve(category: "chatgpt")?.iconName, "openai")
        XCTAssertEqual(ImportedAssistantProvider.resolve(category: "claude")?.iconName, "claude")
        XCTAssertEqual(ImportedAssistantProvider.resolve(category: "gemini")?.iconName, "google")
        XCTAssertEqual(ImportedAssistantProvider.resolve(category: "opencode")?.iconName, "coding")
        XCTAssertEqual(ImportedAssistantProvider.resolve(category: "other")?.displayName, "AI assistant")
        XCTAssertNil(ImportedAssistantProvider.resolve(category: "openmates", isOfficialOpenMatesChat: true))
        XCTAssertNil(ImportedAssistantProvider.resolve(category: "research"))
    }

    // contract-test: direct surface=gui.apple assertions=chats.rendering.assistant-document-convergence,chats.rendering.inline-entity-interaction,chats.surface.semantic-parity
    func testStableMessageBuildsOrderedWebSemanticBlocksOnce() throws {
        let content = """
        # Synthetic result

        Intro with [OpenMates](wiki:OpenMates), [the source](embed:source-inline), and @researcher.

        ```json
        {"type":"app_skill_use","embed_id":"embed-search","app_id":"web","skill_id":"search"}
        ```

        > [Verified synthetic quote](embed:source-result)

        - First item
        - Second item
        """
        let message = Message(
            id: "message-assistant",
            chatId: "chat-synthetic",
            role: .assistant,
            content: content,
            encryptedContent: "ciphertext-content",
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: nil,
            appId: "web",
            isStreaming: false,
            embedRefs: [
                EmbedRef(id: "embed-search", type: "app_skill_use", status: "finished", data: nil),
                EmbedRef(id: "source-inline", type: "web-website", status: "finished", data: nil),
            ],
            modelName: "Synthetic Model",
            senderName: "Synthetic Mate",
            category: "research",
            encryptedSenderName: "ciphertext-sender",
            encryptedCategory: "ciphertext-category",
            encryptedModelName: "ciphertext-model"
        )

        let document = try XCTUnwrap(message.renderDocumentForDisplay)

        XCTAssertEqual(document.messageId, message.id)
        XCTAssertEqual(document.identity.senderName, "Synthetic Mate")
        XCTAssertEqual(document.identity.category, "research")
        XCTAssertEqual(document.identity.modelName, "Synthetic Model")
        XCTAssertEqual(document.identity.role, .assistant)
        XCTAssertEqual(document.blocks.map(\.kind), [
            .heading,
            .paragraph,
            .embedGroup,
            .sourceQuote,
            .unorderedList,
        ])
        XCTAssertEqual(document.blocks[2].embedReferences.map(\.id), ["embed-search"])
        XCTAssertEqual(document.blocks[3].embedReferences.map(\.id), ["source-result"])
        XCTAssertEqual(document.blocks[1].inlineEntities.map(\.kind), [.wiki, .embed, .mention])
        XCTAssertEqual(message.renderDocumentForDisplay, document)
    }

    // contract-test: direct surface=gui.apple assertions=chats.rendering.inline-entity-interaction
    func testUnresolvedInlineEntitiesRetainReadableFallbackText() {
        let entities = ChatHistoryInlineEntity.parse(
            "Compare [Kyoto](wiki:Kyoto) with [the source](embed:missing-ref)."
        )

        XCTAssertEqual(entities.map(\.kind), [.wiki, .embed])
        XCTAssertEqual(entities.map(\.displayText), ["Kyoto", "the source"])
        XCTAssertEqual(entities.map(\.target), ["Kyoto", "missing-ref"])
    }

    // contract-test: direct surface=gui.apple assertions=chats.rendering.inline-entity-interaction,web-search.surface-parity
    func testInlineEmbedReferenceResolvesSearchChildFromParentFallbackBeforeHydration() throws {
        let parent = EmbedRecord(
            id: "search-parent",
            type: EmbedType.webSearch.rawValue,
            status: .finished,
            data: .raw([
                "type": AnyCodable("app_skill_use"),
                "app_id": AnyCodable("web"),
                "skill_id": AnyCodable("search"),
                "query": AnyCodable("native citation fallback"),
                "results_toon": AnyCodable("""
                    results[1]:
                      - type: search_result
                        title: "Hydrating source"
                        url: "https://example.com/source"
                    count: 1
                    """),
            ]),
            parentEmbedId: nil,
            appId: "web",
            skillId: "search",
            embedIds: "source-child",
            createdAt: "2026-09-24T00:00:00Z"
        )

        let resolved = try XCTUnwrap(MarkdownEmbedResolver.resolve(
            "source-child",
            in: [parent.id: parent]
        ))

        XCTAssertEqual(resolved.id, "source-child")
        XCTAssertEqual(resolved.parentEmbedId, parent.id)
        XCTAssertEqual(resolved.rawData?["title"]?.value as? String, "Hydrating source")
        XCTAssertEqual(resolved.rawData?["url"]?.value as? String, "https://example.com/source")
    }

    // contract-test: direct surface=gui.apple assertions=chats.layout.responsive-history,message-input.layout.responsive-parity
    func testResponsiveChatLayoutMatchesWebBreakpoints() {
        XCTAssertEqual(ChatResponsiveLayoutPolicy.contentMaximumWidth, 1_000)
        XCTAssertTrue(ChatResponsiveLayoutPolicy.stacksAssistantIdentity(containerWidth: 500))
        XCTAssertFalse(ChatResponsiveLayoutPolicy.stacksAssistantIdentity(containerWidth: 501))
        XCTAssertEqual(ChatResponsiveLayoutPolicy.inlineCompactComposerHeight, 48)
    }

    // contract-test: direct surface=gui.apple assertions=chats.surface.semantic-parity
    func testResultsViewProtocolPreservesDescriptorWithoutExposingMetadata() throws {
        let message = Message(
            id: "message-results-view",
            chatId: "chat-synthetic",
            role: .assistant,
            content: """
            ```embeds_results_view
            title: Mapped results
            embeds: result-one, result-two
            sources: source-one, result-two
            highlight: source-one
            ```
            """,
            encryptedContent: nil,
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: nil,
            appId: "maps",
            isStreaming: false,
            embedRefs: [
                EmbedRef(id: "result-one", type: "maps-place", status: "finished", data: nil),
                EmbedRef(id: "result-two", type: "maps-place", status: "finished", data: nil),
                EmbedRef(id: "source-one", type: "web-website", status: "finished", data: nil),
            ]
        )

        let document = try XCTUnwrap(message.renderDocumentForDisplay)

        XCTAssertEqual(document.blocks.map(\.kind), [.resultsView])
        XCTAssertEqual(document.blocks[0].resultsView?.title, "Mapped results")
        XCTAssertEqual(document.blocks[0].resultsView?.embedRefs, ["result-one", "result-two"])
        XCTAssertEqual(document.blocks[0].resultsView?.sourceRefs, ["source-one", "result-two"])
        XCTAssertEqual(document.blocks[0].resultsView?.highlightRefs, ["source-one"])
        XCTAssertTrue(document.blocks[0].embedReferences.isEmpty)
        XCTAssertFalse(document.blocks.contains { $0.kind == .codeBlock })

        let restored = try JSONDecoder().decode(ChatHistoryRenderDocument.self, from: JSONEncoder().encode(document))
        XCTAssertEqual(restored.blocks[0].resultsView, document.blocks[0].resultsView)
    }

    // contract-test: direct surface=gui.apple assertions=chats.surface.semantic-parity
    func testResultsViewEligibilityHidesInvalidRecordsAndRetainsDateOnlyCalendarEntry() {
        let descriptor = AppleResultsViewDescriptor.parse("""
            title: Synthetic results
            embeds: missing, invalid, date-only, mapped, mapped
            highlight: mapped
            """)
        let invalid = EmbedRecord(id: "invalid", type: "events-event", status: .finished,
                                  data: .raw(["date": AnyCodable("2026-02-30"),
                                              "latitude": AnyCodable(100), "longitude": AnyCodable(200)]),
                                  parentEmbedId: nil, appId: "events", skillId: nil,
                                  embedIds: nil, createdAt: nil)
        let dated = EmbedRecord(id: "date-only", type: "events-event", status: .finished,
                                data: .raw(["title": AnyCodable("Date-only event"),
                                            "date": AnyCodable("2026-09-20")]),
                                parentEmbedId: nil, appId: "events", skillId: nil,
                                embedIds: nil, createdAt: nil)
        let mapped = EmbedRecord(id: "mapped", type: "maps-place", status: .finished,
                                 data: .raw(["title": AnyCodable("Mapped place"),
                                             "latitude": AnyCodable(52.52), "longitude": AnyCodable(13.405)]),
                                 parentEmbedId: nil, appId: "maps", skillId: nil,
                                 embedIds: nil, createdAt: nil)
        let entries = AppleResultsViewEntry.resolve(descriptor, lookup: [:],
                                                    records: [invalid.id: invalid, dated.id: dated, mapped.id: mapped])
        XCTAssertEqual(entries.map(\.id), ["date-only", "mapped"])
        XCTAssertNotNil(entries[0].date)
        XCTAssertNil(entries[0].coordinate)
        XCTAssertNotNil(entries[1].coordinate)
        XCTAssertFalse(entries[0].matches(category: nil, ranges: ["price": 0...20], options: [:]),
                       "An active facet excludes entries that do not expose that facet")
    }

    // contract-test: direct surface=gui.apple assertions=chats.surface.semantic-parity
    func testResultsViewAcceptsNestedCoordinatesFlatAndStructuredRoutesAndExcludesOnlineMap() {
        func record(_ id: String, _ fields: [String: AnyCodable]) -> EmbedRecord {
            EmbedRecord(id: id, type: "maps-place", status: .finished, data: .raw(fields),
                        parentEmbedId: nil, appId: "maps", skillId: nil,
                        embedIds: nil, createdAt: nil)
        }
        let nested = record("nested", ["venue": AnyCodable(["lat": 52.52, "lng": 13.405] as [String: Any])])
        let gps = record("gps", ["gps_coordinates_latitude": AnyCodable(52.4),
                                 "gps_coordinates_longitude": AnyCodable(13.1)])
        let flat = record("flat", ["legs_0_segments_0_departure_latitude": AnyCodable(52.52),
                                   "legs_0_segments_0_departure_longitude": AnyCodable(13.4),
                                   "legs_0_segments_0_arrival_latitude": AnyCodable(25.27),
                                   "legs_0_segments_0_arrival_longitude": AnyCodable(51.6)])
        let structured = record("structured", ["legs": AnyCodable([
            ["segments": [["departure_latitude": 52.52, "departure_longitude": 13.4,
                            "arrival_latitude": 13.68, "arrival_longitude": 100.74]]]
        ] as [[String: Any]])])
        let online = record("online", ["event_type": AnyCodable("online"),
                                       "venue_lat": AnyCodable(52.52), "venue_lon": AnyCodable(13.4),
                                       "date": AnyCodable("2026-09-20")])
        let records = [nested, gps, flat, structured, online]
        let descriptor = AppleResultsViewDescriptor.parse(
            "embeds: " + records.map(\.id).joined(separator: ", ")
        )
        let entries = AppleResultsViewEntry.resolve(descriptor, lookup: [:],
                                                    records: Dictionary(uniqueKeysWithValues: records.map { ($0.id, $0) }))
        XCTAssertEqual(entries.map(\.id), records.map(\.id))
        XCTAssertEqual(entries[0].coordinate?.latitude, 52.52)
        XCTAssertEqual(entries[1].coordinate?.longitude, 13.1)
        XCTAssertEqual(entries[2].route.count, 2)
        XCTAssertEqual(entries[3].route.count, 2)
        XCTAssertNil(entries[4].coordinate)
        XCTAssertNotNil(entries[4].date)
    }

    // contract-test: direct surface=gui.apple assertions=chats.surface.semantic-parity
    func testResultsViewSourceExpansionCapsAtFortyUniqueRefs() {
        let ids = (0..<45).map { "child-\($0)" }
        let source = EmbedRecord(id: "source", type: "app_skill_use", status: .finished,
                                 data: .raw([:]), parentEmbedId: nil, appId: "maps", skillId: "search",
                                 embedIds: ids.joined(separator: "|"), createdAt: nil)
        let children = ids.map { id in
            EmbedRecord(id: id, type: "maps-place", status: .finished,
                        data: .raw(["latitude": AnyCodable(52.52), "longitude": AnyCodable(13.405)]),
                        parentEmbedId: source.id, appId: "maps", skillId: nil,
                        embedIds: nil, createdAt: nil)
        }
        let descriptor = AppleResultsViewDescriptor.parse("sources: source\nembeds: child-0")
        let records = Dictionary(uniqueKeysWithValues: ([source] + children).map { ($0.id, $0) })
        let entries = AppleResultsViewEntry.resolve(descriptor, lookup: [:], records: records)
        XCTAssertEqual(entries.count, 40)
        XCTAssertEqual(entries.first?.id, "child-0")
        XCTAssertEqual(entries.last?.id, "child-39")

        let rawSource = EmbedRecord(id: "raw-source", type: "app_skill_use", status: .finished,
                                    data: .raw(["child_embed_ids": AnyCodable(["child-3", "child-4"])]),
                                    parentEmbedId: nil, appId: "maps", skillId: "search",
                                    embedIds: nil, createdAt: nil)
        let rawRecords = Dictionary(uniqueKeysWithValues: ([rawSource] + children).map { ($0.id, $0) })
        let rawEntries = AppleResultsViewEntry.resolve(
            AppleResultsViewDescriptor.parse("sources: raw-source"), lookup: [:], records: rawRecords
        )
        XCTAssertEqual(rawEntries.map(\.id), ["child-3", "child-4"])
    }

    // contract-test: direct surface=gui.apple assertions=chats.surface.semantic-parity
    func testLegacyResultsViewDocumentIsRebuiltOnMessageRestore() throws {
        let content = "```embeds_results_view\ntitle: Upgraded\nembeds: mapped\n```"
        let fresh = Message(id: "legacy-results", chatId: "chat-synthetic", role: .assistant,
                            content: content, encryptedContent: nil, createdAt: "2026-01-01T00:00:00Z",
                            updatedAt: nil, appId: "maps", isStreaming: false, embedRefs: nil)
        let identity = try XCTUnwrap(fresh.renderDocumentForDisplay?.identity)
        let lossyBlock = ChatHistoryRenderBlock(messageId: fresh.id, index: 0,
            markdownBlock: .embedGroup([MarkdownEmbedReference(value: "mapped", isRef: false, isLargePreview: false)]),
            embedRefsById: [:])
        let legacy = ChatHistoryRenderDocument(version: 1, messageId: fresh.id,
                                               identity: identity, blocks: [lossyBlock])
        let restored = Message(id: fresh.id, chatId: fresh.chatId, role: fresh.role,
                               content: content, encryptedContent: nil, createdAt: fresh.createdAt,
                               updatedAt: nil, appId: "maps", isStreaming: false,
                               embedRefs: nil, renderDocument: legacy)
        XCTAssertEqual(restored.renderDocumentForDisplay?.version, ChatHistoryRenderDocument.schemaVersion)
        XCTAssertEqual(restored.renderDocumentForDisplay?.blocks.map(\.kind), [.resultsView])
        XCTAssertEqual(restored.renderDocumentForDisplay?.blocks.first?.resultsView?.title, "Upgraded")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testInlineEmbedGroupsBoundAccessibilityCardCount() {
        let embeds = (1...12).map { index in
            EmbedRecord(
                id: "result-\(index)",
                type: "maps-place",
                status: .finished,
                data: nil,
                parentEmbedId: nil,
                appId: "maps",
                skillId: "search",
                embedIds: nil,
                createdAt: nil
            )
        }

        let groups = EmbedGrouper.groupForInlineDisplay(embeds)

        XCTAssertEqual(groups.flatMap(\.embeds).map(\.id), Array(embeds.prefix(6)).map(\.id))
        XCTAssertEqual(embeds.count, 12)
    }

    // contract-test: direct surface=gui.apple assertions=chats.surface.semantic-parity
    func testSystemMessageRetainsRoleWithoutAssistantOwnership() throws {
        let message = Message(
            id: "message-system",
            chatId: "chat-synthetic",
            role: .system,
            content: "System-only synthetic content.",
            encryptedContent: nil,
            createdAt: "2026-01-01T00:00:01Z",
            updatedAt: nil,
            appId: nil,
            isStreaming: false,
            embedRefs: nil
        )

        let document = try XCTUnwrap(message.renderDocumentForDisplay)
        XCTAssertEqual(document.identity.role, .system)
        XCTAssertNil(document.identity.senderName)
        XCTAssertEqual(document.blocks.map(\.kind), [.paragraph])
        XCTAssertTrue(document.blocks.allSatisfy { $0.messageId == message.id })
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testColdBootRestoresEncryptedIdentityAndExactRenderDocument() throws {
        let schema = Schema([PersistedChat.self, PersistedMessage.self])
        let configuration = ModelConfiguration(
            "ChatHistoryRenderDocumentTests",
            schema: schema,
            isStoredInMemoryOnly: true
        )
        let container = try ModelContainer(for: schema, configurations: [configuration])
        let store = OfflineStore(modelContainer: container)
        let message = Message(
            id: "message-restored",
            chatId: "chat-restored",
            role: .assistant,
            content: "Before.\n\n[[embed:embed-restored]]\n\nAfter.",
            encryptedContent: "ciphertext-content",
            createdAt: "2026-01-01T00:00:02Z",
            updatedAt: nil,
            appId: "web",
            isStreaming: false,
            embedRefs: [EmbedRef(id: "embed-restored", type: "web-website", status: "finished", data: nil)],
            modelName: "Synthetic Model",
            senderName: "Synthetic Mate",
            category: "research",
            encryptedSenderName: "ciphertext-sender",
            encryptedCategory: "ciphertext-category",
            encryptedModelName: "ciphertext-model"
        )
        let originalDocument = try XCTUnwrap(message.renderDocumentForDisplay)

        store.persistMessages([message], chatId: message.chatId)
        let restored = try XCTUnwrap(store.loadMessages(chatId: message.chatId).first)

        XCTAssertEqual(restored.id, message.id)
        XCTAssertEqual(restored.senderName, "Synthetic Mate")
        XCTAssertEqual(restored.category, "research")
        XCTAssertEqual(restored.modelName, "Synthetic Model")
        XCTAssertEqual(restored.encryptedSenderName, "ciphertext-sender")
        XCTAssertEqual(restored.encryptedCategory, "ciphertext-category")
        XCTAssertEqual(restored.encryptedModelName, "ciphertext-model")
        XCTAssertEqual(restored.renderDocumentForDisplay, originalDocument)
        XCTAssertEqual(restored.renderDocumentForDisplay?.blocks.map(\.kind), [
            .paragraph,
            .embedGroup,
            .paragraph,
        ])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testDecodedSyncMessageAcceptsEncryptedIdentityAliases() throws {
        let payload = """
        {
          "message_id": "message-decoded",
          "chat_id": "chat-decoded",
          "role": "assistant",
          "content": "Synthetic content",
          "created_at": "2026-01-01T00:00:03Z",
          "sender_name": "Synthetic Mate",
          "category": "research",
          "model_name": "Synthetic Model",
          "encrypted_sender_name": "ciphertext-sender",
          "encrypted_category": "ciphertext-category",
          "encrypted_model_name": "ciphertext-model"
        }
        """

        let message = try JSONDecoder().decode(Message.self, from: Data(payload.utf8))

        XCTAssertEqual(message.senderName, "Synthetic Mate")
        XCTAssertEqual(message.category, "research")
        XCTAssertEqual(message.modelName, "Synthetic Model")
        XCTAssertEqual(message.encryptedSenderName, "ciphertext-sender")
        XCTAssertEqual(message.encryptedCategory, "ciphertext-category")
        XCTAssertEqual(message.encryptedModelName, "ciphertext-model")
        XCTAssertEqual(message.renderDocumentForDisplay?.messageId, "message-decoded")
    }

    // contract-test: direct surface=gui.apple assertions=chats.surface.semantic-parity
    func testMessageAccessibilityPolicyPrefersSemanticTextOverChildren() {
        XCTAssertEqual(
            ChatMessageAccessibilityPolicy.semanticLabel(
                content: "  User-visible prompt  ",
                thinkingContent: nil,
                embedTypes: [],
                fallback: "message-user"
            ),
            "User-visible prompt"
        )
        XCTAssertEqual(
            ChatMessageAccessibilityPolicy.semanticLabel(
                content: "",
                thinkingContent: "  Thinking summary  ",
                embedTypes: [],
                fallback: "message-assistant"
            ),
            "Thinking summary"
        )
        XCTAssertEqual(
            ChatMessageAccessibilityPolicy.semanticLabel(
                content: "",
                thinkingContent: nil,
                embedTypes: [EmbedType.financeCheckAccounts.rawValue],
                fallback: "message-assistant"
            ),
            "Check accounts"
        )
    }

    // contract-test: direct surface=gui.apple assertions=chats.surface.semantic-parity
    func testStreamingRenderPolicyPreservesVisibleMarkdownForRichRendering() {
        let content = "Comparing **[Kyoto](wiki:Kyoto)** and [Osaka](wiki:Osaka)."

        XCTAssertEqual(ChatMessageStreamingRenderPolicy.visibleContent(content), content)
    }

    // contract-test: direct surface=gui.apple assertions=chats.surface.semantic-parity
    func testStreamingRenderPolicyHidesInternalProtocolFences() {
        let content = """
        ```json
        {"type":"app_skill_use","embed_id":"embed-search","app_id":"web","skill_id":"search"}
        ```

        Visible answer.
        """

        XCTAssertEqual(ChatMessageStreamingRenderPolicy.visibleContent(content), "\nVisible answer.")
        XCTAssertEqual(
            ChatMessageStreamingRenderPolicy.visibleContent("```json\n{\"type\":\"app_skill_use\""),
            "```json\n{\"type\":\"app_skill_use\""
        )
        XCTAssertEqual(
            ChatMessageStreamingRenderPolicy.visibleContent("```json\n{\"type\":\"app_skill_use\",\"embed_id\":\"embed-search\""),
            ""
        )
        XCTAssertEqual(
            ChatMessageStreamingRenderPolicy.visibleContent("```json\n{\"answer\":true"),
            "```json\n{\"answer\":true"
        )
        XCTAssertEqual(
            ChatMessageStreamingRenderPolicy.visibleContent("```json\n{\"answer\":true}\n```"),
            "```json\n{\"answer\":true}\n```"
        )
    }

    // contract-test: direct surface=gui.apple assertions=chats.streaming.progressive-presentation,chats.rendering.assistant-document-convergence
    func testSameIDEmbedFinalizationChangesSyncSignatureAndRequiresViewModelRefresh() {
        let processing = EmbedRecord(
            id: "embed-search",
            type: EmbedType.webSearch.rawValue,
            status: .processing,
            data: .raw([
                "type": AnyCodable("app_skill_use"),
                "query": AnyCodable("synthetic query"),
            ]),
            parentEmbedId: nil,
            appId: "web",
            skillId: "search",
            embedIds: nil,
            createdAt: "1800000000"
        )
        let finished = EmbedRecord(
            id: processing.id,
            type: processing.type,
            status: .finished,
            data: nil,
            encryptedContent: "synthetic-ciphertext",
            encryptedType: "synthetic-type-ciphertext",
            parentEmbedId: nil,
            appId: "web",
            skillId: "search",
            embedIds: "child-a|child-b",
            versionNumber: 1,
            contentHash: "synthetic-content-hash",
            createdAt: processing.createdAt
        )

        XCTAssertNotEqual(
            ChatEmbedSyncSignature.make(chatId: "chat", embeds: [processing]),
            ChatEmbedSyncSignature.make(chatId: "chat", embeds: [finished]),
            "A same-ID processing→finished transition must trigger ChatView synchronization"
        )
        XCTAssertTrue(ChatViewModel.embedRecordNeedsRefresh(existing: processing, incoming: finished))
        XCTAssertFalse(ChatViewModel.embedRecordNeedsRefresh(existing: finished, incoming: finished))
    }
}
