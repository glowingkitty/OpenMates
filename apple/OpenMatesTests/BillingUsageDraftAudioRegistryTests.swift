// Synthetic scoped storage; no account, network, microphone, or recording bytes.
import XCTest
@testable import OpenMates

@MainActor
final class BillingUsageDraftAudioRegistryTests: XCTestCase {
    private var suite: String!
    private var defaults: UserDefaults!
    private let chatID = "00000000-0000-0000-0000-000000000370"
    private let otherChatID = "00000000-0000-0000-0000-000000000371"

    override func setUpWithError() throws {
        suite = "org.openmates.tests.draft-audio.\(UUID().uuidString)"
        defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
    }
    override func tearDownWithError() throws { defaults.removePersistentDomain(forName: suite) }
    private func registry(now: @escaping () -> Date = Date.init) -> BillingUsageDraftAudioRegistry {
        BillingUsageDraftAudioRegistry(defaults: defaults, now: now, validate: { _ in })
    }
    private func allocation(_ id: String, fence: UserTasksAccountFence) throws -> BillingUsageDraftAudioRegistry.ConfirmedPreallocation {
        try XCTUnwrap(.init(draftChatID: id, recordingChatID: id, isNewChatComposer: true,
            hasAcceptedUserMessage: false, teamID: fence.teamID))
    }

    // contract-test: supporting surface=gui.apple assertions=billing.usage.landing-complete,billing.access.authenticated-first-party
    func testOnlyExplicitMatchingNewDraftAllocationCanCreateMarker() {
        XCTAssertNil(BillingUsageDraftAudioRegistry.ConfirmedPreallocation(draftChatID: chatID,
            recordingChatID: otherChatID, isNewChatComposer: true, hasAcceptedUserMessage: false, teamID: nil))
        XCTAssertNil(BillingUsageDraftAudioRegistry.ConfirmedPreallocation(draftChatID: chatID,
            recordingChatID: chatID, isNewChatComposer: false, hasAcceptedUserMessage: false, teamID: nil))
        XCTAssertNil(BillingUsageDraftAudioRegistry.ConfirmedPreallocation(draftChatID: chatID,
            recordingChatID: chatID, isNewChatComposer: true, hasAcceptedUserMessage: true, teamID: nil))
        XCTAssertNil(BillingUsageDraftAudioRegistry.ConfirmedPreallocation(draftChatID: "incognito",
            recordingChatID: "incognito", isNewChatComposer: true, hasAcceptedUserMessage: false, teamID: nil))
    }

    // contract-test: supporting surface=gui.apple assertions=billing.usage.landing-complete,billing.access.authenticated-first-party
    func testDiscardAndColdReloadKeepPrivateMarkerInItsOwnerScope() async throws {
        let a = UserTasksAccountFence(accountID: "synthetic-owner-a")
        let b = UserTasksAccountFence(accountID: "synthetic-owner-b")
        let first = registry()
        _ = try await first.mark(allocation(chatID, fence: a), fence: a)
        // Discard has no registry deletion operation and a fresh instance retains evidence.
        let restored = registry()
        let retained = try await restored.contains(chatID: chatID, fence: a)
        let otherOwner = try await restored.contains(chatID: chatID, fence: b)
        XCTAssertTrue(retained); XCTAssertFalse(otherOwner)
        let bytes = try XCTUnwrap(defaults.data(forKey: BillingUsageDraftAudioRegistry.storageKey))
        let text = String(decoding: bytes, as: UTF8.self)
        XCTAssertFalse(text.contains(chatID)); XCTAssertFalse(text.contains("synthetic-owner-a"))
        XCTAssertFalse(text.contains(a.serverProfile.apiBaseURL.absoluteString))
    }

    // contract-test: supporting surface=gui.apple assertions=billing.access.authenticated-first-party
    func testPersistentIdentitySeparatesAccountProfileServerAndTeam() {
        func key(_ account: String, _ profile: ServerProfile, _ team: String?) -> String {
            BillingUsageDraftAudioRegistry.persistentNamespace(accountID: account, profile: profile, teamID: team)
        }
        let keys = [key("owner-a", .production, nil), key("owner-b", .production, nil),
                    key("owner-a", .development, nil), key("owner-a", .production, "team-a"),
                    key("owner-a", .production, "team-b")]
        XCTAssertEqual(Set(keys).count, keys.count)
        XCTAssertTrue(keys.allSatisfy { $0.count == 64 })
    }

    // contract-test: supporting surface=gui.apple assertions=billing.usage.landing-complete
    func testOnlyMatchingDurableOrdinarySendReceiptClearsMarker() async throws {
        let scope = UserTasksAccountFence(accountID: "synthetic-owner-a")
        let store = registry()
        _ = try await store.mark(allocation(chatID, fence: scope), fence: scope)
        try await store.registerOrdinarySend(chatID: chatID, messageID: "ordinary-message", role: .user, fence: scope)
        let ignored: [(String, [String: Any])] = [
            ("error", ["chat_id": chatID, "message_id": "ordinary-message", "new_messages_v": 1]),
            ("chat_message_confirmed", ["chat_id": chatID, "message_id": "ordinary-message", "status": "synced"]),
            ("chat_message_confirmed", ["chat_id": chatID, "message_id": "other-message", "new_messages_v": 1])
        ]
        for (type, fields) in ignored { try await store.consumeAcceptedMessage(type: type, fields: fields, fence: scope) }
        let pending = try await store.contains(chatID: chatID, fence: scope)
        XCTAssertTrue(pending, "Queued, rejected and metadata-only receipts must retain draft evidence")
        try await store.consumeAcceptedMessage(type: "chat_message_confirmed",
            fields: ["chat_id": chatID, "message_id": "ordinary-message", "new_messages_v": 1], fence: scope)
        let sent = try await store.contains(chatID: chatID, fence: scope)
        XCTAssertFalse(sent)
    }

    // contract-test: supporting surface=gui.apple assertions=billing.usage.landing-complete
    func testValidatedPersistedRetryClearsOnlyAfterAdmission() async throws {
        let scope = UserTasksAccountFence(accountID: "synthetic-owner-a")
        let store = registry()
        _ = try await store.mark(allocation(chatID, fence: scope), fence: scope)
        try await store.registerOrdinarySend(chatID: chatID, messageID: "ordinary", role: .user, fence: scope)
        try await store.acceptPersistedOrdinaryTurn(chatID: chatID, messageID: "ordinary", state: "PREPARED", fence: scope)
        let prepared = try await store.contains(chatID: chatID, fence: scope)
        XCTAssertTrue(prepared)
        try await store.acceptPersistedOrdinaryTurn(chatID: chatID, messageID: "ordinary", state: "ENQUEUED", fence: scope)
        let accepted = try await store.contains(chatID: chatID, fence: scope)
        XCTAssertFalse(accepted)
    }

    // contract-test: supporting surface=gui.apple assertions=billing.access.authenticated-first-party
    func testMismatchedTeamAllocationCannotWriteIntoCurrentTeam() async throws {
        let scope = UserTasksAccountFence(accountID: "synthetic-owner-a")
        let other = try XCTUnwrap(BillingUsageDraftAudioRegistry.ConfirmedPreallocation(
            draftChatID: chatID, recordingChatID: chatID, isNewChatComposer: true,
            hasAcceptedUserMessage: false, teamID: "synthetic-other-team"))
        let accepted = try await registry().mark(other, fence: scope)
        XCTAssertFalse(accepted)
        XCTAssertNil(defaults.data(forKey: BillingUsageDraftAudioRegistry.storageKey))
    }

    // contract-test: supporting surface=gui.apple assertions=billing.access.authenticated-first-party,billing.usage.landing-complete
    func testAssistantOrDifferentOwnerReceiptCannotClearPendingUserMarker() async throws {
        let a = UserTasksAccountFence(accountID: "synthetic-owner-a")
        let b = UserTasksAccountFence(accountID: "synthetic-owner-b")
        let store = registry()
        _ = try await store.mark(allocation(chatID, fence: a), fence: a)
        try await store.registerOrdinarySend(chatID: chatID, messageID: "assistant", role: .assistant, fence: a)
        try await store.consumeAcceptedMessage(type: "chat_message_confirmed",
            fields: ["chat_id": chatID, "message_id": "assistant", "new_messages_v": 1], fence: a)
        try await store.registerOrdinarySend(chatID: chatID, messageID: "ordinary", role: .user, fence: a)
        try await store.consumeAcceptedMessage(type: "chat_message_confirmed",
            fields: ["chat_id": chatID, "message_id": "ordinary", "new_messages_v": 1], fence: b)
        let retained = try await store.contains(chatID: chatID, fence: a)
        XCTAssertTrue(retained)
    }

    // contract-test: supporting surface=gui.apple assertions=billing.access.authenticated-first-party,billing.usage.landing-complete
    func testAuthoritativeDeleteAndAccountDataEraseOnlyRemoveTheirScopedMarkers() async throws {
        let a = UserTasksAccountFence(accountID: "synthetic-owner-a")
        let b = UserTasksAccountFence(accountID: "synthetic-owner-b")
        let store = registry()
        _ = try await store.mark(allocation(chatID, fence: a), fence: a)
        _ = try await store.mark(allocation(otherChatID, fence: a), fence: a)
        _ = try await store.mark(allocation(chatID, fence: b), fence: b)
        let cache = OfflineStore.scopeId(userId: a.accountID, apiBaseURL: a.serverProfile.apiBaseURL)
        store.removeDeletedChat(chatID: otherChatID, cacheScopeID: cache)
        let deleted = try await store.contains(chatID: otherChatID, fence: a)
        XCTAssertFalse(deleted)
        store.eraseCacheScope(cache)
        let erased = try await store.contains(chatID: chatID, fence: a)
        let preserved = try await store.contains(chatID: chatID, fence: b)
        XCTAssertFalse(erased); XCTAssertTrue(preserved)
    }

    // contract-test: supporting surface=gui.apple assertions=billing.access.authenticated-first-party
    func testStaleAllocationFailsBeforeAnyWrite() async throws {
        let scope = UserTasksAccountFence(accountID: "synthetic-owner-a")
        let store = BillingUsageDraftAudioRegistry(defaults: defaults, validate: { _ in throw CancellationError() })
        do { _ = try await store.mark(allocation(chatID, fence: scope), fence: scope); XCTFail("Expected stale fence rejection") }
        catch is CancellationError { }
        XCTAssertNil(defaults.data(forKey: BillingUsageDraftAudioRegistry.storageKey))
    }

    // contract-test: supporting surface=gui.apple assertions=billing.access.authenticated-first-party
    func testPersistentLedgerPrunesScopeAndMarkerCapacity() async throws {
        let date = Date(timeIntervalSince1970: 1_792_386_000)
        let scope = UserTasksAccountFence(accountID: "synthetic-owner-a")
        var buckets: [String: Any] = [:]
        let target = BillingUsageDraftAudioRegistry.persistentNamespace(accountID: scope.accountID,
            profile: scope.serverProfile, teamID: scope.teamID)
        var markers: [String: Double] = [:]
        for index in 0..<600 { markers[String(format: "%064x", index)] = date.timeIntervalSince1970 - 10 }
        buckets[target] = ["cacheScopeID": "synthetic-cache", "touchedAt": date.timeIntervalSince1970, "markers": markers]
        for index in 0..<10 {
            let namespace = BillingUsageDraftAudioRegistry.persistentNamespace(accountID: "synthetic-\(index)",
                profile: scope.serverProfile, teamID: nil)
            buckets[namespace] = ["cacheScopeID": "synthetic-cache-\(index)",
                "touchedAt": date.timeIntervalSince1970 - Double(index + 1), "markers": markers]
        }
        defaults.set(try JSONSerialization.data(withJSONObject: ["buckets": buckets]),
            forKey: BillingUsageDraftAudioRegistry.storageKey)
        let store = registry(now: { date })
        _ = try await store.mark(allocation(chatID, fence: scope), fence: scope)
        let data = try XCTUnwrap(defaults.data(forKey: BillingUsageDraftAudioRegistry.storageKey))
        let envelope = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let bounded = try XCTUnwrap(envelope["buckets"] as? [String: [String: Any]])
        XCTAssertEqual(bounded.count, BillingUsageDraftAudioRegistry.maximumScopes)
        XCTAssertTrue(bounded.values.allSatisfy {
            (($0["markers"] as? [String: Any])?.count ?? 0) <= BillingUsageDraftAudioRegistry.maximumMarkersPerScope
        })
    }

    // contract-test: supporting surface=gui.apple assertions=billing.usage.landing-complete
    func testRetentionBoundsAndDeletedDraftProjectionDoNotInventUsageRows() async throws {
        var date = Date(timeIntervalSince1970: 1_792_386_000)
        let scope = UserTasksAccountFence(accountID: "synthetic-owner-a")
        let store = registry(now: { date })
        _ = try await store.mark(allocation(chatID, fence: scope), fence: scope)
        let payload = """
        {"days":[{"date":"2026-10-19","total_credits":8,"items":[{"type":"chat","chat_id":"00000000-0000-0000-0000-000000000370","is_deleted":true,"total_credits":8,"entry_count":1}]}],"has_more_days":false}
        """
        let model = BillingUsageModel(transport: { path, _ in
            Data((path.hasPrefix("/v1/apps/") ? "{\"apps\":{}}" : payload).utf8)
        }, validate: { _ in }, draftAudioRegistry: store)
        await model.load(tab: .overview, accountID: scope.accountID)
        XCTAssertEqual(model.groups.first?.rows.count, 1)
        XCTAssertEqual(model.groups.first?.rows.first?.title, AppStrings.usageUnsentDraft)
        XCTAssertEqual(model.groups.first?.credits, 8)
        date = date.addingTimeInterval(BillingUsageDraftAudioRegistry.retention + 1)
        let expired = try await store.contains(chatID: chatID, fence: scope)
        XCTAssertFalse(expired)
        XCTAssertNil(defaults.data(forKey: BillingUsageDraftAudioRegistry.storageKey), "Expired data must be removed from disk")
    }
}
