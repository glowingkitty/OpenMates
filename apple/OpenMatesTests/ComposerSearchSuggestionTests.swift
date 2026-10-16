import Combine
import XCTest
@testable import OpenMates

@MainActor
final class ComposerSearchSuggestionTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=message-input.suggestions.contextual,message-input.privacy-context
    func testSearchIncludesVisibleOwnerChatsAndExcludesHiddenSubchatAndIncognito() throws {
        let decoder = JSONDecoder()
        func chat(_ id: String, extra: [String: Any] = [:]) throws -> Chat {
            var row: [String: Any] = ["id": id, "title": "Berlin", "created_at": "2026-09-29T12:00:00Z"]
            row.merge(extra) { _, new in new }
            return try decoder.decode(Chat.self, from: JSONSerialization.data(withJSONObject: row))
        }
        let owner = try chat("owner")
        let visible = ComposerSearchSuggestionsController.eligibleChats([
            owner, owner, try chat("hidden", extra: ["is_hidden": true]),
            try chat("child", extra: ["parent_id": "owner", "is_sub_chat": true]), try chat("incognito-test")])
        XCTAssertEqual(visible.map(\.id), ["owner"])
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.suggestions.contextual,message-input.privacy-context
    func testEmbedSearchUsesDisplayFieldsAndNeverEncryptionOrAccountFields() throws {
        func embed(_ id: String, fields: [String: String], status: EmbedStatus = .finished) -> EmbedRecord {
            EmbedRecord(id: id, type: "code-notebook", status: status, data: .raw(fields.mapValues(AnyCodable.init)),
                encryptedContent: nil, encryptedType: nil, encryptedTextPreview: nil, parentEmbedId: nil,
                appId: "code", skillId: nil, embedIds: nil, createdAt: nil)
        }
        let records = [embed("display", fields: ["filename": "Berlin notebook"]),
            embed("key", fields: ["filename": "Safe file", "aes_key": "Berlin", "user_id": "Berlin", "url": "Berlin"]),
            embed("pending", fields: ["filename": "Berlin"], status: .processing)]
        XCTAssertEqual(ComposerSearchSuggestionsController.searchEmbeds(query: "berlin", records: records).map(\.id), ["display"])
        XCTAssertTrue(ComposerSearchSuggestionsController.searchEmbeds(query: " ", records: records).isEmpty)
    }

    // contract-test: direct surface=gui.apple assertions=message-input.embeds.gated-send
    func testSelectingExistingEmbedPreservesTextAndDurableReferenceWithoutUploadPayload() throws {
        let result = ComposerEmbedSearchResult(record: DevComposerSearchPreview.fixtureEmbed,
            title: "Berlin notebook", appID: "code")
        let session = NativeComposerSession(canonicalMarkdown: "Plan Berlin")
        try session.controller.setSelection(NSRange(location: 0, length: 4))
        try result.insert(into: session, nodeID: "selected")
        XCTAssertTrue(session.canonicalMarkdown.contains("Plan Berlin"))
        XCTAssertTrue(session.canonicalMarkdown.contains(result.id))
        XCTAssertFalse(session.hasBlockingEmbeds)
        XCTAssertEqual(session.controller.document.nodes.first(where: { $0.id == "selected" })?.contentRef, "embed:\(result.id)")
        XCTAssertNil(result.pendingReference.serverPayload)
        try session.removeEmbed(nodeID: "selected")
        XCTAssertTrue(session.canonicalMarkdown.contains("Plan Berlin"))
        XCTAssertFalse(session.canonicalMarkdown.contains(result.id))
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.suggestions.contextual,message-input.privacy-context
    func testGuestSearchCannotReadRetainedPersonalStoreRows() async throws {
        let controller = ComposerSearchSuggestionsController()
        let store = ChatStore()
        let personal = Chat(id: "retained-owner", title: "OpenMates private plans", lastMessageAt: nil,
            createdAt: "2026-09-29T12:00:00Z", updatedAt: nil, isArchived: false, isPinned: false,
            appId: "ai", encryptedTitle: nil, encryptedChatKey: nil)
        let publicChat = try XCTUnwrap(PublicChatContent.chat(for: "announcements-introducing-openmates-v09"))
        store.performWithoutPersistence { store.upsertChats([personal, publicChat.chat]) }
        controller.schedule(text: "OpenMates", store: store, authenticated: false, accountID: nil)
        try? await Task.sleep(for: .milliseconds(500))
        XCTAssertFalse(controller.chats.contains(where: { $0.id == personal.id }))
        XCTAssertTrue(controller.chats.contains(where: { $0.id == publicChat.chat.id }))
        controller.cancel()
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.suggestions.contextual
    func testObservedProductionStoreHydrationCompletesAndLaterExternalUpdatesRefresh() async throws {
        let controller = ComposerSearchSuggestionsController()
        let store = ChatStore()
        let hydrated = Chat(id: "hydrated-berlin", title: "Berlin hydrated title", lastMessageAt: nil,
            createdAt: "2026-09-29T12:00:00Z", updatedAt: nil, isArchived: false, isPinned: false,
            appId: "travel", encryptedTitle: nil, encryptedChatKey: nil)
        let later = Chat(id: "external-berlin", title: "Berlin external arrival", lastMessageAt: nil,
            createdAt: "2026-09-30T12:00:00Z", updatedAt: nil, isArchived: false, isPinned: false,
            appId: "travel", encryptedTitle: nil, encryptedChatKey: nil)
        var hydrationCalls = 0
        var hydrationWasCancelled = false
        let prepareMetadata: () async -> Void = {
            hydrationCalls += 1
            // Use the real mutation and publisher that the welcome/chat hosts
            // observe. Also exercise the historical empty-upsert notification.
            store.performWithoutPersistence { store.upsertChats([]); store.upsertChats([hydrated]) }
            await Task.yield()
            hydrationWasCancelled = hydrationWasCancelled || Task.isCancelled
        }
        let observation = store.objectWillChange.sink {
            controller.schedule(text: "Berlin", store: store, authenticated: true, accountID: nil,
                prepareMetadata: prepareMetadata, storeChanged: true)
        }
        defer { observation.cancel(); controller.cancel() }
        controller.schedule(text: "Berlin", store: store, authenticated: true, accountID: nil,
            prepareMetadata: prepareMetadata)
        // Bound the observation window; a self-cancellation loop never emits
        // its hydrated result, while a completed pass does so after one debounce.
        for _ in 0..<150 where controller.chats.isEmpty {
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTAssertEqual(controller.chats.map(\.id), [hydrated.id])
        XCTAssertEqual(hydrationCalls, 1)
        XCTAssertFalse(hydrationWasCancelled)
        store.performWithoutPersistence { store.upsertChats([later]) }
        for _ in 0..<150 where !controller.chats.contains(where: { $0.id == later.id }) {
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTAssertEqual(Set(controller.chats.map(\.id)), [hydrated.id, later.id])
        XCTAssertEqual(hydrationCalls, 2)
        XCTAssertFalse(hydrationWasCancelled)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.suggestions.contextual,message-input.privacy-context
    func testReplacementAccountStoreEventCancelsSuspendedSearchInsteadOfCoalescing() async throws {
        let controller = ComposerSearchSuggestionsController()
        let oldStore = ChatStore()
        let newStore = ChatStore()
        func row(_ id: String) -> Chat {
            Chat(id: id, title: "Berlin synthetic title", lastMessageAt: nil,
                createdAt: "2026-09-29T12:00:00Z", updatedAt: nil, isArchived: false,
                isPinned: false, appId: "travel", encryptedTitle: nil, encryptedChatKey: nil)
        }
        oldStore.performWithoutPersistence { oldStore.upsertChats([row("old-account")]) }
        newStore.performWithoutPersistence { newStore.upsertChats([row("replacement-account")]) }
        var suspended: CheckedContinuation<Void, Never>?
        var oldSearchCancelled = false
        controller.schedule(text: "Berlin", store: oldStore, authenticated: true, accountID: "synthetic-old", prepareMetadata: {
            await withCheckedContinuation { suspended = $0 }
            oldSearchCancelled = Task.isCancelled
        })
        defer { suspended?.resume(); controller.cancel() }
        for _ in 0..<150 where suspended == nil { try await Task.sleep(for: .milliseconds(10)) }
        XCTAssertNotNil(suspended)
        // The observed publication is from the replacement owner/store. It
        // must supersede the suspended search despite being marked storeChanged.
        controller.schedule(text: "Berlin", store: newStore, authenticated: true,
            accountID: "synthetic-new", storeChanged: true)
        suspended?.resume()
        suspended = nil
        for _ in 0..<150 where controller.chats.isEmpty { try await Task.sleep(for: .milliseconds(10)) }
        XCTAssertTrue(oldSearchCancelled)
        XCTAssertEqual(controller.chats.map(\.id), ["replacement-account"])
        XCTAssertFalse(controller.chats.contains { $0.id == "old-account" })
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.suggestions.contextual,message-input.privacy-context
    func testEmptyQueryStoreEventCancelsSuspendedSearchAndSuppressesLateResults() async throws {
        let controller = ComposerSearchSuggestionsController()
        let store = ChatStore()
        var suspended: CheckedContinuation<Void, Never>?
        var oldSearchReturned = false
        var oldSearchCancelled = false
        controller.schedule(text: "Berlin", store: store, authenticated: true, accountID: nil, prepareMetadata: {
            await withCheckedContinuation { suspended = $0 }
            oldSearchCancelled = Task.isCancelled
            oldSearchReturned = true
        })
        defer { suspended?.resume(); controller.cancel() }
        for _ in 0..<150 where suspended == nil { try await Task.sleep(for: .milliseconds(10)) }
        XCTAssertNotNil(suspended)
        controller.schedule(text: "", store: store, authenticated: true, accountID: nil, storeChanged: true)
        suspended?.resume()
        suspended = nil
        for _ in 0..<150 where !oldSearchReturned { try await Task.sleep(for: .milliseconds(10)) }
        XCTAssertTrue(oldSearchReturned)
        XCTAssertTrue(oldSearchCancelled)
        XCTAssertEqual(controller.query, "")
        XCTAssertFalse(controller.hasResults)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.suggestions.contextual
    func testClearingOrReplacingTypedQueryDiscardsDebouncedResults() async {
        let controller = ComposerSearchSuggestionsController()
        let store = ChatStore()
        controller.schedule(text: "Berlin", store: store, authenticated: false, accountID: nil)
        controller.schedule(text: "", store: store, authenticated: false, accountID: nil)
        try? await Task.sleep(for: .milliseconds(450))
        XCTAssertEqual(controller.query, "")
        XCTAssertFalse(controller.hasResults)
    }
}
