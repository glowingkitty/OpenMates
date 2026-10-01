import SwiftUI
// Unit coverage for native embed version-history parity.
// These tests are deterministic and avoid network, credentials, or private
// persisted content. They guard the REST/sync model contract used by the native
// fullscreen timeline.

import XCTest
@testable import OpenMates

final class EmbedDiffEditingParityTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testSourceQuoteScrollPositionCentersMeasuredExcerptAndClampsDocumentEdges() {
        let contentHeight: CGFloat = 3688.7
        let viewportHeight: CGFloat = 874
        let sourceMidY: CGFloat = 2202.7 + 92 / 2
        let anchor = SourceQuoteScrollPosition.unitAnchorY(sourceMidY: sourceMidY,
            contentHeight: contentHeight, viewportHeight: viewportHeight)
        let offset = anchor * (contentHeight - viewportHeight)
        XCTAssertEqual(sourceMidY - offset, viewportHeight / 2, accuracy: 0.01,
                       "The real failed source position must move to the visible viewport center")
        XCTAssertEqual(SourceQuoteScrollPosition.unitAnchorY(sourceMidY: 10,
            contentHeight: contentHeight, viewportHeight: viewportHeight), 0)
        XCTAssertEqual(SourceQuoteScrollPosition.unitAnchorY(sourceMidY: contentHeight - 10,
            contentHeight: contentHeight, viewportHeight: viewportHeight), 1)
        XCTAssertEqual(SourceQuoteScrollPosition.unitAnchorY(sourceMidY: 200,
            contentHeight: 400, viewportHeight: viewportHeight), 0)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    @MainActor
    func testSourceQuoteCanReachProviderReadResultsWithoutLegacyTopLevelContent() {
        let raw: [String: AnyCodable] = ["results": AnyCodable([
            ["markdown": "First provider paragraph."],
            ["content": "The quoted source paragraph."]
        ])]
        let source = WebReadEmbedRenderer.sourceContent(in: raw)
        XCTAssertEqual(source, "First provider paragraph.\n\nThe quoted source paragraph.")
        XCTAssertNotNil(source.flatMap { SourceQuoteMatcher.range(in: $0, quote: "The quoted source paragraph") })
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testSourceQuoteMatchingPreservesOriginalUnicodeOffsetsAndNormalizesTypography() {
        let source = "🌱 Intro. Svelte’s new system — with smart quotes…\n   updates the DOM."
        let quote = "Svelte's new system - with smart quotes... updates the DOM."
        let range = SourceQuoteMatcher.range(in: source, quote: quote)
        XCTAssertNotNil(range)
        XCTAssertEqual(range.map { (source as NSString).substring(with: $0) },
                       "Svelte’s new system — with smart quotes…\n   updates the DOM.")
        XCTAssertEqual(SourceQuoteMatcher.range(in: "  Source     words", quote: "source words"),
                       NSRange(location: 2, length: 16))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testSourceQuoteMatchingUsesVerifiedExcerptFallbackWithoutHighlightingUnrelatedText() {
        let source = "Instead of virtual DOM diffing, Svelte writes code that updates the DOM when state changes."
        let quote = "Svelte writes code that updates the DOM when state changes and performs extra work."
        let range = SourceQuoteMatcher.range(in: source, quote: quote)
        XCTAssertEqual(range.map { (source as NSString).substring(with: $0) },
                       "Svelte writes code that updates the DOM when state changes")
        XCTAssertNil(SourceQuoteMatcher.range(in: source, quote: "There is completely unrelated text in this verified source quotation"))
        XCTAssertNil(SourceQuoteMatcher.range(in: source, quote: " \n "))
        XCTAssertNil(SourceQuoteMatcher.range(in: source, quote: nil))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    @MainActor
    func testSourceQuoteHighlightColorsOnlyMatchedSourceCharacters() throws {
        let source = "Before. Quoted excerpt. After."
        let attributed = SourceQuoteMatcher.attributed(source, range: SourceQuoteMatcher.range(in: source, quote: "Quoted excerpt"))
        let coloredRuns = attributed.runs.filter { $0.backgroundColor != nil }
        XCTAssertEqual(coloredRuns.count, 1)
        let run = try XCTUnwrap(coloredRuns.first)
        XCTAssertEqual(String(attributed[run.range].characters), "Quoted excerpt")
        XCTAssertEqual(run.backgroundColor, Color.highlightYellowSolid.opacity(0.4))
        XCTAssertEqual(String(attributed.characters), source)
        XCTAssertTrue(SourceQuoteMatcher.attributed(source, range: nil).runs.allSatisfy { $0.backgroundColor == nil })
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testFullscreenSelectionSurvivesHydrationReorderAndRemovalByIdentity() {
        let a = embed(id: "a", type: "web-website")
        let b = embed(id: "b", type: "web-website")
        let c = embed(id: "c", type: "web-website")
        let inserted = embed(id: "inserted", type: "web-website")
        var state = EmbedFullscreenSelection()
        state.reconcile(in: [a, b, c], initialID: b.id)
        XCTAssertEqual(state.selectedID, b.id)
        state.reconcile(in: [inserted, a, b, c], initialID: b.id)
        XCTAssertEqual(state.selectedID, b.id, "Inserting ahead of the active result must not select the old numeric index")
        XCTAssertTrue(state.move(by: 1, in: [inserted, a, b, c], initialID: b.id))
        XCTAssertEqual(state.selectedID, c.id)
        state.reconcile(in: [c, b, a, inserted], initialID: b.id)
        XCTAssertEqual(state.selectedID, c.id)
        XCTAssertFalse(state.move(by: -1, in: [c, b, a, inserted], initialID: b.id))
        state.reconcile(in: [b, a, inserted], initialID: b.id)
        XCTAssertEqual(state.selectedID, b.id, "A removed result falls back to the requested route if it remains")
        state.reconcile(in: [a, inserted], initialID: b.id)
        XCTAssertEqual(state.selectedID, a.id)
        state.reconcile(in: [], initialID: b.id)
        XCTAssertNil(state.selectedID)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testFullscreenResultNavigationPreservesSiblingOrderWithoutItsParent() {
        let parent = embed(id: "parent", type: "app-skill-use", embedIds: "child-b|child-a|child-b|missing")
        let a = embed(id: "child-a", type: "web-website", parentEmbedId: parent.id)
        let b = embed(id: "child-b", type: "web-website", parentEmbedId: parent.id)
        let unrelated = embed(id: "unrelated", type: "web-website")
        let records = [parent.id: parent, a.id: a, b.id: b, unrelated.id: unrelated]
        let group = EmbedGrouper.fullscreenNavigationEmbeds(selected: b, messageEmbeds: [parent], allRecords: records)
        XCTAssertEqual(group.map(\.id), ["child-b", "child-a"])
        XCTAssertEqual(EmbedGrouper.fullscreenNavigationEmbeds(selected: parent,
            messageEmbeds: [parent], allRecords: records).map(\.id), [parent.id])
        XCTAssertEqual(EmbedGrouper.fullscreenNavigationEmbeds(selected: parent,
            messageEmbeds: [parent, a, b, unrelated], allRecords: records).map(\.id), [parent.id, unrelated.id],
            "Parent navigation must not step into child citations from the same message")
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testFullscreenNavigationUsesHydratedParentInsteadOfItsCapturedRouteSnapshot() {
        let captured = embed(id: "parent", type: "app-skill-use", embedIds: "a|b")
        let hydrated = embed(id: "parent", type: "app-skill-use", embedIds: "inserted|a|b")
        let inserted = embed(id: "inserted", type: "web-website", parentEmbedId: "parent")
        let a = embed(id: "a", type: "web-website", parentEmbedId: "parent")
        let b = embed(id: "b", type: "web-website", parentEmbedId: "parent")
        XCTAssertEqual(EmbedGrouper.fullscreenNavigationEmbeds(selected: b, messageEmbeds: [captured],
            allRecords: [hydrated.id: hydrated, inserted.id: inserted, a.id: a, b.id: b], parent: captured)
            .map(\.id), [inserted.id, a.id, b.id])
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testFullscreenResultNavigationUsesReverseLinksAndKeepsUnresolvedSelectionReachable() {
        let parent = embed(id: "parent", type: "app-skill-use")
        let a = embed(id: "child-a", type: "web-website", parentEmbedId: parent.id)
        let b = embed(id: "child-b", type: "web-website", parentEmbedId: parent.id)
        let records = [parent.id: parent, b.id: b, a.id: a]
        XCTAssertEqual(EmbedGrouper.fullscreenNavigationEmbeds(selected: a,
            messageEmbeds: [parent], allRecords: records).map(\.id), [a.id, b.id])
        let orphan = embed(id: "orphan", type: "web-website", parentEmbedId: "missing")
        XCTAssertEqual(EmbedGrouper.fullscreenNavigationEmbeds(selected: orphan,
            messageEmbeds: [parent], allRecords: records).map(\.id), [orphan.id])
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    @MainActor
    func testChatOpeningHydratesSyncedEmbedTreeAfterLightweightSelectionMissesReferences() async throws {
        let chat = try JSONDecoder().decode(Chat.self, from: Data("{\"id\":\"embed-cache-chat\",\"title\":\"Fixture\"}".utf8))
        let parent = embed(id: "parent", type: "app-skill-use", data: ["type": "app_skill_use"], embedIds: "child")
        let child = embed(id: "child", type: "web-website", data: ["title": "Result"], parentEmbedId: "parent")
        let store = ChatStore()
        store.upsertEmbeds([parent, child], for: chat.id)
        let message = Message(id: "message", chatId: chat.id, role: .assistant,
                              content: "Search result", encryptedContent: nil,
                              createdAt: "2026-01-01T00:00:00Z", updatedAt: nil,
                              appId: nil, isStreaming: false,
                              embedRefs: [EmbedRef(id: "parent", type: "app-skill-use", status: "finished", data: nil)])
        let model = ChatViewModel()
        model.configure(wsManager: nil, chatStore: store)
        // The initial window can have no embeds because its encrypted messages
        // did not expose references until decryption. No network is available.
        await model.loadChat(id: chat.id, initialChat: chat, initialMessages: [message], initialEmbeds: [])
        for _ in 0..<40 where model.embedRecords["child"] == nil {
            try await Task.sleep(nanoseconds: 25_000_000)
        }
        XCTAssertEqual(model.embedRecords["child"]?.rawData?["title"]?.value as? String, "Result")
        XCTAssertEqual(model.childEmbeds(for: parent).map(\.id), ["child"])
        XCTAssertNil(model.error)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testRelatedRecordsDeduplicateLatestPayloadWhilePreservingFirstSeenOrder() throws {
        let parent = embed(
            id: "parent",
            type: "app-skill-use",
            data: ["type": "app_skill_use"],
            embedIds: "child-one|child-two"
        )
        let staleChild = embed(id: "child-one", type: "web-website", data: ["title": "Stale"])
        let secondChild = embed(id: "child-two", type: "web-website", data: ["title": "Second"])
        let currentChild = embed(id: "child-one", type: "web-website", data: ["title": "Current"])

        let related = EmbedRecord.relatedRecords(
            referencedIds: [parent.id],
            from: [parent, staleChild, secondChild, currentChild],
            context: "test.relatedRecords.deduplication"
        )

        XCTAssertEqual(related.map(\.id), ["parent", "child-one", "child-two"])
        let child = try XCTUnwrap(related.first { $0.id == "child-one" })
        XCTAssertEqual(child.rawData?["title"]?.value as? String, "Current")
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testRelatedRecordsResolveParentAndChildrenFromEitherRelationshipDirection() throws {
        let parent = embed(
            id: "parent",
            type: "app-skill-use",
            data: ["type": "app_skill_use"],
            embedIds: "declared-child"
        )
        let declaredChild = embed(id: "declared-child", type: "web-website")
        let reverseLinkedChild = embed(
            id: "reverse-child",
            type: "web-website",
            parentEmbedId: parent.id
        )

        let fromParent = EmbedRecord.relatedRecords(
            referencedIds: [parent.id],
            from: [parent, declaredChild, reverseLinkedChild],
            context: "test.relatedRecords.fromParent"
        )
        let fromChild = EmbedRecord.relatedRecords(
            referencedIds: [reverseLinkedChild.id],
            from: [parent, declaredChild, reverseLinkedChild],
            context: "test.relatedRecords.fromChild"
        )

        XCTAssertEqual(fromParent.map(\.id), ["parent", "declared-child", "reverse-child"])
        XCTAssertEqual(fromChild.map(\.id), ["parent", "declared-child", "reverse-child"])
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testUnresolvedCompositeParentsRequireTheirDeclaredOrLinkedChildren() {
        let missingChildren = embed(
            id: "missing-parent",
            type: "app-skill-use",
            data: ["type": "app_skill_use"],
            embedIds: "missing-child"
        )
        let linkedParent = embed(
            id: "linked-parent",
            type: "app-skill-use",
            data: ["type": "app_skill_use"]
        )
        let linkedChild = embed(
            id: "linked-child",
            type: "web-website",
            parentEmbedId: linkedParent.id
        )
        let leafSkill = embed(
            id: "leaf-skill",
            type: "app-skill-use",
            data: ["type": "app_skill_use"],
            appId: "math",
            skillId: "calculate"
        )
        let inlinePreview = embed(
            id: "inline-preview",
            type: "app-skill-use",
            data: ["type": "app_skill_use", "preview_results": [["title": "Preview"]]],
            appId: "web",
            skillId: "search"
        )

        XCTAssertEqual(
            EmbedRecord.unresolvedCompositeParentIds(
                referencedIds: [missingChildren.id],
                from: [missingChildren],
                context: "test.unresolved.missing"
            ),
            [missingChildren.id]
        )
        XCTAssertTrue(
            EmbedRecord.unresolvedCompositeParentIds(
                referencedIds: [linkedParent.id],
                from: [linkedParent, linkedChild],
                context: "test.unresolved.linked"
            ).isEmpty
        )
        XCTAssertTrue(
            EmbedRecord.unresolvedCompositeParentIds(
                referencedIds: [leafSkill.id, inlinePreview.id],
                from: [leafSkill, inlinePreview],
                context: "test.unresolved.inline"
            ).isEmpty
        )
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    @MainActor
    func testCompositeHydrationIncludesEncryptedChildrenWithoutDecodedPayloads() {
        let parent = embed(
            id: "search-parent",
            type: "app-skill-use",
            data: ["type": "app_skill_use"],
            embedIds: "search-child"
        )
        let encryptedChild = EmbedRecord(
            id: "search-child",
            type: "web-website",
            status: .finished,
            data: nil,
            encryptedContent: "encrypted-child-content",
            parentEmbedId: parent.id,
            appId: "web",
            skillId: nil,
            embedIds: nil,
            createdAt: "2026-01-01T00:00:01Z"
        )

        XCTAssertTrue(ChatViewModel.hasUndecryptedRequiredEmbed(
            ids: [parent.id, encryptedChild.id],
            records: [parent.id: parent, encryptedChild.id: encryptedChild]
        ))
        XCTAssertFalse(ChatViewModel.hasUndecryptedRequiredEmbed(
            ids: [parent.id],
            records: [parent.id: parent, encryptedChild.id: encryptedChild]
        ))
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testEmbedRecordDecodesVersionMetadataFromWebPayload() throws {
        let json = """
        {
          "embed_id": "embed-1",
          "type": "code",
          "status": "finished",
          "version_number": 3,
          "content_hash": "hash-v3",
          "version_history_readonly": true,
          "version_history": [
            { "version_number": 1, "created_at": 1760000000, "has_snapshot": true, "has_patch": false, "content_hash": "hash-v1" },
            { "version_number": 2, "created_at": 1760000100, "has_snapshot": false, "has_patch": true },
            { "version_number": 3, "created_at": 1760000200, "has_snapshot": false, "has_patch": true, "content_hash": "hash-v3" }
          ],
          "content": "{}"
        }
        """.data(using: .utf8)!

        let record = try JSONDecoder().decode(EmbedRecord.self, from: json)

        XCTAssertEqual(record.id, "embed-1")
        XCTAssertEqual(record.versionNumber, 3)
        XCTAssertEqual(record.contentHash, "hash-v3")
        XCTAssertTrue(record.versionHistoryReadonly)
        XCTAssertEqual(record.versionHistory.map(\.versionNumber), [1, 2, 3])
        XCTAssertEqual(record.versionHistory.first?.hasSnapshot, true)
        XCTAssertEqual(record.versionHistory.last?.contentHash, "hash-v3")
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testRestoreRequestEncodesSnakeCaseContract() throws {
        let request = EmbedVersionRestoreRequest(embedId: "embed-1", versionNumber: 1)
        let data = try JSONEncoder().encode(request)
        let object = try JSONSerialization.jsonObject(with: data) as? [String: Any]

        XCTAssertEqual(object?["embed_id"] as? String, "embed-1")
        XCTAssertEqual(object?["version_number"] as? Int, 1)
    }

    private func embed(
        id: String,
        type: String,
        data: [String: Any] = [:],
        parentEmbedId: String? = nil,
        appId: String? = nil,
        skillId: String? = nil,
        embedIds: String? = nil
    ) -> EmbedRecord {
        EmbedRecord(
            id: id,
            type: type,
            status: .finished,
            data: data.isEmpty ? nil : .raw(data.mapValues { AnyCodable($0) }),
            parentEmbedId: parentEmbedId,
            appId: appId,
            skillId: skillId,
            embedIds: embedIds,
            createdAt: nil
        )
    }
}

@MainActor
final class EmbedHeaderActionLayoutParityTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testHealthMapStartsAtPanelEdgeWhileCTAOwnsItsFullHitBounds() {
        let mapped = HealthAppointmentModel(["latitude": .init(48.137), "longitude": .init(11.575)])
        let unmapped = HealthAppointmentModel(["telehealth": .init(true)])
        XCTAssertNotNil(mapped.mapConfiguration)
        XCTAssertNil(unmapped.mapConfiguration)
        let underlap = EmbedFullscreenHeaderLayout.healthMapUnderlap(
            hasHeaderCTA: true, hasMap: mapped.mapConfiguration != nil)
        XCTAssertEqual(underlap, 22)
        for width: CGFloat in [402, 1_100] {
            let panelHeight = EmbedFullscreenHeaderLayout.height(
                viewportWidth: width, fallbackCompact: false, topContentInset: 62)
            let fullHeaderHitHeight = panelHeight + 22
            XCTAssertEqual(fullHeaderHitHeight - underlap, panelHeight)
        }
        XCTAssertEqual(EmbedFullscreenHeaderLayout.healthMapUnderlap(hasHeaderCTA: false, hasMap: true), 0)
        XCTAssertEqual(EmbedFullscreenHeaderLayout.healthMapUnderlap(
            hasHeaderCTA: true, hasMap: unmapped.mapConfiguration != nil), 0)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testHealthCalendarAvailabilityGroupsShareOnlyOnPhoneAndExportsWebContext() throws {
        let data: [String: AnyCodable] = ["slot_datetime": .init("2026-04-03T10:30:00+02:00"),
            "name": .init("Dr. Example"), "speciality": .init("Cardiology"),
            "address": .init("Example Street 1\nMunich"), "service_name": .init("Consultation"),
            "provider_platform": .init("Doctolib"), "price": .init(120),
            "booking_url": .init("https://www.doctolib.de/example")]
        let file = try XCTUnwrap(HealthAppointmentCalendarFile.make(data, now: Date(timeIntervalSince1970: 0)))
        XCTAssertTrue(EmbedHeaderActionPolicy.usesMore(width: 402, actionCount: 1))
        XCTAssertFalse(EmbedHeaderActionPolicy.usesMore(width: 860, actionCount: 1))
        XCTAssertEqual(file.filename, "dr-example-cardiology-2026-04-03.ics")
        XCTAssertTrue(file.content.contains("DTSTART:20260403T083000Z\r\nDTEND:20260403T093000Z"))
        XCTAssertTrue(file.content.contains("SUMMARY:Dr. Example - Cardiology"))
        XCTAssertTrue(file.content.contains("LOCATION:Example Street 1\\nMunich"))
        let unfolded = file.content.replacingOccurrences(of: "\r\n ", with: "")
        XCTAssertTrue(unfolded.contains("DESCRIPTION:Speciality: Cardiology\\nService: Consultation\\nProvider: Doctolib\\nPrice: 120 EUR\\nhttps://www.doctolib.de/example"))
        XCTAssertTrue(unfolded.contains("URL:https://www.doctolib.de/example"))
        XCTAssertTrue(unfolded.contains("DTSTAMP:19700101T000000Z"))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testCalendarParsesProviderLocalTimeFractionalOffsetAndExclusiveAllDayEnd() throws {
        let zone = try XCTUnwrap(TimeZone(secondsFromGMT: 7_200))
        let local = try XCTUnwrap(EmbedCalendarFile.build(title: "Appointment", start: "2026-04-03T10:30:00",
            location: nil, description: nil, url: nil, timeZone: zone))
        XCTAssertTrue(local.content.contains("DTSTART:20260403T083000Z"))
        let fractional = try XCTUnwrap(EmbedCalendarFile.build(title: "Appointment", start: "2026-04-03T10:30:00.123+02:00",
            location: nil, description: nil, url: nil, timeZone: zone))
        XCTAssertTrue(fractional.content.contains("DTSTART:20260403T083000Z"))
        let allDay = try XCTUnwrap(EmbedCalendarFile.build(title: "Appointment", start: "2026-04-03",
            location: nil, description: nil, url: nil, timeZone: zone))
        XCTAssertTrue(allDay.content.contains("DTSTART;VALUE=DATE:20260403\r\nDTEND;VALUE=DATE:20260404"))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testInvalidAppointmentDateDoesNotExposeCalendarAction() {
        for value in ["", "not a date", "2026-02-30T10:30:00", "2026-04-03T25:30:00",
                      "2026-04-03T10:30:00+99:00", "2026-04-03T10:30:00-99:00",
                      "2026-04-03T10:30:00+24:00", "2026-04-03T10:30:00+01:60",
                      "2026-04-03T10:30:00Z\r\nBEGIN:VEVENT"] {
            XCTAssertNil(HealthAppointmentCalendarFile.make(["slot_datetime": .init(value)]), value)
        }
        XCTAssertNil(HealthAppointmentCalendarFile.make([:]))
        XCTAssertFalse(EmbedHeaderActionPolicy.usesMore(width: 402, actionCount: 0))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testCalendarEscapesPropertyInjectionAndFoldsUnicodeWithoutSplittingUTF8() throws {
        let title = "Dr. Müller, Example; \\ Notes\r\nInjected: text"
        let file = try XCTUnwrap(EmbedCalendarFile.build(title: title, start: "2026-04-03T10:30:00Z",
            location: "Street\rOther", description: String(repeating: "München ", count: 30), url: nil))
        XCTAssertTrue(file.content.contains("SUMMARY:Dr. Müller\\, Example\\; \\\\ Notes\\nInjected: text"))
        XCTAssertTrue(file.content.contains("LOCATION:Street\\nOther"))
        XCTAssertFalse(file.content.contains("\r\nInjected:"))
        for line in file.content.components(separatedBy: "\r\n") { XCTAssertLessThanOrEqual(line.utf8.count, 75) }
        let unfolded = file.content.replacingOccurrences(of: "\r\n ", with: "")
        XCTAssertTrue(unfolded.contains("DESCRIPTION:" + String(repeating: "München ", count: 30)))
        XCTAssertTrue(file.filename.hasSuffix(".ics"))
        XCTAssertFalse(file.filename.contains("/"))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.persistence.client-encrypted
    func testCalendarContextHonorsDisplayedPIIMasking() throws {
        let file = try XCTUnwrap(HealthAppointmentCalendarFile.make([
            "slot_datetime": .init("2026-04-03T10:30:00Z"), "name": .init("Synthetic original"),
            "address": .init("Synthetic original"), "service_name": .init("Synthetic original")
        ], renderText: { $0.replacingOccurrences(of: "Synthetic original", with: "Masked") }))
        XCTAssertFalse(file.content.contains("Synthetic original"))
        XCTAssertTrue(file.content.contains("SUMMARY:Masked"))
        XCTAssertTrue(file.content.contains("LOCATION:Masked"))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testWebSearchKeepsShareDirectAtPhoneWidth() {
        XCTAssertFalse(EmbedHeaderActionPolicy.usesMore(width: 390, actionCount: 0))
        XCTAssertTrue(EmbedHeaderActionPolicy.usesMore(width: 390, actionCount: 2))
        XCTAssertFalse(EmbedHeaderActionPolicy.usesMore(width: 460, actionCount: 1))
        XCTAssertTrue(EmbedHeaderActionPolicy.usesMore(width: 459, actionCount: 1))
        XCTAssertFalse(EmbedHeaderActionPolicy.reportShowsLabel(width: 639))
        XCTAssertTrue(EmbedHeaderActionPolicy.reportShowsLabel(width: 640))
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testMoreMenuFitsActualToolbarAnchorIncludingWideReportLabelAndSafeArea() {
        for (toolbar, anchor) in [
            (CGRect(x: 0, y: 0, width: 390, height: 65), CGRect(x: 65, y: 12, width: 41, height: 41)),
            // Wide Report's visible label moves More beyond the old fixed100pt estimate.
            (CGRect(x: 0, y: 0, width: 700, height: 65), CGRect(x: 260, y: 12, width: 41, height: 41)),
            (CGRect(x: 59, y: 0, width: 582, height: 65), CGRect(x: 220, y: 12, width: 41, height: 41))
        ] {
            let width = EmbedHeaderActionPolicy.menuWidth(toolbar: toolbar, anchor: anchor)
            XCTAssertGreaterThan(width, 41)
            XCTAssertEqual(anchor.minX + width * 1.08 + 8, toolbar.maxX - 16, accuracy: 0.001)
        }
        XCTAssertEqual(EmbedHeaderActionPolicy.menuWidth(toolbar: .zero, anchor: .zero), 0)
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testPhysical135DegreeGradientDoesNotSkewOnWideHeaders() {
        let size = CGSize(width: 390, height: 190)
        let (start, end) = CSSHeaderGradientGeometry.endpoints(size: size)
        XCTAssertEqual((end.x - start.x) * size.width, (end.y - start.y) * size.height, accuracy: 0.001)
        XCTAssertLessThan(start.y, 0)
        XCTAssertEqual(start.x + end.x, 1, accuracy: 0.001)
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testOverlayRequiresActualPerControlIntersection() {
        let control = CGRect(x: 16, y: 12, width: 41, height: 41)
        XCTAssertTrue(EmbedHeaderActionPolicy.overlaps(control: control, header: CGRect(x: 0, y: -100, width: 390, height: 190)))
        XCTAssertFalse(EmbedHeaderActionPolicy.overlaps(control: control, header: CGRect(x: 0, y: -190, width: 390, height: 190)))
        XCTAssertFalse(EmbedHeaderActionPolicy.overlaps(control: control, header: .zero))
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testFullscreenHeaderBreakpointUsesWorkspaceViewportInsteadOfNarrowSidePane() {
        XCTAssertFalse(
            EmbedFullscreenHeaderLayout.isNarrow(viewportWidth: 1_100, fallbackCompact: true),
            "A narrow side pane in a wide iPad workspace keeps the web viewport's desktop header"
        )
        XCTAssertTrue(
            EmbedFullscreenHeaderLayout.isNarrow(viewportWidth: 700, fallbackCompact: false),
            "A genuinely narrow fullscreen viewport uses the web's compact header"
        )
        XCTAssertEqual(
            EmbedFullscreenHeaderLayout.height(viewportWidth: 1_100, fallbackCompact: true, topContentInset: 0),
            240
        )
        XCTAssertEqual(
            EmbedFullscreenHeaderLayout.height(viewportWidth: 700, fallbackCompact: false, topContentInset: 0),
            190
        )
    }
}

@MainActor
final class EmbedHeaderMotionParityTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testExactCSSDriftAndMorphKeyframes() {
        let first = EmbedHeaderMotion.orb(index: 0, elapsed: 19 * 0.25, reduced: false)
        XCTAssertEqual(first.drift[0],130,accuracy:0.0001)
        XCTAssertEqual(first.drift[1],60,accuracy:0.0001)
        let morph = EmbedHeaderMotion.orb(index:0,elapsed:11*0.25,reduced:false)
        XCTAssertEqual(morph.radii,[30,60,70,40,50,60,30,60])
        XCTAssertEqual(EmbedHeaderMotion.orb(index:2,elapsed:29,reduced:false).drift,[0,0])
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testEntranceDelayOrbitAndReducedMotionMatchCSS() {
        let delayed = EmbedHeaderMotion.decoration(right:false,elapsed:0.05,reduced:false)
        XCTAssertEqual(delayed.opacity,0); XCTAssertEqual(delayed.y,40)
        let floating = EmbedHeaderMotion.decoration(right:false,elapsed:0.7,reduced:false)
        XCTAssertEqual(floating.y,-12); XCTAssertEqual(floating.degrees,-15)
        let opposite = EmbedHeaderMotion.decoration(right:true,elapsed:0,reduced:false)
        XCTAssertEqual(opposite.y,12); XCTAssertEqual(opposite.opacity,0.4)
        let reduced = EmbedHeaderMotion.decoration(right:false,elapsed:100,reduced:true)
        XCTAssertEqual(reduced.x,0); XCTAssertEqual(reduced.y,0); XCTAssertEqual(reduced.degrees,0)
        XCTAssertEqual(EmbedHeaderMotion.orb(index:0,elapsed:100,reduced:true).radii,Array(repeating:0,count:8))
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testMorphPathRemainsInItsLocalBounds() {
        let rect = CGRect(x:10,y:20,width:220,height:220)
        for frames in EmbedHeaderMotion.morph {
            for frame in frames {
                let bounds = EmbedHeaderMotion.orbPath(in:rect,percentages:frame.values).boundingRect
                XCTAssertEqual(bounds.minX,rect.minX,accuracy:0.001)
                XCTAssertEqual(bounds.maxX,rect.maxX,accuracy:0.001)
                XCTAssertEqual(bounds.minY,rect.minY,accuracy:0.001)
                XCTAssertEqual(bounds.maxY,rect.maxY,accuracy:0.001)
            }
        }
    }
}


extension EmbedDiffEditingParityTests {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testWebsiteBodyUsesFullscreenContainerBreakpoints() {
        let phone = WebsiteFullscreenMetrics(width: 390)
        XCTAssertEqual(phone.horizontalPadding, 16)
        XCTAssertEqual(phone.topPadding, 16)
        XCTAssertEqual(phone.bottomPadding, 24)
        XCTAssertEqual(phone.snippetPaddingX, 40)
        XCTAssertEqual(phone.quoteSize, 16)
        XCTAssertEqual(WebsiteFullscreenMetrics(width: 400).imageMaxHeight, 180)
        XCTAssertEqual(WebsiteFullscreenMetrics(width: 401).horizontalPadding, 20)
        XCTAssertEqual(WebsiteFullscreenMetrics(width: 600).snippetPaddingX, 50)
        XCTAssertEqual(WebsiteFullscreenMetrics(width: 601).horizontalPadding, 40)
    }
}


extension EmbedDiffEditingParityTests {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testSearchThumbnailsDeduplicateAndBoundHydratedMetadata() {
        let inputs: [String?] = [nil, "a", "a"] + (0..<20).map { "image-\($0)" }
        let urls = WebSearchThumbnailStrip.selectedURLs(inputs)
        XCTAssertEqual(urls.count, 10)
        XCTAssertEqual(urls.first, "a")
        XCTAssertEqual(urls.last, "image-8")
        XCTAssertTrue(WebSearchThumbnailStrip.selectedURLs([]).isEmpty)
    }
}


final class WorkspacePaneMetricsTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testSidebarAndSettingsCanReduceActualChatBelowSplitThreshold() {
        func metrics(sidebar: Bool = false, settings: Bool = false) -> WorkspacePaneMetrics {
            .init(windowWidth: 1280, sidebarOpen: sidebar, settingsOpen: settings,
                  embedOpen: true, embedHasChatContext: true, chatHidden: false)
        }
        XCTAssertEqual(metrics().activeWidth, 1240)
        XCTAssertTrue(metrics().splitCapable)
        XCTAssertEqual(metrics().embedWidth, 830)
        XCTAssertFalse(metrics(sidebar: true).splitCapable)
        XCTAssertFalse(metrics(settings: true).splitCapable)
        XCTAssertFalse(metrics(sidebar: true).settingsOverlays,
                       "Settings overlay uses window width, not sidebar-reduced width")
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testHideChatRetainsItsTextWidthAndRestoresSameSplit() {
        let hidden = WorkspacePaneMetrics(windowWidth: 1280, sidebarOpen: false,
            settingsOpen: false, embedOpen: true, embedHasChatContext: true, chatHidden: true)
        XCTAssertTrue(hidden.splitCapable)
        XCTAssertEqual(hidden.transcriptWidth, 400)
        XCTAssertEqual(hidden.transcriptOffset, -410)
        XCTAssertEqual(hidden.embedWidth, 1240)
        XCTAssertFalse(hidden.transcriptVisible)
    }
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testPhoneAndStandaloneEmbedsNeverInventSplitContext() {
        let phone = WorkspacePaneMetrics(windowWidth: 390, sidebarOpen: true,
            settingsOpen: true, embedOpen: true, embedHasChatContext: true, chatHidden: false)
        XCTAssertTrue(phone.sidebarOverlays)
        XCTAssertTrue(phone.settingsOverlays)
        XCTAssertEqual(phone.activeWidth, 370)
        XCTAssertFalse(phone.splitCapable)
        let standalone = WorkspacePaneMetrics(windowWidth: 1700, sidebarOpen: false,
            settingsOpen: false, embedOpen: true, embedHasChatContext: false, chatHidden: false)
        XCTAssertFalse(standalone.splitCapable)
    }
}


extension WorkspacePaneMetricsTests {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testRevealMaskMatchesCSSInsetKeyframes() {
        let rect = CGRect(x: 0, y: 0, width: 830, height: 759)
        XCTAssertEqual(WorkspaceEmbedRevealMask(progress: 0.5).path(in: rect).boundingRect,
                       CGRect(x: 415, y: 0, width: 415, height: 759))
        XCTAssertEqual(WorkspaceEmbedRevealMask(progress: 1).path(in: rect).boundingRect, rect)
    }
    @MainActor
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testIsolatedSettingsCannotCallAnAccountServiceOrShareGuestState() async {
        let first = LearningModeGuestSession()
        let second = LearningModeGuestSession()
        first.activate(ageGroup: .adult)
        XCTAssertTrue(first.status.enabled)
        XCTAssertFalse(second.status.enabled)
        let client = IsolatedSettingsAccountClient()
        do { _ = try await client.loadStatus(); XCTFail("Isolated account boundary must reject") }
        catch { XCTAssertTrue(error is IsolatedSettingsAccountClient.Unavailable) }
    }
}


extension WorkspacePaneMetricsTests {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testHiddenOrReducedMotionPaneDoesNotScheduleHeaderAnimation() {
        XCTAssertTrue(WorkspaceMotionPolicy.shouldAnimate(paneVisible: true, scrollVisible: true, sceneActive: true, reduced: false))
        for flags in [(false,true,true,false), (true,false,true,false), (true,true,false,false), (true,true,true,true)] {
            XCTAssertFalse(WorkspaceMotionPolicy.shouldAnimate(paneVisible: flags.0, scrollVisible: flags.1, sceneActive: flags.2, reduced: flags.3))
        }
    }
}
