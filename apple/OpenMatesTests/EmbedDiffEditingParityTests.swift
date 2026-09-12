import SwiftUI
// Unit coverage for native embed version-history parity.
// These tests are deterministic and avoid network, credentials, or private
// persisted content. They guard the REST/sync model contract used by the native
// fullscreen timeline.

import XCTest
@testable import OpenMates

final class EmbedDiffEditingParityTests: XCTestCase {
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
