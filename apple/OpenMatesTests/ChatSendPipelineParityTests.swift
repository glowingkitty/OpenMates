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

    func testPrivacyFilterNativeDetectorDoesNotLoadModelForEmptyInput() async throws {
        let detector = PrivacyFilterNativeDetector(runner: ThrowingPrivacyFilterModelRunner())

        let spans = try await detector.detectModelSpans(in: "   \n")

        XCTAssertTrue(spans.isEmpty)
    }

    func testEnhancedPIIFallsBackToRegexWhenModelUnavailable() async {
        let text = "Email alice@example.com before launch."
        let detector = EnhancedPIIDetector(modelDetector: nil)

        let result = await detector.detect(in: text)

        XCTAssertEqual(result.mode, .regexOnly)
        XCTAssertTrue(result.matches.contains { $0.type == .email && $0.value == "alice@example.com" })
        XCTAssertFalse(result.sanitizedStatus.contains("alice@example.com"))
    }

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

    func testCachedKeyWithProvidedWrappedKeyRequiresValidation() {
        let pipeline = ChatSendPipeline()

        XCTAssertTrue(pipeline.requiresCachedChatKeyValidation(cachedKeyExists: true, encryptedChatKey: "wrapped-key"))
        XCTAssertFalse(pipeline.requiresCachedChatKeyValidation(cachedKeyExists: true, encryptedChatKey: nil))
        XCTAssertFalse(pipeline.requiresCachedChatKeyValidation(cachedKeyExists: false, encryptedChatKey: "wrapped-key"))
    }

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
