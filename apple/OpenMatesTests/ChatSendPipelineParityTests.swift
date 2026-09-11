// Unit coverage for Apple chat-send pipeline parity with web chat storage.
// These tests avoid network calls, credentials, private chat content, and raw
// encryption keys. They guard the deterministic payload and retry contracts that
// make Apple-created chats decryptable from other clients such as OpenMates CLI.
// Keep assertions payload-level so the suite remains deterministic on Linux CI
// orchestration and remote Mac runners.

import XCTest
@testable import OpenMates

@MainActor
final class ChatSendPipelineParityTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=apple-notifications.action.routing-coherent
    func testNotificationReplyDoesNotCommitAfterItsSessionChangesDuringPreflight() async throws {
        let payloads = Self.notificationTurnPayloads()
        let transport = NotificationReceiptTransport(state: "PREPARED")
        var validationCount = 0
        do {
            try await ChatSendPipeline().sendSavedChatTurn(turnId: "turn-a",
                preflightPayload: payloads.preflight, outboundPayload: payloads.outbound,
                transport: transport, waitForInferenceReceipt: true,
                validateRemoteSend: {
                    validationCount += 1
                    if validationCount == 2 { throw NotificationReplyError.accountChanged }
                })
            XCTFail("The old account's message/history must not be sent through the replacement session")
        } catch NotificationReplyError.accountChanged {
            XCTAssertEqual(validationCount, 2)
            XCTAssertEqual(transport.waitedTypes, ["chat_turn_preflight_ack"])
            XCTAssertTrue(transport.bareSentTypes.isEmpty)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.action.routing-coherent
    func testDisconnectCancelsPendingNotificationReceipt() async {
        let transport = WebSocketManager()
        let originalGeneration = transport.transportGeneration
        let waiter = Task { @MainActor in
            try await transport.waitForMessage("ai_task_initiated", timeout: .seconds(1)) { _ in true }
        }
        await Task.yield()
        transport.disconnect()
        do {
            _ = try await waiter.value
            XCTFail("A receipt waiter must not survive logout and consume the next account's traffic")
        } catch {
            XCTAssertEqual(error.localizedDescription, "WebSocket is not connected",
                "Disconnect must reject the pending waiter as disconnected, rather than letting its request timeout fire")
            XCTAssertNotEqual(transport.transportGeneration, originalGeneration)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.action.routing-coherent,apple-notifications.delivery.idempotent-visible
    func testNotificationReplyWaitsForItsOwnInferenceReceipt() async throws {
        let transport = NotificationReceiptTransport(state: "PREPARED")
        let payloads = Self.notificationTurnPayloads()
        var completed = false
        let send = Task { @MainActor in
            try await ChatSendPipeline().sendSavedChatTurn(turnId: "turn-a",
                preflightPayload: payloads.preflight, outboundPayload: payloads.outbound,
                transport: transport, waitForInferenceReceipt: true)
            completed = true
        }
        for _ in 0..<1_000 where transport.receiptPredicate == nil { await Task.yield() }
        let matches = try XCTUnwrap(transport.receiptPredicate)
        XCTAssertFalse(completed, "A successful socket write must not complete the notification queue entry")
        XCTAssertEqual(transport.waitedTypes, ["chat_turn_preflight_ack", "ai_task_initiated"])
        XCTAssertTrue(transport.bareSentTypes.isEmpty)
        XCTAssertFalse(matches(["chat_id": "another-chat", "user_message_id": "message-a", "ai_task_id": "task-a"]))
        XCTAssertFalse(matches(["chat_id": "chat-a", "user_message_id": "another-message", "ai_task_id": "task-a"]))
        XCTAssertFalse(matches(["chat_id": "chat-a", "user_message_id": "message-a"]))
        XCTAssertFalse(matches(["code": "ai_dispatch_failed", "turn_id": "another-turn"]))
        XCTAssertTrue(matches(["code": "ai_dispatch_failed", "turn_id": "turn-a"]))
        transport.deliver(["chat_id": "chat-a", "user_message_id": "message-a", "ai_task_id": "task-a"])
        try await send.value
        XCTAssertTrue(completed)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.delivery.idempotent-visible
    func testNotificationRetryDoesNotResubmitAnAlreadyAdmittedTurn() async throws {
        let payloads = Self.notificationTurnPayloads()
        for state in ["ENQUEUED", "RUNNING", "TERMINAL"] {
            let transport = NotificationReceiptTransport(state: state)
            try await ChatSendPipeline().sendSavedChatTurn(turnId: "turn-a",
                preflightPayload: payloads.preflight, outboundPayload: payloads.outbound,
                transport: transport, waitForInferenceReceipt: true)
            XCTAssertEqual(transport.waitedTypes, ["chat_turn_preflight_ack"], state)
            XCTAssertTrue(transport.bareSentTypes.isEmpty, "An interrupted completion must not dispatch another AI turn")
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.action.routing-coherent,apple-notifications.delivery.idempotent-visible
    func testNotificationFailedTurnAndRejectedReceiptRemainFailures() async throws {
        let payloads = Self.notificationTurnPayloads()
        let failed = NotificationReceiptTransport(state: "FAILED")
        do {
            try await ChatSendPipeline().sendSavedChatTurn(turnId: "turn-a",
                preflightPayload: payloads.preflight, outboundPayload: payloads.outbound,
                transport: failed, waitForInferenceReceipt: true)
            XCTFail("A saved turn whose inference failed must not become a successful notification reply")
        } catch {
            XCTAssertEqual(failed.waitedTypes, ["chat_turn_preflight_ack"])
            XCTAssertTrue(failed.bareSentTypes.isEmpty)
        }

        let rejected = NotificationReceiptTransport(state: "LEGACY")
        let send = Task { @MainActor in
            try await ChatSendPipeline().sendSavedChatTurn(turnId: "turn-a",
                preflightPayload: payloads.preflight, outboundPayload: payloads.outbound,
                transport: rejected, waitForInferenceReceipt: true)
        }
        for _ in 0..<1_000 where rejected.receiptPredicate == nil { await Task.yield() }
        XCTAssertNotNil(rejected.receiptPredicate)
        rejected.deliver(["code": "ai_dispatch_failed", "chat_id": "chat-a", "user_message_id": "message-a"])
        do {
            try await send.value
            XCTFail("A correlated admission failure must preserve the queued reply")
        } catch NotificationReceiptTransport.ReceiptError.rejected {
            // The transport's server error must propagate to the queue owner.
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.action.routing-coherent,apple-notifications.delivery.idempotent-visible
    func testNotificationReplyLedgerSurvivesRestartAndSeparatesAccountsAndServers() throws {
        var ledger = NotificationReplyLedger()
        let first = NotificationReplyRequest(id: "notification-a", chatId: "old-chat", content: "Which city?",
            accountId: "account-a", serverURL: "https://dev.example.test")
        ledger.enqueue(first)
        ledger.enqueue(first)
        ledger.enqueue(NotificationReplyRequest(id: "notification-b", chatId: "another-chat", content: "Reply B",
            accountId: "account-b", serverURL: first.serverURL))
        ledger.enqueue(NotificationReplyRequest(id: "notification-c", chatId: first.chatId, content: "Reply C",
            accountId: first.accountId, serverURL: "https://other.example.test"))
        var restored = try JSONDecoder().decode(NotificationReplyLedger.self, from: JSONEncoder().encode(ledger))
        XCTAssertEqual(restored.requests(accountId: first.accountId, serverURL: first.serverURL), [first])
        restored.complete(first.id)
        restored.enqueue(first)
        XCTAssertTrue(restored.requests(accountId: first.accountId, serverURL: first.serverURL).isEmpty,
            "A repeated system callback must not send an already completed reply twice")
        XCTAssertEqual(restored.pending.count, 2)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.action.routing-coherent,apple-notifications.delivery.idempotent-visible
    func testNotificationReplyPersistsExactPreparedTurnForRetry() throws {
        let inference: [String: Any] = ["turn_id": "turn-a", "chat_id": "old-chat", "message": ["message_id": "message-a", "content": "Which city?"]]
        let preflight: [String: Any] = ["turn_id": "turn-a", "expected_messages_v": 8, "inference_request": inference]
        var request = NotificationReplyRequest(id: "notification-a", chatId: "old-chat", content: "Which city?",
            accountId: "account-a", serverURL: "https://dev.example.test")
        request.preparedTurn = try NotificationPreparedTurn(turnId: "turn-a", preflight: preflight, outbound: inference)
        let restored = try JSONDecoder().decode(NotificationReplyRequest.self, from: JSONEncoder().encode(request))
        let prepared = try XCTUnwrap(restored.preparedTurn)
        let payloads = try prepared.payloads()
        XCTAssertEqual(prepared.turnId, "turn-a")
        XCTAssertTrue(NSDictionary(dictionary: payloads.preflight).isEqual(to: preflight))
        XCTAssertTrue(NSDictionary(dictionary: payloads.outbound).isEqual(to: inference),
            "Reconnect must replay the committed message identity and history, not rebuild a new turn")
    }

    // contract-test: supporting surface=gui.apple assertions=pii.surface.semantic-parity
    func testDetectorRespectsWebSettingsAndCustomEntries() {
        let text = "Email alice@example.com, call +49 170 1234567, or send mail to 221B Baker Street in London."
        let options = PIIDetectionOptions(
            disabledCategories: ["phone_numbers"],
            personalDataEntries: [
                PersonalDataForDetection(
                    id: "home-address",
                    textToHide: "221B Baker Street",
                    replaceWith: "[HOME_ADDRESS]",
                    additionalTexts: ["London"],
                    type: .address
                )
            ]
        )

        let matches = PIIDetector.detect(in: text, options: options)

        XCTAssertTrue(matches.contains { $0.type == .email && $0.value == "alice@example.com" })
        XCTAssertFalse(matches.contains { $0.type == .phone }, "Disabled phone_numbers category must not detect phone PII")
        XCTAssertTrue(matches.contains { $0.type == .address && $0.value == "221B Baker Street" })
        XCTAssertTrue(matches.contains { $0.type == .address && $0.value == "London" })
        XCTAssertEqual(matches.first { $0.value == "221B Baker Street" }?.placeholder, "[HOME_ADDRESS]")
    }

    // contract-test: supporting surface=gui.apple assertions=pii.surface.semantic-parity
    func testPrivacySettingsStoreProducesDetectorOptionsForComposer() {
        let store = PIIPrivacySettingsStore(settings: PIIPrivacySettings(
            masterEnabled: true,
            disabledCategories: ["email_addresses"],
            personalDataEntries: [
                PersonalDataForDetection(
                    id: "safe-word",
                    textToHide: "Project Orchid",
                    replaceWith: "[PROJECT]",
                    type: .genericSecret
                )
            ]
        ))

        let matches = PIIDetector.detect(
            in: "Email alice@example.com about Project Orchid.",
            options: store.detectionOptions()
        )

        XCTAssertFalse(matches.contains { $0.type == .email })
        XCTAssertTrue(matches.contains { $0.value == "Project Orchid" && $0.placeholder == "[PROJECT]" })

        store.update(PIIPrivacySettings(
            masterEnabled: false,
            disabledCategories: [],
            personalDataEntries: [
                PersonalDataForDetection(
                    id: "safe-word",
                    textToHide: "Project Orchid",
                    replaceWith: "[PROJECT]",
                    type: .genericSecret
                )
            ]
        ))

        XCTAssertTrue(PIIDetector.detect(
            in: "Email alice@example.com about Project Orchid.",
            options: store.detectionOptions()
        ).isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=pii.surface.semantic-parity
    func testApplePrivacySettingsStateProjectsWebEncryptedEntriesToDetectorSettings() {
        let now = 1_780_000_000
        let state = ApplePrivacySettingsState(
            detectionSettings: ApplePIIDetectionSettings(
                masterEnabled: true,
                categories: [
                    "email_addresses": false,
                    "phone_numbers": true,
                ]
            ),
            entries: [
                ApplePrivacyPersonalDataEntry(
                    id: "project-entry",
                    type: .custom,
                    title: "Project",
                    textToHide: "Project Orchid",
                    replaceWith: "PROJECT",
                    enabled: true,
                    addressLines: nil,
                    createdAt: now,
                    updatedAt: now
                ),
                ApplePrivacyPersonalDataEntry(
                    id: "disabled-entry",
                    type: .custom,
                    title: "Disabled",
                    textToHide: "Do Not Hide",
                    replaceWith: "DISABLED",
                    enabled: false,
                    addressLines: nil,
                    createdAt: now,
                    updatedAt: now
                ),
            ]
        )

        let settings = state.detectorSettings
        let matches = PIIDetector.detect(
            in: "Email alice@example.com about Project Orchid and Do Not Hide.",
            options: settings.detectionOptions
        )

        XCTAssertTrue(settings.disabledCategories.contains("email_addresses"))
        XCTAssertFalse(matches.contains { $0.type == .email })
        XCTAssertTrue(matches.contains { $0.value == "Project Orchid" && $0.placeholder == "[PROJECT]" })
        XCTAssertFalse(matches.contains { $0.value == "Do Not Hide" })
    }

    // contract-test: supporting surface=gui.apple assertions=pii.surface.semantic-parity
    func testForegroundPIIRedactionKeepsExcludedFalsePositiveAndCreatesMappings() {
        let text = "Draft from max@posteo.de to sarah@proton.com. Call +49 170 1234567."
        let matches = PIIDetector.detect(in: text)
        let excluded = Set(matches.filter { $0.value == "max@posteo.de" }.map(\.id))

        let result = PIIDetector.redactionResult(in: text, matches: matches, excludedIds: excluded)

        XCTAssertTrue(result.redactedText.contains("max@posteo.de"), "Excluded PII should stay original")
        XCTAssertFalse(result.redactedText.contains("sarah@proton.com"))
        XCTAssertFalse(result.redactedText.contains("+49 170 1234567"))
        XCTAssertTrue(result.redactedText.contains("[EMAIL_"))
        XCTAssertTrue(result.redactedText.contains("[PHONE_"))
        XCTAssertEqual(result.mappings.count, 2)
        XCTAssertFalse(result.mappings.contains { $0.original == "max@posteo.de" })
        XCTAssertTrue(result.mappings.contains { $0.original == "sarah@proton.com" && $0.type == "EMAIL" })
    }

    // contract-test: supporting surface=gui.apple assertions=pii.surface.semantic-parity
    func testSendTimeRedactionUsesCurrentPrivacySettingsInsteadOfCachedMatches() {
        let text = "Email alice@example.com about Project Orchid."
        let staleMatches = PIIDetector.detect(in: text)
        XCTAssertTrue(staleMatches.contains { $0.type == .email })

        let currentOptions = PIIDetectionOptions(
            disabledCategories: ["email_addresses", "user_at_hostname"],
            personalDataEntries: [
                PersonalDataForDetection(
                    id: "project",
                    textToHide: "Project Orchid",
                    replaceWith: "[PROJECT]",
                    type: .genericSecret
                )
            ]
        )

        let result = PIIDetector.redactionResult(in: text, options: currentOptions)

        XCTAssertTrue(result.redactedText.contains("alice@example.com"))
        XCTAssertFalse(result.redactedText.contains("Project Orchid"))
        XCTAssertTrue(result.redactedText.contains("[PROJECT]"))
        XCTAssertEqual(result.mappings.map(\.original), ["Project Orchid"])
    }

    // contract-test: supporting surface=gui.apple assertions=pii.surface.semantic-parity
    func testPIIRestoreUsesMappingsForUserAndAssistantPlaceholders() {
        let mappings = [
            PIIMapping(placeholder: "[EMAIL_1_com]", original: "alice@example.com", type: "EMAIL"),
            PIIMapping(placeholder: "[EMAIL_1_com_EXTRA]", original: "other@example.com", type: "EMAIL"),
            PIIMapping(placeholder: "[PROJECT]", original: "Project Orchid", type: "GENERIC_SECRET"),
        ]

        let restored = PIIDetector.restorePII(
            in: "Send [EMAIL_1_com] the [PROJECT] update. Keep [EMAIL_1_com_EXTRA] separate.",
            mappings: mappings
        )

        XCTAssertEqual(
            restored,
            "Send alice@example.com the Project Orchid update. Keep other@example.com separate."
        )
    }

    // contract-test: supporting surface=gui.apple assertions=pii.surface.semantic-parity
    func testTextAttachmentEmbedCarriesRedactedContentAndRestoresThroughMappings() throws {
        let mappings = [
            PIIMapping(placeholder: "[EMAIL_1_com]", original: "alice@example.com", type: "EMAIL")
        ]
        let upload = UploadFileResponse(
            embedId: "text-embed-1",
            filename: "notes.md",
            contentType: "text/markdown",
            contentHash: "hash-1",
            files: [
                "original": UploadedFileVariant(
                    s3Key: "uploads/notes.md",
                    sizeBytes: 44,
                    width: nil,
                    height: nil,
                    format: "md"
                )
            ],
            s3BaseUrl: "https://example.invalid/files",
            aesKey: "aes-key",
            aesNonce: "aes-nonce",
            vaultWrappedAesKey: "wrapped-key",
            pageCount: nil,
            deduplicated: true
        )

        let embed = ComposerPendingEmbed.from(
            upload: upload,
            localData: Data("Contact [EMAIL_1_com] about launch".utf8),
            transcription: nil,
            duration: nil,
            piiMappings: mappings,
            textContent: "Contact [EMAIL_1_com] about launch"
        )

        XCTAssertEqual(embed.piiMappings, mappings)
        let payload = try XCTUnwrap(embed.serverPayload)
        let payloadContent = try XCTUnwrap(payload["content"] as? String)
        XCTAssertFalse(payloadContent.contains("alice@example.com"))
        XCTAssertTrue(payloadContent.contains("[EMAIL_1_com]"))
        XCTAssertEqual(embed.record.rawData?["content"]?.value as? String, "Contact [EMAIL_1_com] about launch")

        let restored = PIIDetector.restorePII(in: embed.record, mappings: mappings)
        XCTAssertEqual(restored.rawData?["content"]?.value as? String, "Contact alice@example.com about launch")
    }

    // contract-test: supporting surface=gui.apple assertions=pii.surface.semantic-parity
    func testComposerAttachmentMappingsMergeWithForegroundTextMappings() {
        let pipeline = ChatSendPipeline()
        let textMapping = PIIMapping(placeholder: "[PHONE_1_567]", original: "+49 170 1234567", type: "PHONE")
        let attachmentMapping = PIIMapping(placeholder: "[EMAIL_1_com]", original: "alice@example.com", type: "EMAIL")
        let embed = ComposerPendingEmbed.from(
            upload: UploadFileResponse(
                embedId: "text-embed-1",
                filename: "notes.md",
                contentType: "text/markdown",
                contentHash: nil,
                files: [
                    "original": UploadedFileVariant(
                        s3Key: "uploads/notes.md",
                        sizeBytes: 26,
                        width: nil,
                        height: nil,
                        format: "md"
                    )
                ],
                s3BaseUrl: "https://example.invalid/files",
                aesKey: "aes-key",
                aesNonce: "aes-nonce",
                vaultWrappedAesKey: "wrapped-key",
                pageCount: nil,
                deduplicated: true
            ),
            localData: Data("Email [EMAIL_1_com]".utf8),
            transcription: nil,
            duration: nil,
            piiMappings: [attachmentMapping],
            textContent: "Email [EMAIL_1_com]"
        )

        let merged = pipeline.combinedPIIMappings(
            textMappings: [textMapping],
            composerEmbeds: [embed]
        )

        XCTAssertEqual(merged, [textMapping, attachmentMapping])
    }

    // contract-test: supporting surface=gui.apple assertions=pii.surface.semantic-parity
    func testKnownPIIRewriteUsesPriorMappingsBeforeSend() {
        let pipeline = ChatSendPipeline()
        let priorMappings = [
            PIIMapping(placeholder: "[EMAIL_1_com]", original: "alice@example.com", type: "EMAIL"),
            PIIMapping(placeholder: "[MERCHANT_STREAMING_001]", original: "Spotify", type: "MERCHANT_STREAMING"),
        ]
        let previous = Self.userMessage(id: "message-1", mappings: priorMappings)

        let result = pipeline.contentAndMappingsForSend(
            content: "Email alice@example.com and summarize Spotify spend.",
            existingMessages: [previous]
        )

        XCTAssertEqual(result.content, "Email [EMAIL_1_com] and summarize [MERCHANT_STREAMING_001] spend.")
        XCTAssertEqual(result.piiMappings, priorMappings)
    }

    // contract-test: supporting surface=gui.apple assertions=pii.surface.semantic-parity
    func testKnownPIIRewritePrefersLongestOriginalAndDedupesMappings() {
        let pipeline = ChatSendPipeline()
        let short = PIIMapping(placeholder: "[MERCHANT_SOFTWARE_001]", original: "ACME", type: "MERCHANT_SOFTWARE")
        let long = PIIMapping(placeholder: "[MERCHANT_SOFTWARE_002]", original: "ACME GmbH", type: "MERCHANT_SOFTWARE")
        let previous = Self.userMessage(id: "message-1", mappings: [short, long])

        let result = pipeline.contentAndMappingsForSend(
            content: "Compare ACME GmbH with ACME GmbH.",
            existingMessages: [previous]
        )

        XCTAssertEqual(result.content, "Compare [MERCHANT_SOFTWARE_002] with [MERCHANT_SOFTWARE_002].")
        XCTAssertEqual(result.piiMappings, [long])
    }

    // contract-test: supporting surface=gui.apple assertions=pii.surface.semantic-parity
    func testKnownPIIRewriteRespectsCurrentSendExclusions() {
        let pipeline = ChatSendPipeline()
        let priorMapping = PIIMapping(placeholder: "[EMAIL_1_com]", original: "alice@example.com", type: "EMAIL")
        let currentMapping = PIIMapping(placeholder: "[PHONE_1_567]", original: "+49 170 1234567", type: "PHONE")
        let previous = Self.userMessage(id: "message-1", mappings: [priorMapping])

        let result = pipeline.contentAndMappingsForSend(
            content: "Keep alice@example.com visible but redact +49 170 1234567.",
            existingMessages: [previous],
            piiMappings: [currentMapping],
            excludedPIIOriginals: ["alice@example.com"]
        )

        XCTAssertEqual(result.content, "Keep alice@example.com visible but redact +49 170 1234567.")
        XCTAssertEqual(result.piiMappings, [currentMapping])
    }

    // contract-test: supporting surface=gui.apple assertions=pii.surface.semantic-parity
    func testKnownPIIRewriteProtectsEmbedReferenceBlocks() {
        let mapping = PIIMapping(placeholder: "[EMAIL_1_com]", original: "alice@example.com", type: "EMAIL")
        let content = """
        Ask alice@example.com about this embed.

        ```json
        {"type":"docs-doc","embed_id":"alice@example.com"}
        ```
        """

        let result = PIIDetector.rewriteKnownPIIPlaceholders(in: content, mappings: [mapping])

        XCTAssertTrue(result.text.contains("Ask [EMAIL_1_com] about this embed."))
        XCTAssertTrue(result.text.contains("\"embed_id\":\"alice@example.com\""))
        XCTAssertEqual(result.appliedMappings, [mapping])
    }

    // contract-test: supporting surface=gui.apple assertions=pii.surface.semantic-parity
    func testComposerDocumentRewriteUsesCurrentAttachmentMappingsBeforeDetection() throws {
        let attachmentMapping = PIIMapping(placeholder: "[EMAIL_1_com]", original: "alice@example.com", type: "EMAIL")
        let document = ComposerDocumentV1(
            version: 1,
            nodes: [
                .text(id: "text-1", source: "Summarize alice@example.com from "),
                .embed(
                    id: "embed-1",
                    embedType: "docs-doc",
                    canonicalSource: "```json\n{\"embed_id\":\"embed-1\"}\n```",
                    referenceOnly: true,
                    display: .init(title: "Private doc", mediaKind: "docs-doc")
                )
            ]
        )

        let rewrite = ComposerPIIDecorations.rewriteKnownPIIPlaceholders(
            document: document,
            mappings: [attachmentMapping]
        )
        let redaction = ComposerPIIDecorations.redactedDocument(document: rewrite.document)
        let markdown = try ComposerMarkdownAdapter.serialize(redaction.document)
        let mappings = PIIDetector.mergePIIMappings(rewrite.appliedMappings + redaction.mappings)

        XCTAssertTrue(markdown.contains("Summarize [EMAIL_1_com] from"))
        XCTAssertFalse(markdown.contains("alice@example.com"))
        XCTAssertEqual(mappings, [attachmentMapping])
    }

    // contract-test: supporting surface=gui.apple assertions=pii.surface.semantic-parity
    func testPrivacyFilterTokenDecoderBuildsExactSpansFromBIOESLabels() {
        let text = "Tell Ada Lovelace the token is hunter2."
        let nsText = text as NSString
        let predictions = [
            PrivacyFilterTokenPrediction(label: "B-private_person", range: nsText.range(of: "Ada"), score: 0.9),
            PrivacyFilterTokenPrediction(label: "E-private_person", range: nsText.range(of: "Lovelace"), score: 0.8),
            PrivacyFilterTokenPrediction(label: "O", range: nsText.range(of: "the"), score: 0.99),
            PrivacyFilterTokenPrediction(label: "S-secret", range: nsText.range(of: "hunter2"), score: 0.95),
        ]

        let spans = PrivacyFilterTokenSpanDecoder.decode(predictions, in: text)

        XCTAssertEqual(spans.count, 2)
        XCTAssertEqual(spans[0].label, .privatePerson)
        XCTAssertEqual(nsText.substring(with: spans[0].range), "Ada Lovelace")
        XCTAssertEqual(spans[0].score, 0.85, accuracy: 0.0001)
        XCTAssertEqual(spans[1].label, .secret)
        XCTAssertEqual(nsText.substring(with: spans[1].range), "hunter2")
    }

    // contract-test: supporting surface=gui.apple assertions=pii.surface.semantic-parity
    func testPrivacyFilterNativeDetectorRespectsSettingsScoreAndRanges() async throws {
        let text = "Email alice@example.com, account 42424242, and keep Project Orchid private."
        let nsText = text as NSString
        let detector = PrivacyFilterNativeDetector(
            runner: MockPrivacyFilterModelRunner(spans: [
                PrivacyFilterModelSpan(label: .privateEmail, range: nsText.range(of: "alice@example.com"), score: 0.99),
                PrivacyFilterModelSpan(label: .accountNumber, range: nsText.range(of: "42424242"), score: 0.99),
                PrivacyFilterModelSpan(label: .secret, range: nsText.range(of: "Project Orchid"), score: 0.99),
                PrivacyFilterModelSpan(label: .privatePerson, range: nsText.range(of: "private"), score: 0.2),
                PrivacyFilterModelSpan(label: .privateAddress, range: NSRange(location: nsText.length + 1, length: 5), score: 0.99),
            ]),
            minimumScore: 0.5
        )

        let options = PIIDetectionOptions(disabledCategories: ["credit_card_numbers", "email_addresses"])
        let spans = try await detector.detectModelSpans(in: text, options: options)

        XCTAssertEqual(spans.map(\.label), [.secret])
        XCTAssertEqual(nsText.substring(with: try XCTUnwrap(spans.first?.range)), "Project Orchid")

        let matches = try await detector.detectedMatches(in: text, options: options)
        XCTAssertEqual(matches.map(\.type), [.genericSecret])
        XCTAssertEqual(matches.first?.value, "Project Orchid")
    }

    // contract-test: supporting surface=gui.apple assertions=pii.surface.semantic-parity
    func testPrivacyFilterNativeDetectorKeepsRegexPrecedenceWhenMerging() async throws {
        let text = "Email alice@example.com about Project Orchid."
        let nsText = text as NSString
        let detector = PrivacyFilterNativeDetector(
            runner: MockPrivacyFilterModelRunner(spans: [
                PrivacyFilterModelSpan(label: .privateEmail, range: nsText.range(of: "alice@example.com"), score: 0.99),
                PrivacyFilterModelSpan(label: .secret, range: nsText.range(of: "Project Orchid"), score: 0.98),
                PrivacyFilterModelSpan(label: .privatePerson, range: nsText.range(of: "Orchid"), score: 0.97),
            ])
        )

        let merged = try await detector.detectedMatches(in: text)

        XCTAssertEqual(merged.count, 2)
        XCTAssertEqual(merged[0].type, .email)
        XCTAssertEqual(merged[0].placeholder, "[EMAIL_1_com]")
        XCTAssertEqual(nsText.substring(with: merged[0].range), "alice@example.com")
        let expectedModelId = "pii-model-secret-\(nsText.range(of: "Project Orchid").location)"
        XCTAssertEqual(merged[1].id, expectedModelId)
        XCTAssertEqual(merged[1].type, .genericSecret)
        XCTAssertEqual(merged[1].placeholder, "[SECRET_1_hid]")
        XCTAssertEqual(nsText.substring(with: merged[1].range), "Project Orchid")

        let redaction = PIIDetector.redactionResult(in: text, matches: merged)
        XCTAssertFalse(redaction.redactedText.contains("alice@example.com"))
        XCTAssertFalse(redaction.redactedText.contains("Project Orchid"))
        XCTAssertTrue(redaction.mappings.contains { $0.original == "Project Orchid" && $0.type == "GENERIC_SECRET" })
    }

    // contract-test: supporting surface=gui.apple assertions=pii.surface.semantic-parity
    func testPrivacyFilterNativeDetectorDoesNotLoadModelForEmptyInput() async throws {
        let detector = PrivacyFilterNativeDetector(runner: ThrowingPrivacyFilterModelRunner())

        let spans = try await detector.detectModelSpans(in: "   \n")

        XCTAssertTrue(spans.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=pii.surface.semantic-parity
    func testEnhancedPIIFallsBackToRegexWhenModelUnavailable() async {
        let text = "Email alice@example.com before launch."
        let detector = EnhancedPIIDetector(modelDetector: nil)

        let result = await detector.detect(in: text)

        XCTAssertEqual(result.mode, .regexOnly)
        XCTAssertTrue(result.matches.contains { $0.type == .email && $0.value == "alice@example.com" })
        XCTAssertFalse(result.sanitizedStatus.contains("alice@example.com"))
    }

    // contract-test: supporting surface=gui.apple assertions=pii.surface.semantic-parity
    func testEnhancedPIIComposerSuggestionBackoff() {
        var policy = EnhancedPIIRecommendationPolicy()
        let matches = PIIDetector.detect(in: "Email alice@example.com")
        let now = Date(timeIntervalSince1970: 1_800_000_000)

        XCTAssertFalse(policy.shouldRecommend(regexMatches: [], modelStatus: .notDownloaded, now: now))
        XCTAssertTrue(policy.shouldRecommend(regexMatches: matches, modelStatus: .notDownloaded, now: now))
        XCTAssertFalse(policy.shouldRecommend(regexMatches: matches, modelStatus: .ready(version: "1", sizeBytes: 10), now: now))

        policy.dismiss(now: now)
        XCTAssertFalse(policy.shouldRecommend(regexMatches: matches, modelStatus: .notDownloaded, now: now.addingTimeInterval(60)))
        XCTAssertTrue(policy.shouldRecommend(regexMatches: matches, modelStatus: .notDownloaded, now: now.addingTimeInterval(31 * 24 * 60 * 60)))
    }

    // contract-test: supporting surface=gui.apple assertions=pii.surface.semantic-parity
    func testEnhancedPIIModelSpansMergeIntoMappings() async {
        let text = "Email alice@example.com about Project Orchid."
        let nsText = text as NSString
        let detector = EnhancedPIIDetector(
            modelDetector: PrivacyFilterNativeDetector(
                runner: MockPrivacyFilterModelRunner(spans: [
                    PrivacyFilterModelSpan(label: .privateEmail, range: nsText.range(of: "alice@example.com"), score: 0.99),
                    PrivacyFilterModelSpan(label: .secret, range: nsText.range(of: "Project Orchid"), score: 0.98),
                    PrivacyFilterModelSpan(label: .privatePerson, range: nsText.range(of: "Orchid"), score: 0.97),
                ])
            )
        )

        let result = await detector.detect(in: text)

        XCTAssertEqual(result.mode, .enhanced)
        XCTAssertEqual(result.matches.count, 2)
        XCTAssertEqual(result.matches[0].type, .email)
        XCTAssertEqual(result.matches[1].type, .genericSecret)
        XCTAssertEqual(result.matches[1].value, "Project Orchid")
        let redaction = PIIDetector.redactionResult(in: text, matches: result.matches)
        XCTAssertFalse(redaction.redactedText.contains("Project Orchid"))
        XCTAssertTrue(redaction.mappings.contains { $0.original == "Project Orchid" && $0.type == "GENERIC_SECRET" })
    }

    // contract-test: supporting surface=gui.apple assertions=pii.surface.semantic-parity
    func testEnhancedPIIModelTimeoutFallsBackToRegex() async {
        let text = "Email alice@example.com about Project Orchid."
        let nsText = text as NSString
        let detector = EnhancedPIIDetector(
            modelDetector: PrivacyFilterNativeDetector(
                runner: SlowPrivacyFilterModelRunner(
                    delayNanoseconds: 100_000_000,
                    spans: [PrivacyFilterModelSpan(label: .secret, range: nsText.range(of: "Project Orchid"), score: 0.99)]
                )
            ),
            modelTimeoutNanoseconds: 1_000_000
        )

        let result = await detector.detect(in: text)

        XCTAssertEqual(result.mode, .regexFallback(reason: .timeout))
        XCTAssertTrue(result.matches.contains { $0.type == .email })
        XCTAssertFalse(result.matches.contains { $0.value == "Project Orchid" })
        XCTAssertFalse(result.sanitizedStatus.contains("Project Orchid"))
        XCTAssertFalse(result.sanitizedStatus.contains("alice@example.com"))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    func testCompletedAssistantVersionAdvancesPastUserMessageVersion() {
        let pipeline = ChatSendPipeline()

        XCTAssertEqual(
            pipeline.completedAssistantMessagesVersion(
                currentMessagesV: 1,
                localMessageCountAfterAppendingAssistant: 2
            ),
            2
        )
        XCTAssertEqual(
            pipeline.completedAssistantMessagesVersion(
                currentMessagesV: 5,
                localMessageCountAfterAppendingAssistant: 6
            ),
            6
        )
        XCTAssertEqual(
            pipeline.completedAssistantMessagesVersion(
                currentMessagesV: 1,
                localMessageCountAfterAppendingAssistant: 6
            ),
            6
        )
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    func testAssistantCompletionPayloadContainsOnlyEncryptedContentAndAdvancedVersion() {
        let pipeline = ChatSendPipeline()
        let createdAt = 1_780_000_000
        let message = Message(
            id: "assistant-1",
            chatId: "chat-1",
            role: .assistant,
            content: "Plaintext must stay local",
            encryptedContent: "encrypted-content",
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: nil,
            appId: "general_knowledge",
            isStreaming: false,
            embedRefs: nil,
            modelName: "test-model"
        )

        let payload = pipeline.assistantCompletionPayload(
            for: message,
            userMessageId: "user-1",
            encryptedContent: "encrypted-content",
            encryptedCategory: "encrypted-category",
            encryptedModelName: "encrypted-model",
            createdAtUnix: createdAt,
            currentMessagesV: 1,
            localMessageCountAfterAppendingAssistant: 2
        )

        XCTAssertEqual(payload["chat_id"] as? String, "chat-1")
        let messagePayload = payload["message"] as? [String: Any]
        XCTAssertEqual(messagePayload?["message_id"] as? String, "assistant-1")
        XCTAssertEqual(messagePayload?["encrypted_content"] as? String, "encrypted-content")
        XCTAssertNil(messagePayload?["content"])
        XCTAssertNil(messagePayload?["plaintext"])
        let versions = payload["versions"] as? [String: Int]
        XCTAssertEqual(versions?["messages_v"], 2)
        XCTAssertEqual(versions?["last_edited_overall_timestamp"], createdAt)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    func testAssistantCompletionPersistenceUsesCanonicalEmbedMarkdown() {
        let canonicalContent = """
        Here is the result.

        ```json
        {"type":"app_skill_use","embed_id":"embed-1","app_id":"web","skill_id":"search"}
        ```
        """
        let displayMessage = Message(
            id: "assistant-embed-1",
            chatId: "chat-1",
            role: .assistant,
            content: canonicalContent,
            encryptedContent: nil,
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: nil,
            appId: "web",
            isStreaming: false,
            embedRefs: nil,
            modelName: "test-model"
        )
        let attached = PublicChatContent.attachEmbeds(to: [displayMessage]).messages.first

        XCTAssertTrue(attached?.content?.contains("[[embed:embed-1]]") == true)
        XCTAssertEqual(
            ChatSendPipeline.canonicalAssistantContentForPersistence(
                displayContent: attached?.content,
                canonicalStreamContent: canonicalContent
            ),
            canonicalContent
        )
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testNativeAttachEmbedsCreatesUserAudioPreviewRefsFromCanonicalJson() throws {
        let content = """
        ```json
        {"type":"audio-recording","embed_id":"audio-embed-1"}
        ```
        """
        let message = Message(
            id: "user-audio-1",
            chatId: "chat-1",
            role: .user,
            content: content,
            encryptedContent: nil,
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: nil,
            appId: nil,
            isStreaming: false,
            embedRefs: nil
        )

        let attached = PublicChatContent.attachEmbeds(to: [message])
        let updated = try XCTUnwrap(attached.messages.first)

        XCTAssertEqual(updated.content, "[[embed:audio-embed-1]]")
        XCTAssertEqual(updated.embedRefs?.map(\.id), ["audio-embed-1"])
        XCTAssertEqual(attached.records["audio-embed-1"]?.type, "audio-recording")
        XCTAssertEqual(updated.renderDocumentForDisplay?.blocks.first?.kind, .embedGroup)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testNativeAttachEmbedsPreservesExistingInlineEmbedMarkersAsRefs() throws {
        let message = Message(
            id: "assistant-inline-1",
            chatId: "chat-1",
            role: .assistant,
            content: "[[embed:embed-inline]]\n\n```json\n{\"type\":\"web-website\",\"embed_id\":\"embed-json\"}\n```\n\n[!](embed:embed-large)",
            encryptedContent: nil,
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: nil,
            appId: "web",
            isStreaming: false,
            embedRefs: nil
        )

        let updated = try XCTUnwrap(PublicChatContent.attachEmbeds(to: [message]).messages.first)

        XCTAssertEqual(updated.embedRefs?.map(\.id), ["embed-inline", "embed-json", "embed-large"])
        XCTAssertEqual(updated.content?.contains("[[embedref:embed-large]]"), true)
        XCTAssertEqual(updated.content?.contains("[[embed:embed-inline]]"), true)
        let blocks = try XCTUnwrap(updated.renderDocumentForDisplay?.blocks)
        XCTAssertEqual(blocks.map(\.kind), [.embedGroup, .embedGroup])
        XCTAssertEqual(blocks.flatMap(\.embedReferences).map(\.id), ["embed-inline", "embed-json", "embed-large"])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.completion.pending-delivery
    func testPendingAssistantResponseQueueStoresOnlyIdsAndDedupes() throws {
        let suiteName = "ChatSendPipelineParityTests"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
        defaults.removePersistentDomain(forName: suiteName)
        let queue = PendingAssistantResponseQueue(defaults: defaults, storageKey: "pending-test")

        queue.add(messageId: "assistant-1", chatId: "chat-1")
        queue.add(messageId: "assistant-1", chatId: "chat-1")
        queue.add(messageId: "assistant-2", chatId: "chat-1")

        XCTAssertEqual(queue.all(), [
            PendingAssistantResponseQueue.Entry(messageId: "assistant-1", chatId: "chat-1"),
            PendingAssistantResponseQueue.Entry(messageId: "assistant-2", chatId: "chat-1")
        ])
        let storedJSON = defaults.data(forKey: "pending-test").flatMap { String(data: $0, encoding: .utf8) } ?? ""
        XCTAssertFalse(storedJSON.contains("Plaintext"))

        queue.remove(messageId: "assistant-1")
        XCTAssertEqual(queue.all(), [
            PendingAssistantResponseQueue.Entry(messageId: "assistant-2", chatId: "chat-1")
        ])
        queue.clear()
    }

    // contract-test: supporting surface=gui.apple assertions=chats.sync.key-gated-recovery
    func testCachedKeyWithProvidedWrappedKeyRequiresValidation() {
        let pipeline = ChatSendPipeline()

        XCTAssertTrue(pipeline.requiresCachedChatKeyValidation(cachedKeyExists: true, encryptedChatKey: "wrapped-key"))
        XCTAssertFalse(pipeline.requiresCachedChatKeyValidation(cachedKeyExists: true, encryptedChatKey: nil))
        XCTAssertFalse(pipeline.requiresCachedChatKeyValidation(cachedKeyExists: false, encryptedChatKey: "wrapped-key"))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.completion.pending-delivery
    func testPendingRetryInfersPrecedingUserMessageId() {
        let pipeline = ChatSendPipeline()
        let userMessage = Message(
            id: "user-1",
            chatId: "chat-1",
            role: .user,
            content: "User prompt",
            encryptedContent: "encrypted-user",
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: nil,
            appId: nil,
            isStreaming: false,
            embedRefs: nil
        )
        let assistantMessage = Message(
            id: "assistant-1",
            chatId: "chat-1",
            role: .assistant,
            content: "Assistant response",
            encryptedContent: "encrypted-assistant",
            createdAt: "2026-01-01T00:00:01Z",
            updatedAt: nil,
            appId: nil,
            isStreaming: false,
            embedRefs: nil
        )

        XCTAssertEqual(
            pipeline.inferredUserMessageId(before: assistantMessage, in: [assistantMessage, userMessage]),
            "user-1"
        )
    }

    // contract-test: supporting surface=gui.apple assertions=chats.message.identity-idempotent
    func testEncryptedUserStorageClaimIsSharedAcrossPipelineInstancesAndRetryableAfterFailure() {
        let messageId = "claim-\(UUID().uuidString)"
        let firstPipeline = ChatSendPipeline()
        let secondPipeline = ChatSendPipeline()

        XCTAssertTrue(firstPipeline.claimEncryptedUserStorage(messageId: messageId))
        XCTAssertFalse(secondPipeline.claimEncryptedUserStorage(messageId: messageId))

        firstPipeline.releaseEncryptedUserStorage(messageId: messageId)
        XCTAssertTrue(secondPipeline.claimEncryptedUserStorage(messageId: messageId))
        secondPipeline.releaseEncryptedUserStorage(messageId: messageId)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    func testIncognitoPayloadUsesRequestScopedHistoryWithoutEncryptedStorageFields() {
        let pipeline = ChatSendPipeline()
        let chat = Chat(
            id: IncognitoChatSession.makeChatId(),
            title: nil,
            lastMessageAt: nil,
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: nil,
            isArchived: false,
            isPinned: false,
            appId: "ai",
            encryptedTitle: nil,
            encryptedChatKey: nil,
            messagesV: 0,
            titleV: 0,
            draftV: 0
        )
        let result = pipeline.makeLocalIncognitoUserMessage(
            content: "Private prompt",
            in: chat,
            existingMessages: []
        )

        let payload = pipeline.incognitoUserMessagePayload(
            chatId: result.chat.id,
            message: result.message,
            messageHistory: [result.message]
        )

        XCTAssertEqual(payload["chat_id"] as? String, result.chat.id)
        XCTAssertEqual(payload["is_incognito"] as? Bool, true)
        XCTAssertNil(payload["encrypted_chat_key"])
        XCTAssertNil(payload["encrypted_embeds"])
        XCTAssertNil(payload["encrypted_pii_mappings"])

        let message = payload["message"] as? [String: Any]
        XCTAssertEqual(message?["content"] as? String, "Private prompt")
        XCTAssertEqual(message?["message_id"] as? String, result.message.id)
        XCTAssertNil(message?["encrypted_content"])

        let history = payload["message_history"] as? [[String: Any]]
        XCTAssertEqual(history?.count, 1)
        XCTAssertEqual(history?.first?["content"] as? String, "Private prompt")
        XCTAssertNil(history?.first?["encrypted_content"])
    }
}

private extension ChatSendPipelineParityTests {
    static func notificationTurnPayloads() -> (preflight: [String: Any], outbound: [String: Any]) {
        let outbound: [String: Any] = ["turn_id": "turn-a", "chat_id": "chat-a",
            "message": ["message_id": "message-a", "content": "Which city?"]]
        return (["turn_id": "turn-a", "inference_request": outbound], outbound)
    }

    static func userMessage(id: String, mappings: [PIIMapping]) -> Message {
        Message(
            id: id,
            chatId: "chat-1",
            role: .user,
            content: "Previous message",
            encryptedContent: nil,
            createdAt: "2026-01-01T00:00:00Z",
            updatedAt: nil,
            appId: nil,
            isStreaming: false,
            embedRefs: nil,
            piiMappings: mappings
        )
    }
}

@MainActor
private final class NotificationReceiptTransport: ChatWebSocketTransport {
    enum ReceiptError: Error { case rejected, unexpectedOperation }
    let state: String
    var waitedTypes: [String] = []
    var bareSentTypes: [String] = []
    var receiptPredicate: (([String: Any]) -> Bool)?
    private var receiptContinuation: CheckedContinuation<WebSocketResponse, Error>?

    init(state: String) { self.state = state }

    func send(_ message: WSOutboundMessage) async throws { bareSentTypes.append(message.type) }

    func sendAndWait(_ message: WSOutboundMessage, responseType: String, timeout: Duration,
                     matching predicate: @escaping ([String: Any]) -> Bool) async throws -> WebSocketResponse {
        waitedTypes.append(responseType)
        if responseType == "chat_turn_preflight_ack" {
            let fields: [String: Any] = ["turn_id": "turn-a", "preflight_id": "preflight-a", "state": state]
            guard message.type == "chat_turn_preflight", predicate(fields) else { throw ReceiptError.unexpectedOperation }
            return WebSocketResponse(fields: fields)
        }
        guard message.type == "chat_message_added", responseType == "ai_task_initiated" else {
            throw ReceiptError.unexpectedOperation
        }
        return try await withCheckedThrowingContinuation { continuation in
            receiptPredicate = predicate
            receiptContinuation = continuation
        }
    }

    func waitForMessage(_ type: String, timeout: Duration,
                        matching predicate: @escaping ([String: Any]) -> Bool) async throws -> WebSocketResponse {
        throw ReceiptError.unexpectedOperation
    }

    func deliver(_ fields: [String: Any]) {
        guard receiptPredicate?(fields) == true, let continuation = receiptContinuation else { return }
        receiptContinuation = nil
        if fields["code"] != nil {
            continuation.resume(throwing: ReceiptError.rejected)
        } else {
            continuation.resume(returning: WebSocketResponse(fields: fields))
        }
    }
}

private struct MockPrivacyFilterModelRunner: PrivacyFilterModelRunning {
    let spans: [PrivacyFilterModelSpan]

    func detectedSpans(in text: String) async throws -> [PrivacyFilterModelSpan] {
        spans
    }
}

private struct ThrowingPrivacyFilterModelRunner: PrivacyFilterModelRunning {
    enum RunnerError: Error {
        case unexpectedlyCalled
    }

    func detectedSpans(in text: String) async throws -> [PrivacyFilterModelSpan] {
        throw RunnerError.unexpectedlyCalled
    }
}

private struct SlowPrivacyFilterModelRunner: PrivacyFilterModelRunning {
    let delayNanoseconds: UInt64
    let spans: [PrivacyFilterModelSpan]

    func detectedSpans(in text: String) async throws -> [PrivacyFilterModelSpan] {
        try await Task.sleep(nanoseconds: delayNanoseconds)
        return spans
    }
}
