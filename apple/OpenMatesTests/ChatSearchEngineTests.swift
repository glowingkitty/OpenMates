// Specification: specifications/features/message-input/specification.yml
// Assertions: message-input.suggestions.contextual, message-input.privacy-context
import XCTest
@testable import OpenMates

@MainActor
final class ChatSearchEngineTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=message-input.suggestions.contextual,message-input.privacy-context
    func testSettledSameQueryRefreshKeepsRowsButReplacementQueryClearsThemAndRejectsLateRefresh() async throws {
        let controller = ChatSearchController()
        defer { controller.cancel() }
        func results(_ ids: [String]) -> ChatSearchResults {
            let items = ids.map { id in
                let chat = Chat(id: id, title: "Berlin", lastMessageAt: nil, createdAt: "2026-09-29T12:00:00Z",
                    updatedAt: nil, isArchived: false, isPinned: false, appId: "ai", encryptedTitle: nil, encryptedChatKey: nil)
                return ChatSearchResult(id: id, chat: chat, decryptedTitle: chat.title, titleMatch: true,
                    messageSnippets: [], metadataSnippets: [], sortDate: .distantPast)
            }
            return .init(groups: [.init(id: "synthetic", title: "Synthetic", items: items)], totalCount: items.count)
        }
        controller.retainResults(for: ["retained", "deleted", "new-query"])
        controller.schedule(query: "Berlin", immediately: true) { _ in results(["retained", "deleted"]) }
        try await waitUntil { controller.results.totalCount == 2 && !controller.isSearching }
        var refresh: CheckedContinuation<ChatSearchResults, Never>?
        controller.schedule(query: "Berlin", storeChanged: true, immediately: true) { _ in
            await withCheckedContinuation { refresh = $0 }
        }
        try await waitUntil { refresh != nil }
        XCTAssertEqual(controller.results.groups.flatMap(\.items).map(\.id), ["retained", "deleted"],
            "A settled same-query refresh must leave tappable rows mounted")
        controller.retainResults(for: ["retained", "new-query"])
        XCTAssertEqual(controller.results.groups.flatMap(\.items).map(\.id), ["retained"],
            "Deletion removes a retained row before background refresh completes")
        var replacement: CheckedContinuation<ChatSearchResults, Never>?
        controller.schedule(query: "Paris", immediately: true) { _ in
            await withCheckedContinuation { replacement = $0 }
        }
        XCTAssertEqual(controller.results.totalCount, 0, "Changed query must clear mismatching old rows immediately")
        try await waitUntil { replacement != nil }
        refresh?.resume(returning: results(["deleted", "retained"]))
        replacement?.resume(returning: results(["new-query"]))
        try await waitUntil { controller.results.totalCount == 1 && !controller.isSearching }
        XCTAssertEqual(controller.results.groups.flatMap(\.items).map(\.id), ["new-query"])
    }

    // contract-test: supporting surface=gui.apple assertions=landing-onboarding.legacy-intros-retired,public-example-chats.catalog.discoverable
    func testRetiredIntroVisibilityKeepsExamplesAndSameTitlePersonalChats() throws {
        for id in RetiredIntroChatPolicy.ids {
            XCTAssertTrue(RetiredIntroChatPolicy.excludes(id))
            XCTAssertFalse(PublicChatContent.isPublicChat(id))
            XCTAssertNil(PublicChatContent.chat(for: id))
        }
        let example = try XCTUnwrap(PublicChatContent.chat(for: "example-gigantic-airplanes")?.chat)
        let personal = Chat(id: "personal-copy", title: "Who develops OpenMates?", lastMessageAt: nil,
            createdAt: "2026-09-29T12:00:00Z", updatedAt: nil, isArchived: false, isPinned: false,
            appId: "ai", encryptedTitle: nil, encryptedChatKey: nil)
        let retired = Chat(id: "demo-who-develops-openmates", title: personal.title, lastMessageAt: nil,
            createdAt: personal.createdAt, updatedAt: nil, isArchived: false, isPinned: false,
            appId: "ai", encryptedTitle: nil, encryptedChatKey: nil)
        let rows = [retired, example, personal]
        XCTAssertEqual(ComposerSearchSuggestionsController.eligibleChats(rows).map(\.id), [example.id, personal.id])
        XCTAssertEqual(ChatSearchMetadata.missingCachedChats(rows, loaded: []).map(\.id), [example.id, personal.id])
        let store = ChatStore()
        store.performWithoutPersistence { store.upsertChats(rows) }
        XCTAssertEqual(ChatSearchEngine.search(query: "Who develops", chats: rows, chatStore: store,
            offlineStore: nil, offlineContentChatIds: []).groups.flatMap(\.items).map(\.id), [personal.id])
        XCTAssertNotNil(store.chat(for: retired.id), "Visibility retirement must not delete cached records")
    }

    private func waitUntil(_ predicate: () -> Bool) async throws {
        for _ in 0..<250 {
            if predicate() { return }
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTFail("Search did not settle in the bounded observation window")
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.suggestions.contextual,message-input.privacy-context
    func testBundledFixtureCacheRejectsPrivateIDsAndRebuildsOnlyOnLocaleChange() {
        var cache = LocalizedPublicChatCache<String>()
        var builds = 0
        let allowed: Set<String> = ["example-public"]
        let build = { builds += 1; return "fixture-\(builds)" }
        XCTAssertNil(cache.value(for: "account-chat", locale: "en", allowedIDs: allowed, build: build))
        XCTAssertEqual(builds, 0)
        XCTAssertEqual(cache.value(for: "example-public", locale: "en", allowedIDs: allowed, build: build), "fixture-1")
        for _ in 0..<600 {
            XCTAssertEqual(cache.value(for: "example-public", locale: "en", allowedIDs: allowed, build: build), "fixture-1")
        }
        XCTAssertEqual(builds, 1)
        XCTAssertEqual(cache.value(for: "example-public", locale: "de", allowedIDs: allowed, build: build), "fixture-2")
        XCTAssertEqual(cache.value(for: "example-public", locale: "en", allowedIDs: allowed, build: build), "fixture-3")
        XCTAssertEqual(builds, 3)
        XCTAssertFalse(PublicChatContent.isPublicChat("account-chat"))
        XCTAssertNil(PublicChatContent.chat(for: "account-chat"))
        for id in ["announcements-introducing-openmates-v09",
                   "legal-privacy", "legal-terms", "legal-imprint", "example-gigantic-airplanes",
                   "example-artemis-ii-mission", "example-beautiful-single-page-html",
                   "example-eu-chat-control-law", "example-flights-berlin-bangkok",
                   "example-creativity-drawing-meetups-berlin"] {
            XCTAssertTrue(PublicChatContent.isPublicChat(id))
            XCTAssertNotNil(PublicChatContent.chat(for: id))
        }
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.suggestions.contextual
    func testMetadataBurstFinishesCurrentPassAndCoalescesOneFollowup() async throws {
        let controller = ChatSearchController()
        defer { controller.cancel() }
        var calls = 0
        var pending: [CheckedContinuation<ChatSearchResults, Never>] = []
        let search: @MainActor (String) async throws -> ChatSearchResults = { _ in
            calls += 1
            return await withCheckedContinuation { pending.append($0) }
        }
        controller.schedule(query: "Berlin", immediately: true, search: search)
        try await waitUntil { calls == 1 }
        for _ in 0..<600 { controller.schedule(query: "Berlin", storeChanged: true, search: search) }
        XCTAssertEqual(calls, 1)
        pending.removeFirst().resume(returning: .init(groups: [], totalCount: 1))
        try await waitUntil { calls == 2 }
        XCTAssertEqual(controller.results.totalCount, 1, "A hydrated result publishes before another pass")
        XCTAssertFalse(controller.isSearching, "A steady metadata stream must not leave Loading visible")
        pending.removeFirst().resume(returning: .init(groups: [], totalCount: 2))
        try await waitUntil { controller.results.totalCount == 2 }
        XCTAssertEqual(calls, 2)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.suggestions.contextual,message-input.privacy-context
    func testReplacementQueryRejectsLateCancelledResult() async throws {
        let controller = ChatSearchController()
        defer { controller.cancel() }
        var old: CheckedContinuation<ChatSearchResults, Never>?
        controller.schedule(query: "Old", immediately: true) { _ in
            await withCheckedContinuation { old = $0 }
        }
        try await waitUntil { old != nil }
        controller.schedule(query: "New", immediately: true) { _ in .init(groups: [], totalCount: 7) }
        try await waitUntil { controller.results.totalCount == 7 }
        old?.resume(returning: .init(groups: [], totalCount: 99))
        try await Task.sleep(for: .milliseconds(30))
        XCTAssertEqual(controller.results.totalCount, 7)
        XCTAssertFalse(controller.isSearching)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.suggestions.contextual,message-input.privacy-context
    func testScopeReplacementCannotCoalesceIntoOldOwnerAndLateResultIsRejected() async throws {
        let controller = ChatSearchController()
        defer { controller.cancel() }
        var current = true
        var old: CheckedContinuation<ChatSearchResults, Never>?
        controller.schedule(query: "Berlin", immediately: true, isCurrent: { current }) { _ in
            await withCheckedContinuation { old = $0 }
        }
        try await waitUntil { old != nil }
        current = false
        controller.schedule(query: "Berlin", storeChanged: true, immediately: true) { _ in
            .init(groups: [], totalCount: 2)
        }
        try await waitUntil { controller.results.totalCount == 2 }
        old?.resume(returning: .init(groups: [], totalCount: 99))
        try await Task.sleep(for: .milliseconds(30))
        XCTAssertEqual(controller.results.totalCount, 2)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.suggestions.contextual,message-input.privacy-context
    func testScopeInvalidationAndDisappearanceClearPlaintextResults() async throws {
        let controller = ChatSearchController()
        var current = true
        var pending: CheckedContinuation<ChatSearchResults, Never>?
        controller.schedule(query: "Berlin", immediately: true, isCurrent: { current }) { _ in
            await withCheckedContinuation { pending = $0 }
        }
        try await waitUntil { pending != nil }
        current = false
        pending?.resume(returning: .init(groups: [], totalCount: 99))
        try await waitUntil { !controller.isSearching }
        XCTAssertEqual(controller.results.totalCount, 0)
        controller.schedule(query: "New", immediately: true) { _ in .init(groups: [], totalCount: 7) }
        try await waitUntil { controller.results.totalCount == 7 }
        controller.cancel()
        XCTAssertEqual(controller.results.totalCount, 0)
        XCTAssertFalse(controller.isSearching)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.suggestions.contextual,message-input.privacy-context
    func testAsyncMatcherPreservesTitleMessageMetadataPublicAndHiddenSearchOutcomes() async throws {
        let store = ChatStore()
        func chat(_ id: String, _ title: String, extra: [String: Any] = [:]) throws -> Chat {
            var row: [String: Any] = ["id": id, "title": title, "created_at": "2026-09-29T12:00:00Z"]
            row.merge(extra) { _, new in new }
            return try JSONDecoder().decode(Chat.self, from: JSONSerialization.data(withJSONObject: row))
        }
        let rows = try [chat("title", "Berlin title"), chat("message", "Other"),
                        chat("metadata", "Other", extra: ["chatSummary": "Berlin summary"]),
                        chat("hidden", "Berlin secret", extra: ["is_hidden": true])]
        let message = Message(id: "match", chatId: "message", role: .assistant,
            content: "**Berlin** travel plan", encryptedContent: nil, createdAt: "2026-09-29T12:00:00Z",
            updatedAt: nil, appId: nil, isStreaming: false, embedRefs: nil)
        store.performWithoutPersistence {
            store.upsertChats(rows)
            store.setMessages(for: "message", messages: [message])
        }
        let ids = Set(rows.map(\.id))
        let reference = ChatSearchEngine.search(query: "berlin", chats: rows, chatStore: store,
            offlineStore: nil, offlineContentChatIds: ids)
        let result = try await ChatSearchEngine.searchAsync(query: "berlin", chats: rows, chatStore: store,
            offlineStore: nil, offlineContentChatIds: ids)
        XCTAssertEqual(result.totalCount, 3)
        XCTAssertEqual(result.groups.flatMap(\.items).map(\.id), reference.groups.flatMap(\.items).map(\.id))
        XCTAssertEqual(result.groups.flatMap(\.items).first(where: { $0.id == "message" })?.messageSnippets.first?.text,
                       "Berlin travel plan")
        let publicRow = try XCTUnwrap(PublicChatContent.chat(for: "announcements-introducing-openmates-v09")?.chat)
        let publicResult = try await ChatSearchEngine.searchAsync(query: "OpenMates", chats: [publicRow],
            chatStore: store, offlineStore: nil, offlineContentChatIds: [publicRow.id])
        XCTAssertEqual(publicResult.totalCount, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.suggestions.contextual,message-input.privacy-context
    func testAsyncMatcherStopsAtBatchScopeFence() async throws {
        let store = ChatStore()
        let rows = (0..<600).map { index in
            Chat(id: "local-\(index)", title: "Berlin", lastMessageAt: nil,
                createdAt: "2026-09-29T12:00:00Z", updatedAt: nil, isArchived: false, isPinned: false,
                appId: "ai", encryptedTitle: nil, encryptedChatKey: nil)
        }
        var checks = 0
        do {
            _ = try await ChatSearchEngine.searchAsync(query: "Berlin", chats: rows, chatStore: store,
                offlineStore: nil, offlineContentChatIds: [], isCurrent: {
                    checks += 1
                    return checks < 2
                })
            XCTFail("Obsolete scope must throw before scanning another batch or returning results")
        } catch is CancellationError {
            XCTAssertEqual(checks, 2)
        }
    }
}
