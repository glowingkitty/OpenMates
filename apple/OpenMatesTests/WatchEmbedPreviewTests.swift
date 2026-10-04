// Unit coverage for the Watch embed preview contract.
// These tests lock down the small watchOS card mapping without rendering the
// iOS/macOS embed stack or storing private chat content in fixtures.

import XCTest
import CryptoKit
@testable import OpenMates

final class WatchEmbedPreviewTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.iphone-first-fallback
    func testWatchPairLoginUIContractIdentifiersAreStable() {
        XCTAssertEqual(Set(WatchUIContract.pairLoginIdentifiers), [
            "watch-pair-login",
            "watch-pair-confirm-iphone-title",
            "watch-pair-manual-fallback",
            "watch-pair-login-without-iphone-button",
            "watch-pair-token",
            "watch-pair-url",
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

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.compact-layout,apple-watch.chats.audio-reply
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
            "watch-audio-recording-screen",
            "watch-audio-recording-duration",
            "watch-audio-cancel-button",
            "watch-audio-send-button",
            "watch-pending-audio-embed",
            "watch-audio-error",
            "watch-audio-retry-button",
            "watch-audio-back-button",
        ])
        XCTAssertNoDuplicates(WatchUIContract.chatFlowIdentifiers)
        XCTAssertNoDuplicates(WatchUIContract.audioComposerIdentifiers)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.compact-layout
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

    // contract-test: supporting surface=gui.apple assertions=apple-watch.hub.compact-navigation
    func testWatchDesignReviewContractRejectsStockProductChrome() {
        XCTAssertEqual(Set(WatchUIContract.forbiddenProductChrome), [
            "List",
            "Form",
            "NavigationStack",
            "TabView",
            "navigationTitle",
            "toolbar",
        ])
        XCTAssertTrue(WatchUIContract.designEvidence.contains { $0.contains("Color.grey100") })
        XCTAssertTrue(WatchUIContract.designEvidence.contains { $0.contains("ScrollView/LazyVStack") })
        XCTAssertTrue(WatchUIContract.designEvidence.contains { $0.contains("encrypted audio-recording embed") })
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.compact-layout
    func testWatchChatThreadClaimsFullDisplayWithoutPagedTabChrome() throws {
        let source = try watchSource(named: "WatchChatViews.swift")

        XCTAssertFalse(source.contains("TabView("))
        XCTAssertFalse(source.contains(".tabViewStyle(.page"))
        XCTAssertTrue(source.contains(".frame(maxWidth: .infinity, maxHeight: .infinity)"))
        XCTAssertTrue(source.contains(".ignoresSafeArea(edges: .bottom)"))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.compact-layout
    func testWatchEmbedPreviewUsesFixedWatchCardWidth() throws {
        let source = try watchSource(named: "WatchEmbedViews.swift")

        XCTAssertEqual(WatchEmbedPreviewModel.cardWidth, 156)
        XCTAssertTrue(source.contains("width: CGFloat(WatchEmbedPreviewModel.cardWidth)"))
        XCTAssertTrue(source.contains("gradient(forAppId: model.appId)"))
        XCTAssertTrue(source.contains("watch-embed-app-bar-"))
        XCTAssertTrue(source.contains("multilineTextAlignment(.center)"))
        XCTAssertFalse(source.contains("Circle()"), "Watch previews use the approved full-width mobile app bar")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.compact-layout
    func testCodePreviewUsesEmbedTitleAndLineCount() {
        let embed = Self.embed(
            type: EmbedType.codeCode.rawValue,
            raw: ["title": AnyCodable("Write"), "line_count": AnyCodable(28)]
        )

        let model = WatchEmbedPreviewMapper.makeModel(for: embed, chatId: "chat-123")

        XCTAssertEqual(model.family, .code)
        XCTAssertEqual(model.title, "Write")
        XCTAssertEqual(model.detail, "28 lines")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.compact-layout
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

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.compact-layout
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

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.compact-layout
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

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.compact-layout
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

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.compact-layout
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

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.compact-layout
    func testWatchExtractsInlineEmbedMarkersWhenApiOmitsRefs() throws {
        let content = """
        [[embed:embed-inline]]

        ```json
        {"type":"web-website","embed_id":"embed-json","title":"Safe title","transcript":"private transcript","aes_key":"secret-key","vault_wrapped_aes_key":"secret-wrapped"}
        ```

        [!](embed:embed-large)
        """

        let refs = WatchMessageContentSanitizer.inlineEmbedRefs(content: content)

        XCTAssertEqual(refs.map(\.id), ["embed-inline", "embed-json", "embed-large"])
        XCTAssertEqual(refs.map(\.type), [EmbedType.webWebsite.rawValue, EmbedType.webWebsite.rawValue, EmbedType.webWebsite.rawValue])
        XCTAssertEqual(refs[1].data?["title"]?.value as? String, "Safe title")
        XCTAssertNil(refs[1].data?["transcript"])
        XCTAssertNil(refs[1].data?["aes_key"])
        XCTAssertNil(refs[1].data?["vault_wrapped_aes_key"])
        XCTAssertNil(WatchMessageContentSanitizer.displayText(content: content, embedRefs: refs))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.compact-layout
    func testWatchRendersMarkdownEmbedReferencesWithoutLeakingSyntax() throws {
        let content = "See [CSD Magdeburg](embed:csd-deutschland.de-NXT) for details."

        let refs = WatchMessageContentSanitizer.inlineEmbedRefs(content: content)
        let displayText = WatchMessageContentSanitizer.displayText(content: content, embedRefs: refs)

        XCTAssertTrue(refs.isEmpty, "Inline reference links must not be promoted to generic preview cards")
        XCTAssertEqual(displayText, "See CSD Magdeburg for details.")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.compact-layout
    func testWatchDerivesReadableTravelEmbedReferenceLabels() {
        XCTAssertEqual(
            WatchMessageContentSanitizer.displayText(
                content: "[ice-0800-PsB](embed:ice-0800-PsB)",
                embedRefs: nil
            ),
            "ICE 08:00"
        )
        XCTAssertEqual(
            WatchMessageContentSanitizer.displayText(
                content: "[](embed:flixtrain-1423-3VT)",
                embedRefs: nil
            ),
            "FlixTrain 14:23"
        )
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.compact-layout
    func testWatchReplacesMultipleUnicodeEmbedReferenceLabels() {
        let content = "[Café Köln](embed:cafe.example-AbC) and [Zürich HB](embed:ice-1730-XyZ)"

        XCTAssertEqual(
            WatchMessageContentSanitizer.displayText(content: content, embedRefs: nil),
            "Café Köln and Zürich HB"
        )
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.compact-layout
    func testWatchDoesNotRenderApiEmbedRecordAsCardWhenConsumedByInlineReference() {
        let ref = WatchEmbedRef(
            id: "embed-uuid",
            type: EmbedType.webWebsite.rawValue,
            status: "finished",
            data: [
                "embed_ref": AnyCodable("csd-deutschland.de-NXT"),
                "title": AnyCodable("CSD Magdeburg"),
            ]
        )
        let message = WatchChatMessage(
            id: "message-1",
            chatId: "chat-1",
            role: .assistant,
            content: "See [CSD Magdeburg](embed:csd-deutschland.de-NXT) for details.",
            encryptedContent: nil,
            embedRefs: [ref],
            createdAt: "2026-08-03T00:00:00Z",
            isPending: false
        )

        XCTAssertEqual(message.watchDisplayContent, "See CSD Magdeburg for details.")
        XCTAssertTrue(message.watchEmbedRecords.isEmpty)
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

    private func watchSource(named filename: String) throws -> String {
        let appleRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let sourceURL = appleRoot.appendingPathComponent("OpenMatesWatch/Sources/\(filename)")
        return try String(contentsOf: sourceURL, encoding: .utf8)
    }

    private func XCTAssertNoDuplicates(
        _ values: [String],
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        XCTAssertEqual(values.count, Set(values).count, file: file, line: line)
    }
}

extension WatchEmbedPreviewTests {
    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.compact-layout
    func testWatchMarkdownKeepsHeadingListsQuoteAndCodeSemantics() throws {
        let blocks = WatchMarkdownParser.blocks("# Berlin **Meetup**\n\nA *public* [link](https://example.com).\n\n- First\n2. Second\n> Quoted\n```swift\nlet value = 1\n```")
        XCTAssertEqual(blocks.map(\.kind), [.heading(1), .paragraph, .list("•"), .list("2."), .quote, .code("swift")])
        XCTAssertEqual(blocks.last?.text, "let value = 1")
        let inline = try AttributedString(markdown: blocks[0].text, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))
        XCTAssertEqual(String(inline.characters), "Berlin Meetup")
        XCTAssertTrue(inline.runs.contains { $0.inlinePresentationIntent?.contains(.stronglyEmphasized) == true })
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.compact-layout
    func testWatchEventsAndDocumentSkillFamiliesPreserveAppSemantics() {
        let fixtures: [(EmbedType, WatchEmbedPreviewFamily, String)] = [
            (.eventsSearch, .searchResults, "events"), (.eventsEvent, .event, "events"),
            (.docsDoc, .document, "docs"), (.sheetsSheet, .spreadsheet, "sheets"),
            (.mindmapsMindmap, .mindmap, "mindmaps"), (.audioSpeak, .audio, "audio"),
            (.nutritionSearch, .searchResults, "nutrition")
        ]
        for (type, family, appID) in fixtures {
            let record = Self.embed(type: type.rawValue, raw: ["title": AnyCodable("Public fixture"), "query": AnyCodable("Berlin")])
            let preview = WatchEmbedPreviewMapper.makeModel(for: record, chatId: "fixture-chat")
            XCTAssertEqual(preview.family, family, type.rawValue)
            XCTAssertEqual(preview.appId, appID, type.rawValue)
            XCTAssertEqual(preview.state, .ready, type.rawValue)
            if appID == "mindmaps" { XCTAssertEqual(preview.iconName, "workflow") }
        }
    }
}

extension WatchEmbedPreviewTests {
    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.compact-layout
    func testInlineSkillFenceRetainsKnownAppSkillIdentityForPreview() {
        let content = """
        ```json_embed
        {"embed_id":"public-events","type":"app-skill-use","app_id":"events","skill_id":"search","title":"Berlin meetups","result_count":3,"secret":"discarded"}
        ```
        """
        let refs = WatchMessageContentSanitizer.inlineEmbedRefs(content: content)
        XCTAssertEqual(refs.count, 1)
        XCTAssertNil(refs.first?.data?["secret"])
        let model = refs.first.map { WatchEmbedPreviewMapper.makeModel(for: $0, chatId: "public-chat") }
        XCTAssertEqual(model?.family, .searchResults)
        XCTAssertEqual(model?.appId, "events")
        XCTAssertEqual(model?.typeLabel, "Events")
        XCTAssertEqual(model?.state, .ready)
    }
}

extension WatchEmbedPreviewTests {
    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.compact-layout,drafts.access.first-party-encrypted
    func testSavedWatchEmbedHydratesOnlyBoundAccountChatAndEmbedWrappers() throws {
        let masterKey = SymmetricKey(size: .bits256)
        let chatKey = SymmetricKey(size: .bits256)
        let embedKey = SymmetricKey(size: .bits256)
        func hash(_ value: String) -> String {
            SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
        }
        let body = #"{"app_id":"events","skill_id":"search","query":"Berlin public meetups","result_count":3}"#
        let encryptedContent = try ComposerEmbedCrypto.encryptContent(body, using: embedKey)
        let wrapper: [String: Any] = ["hashed_embed_id": hash("public-embed"), "key_type": "master",
            "hashed_user_id": hash("public-owner"), "encrypted_embed_key": try ComposerEmbedCrypto.wrapKey(embedKey, using: masterKey)]
        let payload: [String: Any] = ["embed_id": "public-embed", "user_id": "public-owner",
            "already_encrypted": true, "encryption_mode": "client", "content": encryptedContent,
            "type": try ComposerEmbedCrypto.encryptContent("app_skill_use", using: embedKey),
            "status": "finished", "embed_keys": [wrapper]]
        let ref = try WatchEmbedHydration.open(payload: payload, embedID: "public-embed", chatID: "public-chat",
            accountID: "public-owner", masterKey: masterKey, chatKey: chatKey)
        let model = WatchEmbedPreviewMapper.makeModel(for: ref, chatId: "public-chat")
        XCTAssertEqual(model.family, .searchResults)
        XCTAssertEqual(model.appId, "events")
        XCTAssertEqual(model.title, "Berlin public meetups")
        XCTAssertEqual(model.typeLabel, "Events")
        XCTAssertThrowsError(try WatchEmbedHydration.open(payload: payload, embedID: "different-embed", chatID: "public-chat",
            accountID: "public-owner", masterKey: masterKey, chatKey: chatKey))
        XCTAssertThrowsError(try WatchEmbedHydration.open(payload: payload, embedID: "public-embed", chatID: "public-chat",
            accountID: "other-owner", masterKey: masterKey, chatKey: chatKey))
        XCTAssertThrowsError(try WatchEmbedHydration.open(payload: payload, embedID: "public-embed", chatID: "public-chat",
            accountID: "public-owner", masterKey: SymmetricKey(size: .bits256), chatKey: chatKey))
        var chatPayload = payload
        chatPayload["embed_keys"] = [["hashed_embed_id": hash("public-embed"), "key_type": "chat",
            "hashed_chat_id": hash("public-chat"), "encrypted_embed_key": try ComposerEmbedCrypto.wrapKey(embedKey, using: chatKey)]]
        XCTAssertThrowsError(try WatchEmbedHydration.open(payload: chatPayload, embedID: "public-embed", chatID: "another-chat",
            accountID: "public-owner", masterKey: masterKey, chatKey: chatKey))
    }
}

extension WatchEmbedPreviewTests {
    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.new-text-reply,apple-watch.chats.compact-layout
    func testWatchLiveEmbedStorageQueuesOnlyCiphertextAndBoundMasterChatWrappers() throws {
        let masterKey = SymmetricKey(size: .bits256)
        let chatKey = SymmetricKey(size: .bits256)
        let content = #"{"app_id":"events","skill_id":"search","query":"Berlin public meetup","result_count":3}"#
        let live: [String: Any] = ["embed_id": "public-embed", "user_id": "public-owner", "chat_id": "public-chat",
            "type": "app_skill_use", "content": content, "status": "finished", "text_preview": "Public meetup",
            "embed_ids": ["public-child"], "is_private": false, "is_shared": false]
        let wire = try WatchEmbedHydration.prepareStorage(payload: live, embedID: "public-embed", chatID: "public-chat",
            messageID: "public-message", accountID: "public-owner", masterKey: masterKey, chatKey: chatKey, now: 123)
        let wrappers = try XCTUnwrap(wire.keys["keys"] as? [[String: Any]])
        XCTAssertEqual(wrappers.count, 2)
        XCTAssertEqual(wrappers.map { $0["key_type"] as? String }, ["master", "chat"])
        let ciphertext = try XCTUnwrap(wire.embed["encrypted_content"] as? String)
        for (index, wrappingKey) in [masterKey, chatKey].enumerated() {
            let key = try ComposerEmbedCrypto.unwrapKey(try XCTUnwrap(wrappers[index]["encrypted_embed_key"] as? String), using: wrappingKey)
            XCTAssertEqual(try ComposerEmbedCrypto.decryptContent(ciphertext, using: key), content)
        }
        XCTAssertEqual(wire.embed["embed_ids"] as? [String], ["public-child"])
        // Child routing IDs survive both canonical envelope representations,
        // including when supplied inside encrypted content rather than beside it.
        for childIDs: Any in [["public-child", "public-child-2"], "public-child|public-child-2"] {
            var variant = live
            variant["embed_ids"] = childIDs
            let prepared = try WatchEmbedHydration.prepareStorage(payload: variant, embedID: "public-embed", chatID: "public-chat",
                messageID: "public-message", accountID: "public-owner", masterKey: masterKey, chatKey: chatKey, now: 123)
            XCTAssertEqual(prepared.embed["embed_ids"] as? [String], ["public-child", "public-child-2"])
        }
        var nested = live
        nested.removeValue(forKey: "embed_ids")
        nested["content"] = #"{"app_id":"events","skill_id":"search","embed_ids":["public-child"]}"#
        let nestedWire = try WatchEmbedHydration.prepareStorage(payload: nested, embedID: "public-embed", chatID: "public-chat",
            messageID: "public-message", accountID: "public-owner", masterKey: masterKey, chatKey: chatKey, now: 123)
        XCTAssertEqual(nestedWire.embed["embed_ids"] as? [String], ["public-child"])
        XCTAssertEqual(wire.embed["created_at"] as? Int, 123)
        XCTAssertNotNil(wire.keys["request_id"] as? String)
        XCTAssertNotNil(wire.embed["request_id"] as? String)
        let keysID = try XCTUnwrap(wire.keys["request_id"] as? String)
        let embedID = try XCTUnwrap(wire.embed["request_id"] as? String)
        let queued = [
            WatchPendingCompletion(id: keysID, chatId: "public-chat", eventType: "store_embed_keys", encryptedPayload: try JSONSerialization.data(withJSONObject: wire.keys)),
            WatchPendingCompletion(id: embedID, chatId: "public-chat", eventType: "store_embed", encryptedPayload: try JSONSerialization.data(withJSONObject: wire.embed))
        ]
        let durableJSON = String(decoding: try JSONEncoder().encode(queued), as: UTF8.self)
        XCTAssertFalse(durableJSON.contains("Berlin public meetup"))
        XCTAssertFalse(durableJSON.contains("Public meetup"))
        XCTAssertNil(wire.embed["content"])
        XCTAssertNil(wire.embed["type"])
        XCTAssertThrowsError(try WatchEmbedHydration.prepareStorage(payload: live, embedID: "public-embed", chatID: "other-chat",
            messageID: "public-message", accountID: "public-owner", masterKey: masterKey, chatKey: chatKey))
    }
}

extension WatchEmbedPreviewTests {
    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.compact-layout
    func testEmptyOrPartialAPIRefsCannotSuppressActualMessageBlockEmbeds() {
        let content = "[[embed:sheet-marker]]\n[!](embed:code-marker)"
        let empty = WatchMessageContentSanitizer.mergedEmbedRefs(content: content, provided: [])
        XCTAssertEqual(empty.map(\.id), ["sheet-marker", "code-marker"])
        let supplied = WatchEmbedRef(id: "sheet-marker", type: EmbedType.sheetsSheet.rawValue,
            status: "finished", data: ["title": AnyCodable("devices.xls")])
        let merged = WatchMessageContentSanitizer.mergedEmbedRefs(content: content, provided: [supplied])
        XCTAssertEqual(merged.map(\.id), ["sheet-marker", "code-marker"])
        XCTAssertEqual(merged[0].type, EmbedType.sheetsSheet.rawValue)
        XCTAssertEqual(merged[0].data?["title"]?.value as? String, "devices.xls")
        XCTAssertEqual(WatchMessageContentSanitizer.mergedEmbedRefs(content: content, provided: merged).count, 2)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.compact-layout
    func testUnhydratedReferenceShowsUnavailableWithoutInventingContent() {
        let ref = WatchEmbedRef(id: "sheet-marker", type: EmbedType.sheetsSheet.rawValue, status: "finished", data: nil)
        let model = WatchEmbedPreviewMapper.makeModel(for: ref, chatId: "fixture-chat")
        XCTAssertEqual(model.state, .unavailable)
        XCTAssertEqual(model.visual, .symbol)
        XCTAssertEqual(model.family, .spreadsheet)
        XCTAssertEqual(model.continuation.embedId, "sheet-marker")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.compact-layout
    func testSheetMobileVisualKeepsOnlyBoundedCellsButUsesAuthoritativeTotal() {
        let table = "| Device | Type | Price |\n| --- | --- | --- |\n| Nexus Fold X | Phone | 1 |\n| Lumina Watch Pro | Watch | 2 |\n| AuraBook Air | Laptop | 3 |\n| Pixel Pad | Tablet | 4 |"
        let ref = WatchEmbedRef(id: "sheet", type: EmbedType.sheetsSheet.rawValue, status: "finished",
            data: ["title": AnyCodable("devices.xls"), "table": AnyCodable(table),
                   "row_count": AnyCodable(29), "col_count": AnyCodable(2)])
        let model = WatchEmbedPreviewMapper.makeModel(for: ref, chatId: "fixture-chat")
        XCTAssertEqual(model.visual, .table(headers: ["Device", "Type"],
            rows: [["Nexus Fold X", "Phone"], ["Lumina Watch Pro", "Watch"], ["AuraBook Air", "Laptop"]], cellCount: 58))
        XCTAssertEqual(model.title, "devices.xls")
        XCTAssertEqual(model.state, .ready)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.compact-layout,drafts.access.first-party-encrypted
    func testEncryptedSheetHydrationUsesSharedContentDecoderAndKeepsNullEnvelopeChildren() throws {
        let master = SymmetricKey(size: .bits256), key = SymmetricKey(size: .bits256)
        func hash(_ value: String) -> String { SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined() }
        let content = #"{"title":"devices.xls","table":"| Device |\n| --- |\n| Nexus Fold X |","embed_ids":["child-fixture"]}"#
        let payload: [String: Any] = ["embed_id": "sheet", "user_id": "owner", "already_encrypted": true,
            "type": try ComposerEmbedCrypto.encryptContent(EmbedType.sheetsSheet.rawValue, using: key),
            "content": try ComposerEmbedCrypto.encryptContent(content, using: key), "embed_ids": NSNull(),
            "parent_embed_id": NSNull(), "embed_keys": [["key_type": "master", "hashed_embed_id": hash("sheet"),
                "hashed_user_id": hash("owner"), "encrypted_embed_key": try ComposerEmbedCrypto.wrapKey(key, using: master)]]]
        let ref = try WatchEmbedHydration.open(payload: payload, embedID: "sheet", chatID: "fixture-chat",
            accountID: "owner", masterKey: master, chatKey: nil)
        XCTAssertEqual(WatchEmbedPreviewMapper.embedRecord(from: ref).childEmbedIds, ["child-fixture"])
        XCTAssertEqual(WatchEmbedPreviewMapper.makeModel(for: ref, chatId: "fixture-chat").visual,
                       .table(headers: ["Device"], rows: [["Nexus Fold X"]], cellCount: 1))
        XCTAssertThrowsError(try WatchEmbedHydration.open(payload: payload, embedID: "sheet", chatID: "fixture-chat",
            accountID: "other-owner", masterKey: master, chatKey: nil))
    }
}

extension WatchEmbedPreviewTests {
    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.compact-layout
    func testNestedEnvelopeNormalizesMetadataWithoutDisplayingPrivateWireContent() {
        let encoded = #"{"title":"devices.xls","table":"| Device |\n| --- |\n| Nexus Fold X |","aes_key":"never-display-key"}"#
        let ref = WatchEmbedRef(id: "sheet", type: EmbedType.sheetsSheet.rawValue, status: "finished",
            data: ["content": AnyCodable(encoded)])
        let record = WatchEmbedPreviewMapper.embedRecord(from: ref)
        XCTAssertNil(record.rawData?["content"], "The serialized envelope cannot become a text excerpt")
        let model = WatchEmbedPreviewMapper.makeModel(for: ref, chatId: "fixture-chat")
        XCTAssertEqual(model.title, "devices.xls")
        XCTAssertEqual(model.visual, .table(headers: ["Device"], rows: [["Nexus Fold X"]], cellCount: 1))
    }
}

extension WatchEmbedPreviewTests {
    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.compact-layout
    func testPreviewPositionsGroupsAndInlineCitationsRemainDistinct() {
        let message = WatchChatMessage(id: "fixture-message", chatId: "fixture-chat", role: .assistant,
            content: "Before\n\n[!](embed:first)\n\n[!](embed:second)\n\nAfter [reference](embed:citation)",
            encryptedContent: nil, embedRefs: ["first", "second", "citation"].map {
                WatchEmbedRef(id: $0, type: EmbedType.webWebsite.rawValue, status: "finished", data: ["title": AnyCodable($0)])
            }, createdAt: "2026-10-03T12:00:00Z", isPending: false)
        let segments = WatchMessageRenderProjection.segments(message: message)
        XCTAssertEqual(segments.count, 3)
        XCTAssertEqual(segments[0].content, .markdown("Before"))
        guard case .embeds(let previews) = segments[1].content else { return XCTFail("Expected inline group") }
        XCTAssertEqual(previews.map(\.id), ["first", "second"])
        XCTAssertEqual(segments[2].content, .markdown("After reference"))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.compact-layout
    func testMarkersInsideOrdinaryCodeDoNotProducePreviewsAndZoomIsBounded() {
        let message = WatchChatMessage(id: "code", chatId: "fixture-chat", role: .assistant,
            content: "```swift\nlet marker = \"[!](embed:example)\"\n```", encryptedContent: nil,
            embedRefs: nil, createdAt: "2026-10-03T12:00:00Z", isPending: false)
        let segments = WatchMessageRenderProjection.segments(message: message)
        XCTAssertFalse(segments.contains { if case .embeds = $0.content { return true }; return false })
        XCTAssertEqual(WatchTranscriptZoom.scale(for: 0), 1)
        XCTAssertGreaterThan(WatchTranscriptZoom.scale(for: 1), 1)
        XCTAssertLessThan(WatchTranscriptZoom.scale(for: -1), 1)
        XCTAssertEqual(WatchTranscriptZoom.adjust(WatchTranscriptZoom.maximum, increase: true), WatchTranscriptZoom.maximum)
        XCTAssertEqual(WatchTranscriptZoom.adjust(WatchTranscriptZoom.minimum, increase: false), WatchTranscriptZoom.minimum)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.embeds.read-only-fullscreen
    func testFullscreenPreservesFullSheetContentAndRejectsUnsafeMapAndThumbnailFields() {
        let table = "| Device | Price |\n| --- | --- |\n| A | 1 |\n| B | 2 |\n| C | 3 |\n| D | 4 |"
        let sheet = WatchEmbedPreviewMapper.makeModel(for: WatchEmbedRef(id: "sheet", type: EmbedType.sheetsSheet.rawValue,
            status: "finished", data: ["table": AnyCodable(table)]), chatId: "fixture-chat")
        XCTAssertEqual(sheet.detailContent.text, table)
        XCTAssertEqual(sheet.detailContent.tableRows.count, 4)
        let map = WatchEmbedPreviewMapper.makeModel(for: WatchEmbedRef(id: "map", type: EmbedType.mapsPlace.rawValue,
            status: "finished", data: ["name": AnyCodable("Public place"), "latitude": AnyCodable(true),
                "longitude": AnyCodable(181), "thumbnail_url": AnyCodable("https://user:secret@example.com/image.png")]), chatId: "fixture-chat")
        XCTAssertNil(map.detailContent.latitude); XCTAssertNil(map.detailContent.longitude); XCTAssertNil(map.detailContent.imageURL)
        let valid = WatchEmbedPreviewMapper.makeModel(for: WatchEmbedRef(id: "valid-map", type: EmbedType.mapsPlace.rawValue,
            status: "finished", data: ["location": AnyCodable(["latitude": 52.52, "longitude": 13.405]),
                "thumbnail_url": AnyCodable("https://example.com/thumb.png")]), chatId: "fixture-chat")
        XCTAssertEqual(valid.detailContent.latitude, 52.52)
        XCTAssertEqual(valid.detailContent.longitude, 13.405)
        XCTAssertEqual(valid.detailContent.imageURL?.host, "example.com")
    }
}
