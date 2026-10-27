// Unit coverage for Apple chat-send pipeline parity with web chat storage.
// These tests avoid network calls, credentials, private chat content, and raw
// encryption keys. They guard the deterministic payload and retry contracts that
// make Apple-created chats decryptable from other clients such as OpenMates CLI.
// Keep assertions payload-level so the suite remains deterministic on Linux CI
// orchestration and remote Mac runners.

import XCTest
import CryptoKit
@testable import OpenMates

@MainActor
final class ChatSendPipelineParityTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=message-input.privacy-context,pii.composer.detect-redact-exclude
    func testFreshPersonalSnapshotCompilesAllEncryptedRowsAndFailsClosed() async throws {
        let bodies = [
            "settings-cipher": "{\"memory_documents\":[{\"id\":\"guide\"}]}",
            "preferences-cipher": "{\"masterEnabled\":true,\"categories\":{\"phone_numbers\":false}}",
            "personal-cipher": "{\"enabled\":true,\"textToHide\":\"Synthetic Name\",\"replaceWith\":\"[PERSON]\",\"addressLines\":{\"city\":\"Synthetic City\"}}"
        ]
        let snapshot: [String: Any] = ["encrypted_settings": "settings-cipher", "memories": [
            ["id": "preferences", "app_id": "privacy", "item_type": "pii_detection_settings", "encrypted_item_json": "preferences-cipher"],
            ["id": "entry", "app_id": "privacy", "item_type": "personal_data_entry", "encrypted_item_json": "personal-cipher"]]]
        let compiled = try await NativeCompiledPersonalPrivacy.compile(snapshot) { cipher in
            guard let value = bodies[cipher] else { throw NativePersonalPrivacyError.invalidSnapshot }; return value
        }
        XCTAssertTrue(compiled.settings.masterEnabled)
        XCTAssertEqual(compiled.settings.disabledCategories, ["phone_numbers"])
        XCTAssertEqual(compiled.settings.personalDataEntries.first?.textToHide, "Synthetic Name")
        XCTAssertTrue(compiled.metadataKeys.contains("privacy-personal_data_entry"))
        XCTAssertTrue(compiled.metadataKeys.contains("openmates-memories"), "Legacy account documents use the existing discovery key")
        var malformed = snapshot
        malformed["memories"] = [["id": "missing", "app_id": "privacy", "item_type": "personal_data_entry"]]
        do {
            _ = try await NativeCompiledPersonalPrivacy.compile(malformed) { _ in "{}" }
            XCTFail("Incomplete encrypted snapshots must never become an empty policy")
        } catch { XCTAssertEqual(error as? NativePersonalPrivacyError, .invalidSnapshot) }
        malformed = snapshot; malformed.removeValue(forKey: "encrypted_settings")
        do {
            _ = try await NativeCompiledPersonalPrivacy.compile(malformed) { _ in "{}" }
            XCTFail("Absent settings is not an authoritative null settings snapshot")
        } catch { XCTAssertEqual(error as? NativePersonalPrivacyError, .invalidSnapshot) }
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.send.ownership,chat-queued-followups.editing.stable-revision
    func testSavedAdmissionLeaseSurvivesWaiterCancellationAndSeparatesScopes() async throws {
        let gate = ChatSavedSendAdmissionGate()
        let owner = UUID(), keys = UUID()
        let scope = ChatPreparationScope(account: owner, server: "https://example.invalid", keyGeneration: keys,
            teamID: nil, teamEpoch: 1, socketGeneration: 4)
        let key = ChatSavedSendAdmissionGate.Key(scope: scope, chatID: "chat")
        let reconnected = ChatPreparationScope(account: owner, server: scope.server, keyGeneration: keys,
            teamID: nil, teamEpoch: 1, socketGeneration: 5)
        XCTAssertEqual(key, .init(scope: reconnected, chatID: "chat"), "Reconnect cannot run two optimistic versions of the same saved chat concurrently")
        let first = try await gate.acquire(key)
        let waiting = expectation(description: "second admission starts waiting")
        let second = Task { @MainActor in
            waiting.fulfill()
            return try await gate.acquire(key)
        }
        await fulfillment(of: [waiting], timeout: 1)
        second.cancel()
        do { let lease = try await second.value; lease.release(); XCTFail("Cancelled preparation must not enter admission") }
        catch { XCTAssertTrue(error is CancellationError) }
        // Another chat can admit while the first chat remains leased.
        let other = try await gate.acquire(.init(scope: scope, chatID: "other-chat")); other.release()
        first.release(); first.release()
        let next = try await gate.acquire(key); next.release()
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.privacy-context,message-input.send.ownership
    func testPrivacyExclusionIntentSurvivesReconnectOnlyWithinItsOriginalOwner() {
        let owner = UUID(), key = UUID(), now = Date(timeIntervalSince1970: 1_800_000_000)
        let scope = ChatPreparationScope(account: owner, server: "https://example.invalid", keyGeneration: key,
            teamID: nil, teamEpoch: 1, socketGeneration: 4)
        let intent = NativePersonalPrivacyExclusionIntent(scope: scope, originals: ["visible@example.invalid"], recordedAt: now)
        let reconnected = ChatPreparationScope(account: owner, server: scope.server, keyGeneration: key,
            teamID: nil, teamEpoch: 1, socketGeneration: 5)
        XCTAssertEqual(intent.values(for: reconnected, now: now.addingTimeInterval(30)), ["visible@example.invalid"])
        let otherOwner = ChatPreparationScope(account: UUID(), server: scope.server, keyGeneration: key,
            teamID: nil, teamEpoch: 1, socketGeneration: 5)
        XCTAssertTrue(intent.values(for: otherOwner, now: now).isEmpty)
        let otherTeam = ChatPreparationScope(account: owner, server: scope.server, keyGeneration: key,
            teamID: "team", teamEpoch: 2, socketGeneration: 5)
        XCTAssertTrue(intent.values(for: otherTeam, now: now).isEmpty)
        XCTAssertTrue(intent.values(for: reconnected, now: now.addingTimeInterval(7_200)).isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=chat-queued-followups.admission.synced,chat-queued-followups.editing.stable-revision
    func testQueuedHistoryFieldsDecodeWithRawAndNetworkKeyStrategies() throws {
        let bytes = Data("{\"id\":\"queued\",\"chat_id\":\"chat\",\"role\":\"user\",\"created_at\":1800000000,\"queue_revision\":3,\"queue_mode\":\"steer\",\"queue_dispatch_status\":\"queued\",\"queue_dispatch_mode\":\"steer\",\"status\":\"queued\"}".utf8)
        for converted in [false, true] {
            let decoder = JSONDecoder()
            if converted { decoder.keyDecodingStrategy = .convertFromSnakeCase }
            let row = try decoder.decode(Message.self, from: bytes)
            XCTAssertEqual(ChatQueuedFollowupState.from(row)?.revision, 3)
            XCTAssertEqual(row.queueMode, "steer")
            XCTAssertEqual(row.queueDispatchMode, "steer")
            XCTAssertEqual(row.deliveryStatus, "queued")
        }
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.privacy-context,pii.composer.detect-redact-exclude
    func testFreshPrivacyFilteringPreservesReferencesExclusionsAndPlaceholderOwnership() throws {
        let identity = "12345678-1234-4123-8123-123456789012"
        let text = "```json\n{\"type\":\"image\",\"embed_id\":\"\(identity)\",\"note\":\"new@example.invalid\"}\n```\nKeep visible@example.invalid"
        let first = PIIDetector.detect(in: "old@example.invalid").first!
        let settings = PIIPrivacySettings.enabled
        let result = try NativePersonalPrivacyFilter.apply(text, settings: settings,
            existingMappings: [PIIMapping(placeholder: first.placeholder, original: "old@example.invalid", type: first.type.rawValue)],
            excludedOriginals: ["visible@example.invalid"])
        XCTAssertTrue(result.content.contains(identity), "Only validated reference values are protected")
        XCTAssertFalse(result.content.contains("new@example.invalid"), "A note next to a reference remains subject to privacy")
        XCTAssertTrue(result.content.contains("visible@example.invalid"), "Explicit exclusions remain current-turn choices")
        let occupied = Dictionary(grouping: result.mappings, by: \.placeholder)
        XCTAssertTrue(occupied.values.allSatisfy { Set($0.map(\.original)).count == 1 })
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.privacy-context,message-input.send.ownership
    func testUncertainPrivacyWriteRequiresMatchingFreshPersistedPolicy() async throws {
        let store = PIIPrivacySettingsStore()
        let desired = PIIPrivacySettings(masterEnabled: true, disabledCategories: ["phone_numbers"], personalDataEntries: [])
        let token = store.beginPrivacyMutation(intended: desired)
        store.endPrivacyMutation(token, succeeded: false)
        try await store.waitForPrivacyMutations()
        XCTAssertThrowsError(try store.reconcilePrivacyPersistence(with: .enabled, expectedRevision: store.privacyMutationRevision))
        XCTAssertNoThrow(try store.reconcilePrivacyPersistence(with: desired, expectedRevision: store.privacyMutationRevision))
        let stale = store.privacyMutationRevision
        let next = store.beginPrivacyMutation(intended: .enabled)
        store.endPrivacyMutation(next, succeeded: true)
        XCTAssertThrowsError(try store.reconcilePrivacyPersistence(with: .enabled, expectedRevision: stale))
    }

    // contract-test: supporting surface=gui.apple assertions=chat-queued-followups.editing.cancel,chat-queued-followups.editing.stable-revision
    func testQueuedEditRestoresOnlyItsOwnedDraftAndDetectsUnchangedText() throws {
        let previous = try ComposerMarkdownAdapter.parse("Previous unsent draft")
        let edit = try ComposerMarkdownAdapter.parse("Queued source")
        let newer = try ComposerMarkdownAdapter.parse("New typing while the request settles")
        let state = ChatQueuedFollowupState(chatID: "chat", messageID: "queued", revision: 2, mode: .followUp, phase: .queued)
        let session = ChatQueuedEditSession(state: state, scope: UUID(), teamEpoch: 1, originalContent: "Queued source",
            previousDraft: previous, ownedDraft: edit, ownedRevision: 5)
        XCTAssertEqual(session.draftOnCancel(current: edit, revision: 5), previous)
        XCTAssertEqual(session.draftOnCancel(current: newer, revision: 6), newer)
        XCTAssertEqual(session.draftOnCancel(current: edit, revision: 7), edit, "Same-text ABA does not give the old edit draft ownership")
        XCTAssertTrue(session.isUnchanged("Queued source"))
        XCTAssertFalse(session.isUnchanged("Queued source changed"))
    }

    // contract-test: supporting surface=gui.apple assertions=chat-queued-followups.admission.synced,chat-queued-followups.editing.stable-revision
    func testQueuedRevisionMetadataAndSourceIdentitySurvivePersistedMessageRoundTrip() throws {
        let message = Message(id: "queued", chatId: "chat", role: .user, content: "Filtered request", encryptedContent: "synthetic-cipher",
            createdAt: "2026-10-19T00:00:00Z", updatedAt: nil, appId: nil, isStreaming: false, embedRefs: nil,
            userMessageId: "source", queueRevision: 3, queueMode: "steer", queueDispatchStatus: "queued", queueDispatchMode: "steer", deliveryStatus: "queued")
        let restored = PersistedMessage(from: message).toMessage()
        XCTAssertEqual(restored.userMessageId, "source")
        XCTAssertEqual(ChatQueuedFollowupState.from(restored)?.revision, 3)
        XCTAssertEqual(ChatQueuedFollowupState.from(restored)?.mode, .steer)
        XCTAssertEqual(restored.encryptedContent, message.encryptedContent)
        XCTAssertNil(ChatQueuedFollowupState.from(restored.afterQueuedDispatch(.processing)))
        let current = ChatQueuedFollowupState.from(restored)!
        XCTAssertFalse(current.mayAccept(.init(chatID: "chat", messageID: "queued", revision: 5, mode: .steer, phase: .queued), hasCiphertext: false))
        XCTAssertFalse(current.mayAccept(.init(chatID: "other-chat", messageID: "queued", revision: 4, mode: .steer, phase: .queued), hasCiphertext: true))
        XCTAssertFalse(current.mayAccept(.init(chatID: "chat", messageID: "queued", revision: 3, mode: .followUp, phase: .queued), hasCiphertext: true))
    }

    // contract-test: supporting surface=gui.apple assertions=chat-queued-followups.editing.stable-revision,chat-queued-followups.access.scoped
    func testQueueEditAuthorityRequiresTheExactProtectedRevision() {
        let row = Message(id: "queued", chatId: "chat", role: .user, content: "Protected revision three",
            encryptedContent: "cipher-three", createdAt: "2026-10-19T00:00:00Z", updatedAt: nil,
            appId: nil, isStreaming: false, embedRefs: nil, queueRevision: 3, queueMode: "follow_up", deliveryStatus: "queued")
        let current = ChatQueuedFollowupState(chatID: "chat", messageID: "queued", revision: 3, mode: .followUp, phase: .queued)
        XCTAssertTrue(current.acceptsProtectedRow(row, incomingCiphertext: nil))
        XCTAssertTrue(current.acceptsProtectedRow(row, incomingCiphertext: "cipher-three"))
        XCTAssertFalse(current.acceptsProtectedRow(row, incomingCiphertext: "different-cipher"))
        let newer = ChatQueuedFollowupState(chatID: "chat", messageID: "queued", revision: 4, mode: .steer, phase: .queued)
        XCTAssertFalse(newer.acceptsProtectedRow(row, incomingCiphertext: nil), "Content-free newer snapshots must fetch their protected history")
        XCTAssertTrue(newer.acceptsProtectedRow(row, incomingCiphertext: "cipher-four"))
        let older = ChatQueuedFollowupState(chatID: "chat", messageID: "queued", revision: 2, mode: .followUp, phase: .queued)
        XCTAssertFalse(older.acceptsProtectedRow(row, incomingCiphertext: "cipher-two"))
        let foreign = ChatQueuedFollowupState(chatID: "foreign", messageID: "queued", revision: 4, mode: .followUp, phase: .queued)
        XCTAssertFalse(foreign.acceptsProtectedRow(row, incomingCiphertext: "cipher-four"))
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.privacy-context,message-input.send.ownership
    func testPreparedPrivacyReuseRequiresFreshGenerationAndExactScope() {
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        let owner = UUID(), keys = UUID()
        let scope = ChatPreparationScope(account: owner, server: "https://example.invalid", keyGeneration: keys,
            teamID: nil, teamEpoch: 1, socketGeneration: 4)
        var prepared = ChatPreparedPrivacyGeneration(scope: scope, generation: "generation-a", mutationRevision: 2, touchedAt: now)
        XCTAssertFalse(prepared.validateReuse(scope: scope, freshGeneration: nil, mutationRevision: 2, now: now))
        XCTAssertFalse(prepared.validateReuse(scope: scope, freshGeneration: "generation-b", mutationRevision: 2, now: now))
        XCTAssertFalse(prepared.validateReuse(scope: scope, freshGeneration: "generation-a", mutationRevision: 3, now: now))
        let replacement = ChatPreparationScope(account: owner, server: scope.server, keyGeneration: keys,
            teamID: nil, teamEpoch: 1, socketGeneration: 5)
        XCTAssertFalse(prepared.validateReuse(scope: replacement, freshGeneration: "generation-a", mutationRevision: 2, now: now))
        XCTAssertFalse(prepared.validateReuse(scope: scope, freshGeneration: "generation-a", mutationRevision: 2, now: now.addingTimeInterval(7_200)))
        XCTAssertTrue(prepared.validateReuse(scope: scope, freshGeneration: "generation-a", mutationRevision: 2, now: now.addingTimeInterval(30)))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.message.identity-idempotent,chats.persistence.client-encrypted
    func testQueuedRevisionUsesStableIdentityImmutableEncryptionAndExactReceipt() throws {
        let request = try ChatQueuedRevisionRequest(chatID: "chat", messageID: "queued", expectedRevision: 3,
            clientRequestID: "request", mode: .followUp, teamID: nil, content: "Filtered text",
            encryptedContent: "synthetic-cipher", encryptedPIIMappings: "synthetic-mappings")
        let first = try request.payload(), retry = try request.payload()
        XCTAssertTrue(NSDictionary(dictionary: first).isEqual(to: retry))
        XCTAssertEqual(first["message_id"] as? String, "queued")
        var accepted: [String: Any] = ["chat_id": "chat", "message_id": "queued", "client_request_id": "request",
            "queue_revision": 4, "queue_mode": "follow_up", "encrypted_content": "synthetic-cipher",
            "encrypted_pii_mappings": "synthetic-mappings"]
        XCTAssertEqual(try request.validateReceipt(accepted, type: "queued_message_updated"), 4)
        accepted["encrypted_content"] = "different-cipher"
        XCTAssertThrowsError(try request.validateReceipt(accepted, type: "queued_message_updated"))
        let conflict: [String: Any] = ["chat_id": "chat", "message_id": "queued", "client_request_id": "request",
            "reason_code": "conflict", "current_revision": 4, "retryable": true]
        XCTAssertThrowsError(try request.validateReceipt(conflict, type: "queued_message_revision_rejected")) {
            XCTAssertEqual($0 as? ChatQueuedRevisionError, .rejected(reason: "conflict", currentRevision: 4, retryable: true))
        }
        XCTAssertThrowsError(try ChatQueuedRevisionRequest(chatID: "chat", messageID: "queued", expectedRevision: 3,
            mode: .followUp, teamID: nil, content: "Changed text"))
        let steer = try ChatQueuedRevisionRequest(chatID: "chat", messageID: "queued", expectedRevision: 3, mode: .steer, teamID: "team")
        XCTAssertNil(try steer.payload()["content"])
        XCTAssertNil(try steer.payload()["encrypted_content"])
        XCTAssertEqual(try steer.payload()["queue_mode"] as? String, "steer")
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.drafts.preview-persistence
    func testAcceptedSendClearsOnlyUneditedSnapshotAndRejectedPreparationKeepsDraft() async {
        let composer = NativeComposerSession(canonicalMarkdown: "Synthetic pending draft")
        let document = composer.controller.document
        let revision = composer.revision
        await Task.yield() // Model/encryption/retention awaits must not clear it.
        XCTAssertEqual(composer.canonicalMarkdown, "Synthetic pending draft")
        XCTAssertFalse(ComposerAcceptedSendSnapshotPolicy.shouldClear(accepted: false,
            submittedRevision: revision, currentRevision: composer.revision,
            submittedDocument: document, currentDocument: composer.controller.document))
        XCTAssertTrue(ComposerAcceptedSendSnapshotPolicy.shouldClear(accepted: true,
            submittedRevision: revision, currentRevision: composer.revision,
            submittedDocument: document, currentDocument: composer.controller.document))
        composer.replaceMarkdown("Later draft belongs to the next send")
        XCTAssertFalse(ComposerAcceptedSendSnapshotPolicy.shouldClear(accepted: true,
            submittedRevision: revision, currentRevision: composer.revision,
            submittedDocument: document, currentDocument: composer.controller.document))
        XCTAssertEqual(composer.canonicalMarkdown, "Later draft belongs to the next send")
        XCTAssertFalse(ComposerAcceptedSendSnapshotPolicy.shouldClear(accepted: true,
            submittedRevision: revision, currentRevision: revision + 1,
            submittedDocument: document, currentDocument: document), "Retyping identical content is still a newer editor revision")
        XCTAssertFalse(ComposerAcceptedSendSnapshotPolicy.shouldClear(accepted: true,
            submittedRevision: revision, currentRevision: revision,
            submittedDocument: document, currentDocument: composer.controller.document), "Both revision and semantic snapshot must match")
    }

    private func storageEmbed(content: String?, disposition: ComposerEmbedStorageDisposition = .requiredEncryptedBundle) -> ComposerPendingEmbed {
        let source = ComposerPendingEmbed.document(filename: "synthetic.txt", textContent: "Synthetic attachment", piiMappings: [])
        return ComposerPendingEmbed(id: "synthetic-embed", type: source.type, referenceType: source.referenceType,
            status: source.status, content: content, textPreview: source.textPreview, record: source.record,
            localData: nil, filename: source.filename, size: 0, piiMappings: [], storageDisposition: disposition)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send,chats.persistence.client-encrypted
    func testRequiredEmbedMissingContentFailsInsteadOfBeingFiltered() {
        let scope = ComposerEmbedReferenceScope(accountScope: UUID(), server: "https://synthetic.invalid", teamID: nil, teamEpoch: 0)
        XCTAssertThrowsError(try ChatSendPipeline.requiredEncryptedBundles([storageEmbed(content: nil)], referenceScope: scope)) {
            XCTAssertEqual($0 as? ComposerEmbedStorageError, .missingRequiredContent("synthetic-embed"))
        }
        XCTAssertEqual(try ChatSendPipeline.requiredEncryptedBundles([storageEmbed(content: "{}")], referenceScope: scope).count, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send,chats.persistence.client-encrypted
    func testStoredReferenceRequiresExplicitCurrentProvenanceAndNeverDiscardsAnEdit() {
        let scope = ComposerEmbedReferenceScope(accountScope: UUID(), server: "https://synthetic.invalid", teamID: "team-a", teamEpoch: 4)
        let reference = storageEmbed(content: nil, disposition: .existingStoredReference(scope))
        XCTAssertTrue(try ChatSendPipeline.requiredEncryptedBundles([reference], referenceScope: scope).isEmpty)
        let stale = ComposerEmbedReferenceScope(accountScope: scope.accountScope, server: scope.server, teamID: scope.teamID, teamEpoch: 5)
        XCTAssertThrowsError(try ChatSendPipeline.requiredEncryptedBundles([reference], referenceScope: stale)) {
            XCTAssertEqual($0 as? ComposerEmbedStorageError, .staleStoredReference("synthetic-embed"))
        }
        XCTAssertThrowsError(try ChatSendPipeline.requiredEncryptedBundles(
            [storageEmbed(content: "edited", disposition: .existingStoredReference(scope))], referenceScope: scope)) {
            XCTAssertEqual($0 as? ComposerEmbedStorageError, .changedStoredReference("synthetic-embed"))
        }
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send,chats.persistence.client-encrypted
    func testFreshRestoredReferenceUsesReadyReceiptWithoutBuildingNewCiphertext() async throws {
        let scope = ComposerEmbedReferenceScope(accountScope: UUID(), server: ServerProfile.development.apiBaseURL.absoluteString,
            teamID: nil, teamEpoch: 0)
        let source = storageEmbed(content: nil, disposition: .existingStoredReference(scope))
        // Origin chat differs: the server's personal master wrapper authorization,
        // not local source-chat equality, decides whether this reference is usable.
        let record = EmbedRecord(id: source.id, type: source.type, status: source.record.status, data: source.record.data,
            parentEmbedId: nil, appId: nil, skillId: nil, embedIds: nil,
            hashedChatId: "another-owned-chat", createdAt: nil)
        let restored = ComposerPendingEmbed(id: source.id, type: source.type, referenceType: source.referenceType,
            status: source.status, content: nil, textPreview: nil, record: record, localData: nil,
            filename: source.filename, size: 0, piiMappings: [], storageDisposition: source.storageDisposition)
        var probes = 0
        try await ChatSendPipeline.validateFreshStoredReferences([restored], referenceScope: scope,
            serverProfile: .development, validate: {}) { ids in
                probes += 1
                XCTAssertEqual(ids, [restored.id])
                return [restored.id: .ready]
            }
        XCTAssertEqual(probes, 1)
        XCTAssertTrue(try ChatSendPipeline.requiredEncryptedBundles([restored], referenceScope: scope).isEmpty)
        XCTAssertNil(restored.content)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send,chats.persistence.client-encrypted
    func testFreshReferenceMissingUnusableMalformedAndUnavailableBlockSend() async throws {
        let scope = ComposerEmbedReferenceScope(accountScope: UUID(), server: ServerProfile.development.apiBaseURL.absoluteString,
            teamID: "team-a", teamEpoch: 4)
        let ref = storageEmbed(content: nil, disposition: .existingStoredReference(scope))
        for state in [EmbedReferenceAvailabilityState.missing, .unusable] {
            do {
                try await ChatSendPipeline.validateFreshStoredReferences([ref], referenceScope: scope,
                    serverProfile: .development, validate: {}) { _ in [ref.id: state] }
                XCTFail("Unavailable reference must not authorize send")
            } catch let error as ComposerEmbedStorageError {
                XCTAssertEqual(error.reason, state == .missing ? .missingContent : .staleReference)
            }
        }
        let malformedResponses: [[String: EmbedReferenceAvailabilityState]] = [[:], [ref.id: .ready, "unexpected": .ready]]
        for response in malformedResponses {
            do {
                try await ChatSendPipeline.validateFreshStoredReferences([ref], referenceScope: scope,
                    serverProfile: .development, validate: {}) { _ in response }
                XCTFail("Exact reference result set is required")
            } catch { XCTAssertTrue(error is APIError) }
        }
        do {
            try await ChatSendPipeline.validateFreshStoredReferences([ref], referenceScope: scope,
                serverProfile: .development, validate: {}) { _ in throw URLError(.notConnectedToInternet) }
            XCTFail("No receipt must block send")
        } catch { XCTAssertEqual((error as? URLError)?.code, .notConnectedToInternet) }
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send,auth.session.isolation
    func testFreshReferenceRejectsTeamRevocationAfterProbeAndPreservesLegacyProfiles() async throws {
        let scope = ComposerEmbedReferenceScope(accountScope: UUID(), server: ServerProfile.development.apiBaseURL.absoluteString,
            teamID: "team-a", teamEpoch: 4)
        let ref = storageEmbed(content: nil, disposition: .existingStoredReference(scope))
        var epoch = scope.teamEpoch
        do {
            try await ChatSendPipeline.validateFreshStoredReferences([ref], referenceScope: scope,
                serverProfile: .development, validate: {
                    guard epoch == scope.teamEpoch else { throw CancellationError() }
                }) { _ in epoch += 1; return [ref.id: .ready] }
            XCTFail("A revoked Team response must not authorize send")
        } catch { XCTAssertTrue(error is CancellationError) }
        for profile in [ServerProfile.production, .custom(domain: "legacy.example.invalid")] {
            try await ChatSendPipeline.validateFreshStoredReferences([ref], referenceScope: scope,
                serverProfile: profile, validate: {}) { _ in
                    XCTFail("Unverified profiles must not use the dev-only endpoint")
                    throw APIError.invalidResponse
                }
        }
    }

    private func retryFence(process: UUID, accountScope: UUID, keyGeneration: UUID, accountID: String = "synthetic-owner",
                            server: String = "https://synthetic.invalid", teamID: String? = nil,
                            teamEpoch: UInt64 = 0, deletion: Int = 0, keyDigest: String = "synthetic-key-digest") -> ChatSendRetryFence {
        ChatSendRetryFence(processEpoch: process, accountID: accountID, accountScope: accountScope, server: server,
            teamID: teamID, teamEpoch: teamEpoch, keyGeneration: keyGeneration, deletionVersion: deletion, chatKeyDigest: keyDigest)
    }

    private func retainedBundle(fence: ChatSendRetryFence, turnID: String = "synthetic-turn", encryptedEmbed: String) throws -> ChatRetainedSendBundle {
        let outbound: [String: Any] = ["chat_id": "synthetic-chat", "turn_id": turnID,
            "message": ["message_id": "synthetic-message", "content": "Synthetic prompt"],
            "encrypted_embeds": [["embed_id": "synthetic-embed", "encrypted_content": encryptedEmbed]]]
        return try ChatRetainedSendBundle(chatID: "synthetic-chat", messageID: "synthetic-message", turnID: turnID,
            inputDigest: "synthetic-input-digest", messagesVersion: 2, fence: fence,
            preflight: ["chat_id": "synthetic-chat", "message_id": "synthetic-message", "turn_id": turnID,
                        "encrypted_user_message": ["encrypted_content": "synthetic-message-ciphertext"],
                        "inference_request": outbound], outbound: outbound)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,storage.privacy.ciphertext-boundary
    func testClosedAppRetryRetainsOriginalEncryptedBundleAndRejectsFreshNonceReplacement() throws {
        let master = SymmetricKey(size: .bits256), embedKey = SymmetricKey(size: .bits256)
        let cipher = try ComposerEmbedCrypto.encryptContent("Synthetic attachment", using: embedKey)
        let fence = retryFence(process: UUID(), accountScope: UUID(), keyGeneration: UUID())
        let original = try retainedBundle(fence: fence, encryptedEmbed: cipher)
        var disk: [String: Data] = [:]
        var writes = 0
        func store() -> ChatRetainedSendStore {
            ChatRetainedSendStore(read: { disk[$0] }, write: { disk[$0] = $1; writes += 1 }, erase: { disk.removeValue(forKey: $0) })
        }
        try store().save(original, masterKey: master)
        XCTAssertFalse(disk.values.contains { String(decoding: $0, as: UTF8.self).contains("Synthetic prompt") })
        let reloaded = try XCTUnwrap(store().load(accountID: fence.accountID, server: fence.server,
            chatID: original.chatID, messageID: original.messageID, masterKey: master))
        XCTAssertEqual(reloaded, original)
        let payload = try reloaded.payloads().outbound
        XCTAssertEqual((payload["encrypted_embeds"] as? [[String: Any]])?.first?["encrypted_content"] as? String, cipher)
        try store().save(reloaded, masterKey: master)
        XCTAssertEqual(writes, 1)
        let freshCipher = try ComposerEmbedCrypto.encryptContent("Synthetic attachment", using: embedKey)
        XCTAssertNotEqual(freshCipher, cipher)
        XCTAssertThrowsError(try store().save(retainedBundle(fence: fence, encryptedEmbed: freshCipher), masterKey: master))
        XCTAssertEqual(try store().load(accountID: fence.accountID, server: fence.server,
            chatID: original.chatID, messageID: original.messageID, masterKey: master), original)
        XCTAssertThrowsError(try store().load(accountID: fence.accountID, server: fence.server,
            chatID: original.chatID, messageID: original.messageID, masterKey: SymmetricKey(size: .bits256)))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    func testRetainedBundleCleanupCannotRemoveANewerTurnOrAnotherOwner() throws {
        let key = SymmetricKey(size: .bits256)
        let fence = retryFence(process: UUID(), accountScope: UUID(), keyGeneration: UUID())
        let original = try retainedBundle(fence: fence, encryptedEmbed: "synthetic-ciphertext")
        let newer = try retainedBundle(fence: fence, turnID: "newer-turn", encryptedEmbed: "synthetic-newer-ciphertext")
        var disk: [String: Data] = [:]
        let store = ChatRetainedSendStore(read: { disk[$0] }, write: { disk[$0] = $1 }, erase: { disk.removeValue(forKey: $0) })
        try store.save(original, masterKey: key)
        XCTAssertNil(try store.load(accountID: "other-owner", server: fence.server, chatID: original.chatID, messageID: original.messageID, masterKey: key))
        try store.remove(original, masterKey: key)
        try store.save(newer, masterKey: key)
        try store.remove(original, masterKey: key)
        XCTAssertEqual(try store.load(accountID: fence.accountID, server: fence.server, chatID: newer.chatID, messageID: newer.messageID, masterKey: key), newer)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    func testMalformedRetainedPairOrUnreadableCiphertextFailsBeforeReplacement() throws {
        let key = SymmetricKey(size: .bits256)
        let fence = retryFence(process: UUID(), accountScope: UUID(), keyGeneration: UUID())
        let original = try retainedBundle(fence: fence, encryptedEmbed: "synthetic-ciphertext")
        let payloads = try original.payloads()
        var changed = payloads.outbound
        changed["turn_id"] = "mismatched-turn"
        let malformed = try ChatRetainedSendBundle(chatID: original.chatID, messageID: original.messageID,
            turnID: original.turnID, inputDigest: original.inputDigest, messagesVersion: original.messagesVersion,
            fence: fence, preflight: payloads.preflight, outbound: changed)
        var writes = 0
        let store = ChatRetainedSendStore(read: { _ in nil }, write: { _, _ in writes += 1 }, erase: { _ in })
        XCTAssertThrowsError(try store.save(malformed, masterKey: key))
        XCTAssertEqual(writes, 0)
        let unreadable = ChatRetainedSendStore(read: { _ in Data([0xff]) }, write: { _, _ in writes += 1 }, erase: { _ in })
        XCTAssertThrowsError(try unreadable.save(original, masterKey: key))
        XCTAssertEqual(writes, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,message-input.send.ownership
    func testRetainedPersistenceFailureBlocksLargePayloadBeforeEditOrOptimisticInsertion() async throws {
        let key = SymmetricKey(size: .bits256)
        let fence = retryFence(process: UUID(), accountScope: UUID(), keyGeneration: UUID())
        let bundle = try retainedBundle(fence: fence, encryptedEmbed: String(repeating: "synthetic-ciphertext", count: 65_536))
        var attemptedBytes = 0
        var committed = false
        let persistenceError = NSError(domain: "SyntheticKeychain", code: -50,
            userInfo: [NSLocalizedDescriptionKey: "Synthetic persistence failure"])
        let store = ChatRetainedSendStore(read: { _ in nil }, write: { _, data in
            attemptedBytes = data.count
            throw persistenceError
        }, erase: { _ in })
        do {
            try await ChatPreparedSendRetentionStage.retainThenCommit(retain: {
                try store.save(bundle, masterKey: key)
            }, commit: {
                committed = true // Represents edit deletion and optimistic insertion.
            })
            XCTFail("Persistence failure must remain visible to the send caller")
        } catch {
            XCTAssertEqual((error as NSError).domain, persistenceError.domain)
            XCTAssertEqual(error.localizedDescription, "Synthetic persistence failure")
        }
        XCTAssertGreaterThan(attemptedBytes, 1_000_000)
        XCTAssertFalse(committed)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    func testRetainedRetryFencesScopeServerTeamKeyDeletionVersionAndColdLaunch() {
        let process = UUID(), scope = UUID(), keyGeneration = UUID()
        let original = retryFence(process: process, accountScope: scope, keyGeneration: keyGeneration, teamID: "team-a", teamEpoch: 4)
        XCTAssertTrue(original.permitsReplay(in: original, hasOriginalMessage: true, expectedVersion: 2, currentVersion: 2))
        let stale = [
            retryFence(process: process, accountScope: UUID(), keyGeneration: keyGeneration, teamID: "team-a", teamEpoch: 4),
            retryFence(process: process, accountScope: scope, keyGeneration: UUID(), teamID: "team-a", teamEpoch: 4),
            retryFence(process: process, accountScope: scope, keyGeneration: keyGeneration, accountID: "other-owner", teamID: "team-a", teamEpoch: 4),
            retryFence(process: process, accountScope: scope, keyGeneration: keyGeneration, server: "https://other.invalid", teamID: "team-a", teamEpoch: 4),
            retryFence(process: process, accountScope: scope, keyGeneration: keyGeneration, teamID: "team-b", teamEpoch: 4),
            retryFence(process: process, accountScope: scope, keyGeneration: keyGeneration, teamID: "team-a", teamEpoch: 5),
            retryFence(process: process, accountScope: scope, keyGeneration: keyGeneration, teamID: "team-a", teamEpoch: 4, deletion: 1),
            retryFence(process: process, accountScope: scope, keyGeneration: keyGeneration, teamID: "team-a", teamEpoch: 4, keyDigest: "replacement-key")
        ]
        for current in stale { XCTAssertFalse(original.permitsReplay(in: current, hasOriginalMessage: true, expectedVersion: 2, currentVersion: 2)) }
        XCTAssertFalse(original.permitsReplay(in: original, hasOriginalMessage: false, expectedVersion: 2, currentVersion: 2))
        XCTAssertFalse(original.permitsReplay(in: original, hasOriginalMessage: true, expectedVersion: 2, currentVersion: 3))
        let cold = retryFence(process: UUID(), accountScope: UUID(), keyGeneration: UUID(), teamID: "team-a", teamEpoch: 0)
        XCTAssertTrue(original.permitsReplay(in: cold, hasOriginalMessage: true, expectedVersion: 2, currentVersion: 2))
        XCTAssertFalse(original.permitsReplay(in: cold, hasOriginalMessage: false, expectedVersion: 2, currentVersion: 2))
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.privacy-context,chats.persistence.client-encrypted
    func testRetainedSendInputDigestChangesForAttachmentEditsAndPIIExclusions() throws {
        func digest(_ content: String = "Synthetic prompt", embedContent: String = "{}", excluded: Set<String> = [], mappings: [PIIMapping] = []) throws -> String {
            try ChatSendPipeline.sendInputDigest(content: content, composerEmbeds: [storageEmbed(content: embedContent)],
                piiMappings: mappings, excludedPIIOriginals: excluded, excludedPIIPlaceholders: [],
                broadcastToSiblings: false, createdAtOverride: nil, isEdit: false)
        }
        let original = try digest()
        XCTAssertEqual(try digest(), original)
        XCTAssertNotEqual(try digest("Edited prompt"), original)
        XCTAssertNotEqual(try digest(embedContent: "edited attachment"), original)
        XCTAssertNotEqual(try digest(excluded: ["synthetic@example.invalid"]), original)
        XCTAssertNotEqual(try digest(mappings: [PIIMapping(placeholder: "[EMAIL_1]", original: "synthetic@example.invalid", type: "EMAIL")]), original)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.delivery.idempotent-visible
    func testBackgroundLifecycleTimeoutClosesCurrentSocketAndEndsExecutionOnce() async {
        let context = NativeLifecycleDeliveryContext(accountID: "owner", profile: .development, scope: UUID(),
            socketGeneration: 1, scene: .background, applicationIsBackground: true)
        var disconnects = 0
        var ended = 0
        let attempt = NativeLifecycleAcknowledgementAttempt(captured: context, current: { context },
            disconnect: { disconnects += 1 })
        attempt.attachBackgroundExecutionEnd { ended += 1 }
        await attempt.waitForAcknowledgement { throw URLError(.timedOut) }
        attempt.expire()
        attempt.cancel()
        XCTAssertEqual(disconnects, 1)
        XCTAssertEqual(ended, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.delivery.idempotent-visible
    func testBackgroundLifecycleTimeoutCannotCloseForegroundOrReplacementSession() async {
        let scope = UUID()
        let captured = NativeLifecycleDeliveryContext(accountID: "owner", profile: .development, scope: scope,
            socketGeneration: 1, scene: .background, applicationIsBackground: true)
        let replacements = [
            NativeLifecycleDeliveryContext(accountID: "owner", profile: .development, scope: scope,
                socketGeneration: 1, scene: .active, applicationIsBackground: false),
            NativeLifecycleDeliveryContext(accountID: "owner", profile: .development, scope: scope,
                socketGeneration: 1, scene: .background, applicationIsBackground: false),
            NativeLifecycleDeliveryContext(accountID: "replacement", profile: .development, scope: scope,
                socketGeneration: 1, scene: .background, applicationIsBackground: true),
            NativeLifecycleDeliveryContext(accountID: "owner", profile: .production, scope: scope,
                socketGeneration: 1, scene: .background, applicationIsBackground: true),
            NativeLifecycleDeliveryContext(accountID: "owner", profile: .development, scope: UUID(),
                socketGeneration: 1, scene: .background, applicationIsBackground: true),
            NativeLifecycleDeliveryContext(accountID: "owner", profile: .development, scope: scope,
                socketGeneration: 2, scene: .background, applicationIsBackground: true)
        ]
        for replacement in replacements {
            var disconnects = 0
            var ended = 0
            let attempt = NativeLifecycleAcknowledgementAttempt(captured: captured, current: { replacement },
                disconnect: { disconnects += 1 })
            attempt.attachBackgroundExecutionEnd { ended += 1 }
            await attempt.waitForAcknowledgement { throw URLError(.timedOut) }
            XCTAssertEqual(disconnects, 0)
            XCTAssertEqual(ended, 1)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.delivery.idempotent-visible
    func testBackgroundLifecycleKeepsExecutionUntilServerAcknowledgement() async {
        let context = NativeLifecycleDeliveryContext(accountID: "owner", profile: .development, scope: UUID(),
            socketGeneration: 1, scene: .background, applicationIsBackground: true)
        var continuation: CheckedContinuation<Void, Never>?
        var ended = 0
        var disconnects = 0
        let sent = expectation(description: "waiting for lifecycle acknowledgement")
        let attempt = NativeLifecycleAcknowledgementAttempt(captured: context, current: { context },
            disconnect: { disconnects += 1 })
        attempt.attachBackgroundExecutionEnd { ended += 1 }
        let waiting = Task { @MainActor in
            await attempt.waitForAcknowledgement {
                await withCheckedContinuation { continuation = $0; sent.fulfill() }
            }
        }
        await fulfillment(of: [sent], timeout: 1)
        XCTAssertEqual(ended, 0)
        continuation?.resume()
        await waiting.value
        attempt.expire()
        XCTAssertEqual(ended, 1)
        XCTAssertEqual(disconnects, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.delivery.idempotent-visible
    func testBackgroundLifecycleOSExpirationCancelsWaitAndCleansUpOnce() async {
        let context = NativeLifecycleDeliveryContext(accountID: "owner", profile: .development, scope: UUID(),
            socketGeneration: 1, scene: .background, applicationIsBackground: true)
        var disconnects = 0
        var ended = 0
        let sent = expectation(description: "in-flight lifecycle acknowledgement")
        let attempt = NativeLifecycleAcknowledgementAttempt(captured: context, current: { context },
            disconnect: { disconnects += 1 })
        attempt.attachBackgroundExecutionEnd { ended += 1 }
        let waiting = Task { @MainActor in
            await attempt.waitForAcknowledgement {
                sent.fulfill()
                try await Task.sleep(for: .seconds(60))
            }
        }
        await fulfillment(of: [sent], timeout: 1)
        attempt.expire()
        attempt.expire()
        await waiting.value
        XCTAssertEqual(disconnects, 1)
        XCTAssertEqual(ended, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.delivery.idempotent-visible
    func testForegroundLifecycleCancelsOldTimeoutEvenAfterNextBackgroundTransition() async {
        let context = NativeLifecycleDeliveryContext(accountID: "owner", profile: .development, scope: UUID(),
            socketGeneration: 1, scene: .background, applicationIsBackground: true)
        let coordinator = NativeLifecycleAcknowledgementCoordinator()
        var disconnects = 0
        var ended = 0
        let old = coordinator.begin(captured: context, current: { context }, disconnect: { disconnects += 1 })
        old.attachBackgroundExecutionEnd { ended += 1 }
        coordinator.cancelPending()
        let next = coordinator.begin(captured: context, current: { context }, disconnect: { disconnects += 1 })
        next.attachBackgroundExecutionEnd { ended += 1 }
        old.expire()
        XCTAssertEqual(disconnects, 0)
        XCTAssertEqual(ended, 1)
        await next.waitForAcknowledgement { }
        XCTAssertEqual(ended, 2)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.registration.lifecycle
    func testPushRegistrationRetriesFailedAcknowledgementsAndDeduplicatesToken() async {
        let context = PushRegistrationContext(accountID: "owner", profile: .development, scope: UUID())
        var calls = 0
        var delays: [Duration] = []
        var states: [Bool] = []
        let acknowledged = expectation(description: "registration acknowledged after transient failures")
        let registration = PushDeviceRegistration(context: { context }, register: { token, captured in
            XCTAssertEqual(token, "synthetic-installation-token")
            XCTAssertEqual(captured, context)
            calls += 1
            if calls < 3 { throw URLError(.notConnectedToInternet) }
        }, sleep: { delays.append($0) }, retryDelays: [.seconds(1), .seconds(4), .seconds(16)], acknowledge: { value in
            states.append(value)
            if value { acknowledged.fulfill() }
        })
        registration.refresh(token: "synthetic-installation-token")
        registration.refresh(token: "synthetic-installation-token")
        await fulfillment(of: [acknowledged], timeout: 1)
        registration.refresh(token: "synthetic-installation-token")
        XCTAssertEqual(calls, 3)
        XCTAssertEqual(delays, [.seconds(1), .seconds(4)])
        XCTAssertEqual(states.filter { $0 }.count, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.registration.lifecycle
    func testPushCachedTokenWaitsForVerifiedOnlineContextAndResumesAfterBoundedFailures() async {
        let online = PushRegistrationContext(accountID: "owner", profile: .development, scope: UUID())
        var context: PushRegistrationContext?
        var calls = 0
        let exhausted = expectation(description: "bounded registration burst exhausted")
        let acknowledged = expectation(description: "next online transition retried cached token")
        var didReportExhaustion = false
        let registration = PushDeviceRegistration(context: { context }, register: { token, _ in
            XCTAssertEqual(token, "cached-installation-token")
            calls += 1
            if calls <= 4 { throw URLError(.timedOut) }
        }, sleep: { _ in }, retryDelays: [.seconds(1), .seconds(4), .seconds(16)], acknowledge: { value in
            if calls == 4, !value, !didReportExhaustion {
                didReportExhaustion = true
                exhausted.fulfill()
            }
            if value { acknowledged.fulfill() }
        })
        registration.refresh(token: "cached-installation-token")
        await Task.yield()
        XCTAssertEqual(calls, 0, "An offline account must not register through the current cookie jar")
        context = online
        registration.refresh(token: "cached-installation-token")
        await fulfillment(of: [exhausted], timeout: 1)
        context = nil
        registration.invalidate()
        context = online
        registration.refresh(token: "cached-installation-token")
        await fulfillment(of: [acknowledged], timeout: 1)
        XCTAssertEqual(calls, 5)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.registration.lifecycle
    func testPushOldProfileAcknowledgementCannotMarkReplacementAccountRegistered() async {
        let oldContext = PushRegistrationContext(accountID: "owner", profile: .development, scope: UUID())
        let replacement = PushRegistrationContext(accountID: "replacement", profile: .production, scope: UUID())
        var current = oldContext
        var continuation: CheckedContinuation<Void, Never>?
        var requests: [PushRegistrationContext] = []
        var acknowledgements = 0
        let suspended = expectation(description: "old request in flight")
        let completed = expectation(description: "replacement registration acknowledged")
        let registration = PushDeviceRegistration(context: { current }, register: { _, captured in
            requests.append(captured)
            if captured == oldContext {
                await withCheckedContinuation {
                    continuation = $0
                    suspended.fulfill()
                }
            }
        }, sleep: nil, retryDelays: [.seconds(1), .seconds(4), .seconds(16)], acknowledge: { value in
            if value { acknowledgements += 1; completed.fulfill() }
        })
        registration.refresh(token: "synthetic-token")
        await fulfillment(of: [suspended], timeout: 1)
        registration.invalidate()
        current = replacement
        continuation?.resume()
        await Task.yield()
        XCTAssertEqual(acknowledgements, 0)
        registration.refresh(token: "synthetic-token")
        await fulfillment(of: [completed], timeout: 1)
        XCTAssertEqual(requests, [oldContext, replacement])
        XCTAssertEqual(acknowledgements, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.registration.lifecycle
    func testPushRetryDropsOldOfflineScopeAndTokenRotationStartsFreshRequest() async {
        var current = PushRegistrationContext(accountID: "owner", profile: .development, scope: UUID())
        var tokens: [String] = []
        let changed = expectation(description: "account scope changed during retry backoff")
        let completed = expectation(description: "rotated token acknowledged in fresh scope")
        let registration = PushDeviceRegistration(context: { current }, register: { token, _ in
            tokens.append(token)
            if token == "old-token" { throw URLError(.timedOut) }
        }, sleep: { _ in
            current = PushRegistrationContext(accountID: "owner", profile: .development, scope: UUID())
            changed.fulfill()
        }, retryDelays: [.seconds(1), .seconds(4), .seconds(16)], acknowledge: { if $0 { completed.fulfill() } })
        registration.refresh(token: "old-token")
        await fulfillment(of: [changed], timeout: 1)
        registration.refresh(token: "rotated-token")
        await fulfillment(of: [completed], timeout: 1)
        XCTAssertEqual(tokens, ["old-token", "rotated-token"])
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.delivery.idempotent-visible
    func testNativeWindowVisibilityPreservesOtherWindowAndPublishesLastWindowBackground() {
        var ownership = SharedSocketWindowOwnership()
        let first = UUID(), second = UUID()
        ownership.register(first); ownership.register(second)
        ownership.updateVisibility(first, isVisible: true, isKey: true)
        ownership.updateVisibility(second, isVisible: true, isKey: false)
        func action() -> NativeMacWindowVisibilityPolicy.Publication {
            NativeMacWindowVisibilityPolicy.publication(appIsActive: true,
                hasVisibleWindow: !ownership.visibleWindowIDs.isEmpty,
                hasKeyWindow: !ownership.keyWindowIDs.isEmpty)
        }
        // Minimize the key window: visible second window still keeps the app
        // completion-capable, but no chat is presently the key active chat.
        ownership.updateVisibility(first, isVisible: false, isKey: false)
        XCTAssertEqual(action(), .clearActiveChat)
        ownership.updateVisibility(second, isVisible: true, isKey: true)
        XCTAssertEqual(action(), .preserveOtherOwner)
        ownership.unregister(first)
        XCTAssertEqual(action(), .preserveOtherOwner, "Closing another window must not clear the key owner's chat")
        ownership.updateVisibility(second, isVisible: false, isKey: false)
        XCTAssertEqual(action(), .background, "Last minimized window is background even while NSApp remains active")
        ownership.updateVisibility(second, isVisible: true, isKey: true)
        XCTAssertEqual(action(), .preserveOtherOwner, "Restoring the key window resumes its ownership")
        ownership.unregister(second)
        XCTAssertEqual(action(), .background, "Last closed window is background even while NSApp remains active")
        ownership.updateVisibility(second, isVisible: true, isKey: true)
        XCTAssertEqual(action(), .background, "Late detached-window callbacks cannot reacquire ownership")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.delivery.idempotent-visible
    func testNativeWindowResignBecomeKeyHandoffPreservesCurrentOwner() {
        var ownership = SharedSocketWindowOwnership()
        let first = UUID(), second = UUID()
        ownership.register(first); ownership.register(second)
        ownership.updateVisibility(first, isVisible: true, isKey: true)
        ownership.updateVisibility(second, isVisible: true, isKey: false)
        ownership.updateVisibility(first, isVisible: true, isKey: false)
        ownership.updateVisibility(second, isVisible: true, isKey: true)
        XCTAssertEqual(ownership.keyWindowIDs, [second])
        XCTAssertEqual(NativeMacWindowVisibilityPolicy.publication(appIsActive: true,
            hasVisibleWindow: !ownership.visibleWindowIDs.isEmpty, hasKeyWindow: !ownership.keyWindowIDs.isEmpty), .preserveOtherOwner)
        XCTAssertEqual(NativeMacWindowVisibilityPolicy.publication(appIsActive: false,
            hasVisibleWindow: true, hasKeyWindow: true), .background, "Application deactivation wins over retained window state")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.delivery.idempotent-visible
    func testNativeActiveChatClearEncodesExplicitNullAndSelectedChatUsesString() throws {
        for chatID in [nil, "synthetic-current-chat"] as [String?] {
            let bytes = try NativeActiveChatAnnouncement.message(chatID: chatID).encodedData()
            let wire = try XCTUnwrap(JSONSerialization.jsonObject(with: bytes) as? [String: Any])
            let payload = try XCTUnwrap(wire["payload"] as? [String: Any])
            XCTAssertEqual(wire["type"] as? String, "set_active_chat")
            if let chatID { XCTAssertEqual(payload["chat_id"] as? String, chatID) }
            else { XCTAssertTrue(payload["chat_id"] is NSNull, "Clear must be an explicit JSON null, not an omitted or boxed Optional") }
        }
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.isolation,apps.anonymous.local-results-and-promotion
    func testSuspendedAnonymousPromotionRejectsChangedAccountBeforeSendOrApply() async throws {
        var currentAccount = "synthetic-account-a"
        let capturedAccount = currentAccount
        var prepared = false
        var sends = 0
        var stores = 0
        do {
            _ = try await AnonymousFreeUsageService.withPromotionAuthority(isCurrent: { currentAccount == capturedAccount }) {
                await Task.yield()
                currentAccount = "synthetic-account-b"
                prepared = true
                return "synthetic-encrypted-history"
            }
            sends += 1
            stores += 1
            XCTFail("A suspended promotion must reject ciphertext prepared under the previous account")
        } catch is CancellationError {
            // Expected after the preparation suspension changes authority.
        }
        XCTAssertTrue(prepared)
        XCTAssertEqual(sends, 0)
        XCTAssertEqual(stores, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.isolation,apps.anonymous.local-results-and-promotion
    func testSuspendedAnonymousPromotionRejectsChangedAccountBeforeLocalApply() async throws {
        var currentAccount = "synthetic-account-a"
        let capturedAccount = currentAccount
        var sends = 0
        var stores = 0
        do {
            try await AnonymousFreeUsageService.withPromotionAuthority(isCurrent: { currentAccount == capturedAccount }) {
                sends += 1
                await Task.yield()
                currentAccount = "synthetic-account-b"
            }
            stores += 1
            XCTFail("A send that resumes under another account must not mutate its store")
        } catch is CancellationError {
            // Expected after the transport suspension changes authority.
        }
        XCTAssertEqual(sends, 1)
        XCTAssertEqual(stores, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.session.isolation,sync.surface.semantic-parity
    func testSessionResetPreservesRegisteredWindowSyncOwnership() {
        var ownership = SharedSocketWindowOwnership()
        let first = UUID(), second = UUID()
        ownership.register(first)
        ownership.register(second)
        ownership.updateVisibility(first, isVisible: true, isKey: true)
        ownership.updateVisibility(second, isVisible: true, isKey: false)
        XCTAssertTrue(ownership.claimReconnectWork(first))
        ownership.resetSessionWork()
        XCTAssertEqual(ownership.windowIDs, [first, second])
        XCTAssertEqual(ownership.visibleWindowIDs, [first, second])
        XCTAssertEqual(ownership.keyWindowIDs, [first])
        XCTAssertEqual(ownership.reconnectWorkCount, 0)
        XCTAssertTrue(ownership.ownsSharedSync(first))
        XCTAssertFalse(ownership.ownsSharedSync(second))
        // Reconciliation of a retained authenticated window is idempotent and
        // must not steal the shared socket from an earlier mounted window.
        ownership.register(second)
        ownership.register(first)
        XCTAssertEqual(ownership.windowIDs, [first, second])
        ownership.unregister(first)
        XCTAssertTrue(ownership.ownsSharedSync(second))
        XCTAssertTrue(ownership.claimReconnectWork(second))
        ownership.unregister(second)
        ownership.resetSessionWork()
        XCTAssertFalse(ownership.ownsSharedSync(second), "Reset cannot restore a closed window")
        XCTAssertTrue(ownership.visibleWindowIDs.isEmpty)
        XCTAssertTrue(ownership.keyWindowIDs.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.streaming.progressive-presentation
    func testSharedSocketReconnectWorkHasOneWindowOwnerAndMigratesOnClose() {
        var ownership = SharedSocketWindowOwnership()
        let firstWindow = UUID()
        let secondWindow = UUID()
        ownership.register(firstWindow)
        ownership.register(secondWindow)

        XCTAssertFalse(ownership.claimReconnectWork(secondWindow))
        XCTAssertTrue(ownership.claimReconnectWork(firstWindow))
        XCTAssertEqual(ownership.reconnectWorkCount, 1)

        ownership.unregister(firstWindow)
        XCTAssertTrue(ownership.claimReconnectWork(secondWindow))
        XCTAssertEqual(ownership.reconnectWorkCount, 2)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    func testNewChatEncryptedKeyWrapperStaysStableAcrossConcurrentWraps() async throws {
        let chatId = UUID().uuidString.lowercased()
        let key = await ChatKeyManager.shared.createKeyForNewChat(chatId)
        defer { ChatKeyManager.shared.removeKey(for: chatId) }
        let masterKey = SymmetricKey(size: .bits256)
        let firstWrap = try await CryptoManager.shared.wrapChatKey(key, masterKey: masterKey)
        let secondWrap = try await CryptoManager.shared.wrapChatKey(key, masterKey: masterKey)
        XCTAssertNotEqual(firstWrap, secondWrap, "Wrapping the same key uses a fresh nonce")

        let first = ChatKeyManager.shared.rememberNewEncryptedKeyIfAbsent(firstWrap, for: chatId, matching: key)
        let second = ChatKeyManager.shared.rememberNewEncryptedKeyIfAbsent(secondWrap, for: chatId, matching: key)
        XCTAssertEqual(first, firstWrap)
        XCTAssertEqual(second, firstWrap, "Every send must use the wrapper first assigned to this chat")
        XCTAssertEqual(ChatKeyManager.shared.encryptedKey(for: chatId), firstWrap)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent
    func testOverlappingFirstSendsUseOneChatKeyAndWrapper() async throws {
        let chatId = UUID().uuidString.lowercased()
        let gate = OverlappingChatKeyGate()
        defer { ChatKeyManager.shared.removeKey(for: chatId) }

        let first = Task { await ChatKeyManager.shared.createKeyForNewChat(
            chatId, generateKey: { await gate.generate() }
        ) }
        await gate.waitForFirstGeneration()
        let second = Task { await ChatKeyManager.shared.createKeyForNewChat(
            chatId, generateKey: { await gate.generate() }
        ) }
        let secondKey = await second.value
        await gate.releaseFirstGeneration()
        let firstKey = await first.value
        XCTAssertEqual(Self.keyData(firstKey), Self.keyData(secondKey))

        let masterKey = SymmetricKey(size: .bits256)
        let firstWrap = try await CryptoManager.shared.wrapChatKey(firstKey, masterKey: masterKey)
        let secondWrap = try await CryptoManager.shared.wrapChatKey(secondKey, masterKey: masterKey)
        let stableFirst = ChatKeyManager.shared.rememberNewEncryptedKeyIfAbsent(
            firstWrap, for: chatId, matching: firstKey
        )
        let stableSecond = ChatKeyManager.shared.rememberNewEncryptedKeyIfAbsent(
            secondWrap, for: chatId, matching: secondKey
        )
        XCTAssertEqual(stableFirst, stableSecond)
    }

    private static func keyData(_ key: SymmetricKey) -> Data {
        key.withUnsafeBytes { Data($0) }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    func testStaleWrapCannotReplaceNewChatKeyAfterKeyReplacement() async throws {
        let chatId = UUID().uuidString.lowercased()
        let oldKey = await ChatKeyManager.shared.createKeyForNewChat(chatId)
        let newKey = SymmetricKey(size: .bits256)
        let generation = ChatKeyManager.shared.cacheGeneration
        defer { ChatKeyManager.shared.removeKey(for: chatId) }
        ChatKeyManager.shared.setKey(newKey, for: chatId)
        XCTAssertNil(ChatKeyManager.shared.rememberNewEncryptedKeyIfAbsent(
            "stale-wrap", for: chatId, matching: oldKey
        ))
        XCTAssertNil(ChatKeyManager.shared.installValidatedKey(
            oldKey, encryptedKey: "old-server-wrap", for: chatId, expectedGeneration: generation
        ))
        XCTAssertNil(ChatKeyManager.shared.encryptedKey(for: chatId))
    }

    // contract-test: supporting surface=gui.apple assertions=apple-notifications.action.routing-coherent
    func testNotificationReplyDoesNotCommitAfterItsSessionChangesDuringPreflight() async throws {
        let payloads = Self.notificationTurnPayloads()
        let transport = NotificationReceiptTransport(state: "PREPARED")
        var validatedBeforePreflight = false
        var rejectedAfterPreflight = false
        do {
            try await ChatSendPipeline().sendSavedChatTurn(turnId: "turn-a",
                preflightPayload: payloads.preflight, outboundPayload: payloads.outbound,
                transport: transport, waitForInferenceReceipt: true,
                validateRemoteSend: {
                    // Replace the session after the actual preflight exchange;
                    // earlier owner/key guards may legitimately validate often.
                    if transport.waitedTypes.contains("chat_turn_preflight_ack") {
                        rejectedAfterPreflight = true
                        throw NotificationReplyError.accountChanged
                    }
                    validatedBeforePreflight = true
                })
            XCTFail("The old account's message/history must not be sent through the replacement session")
        } catch NotificationReplyError.accountChanged {
            XCTAssertTrue(validatedBeforePreflight, "The original session must authorize preflight")
            XCTAssertTrue(rejectedAfterPreflight, "Replacement must reject the turn after its preflight exchange")
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

    // contract-test: direct surface=gui.apple assertions=pii.composer.detect-redact-exclude,pii.surface.semantic-parity
    func testContextualPIIPatternsReplaceTheSameFullMatchAsWeb() throws {
        let awsSecret = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmn"
        let azureSecret = "0123456789abcdef0123456789abcdef"
        let fixtures: [(text: String, type: PIIType, expectedOriginal: String)] = [
            ("password=supersecret123", .genericSecret, "password=supersecret123"),
            ("aws_secret=\(awsSecret)", .awsSecretKey, "aws_secret=\(awsSecret)"),
            ("azure_key=\(azureSecret)", .azureKey, "azure_key=\(azureSecret)"),
            ("passport no: C01X00T47", .passport, "passport no: C01X00T47"),
            ("tax id: 12-3456789", .taxId, "tax id: 12-3456789"),
            ("license plate: B AB 1234", .vehiclePlate, "license plate: B AB 1234"),
        ]

        for fixture in fixtures {
            let match = try XCTUnwrap(
                PIIDetector.detect(in: fixture.text).first { $0.type == fixture.type },
                "Expected \(fixture.type.rawValue) in \(fixture.text)"
            )
            XCTAssertEqual(match.value, fixture.expectedOriginal)
            XCTAssertEqual((fixture.text as NSString).substring(with: match.range), fixture.expectedOriginal)
            XCTAssertEqual(match.id, "pii-\(fixture.type.rawValue)-0")

            let redaction = PIIDetector.redactionResult(in: fixture.text, matches: [match])
            XCTAssertEqual(redaction.redactedText, match.placeholder)
            XCTAssertEqual(redaction.mappings.first?.original, fixture.expectedOriginal)
            XCTAssertEqual(redaction.mappings.first?.type, fixture.type.rawValue)

            let excludedRedaction = PIIDetector.redactionResult(
                in: fixture.text,
                matches: [match],
                excludedIds: [match.id]
            )
            XCTAssertEqual(
                excludedRedaction.redactedText,
                fixture.text,
                "The same stable full-match ID must preserve the current-send exclusion"
            )
            XCTAssertTrue(excludedRedaction.mappings.isEmpty)
        }
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

    // contract-test: direct surface=gui.apple assertions=message-input.recording.lifecycle,message-input.embeds.gated-send
    func testAudioOnlySendAddsDurableReferenceExactlyOnce() {
        let embed = ComposerPendingEmbed.from(
            upload: UploadFileResponse(
                embedId: "audio-embed-1",
                filename: "recording.m4a",
                contentType: "audio/mp4",
                contentHash: nil,
                files: ["original": UploadedFileVariant(
                    s3Key: "audio.bin", sizeBytes: 12, width: nil, height: nil, format: "m4a"
                )],
                s3BaseUrl: "https://example.invalid/audio",
                aesKey: "key", aesNonce: "nonce", vaultWrappedAesKey: "wrapped",
                pageCount: nil, deduplicated: false
            ),
            localData: Data([0x01]),
            transcription: TranscriptionMetadata(transcript: "Recorded request"),
            duration: 1
        )

        let audioOnly = ChatSendPipeline.contentByAppendingComposerEmbedReferences(
            "",
            composerEmbeds: [embed]
        )
        let repeated = ChatSendPipeline.contentByAppendingComposerEmbedReferences(
            audioOnly,
            composerEmbeds: [embed]
        )

        XCTAssertEqual(audioOnly, embed.markdownReference)
        XCTAssertEqual(repeated, audioOnly)
        XCTAssertEqual(
            ChatSendPipeline.provisionalTitleSource(content: audioOnly, composerEmbeds: [embed]),
            "[Audio] Recorded request"
        )
    }

    // contract-test: direct surface=gui.apple assertions=chats.surface.semantic-parity
    func testTextAndEmbedProvisionalTitleExcludesEmbedMarkup() {
        let embed = ComposerPendingEmbed.uiTestFixture
        let content = "Summarize this\n\n\(embed.markdownReference)"
        let canonical = ChatSendPipeline.contentByAppendingComposerEmbedReferences(
            "Summarize this",
            composerEmbeds: [embed]
        )

        XCTAssertEqual(
            ChatSendPipeline.provisionalTitleSource(content: content, composerEmbeds: [embed]),
            "[Image] Summarize this"
        )
        XCTAssertTrue(canonical.contains("Summarize this"))
        XCTAssertTrue(canonical.contains("\"embed_id\": \"ui-test-pending-image\""))
        let payload = embed.serverPayload
        let payloadContent = payload?["content"] as? String
        XCTAssertNotNil(payloadContent)
        let contentObject = payloadContent?.data(using: String.Encoding.utf8).flatMap {
            try? JSONSerialization.jsonObject(with: $0) as? [String: Any]
        }
        XCTAssertEqual(contentObject?["embed_ref"] as? String, "ui-test-image.png")
        XCTAssertEqual(embed.record.rawData?["embed_ref"]?.value as? String, "ui-test-image.png")
        XCTAssertEqual(embed.record.type, "images-image")
    }

    // contract-test: direct surface=gui.apple assertions=chats.surface.semantic-parity,message-input.embeds.gated-send
    func testImageUploadPreservesMediaEncryptionAndTitlesHideEmbedIdentifiers() throws {
        let uploadJSON = """
        {
          "embed_id": "image-1", "filename": "photo.jpg", "content_type": "image/jpeg",
          "files": {"original": {"s3_key": "media/photo.jpg", "encryption": "aes-gcm-nonce-prefixed-v1"}},
          "s3_base_url": "https://example.invalid", "aes_key": "key", "aes_nonce": "",
          "vault_wrapped_aes_key": "wrapped"
        }
        """
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let upload = try decoder.decode(UploadFileResponse.self, from: Data(uploadJSON.utf8))
        let embed = ComposerPendingEmbed.from(
            upload: upload, localData: nil, transcription: nil, duration: nil
        )
        let contentData = try XCTUnwrap(embed.content?.data(using: .utf8))
        let contentObject = try XCTUnwrap(
            JSONSerialization.jsonObject(with: contentData) as? [String: Any]
        )
        let files = try XCTUnwrap(contentObject["files"] as? [String: [String: Any]])
        XCTAssertEqual(files["original"]?["encryption"] as? String, "aes-gcm-nonce-prefixed-v1")
        XCTAssertEqual(contentObject["embed_ref"] as? String, "photo.jpg")
        XCTAssertEqual(
            ChatSendPipeline.provisionalTitleSource(content: "what is this?", composerEmbeds: [embed]),
            "[Image] what is this?"
        )
        XCTAssertEqual(
            ChatSendPipeline.titleByReplacingEmbedReferences(
                "[[embed:image-1]] what is this?", embedTypes: ["images-image"]
            ),
            "[Image] what is this?"
        )
    }

    // contract-test: direct surface=gui.apple assertions=message-input.recording.lifecycle
    func testLegacyAudioOnlyMessageRecoversItsPersistedEmbedLink() throws {
        let messageID = "legacy-audio-message"
        let messageHash = SHA256.hash(data: Data(messageID.utf8))
            .map { String(format: "%02x", $0) }
            .joined()
        XCTAssertEqual(
            messageHash,
            "b01c731376d38838b752117a8df680216c9fedf304994c2968eef09e4d6dc7f9"
        )
        let embedJSON = """
        {
          "embed_id":"legacy-audio",
          "status":"finished",
          "encrypted_type":"encrypted-type-fixture",
          "encrypted_content":"encrypted-content-fixture",
          "encrypted_text_preview":"encrypted-preview-fixture",
          "hashed_chat_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "hashed_message_id":"\(messageHash)",
          "hashed_user_id":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          "created_at":1727172000
        }
        """
        let embed = try JSONDecoder().decode(EmbedRecord.self, from: Data(embedJSON.utf8))
        let message = Message(
            id: messageID, chatId: "chat-1", role: .user, content: "",
            encryptedContent: "ciphertext", createdAt: "2026-09-24T10:00:00Z",
            updatedAt: nil, appId: nil, isStreaming: false, embedRefs: nil
        )

        let recovered = try XCTUnwrap(
            ChatLegacyEmbedLinkPolicy.applying(to: [message], embeds: [embed]).first
        )

        XCTAssertEqual(embed.hashedMessageId, messageHash)
        XCTAssertEqual(recovered.embedRefs?.map(\.id), ["legacy-audio"])
        XCTAssertTrue(recovered.content?.contains("\"embed_id\": \"legacy-audio\"") == true)

        let rawRecovery = try XCTUnwrap(ChatLegacyEmbedLinkPolicy.applying(
            to: [message],
            embeds: [embed],
            synthesizeMissingContent: false
        ).first)
        XCTAssertEqual(rawRecovery.content, "", "Raw encrypted content must still decrypt before fallback synthesis")
        XCTAssertEqual(rawRecovery.embedRefs?.map(\.id), ["legacy-audio"])
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

    // contract-test: supporting surface=gui.apple assertions=chats.streaming.progressive-presentation
    func testSendTimingRejectsHistoricalIdentityAndTracksTransientSavedHandoff() {
        let timing = NativeChatSendTiming()
        let token = timing.beginAction(chatID: "synthetic-chat")
        defer { timing.cancel(chatID: "synthetic-chat", token: token) }
        timing.bind(chatID: "synthetic-chat", messageID: "current-user")
        var lifecycle = ChatStreamingLifecycleState()
        let initiated = StreamingClient.StreamEvent.taskInitiated(chatId: "synthetic-chat", taskId: "current-task", userMessageId: "current-user")
        timing.serverEventReceived(initiated, chatID: "synthetic-chat")
        lifecycle.apply(initiated)
        let selected = StreamingClient.StreamEvent.preprocessingStep(chatId: "synthetic-chat", step: "mate_selected", data: ["mate_category": "science"])
        timing.serverEventReceived(selected, chatID: "synthetic-chat")
        lifecycle.apply(selected)
        let transient = NativeChatSendTimingBinding(chatID: "synthetic-chat", userMessageID: "current-user",
            responseID: "current-task", category: "science")
        XCTAssertNil(timing.matchingToken(transient), "Rendering cannot infer a Mate before an accepted authoritative event")
        timing.acceptedMate(lifecycle: lifecycle, receivedAt: NativeSyncPerfLog.now())
        XCTAssertEqual(timing.matchingToken(transient), token)
        XCTAssertNil(timing.matchingToken(.init(chatID: "synthetic-chat", userMessageID: "old-user", responseID: "old-response", category: "science")))
        XCTAssertNil(timing.matchingToken(.init(chatID: "synthetic-chat", userMessageID: "current-user", responseID: "old-response", category: "science")))
        lifecycle.apply(.typingStarted(chatId: "synthetic-chat", messageId: "new-assistant", metadata: nil))
        timing.acceptedMate(lifecycle: lifecycle, receivedAt: NativeSyncPerfLog.now())
        XCTAssertNil(timing.matchingToken(transient), "A retired transient cannot satisfy the saved response's frame")
        let saved = NativeChatSendTimingBinding(chatID: "synthetic-chat", userMessageID: "current-user",
            responseID: "new-assistant", category: "science")
        XCTAssertEqual(timing.matchingToken(saved), token)
        XCTAssertTrue(timing.awaitingFrame(saved))
        timing.frameOpportunity(transient, token: token)
        XCTAssertTrue(timing.awaitingFrame(saved), "A stale scheduled callback must not finish the new identity")
        timing.frameOpportunity(saved, token: token)
        XCTAssertFalse(timing.awaitingFrame(saved))
        let replacement = timing.beginAction(chatID: "synthetic-chat")
        timing.cancel(chatID: "synthetic-chat", token: token)
        timing.bind(chatID: "synthetic-chat", messageID: "replacement-user")
        var replacementLifecycle = ChatStreamingLifecycleState()
        replacementLifecycle.apply(.taskInitiated(chatId: "synthetic-chat", taskId: "replacement-task", userMessageId: "replacement-user"))
        replacementLifecycle.apply(.preprocessingStep(chatId: "synthetic-chat", step: "mate_selected", data: ["mate_category": "science"]))
        timing.acceptedMate(lifecycle: replacementLifecycle, receivedAt: NativeSyncPerfLog.now())
        XCTAssertEqual(timing.matchingToken(.init(chatID: "synthetic-chat", userMessageID: "replacement-user",
            responseID: "replacement-task", category: "science")), replacement, "Cancelling an old action must preserve its replacement")
        timing.cancel(chatID: "synthetic-chat", token: replacement)
        XCTAssertNil(timing.matchingToken(saved))
    }

    // contract-test: supporting surface=gui.apple assertions=pii.surface.semantic-parity
    func testHistoricalPIISnapshotPreservesBothPreparationPassesAndRetryDigest() throws {
        let pipeline = ChatSendPipeline()
        let older = PIIMapping(placeholder: "[EMAIL_1_com]", original: "alice@example.com", type: "EMAIL")
        let edited = PIIMapping(placeholder: "[EMAIL_2_com]", original: "bob@example.com", type: "EMAIL")
        let history = [Self.userMessage(id: "older", mappings: [older]),
                       Self.userMessage(id: "edited", mappings: [older, edited])]
        let snapshot = pipeline.historicalPIIMappingSnapshot(in: history, excludingDigestMessageID: "edited")
        XCTAssertEqual(snapshot.preparation, [older, edited])
        XCTAssertEqual(snapshot.digest, [older], "Retry digests must exclude mappings introduced only by the original message")
        let newSnapshot = pipeline.historicalPIIMappingSnapshot(in: history, excludingDigestMessageID: nil)
        XCTAssertEqual(newSnapshot.preparation, newSnapshot.digest)
        let unknownRetry = pipeline.historicalPIIMappingSnapshot(in: history, excludingDigestMessageID: "new-id")
        XCTAssertEqual(unknownRetry.preparation, unknownRetry.digest)
        for content in ["Email alice@example.com and bob@example.com.", "[EMAIL_1_com] and bob@example.com."] {
            let before = pipeline.contentAndMappingsForSend(content: content, existingMessages: history,
                excludedPIIOriginals: ["bob@example.com"])
            let cached = pipeline.contentAndMappingsForSend(content: content, knownMappings: snapshot.preparation,
                excludedPIIOriginals: ["bob@example.com"])
            XCTAssertEqual(cached.content, before.content)
            XCTAssertEqual(cached.piiMappings, before.piiMappings)
            let secondBefore = pipeline.contentAndMappingsForSend(content: before.content, existingMessages: history,
                piiMappings: before.piiMappings, excludedPIIPlaceholders: ["[EMAIL_2_com]"])
            let secondCached = pipeline.contentAndMappingsForSend(content: cached.content, knownMappings: snapshot.preparation,
                piiMappings: cached.piiMappings, excludedPIIPlaceholders: ["[EMAIL_2_com]"])
            XCTAssertEqual(secondCached.content, secondBefore.content)
            XCTAssertEqual(secondCached.piiMappings, secondBefore.piiMappings)
        }
        let digestArguments: ([PIIMapping]) throws -> String = { mappings in
            try ChatSendPipeline.sendInputDigest(content: "alice@example.com", composerEmbeds: [], piiMappings: [],
                excludedPIIOriginals: [], excludedPIIPlaceholders: [], broadcastToSiblings: false,
                createdAtOverride: nil, isEdit: false, knownMappings: mappings)
        }
        XCTAssertEqual(try digestArguments(snapshot.digest), try digestArguments(pipeline.knownPIIMappings(in: [history[0]])))
        XCTAssertNotEqual(try digestArguments(snapshot.digest), try digestArguments(snapshot.preparation))
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
    // contract-test: supporting surface=gui.apple assertions=chats.message.confirmed-haptic
    func testMessageHapticRequiresBothDurableProofsInEitherOrder() {
        for storedFirst in [false, true] {
            var events: [NativeHaptics.Event] = []
            let output = NativeHaptics(enabled: { true }, render: { events.append($0) })
            let gate = NativeMessageHapticGate(haptics: output)
            gate.begin(turnID: "turn", chatID: "chat", messageID: "user", preflightState: "LEGACY", scope: "scope")
            let admission: [String: Any] = ["chat_id": "chat", "user_message_id": "user", "ai_task_id": "task"]
            let storage: [String: Any] = ["chat_id": "chat", "message_id": "user", "versions": ["messages_v": 1]]
            if storedFirst { gate.confirmedDurability(chatID: "chat", messageID: "user", version: 1, scope: "scope") }
            else { gate.consume(type: "ai_task_initiated", fields: admission, scope: "scope") }
            XCTAssertTrue(events.isEmpty)
            // This production legacy ACK is only queued, even with a version.
            gate.consume(type: "encrypted_metadata_stored", fields: storage, scope: "scope")
            XCTAssertTrue(events.isEmpty)
            if storedFirst { gate.consume(type: "ai_task_initiated", fields: admission, scope: "scope") }
            else { gate.confirmedDurability(chatID: "chat", messageID: "user", version: 1, scope: "scope") }
            gate.consume(type: "ai_task_initiated", fields: admission, scope: "scope")
            XCTAssertEqual(events, [.messageAccepted])
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.message.confirmed-haptic
    func testMessageHapticRejectsTypingFailuresReplayAndChangedScope() {
        var events: [NativeHaptics.Event] = []
        let gate = NativeMessageHapticGate(haptics: NativeHaptics(enabled: { true }, render: { events.append($0) }))
        let admission: [String: Any] = ["chat_id": "chat", "user_message_id": "user", "ai_task_id": "task"]
        gate.begin(turnID: "turn", chatID: "chat", messageID: "user", preflightState: "RUNNING", scope: "scope")
        gate.consume(type: "ai_task_initiated", fields: admission, scope: "scope")
        XCTAssertTrue(events.isEmpty)
        gate.begin(turnID: "turn", chatID: "chat", messageID: "user", preflightState: "PREPARED", scope: "scope")
        gate.consume(type: "ai_typing_started", fields: admission, scope: "scope")
        var failed = admission; failed["code"] = "rejected"
        gate.consume(type: "ai_task_initiated", fields: failed, scope: "scope")
        XCTAssertTrue(events.isEmpty)
        gate.consume(type: "ai_task_initiated", fields: admission, scope: "new-scope")
        XCTAssertTrue(events.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.message.confirmed-haptic,apple-notifications.delivery.confirmed-action-haptics
    func testConfirmedHapticsDeduplicateAndNeverReplaySuppressedFeedback() {
        var enabled = false
        var events: [NativeHaptics.Event] = []
        let output = NativeHaptics(enabled: { enabled }, render: { events.append($0) })
        output.confirmed(.notification, id: "notice", scope: "owner")
        enabled = true
        output.confirmed(.notification, id: "notice", scope: "owner")
        XCTAssertTrue(events.isEmpty)
        for event in NativeHaptics.Event.allCases {
            output.confirmed(event, id: "operation", scope: "owner")
            output.confirmed(event, id: "operation", scope: "owner")
        }
        XCTAssertEqual(events, NativeHaptics.Event.allCases)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.message.confirmed-haptic
    func testMessageHapticCancelsFailedWritesAndNeverRearmsRetries() {
        var events: [NativeHaptics.Event] = []
        let gate = NativeMessageHapticGate(haptics: NativeHaptics(enabled: { true }, render: { events.append($0) }))
        let fields: [String: Any] = ["chat_id": "chat", "user_message_id": "user", "ai_task_id": "task"]
        gate.begin(turnID: "failed-turn", chatID: "chat", messageID: "user", preflightState: "PREPARED", scope: "first")
        gate.cancel(messageID: "user", scope: "first")
        gate.consume(type: "ai_task_initiated", fields: fields, scope: "first")
        gate.begin(turnID: "failed-turn", chatID: "chat", messageID: "user", preflightState: "PREPARED", scope: "reconnect", committedVersion: 1)
        gate.consume(type: "ai_task_initiated", fields: fields, scope: "reconnect")
        XCTAssertTrue(events.isEmpty)
        gate.begin(turnID: "fresh-turn", chatID: "chat", messageID: "user", preflightState: "PREPARED", scope: "reconnect", committedVersion: 1)
        gate.consume(type: "ai_task_initiated", fields: fields, scope: "reconnect")
        XCTAssertEqual(events, [.messageAccepted])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.message.confirmed-haptic
    func testProductionSendWiresOnlyFreshConfirmedProcessingToHapticGate() async throws {
        for (state, optedIn, expectedCount) in [("PREPARED", true, 1), ("PREPARED", false, 0), ("LEGACY", true, 0)] {
            var events: [NativeHaptics.Event] = []
            let gate = NativeMessageHapticGate(haptics: NativeHaptics(enabled: { true }, render: { events.append($0) }))
            let transport = NotificationReceiptTransport(state: state)
            let payloads = Self.notificationTurnPayloads()
            let send = Task { @MainActor in
                try await ChatSendPipeline().sendSavedChatTurn(turnId: "turn-a",
                    preflightPayload: payloads.preflight, outboundPayload: payloads.outbound,
                    transport: transport, waitForInferenceReceipt: true, confirmHaptic: optedIn,
                    hapticConfirmation: gate, suppliedHapticScope: "synthetic-scope")
            }
            for _ in 0..<1_000 where transport.receiptPredicate == nil { await Task.yield() }
            XCTAssertNotNil(transport.receiptPredicate)
            XCTAssertTrue(events.isEmpty, "Preflight persistence and socket write alone cannot vibrate")
            transport.deliver(["chat_id": "chat-a", "user_message_id": "message-a", "ai_task_id": "task-a"])
            try await send.value
            XCTAssertEqual(events.count, expectedCount)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.message.confirmed-haptic
    func testStorageProofRejectsQueueAcknowledgementsAndInvalidVersions() {
        XCTAssertEqual(NativeMessageHapticGate.preparedStorageVersion(["state": "PREPARED", "committed_messages_v": 3], expected: 2), 3)
        let invalidVersions: [Any] = [true, 3.0, -1, "3", 4]
        for version in invalidVersions {
            XCTAssertNil(NativeMessageHapticGate.preparedStorageVersion(["state": "PREPARED", "committed_messages_v": version], expected: 2))
        }
        XCTAssertNil(NativeMessageHapticGate.preparedStorageVersion(["state": "LEGACY", "committed_messages_v": 3], expected: 2))
        XCTAssertNil(NativeMessageHapticGate.preparedStorageVersion(["status": "queued_for_storage", "versions": ["messages_v": 3]], expected: 2))
    }

}

private extension ChatSendPipelineParityTests {
    static func notificationTurnPayloads() -> (preflight: [String: Any], outbound: [String: Any]) {
        let outbound: [String: Any] = ["turn_id": "turn-a", "chat_id": "chat-a",
            "message": ["message_id": "message-a", "content": "Which city?"]]
        return (["turn_id": "turn-a", "inference_request": outbound, "expected_messages_v": 0], outbound)
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
            let fields: [String: Any] = ["turn_id": "turn-a", "preflight_id": "preflight-a", "state": state, "committed_messages_v": 1]
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

    func sendAndWait(_ message: WSOutboundMessage, responseType: String, timeout: Duration,
                     matching predicate: @escaping ([String: Any]) -> Bool,
                     beforeSend: @escaping @MainActor () throws -> Void) async throws -> WebSocketResponse {
        try beforeSend()
        return try await sendAndWait(message, responseType: responseType, timeout: timeout, matching: predicate)
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

private actor OverlappingChatKeyGate {
    private var calls = 0
    private var firstStarted = false
    private var startedWaiter: CheckedContinuation<Void, Never>?
    private var firstRelease: CheckedContinuation<Void, Never>?

    func generate() async -> SymmetricKey {
        calls += 1
        if calls == 1 {
            firstStarted = true
            startedWaiter?.resume()
            startedWaiter = nil
            await withCheckedContinuation { firstRelease = $0 }
            return SymmetricKey(data: Data(repeating: 0x11, count: 32))
        }
        return SymmetricKey(data: Data(repeating: 0x22, count: 32))
    }

    func waitForFirstGeneration() async {
        if firstStarted { return }
        await withCheckedContinuation { startedWaiter = $0 }
    }

    func releaseFirstGeneration() {
        firstRelease?.resume()
        firstRelease = nil
    }
}
