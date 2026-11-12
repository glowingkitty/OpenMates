// Tests of `CoreDrafts` (Core/CoreBridge/CoreDrafts.swift) and of the draft
// calls `DraftService` makes through it: save and clear reach the core in
// order, a burst behind a running call sends only the latest request, chats do
// not wait for each other, sign-out drops the waiting requests, a typed core
// error is kept and an app without a core drops the requests. The new-chat
// composer's draft reaches the core under its allocated chat id and an empty
// composer clears the core draft. Reading returns the core's draft, nil or its
// typed error; a draft saved or cleared on another device replaces or removes
// the local copy unless this device's own save is still unsent, and on chat
// open the core's draft is adopted unless the local copy holds newer unsent
// edits (then it is sent again). The core calls go to a scripted fake
// (`FakeDraftsClient`) and its events to a local subject; the core's draft
// encryption, versions and tombstones are covered by the crate tests.
import Combine
import CryptoKit
import Foundation
import SwiftData
import XCTest
@testable import OpenMates

@MainActor
private final class FakeDraftsClient: DraftsCoreClient {
    private(set) var calls: [String] = []
    var failure: CoreError?
    /// What `readDraft` returns (or throws).
    var readResult: Result<DraftViewRecord?, CoreError> = .success(nil)
    /// While true, each call waits for `releaseHeld()`.
    var holdsCalls = false
    private var held: [CheckedContinuation<Void, Never>] = []

    var heldCount: Int { held.count }

    func saveDraft(chatId: String?, markdown: String) async throws -> String {
        calls.append("save:\(chatId ?? "new"):\(markdown)")
        await holdIfNeeded()
        if let failure { throw failure }
        return chatId ?? "5d1c2b3a-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
    }

    func clearDraft(chatId: String) async throws {
        calls.append("clear:\(chatId)")
        await holdIfNeeded()
        if let failure { throw failure }
    }

    func readDraft(chatId: String) async throws -> DraftViewRecord? {
        calls.append("read:\(chatId)")
        return try readResult.get()
    }

    /// Ends every held call.
    func releaseHeld() {
        let pending = held
        held = []
        for continuation in pending { continuation.resume() }
    }

    private func holdIfNeeded() async {
        guard holdsCalls else { return }
        await withCheckedContinuation { held.append($0) }
    }
}

@MainActor
final class CoreDraftsTests: XCTestCase {
    private static let chatID = "8f14e45f-ceea-4e7a-9f1b-2c3d4e5f6a7b"
    private static let otherChatID = "c9f0f895-fb98-4b9a-8d1e-0a1b2c3d4e5f"

    private func makeDrafts() -> (CoreDrafts, FakeDraftsClient, PassthroughSubject<ViewEventRecord, Never>) {
        let drafts = CoreDrafts()
        let client = FakeDraftsClient()
        let events = PassthroughSubject<ViewEventRecord, Never>()
        drafts.attach(client: client, events: events.eraseToAnyPublisher())
        return (drafts, client, events)
    }

    /// Yields until `condition` holds (the drafts' tasks run on the main actor).
    private func waitUntil(_ condition: () -> Bool, file: StaticString = #filePath, line: UInt = #line) async {
        for _ in 0..<200 {
            if condition() { return }
            await Task.yield()
        }
        XCTFail("Condition not reached", file: file, line: line)
    }

    /// Waits (real time, the draft copy encrypts off the main actor) until `condition` holds.
    private func eventually(_ condition: () async throws -> Bool,
                            file: StaticString = #filePath, line: UInt = #line) async throws {
        for _ in 0..<300 {
            if try await condition() { return }
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        XCTFail("Condition not reached", file: file, line: line)
    }

    private func remote(_ markdown: String, version: UInt64) -> DraftViewRecord {
        DraftViewRecord(chatId: Self.chatID, markdown: markdown, preview: nil, draftV: version)
    }

    private func makeService(drafts: CoreDrafts) throws -> DraftService {
        let schema = Schema([PersistedComposerDraft.self])
        let configuration = ModelConfiguration("CoreDraftsTests", schema: schema, isStoredInMemoryOnly: true)
        let container = try ModelContainer(for: schema, configurations: [configuration])
        let key = SymmetricKey(size: .bits256)
        return DraftService(
            repository: OfflineStore(modelContainer: container),
            masterKeyProvider: { key },
            coreDrafts: drafts
        )
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract,drafts.sync.version-authoritative
    func testSaveAndClearReachTheCoreInOrder() async {
        let (drafts, client, _) = makeDrafts()
        drafts.save(chatId: Self.chatID, markdown: "Paint the kitchen walls")
        await drafts.settle(chatId: Self.chatID)
        drafts.clear(chatId: Self.chatID)
        await drafts.settle(chatId: Self.chatID)
        XCTAssertEqual(client.calls, ["save:\(Self.chatID):Paint the kitchen walls", "clear:\(Self.chatID)"])
        XCTAssertFalse(drafts.isBusy(chatId: Self.chatID))
        XCTAssertNil(drafts.lastError)
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract,drafts.sync.version-authoritative
    func testBurstBehindARunningCallSendsOnlyTheLatestRequest() async {
        let (drafts, client, _) = makeDrafts()
        client.holdsCalls = true
        drafts.save(chatId: Self.chatID, markdown: "P")
        await waitUntil { client.heldCount == 1 }
        drafts.save(chatId: Self.chatID, markdown: "Pa")
        drafts.clear(chatId: Self.chatID)
        drafts.save(chatId: Self.chatID, markdown: "Paint")
        XCTAssertTrue(drafts.isBusy(chatId: Self.chatID))
        client.holdsCalls = false
        client.releaseHeld()
        await drafts.settle(chatId: Self.chatID)
        XCTAssertEqual(client.calls, ["save:\(Self.chatID):P", "save:\(Self.chatID):Paint"])
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract,drafts.draft-only.lifecycle
    func testClearQueuedBehindARunningSaveRunsAfterIt() async {
        let (drafts, client, _) = makeDrafts()
        client.holdsCalls = true
        drafts.save(chatId: Self.chatID, markdown: "Paint the kitchen walls")
        await waitUntil { client.heldCount == 1 }
        drafts.clear(chatId: Self.chatID)
        XCTAssertEqual(client.calls.count, 1, "The clear waits for the running save")
        client.holdsCalls = false
        client.releaseHeld()
        await drafts.settle(chatId: Self.chatID)
        XCTAssertEqual(client.calls, ["save:\(Self.chatID):Paint the kitchen walls", "clear:\(Self.chatID)"])
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    func testChatsDoNotWaitForEachOther() async {
        let (drafts, client, _) = makeDrafts()
        client.holdsCalls = true
        drafts.save(chatId: Self.chatID, markdown: "Kitchen")
        drafts.save(chatId: Self.otherChatID, markdown: "Garden")
        await waitUntil { client.heldCount == 2 }
        XCTAssertEqual(Set(client.calls), ["save:\(Self.chatID):Kitchen", "save:\(Self.otherChatID):Garden"])
        client.holdsCalls = false
        client.releaseHeld()
        await drafts.settle(chatId: Self.chatID)
        await drafts.settle(chatId: Self.otherChatID)
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract,drafts.boundaries.session-and-incognito
    func testSignOutDropsWaitingRequestsAndForgetsTheError() async {
        let (drafts, client, events) = makeDrafts()
        client.failure = .Offline
        drafts.save(chatId: Self.chatID, markdown: "Kitchen")
        await drafts.settle(chatId: Self.chatID)
        XCTAssertEqual(drafts.lastError, .Offline)

        client.failure = nil
        client.holdsCalls = true
        drafts.save(chatId: Self.chatID, markdown: "Kitchen list")
        await waitUntil { client.heldCount == 1 }
        drafts.save(chatId: Self.chatID, markdown: "Kitchen list of the old account")
        events.send(.session(event: .signedOut))
        XCTAssertFalse(drafts.isBusy(chatId: Self.chatID))
        XCTAssertNil(drafts.lastError)

        client.holdsCalls = false
        client.releaseHeld()
        for _ in 0..<20 { await Task.yield() }
        XCTAssertEqual(client.calls, ["save:\(Self.chatID):Kitchen", "save:\(Self.chatID):Kitchen list"],
                       "A request waiting at sign-out never reaches the core")
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    func testCancelledCallIsNotAFailure() async {
        let (drafts, client, _) = makeDrafts()
        client.failure = .Cancelled
        drafts.clear(chatId: Self.chatID)
        await drafts.settle(chatId: Self.chatID)
        XCTAssertEqual(client.calls, ["clear:\(Self.chatID)"])
        XCTAssertNil(drafts.lastError)
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    func testAnAppWithoutACoreDropsTheRequests() async {
        let drafts = CoreDrafts()
        XCTAssertFalse(drafts.isAttached)
        drafts.save(chatId: Self.chatID, markdown: "Kitchen")
        drafts.clear(chatId: Self.chatID)
        XCTAssertFalse(drafts.isBusy(chatId: Self.chatID))
        await drafts.settle(chatId: Self.chatID)
        XCTAssertNil(drafts.lastError)
    }

    // contract-test: supporting surface=gui.apple assertions=drafts.draft-only.lifecycle,client-core.shell.allowed-responsibilities
    func testNewChatDraftReachesTheCoreUnderItsAllocatedChatId() async throws {
        let (drafts, client, _) = makeDrafts()
        let service = try makeService(drafts: drafts)
        try await service.saveDraft(canonicalMarkdown: "Paint the kitchen walls", preview: "Paint the kitchen walls",
                                    chatId: DraftService.syntheticNewChatId, revision: 1, draftVersion: 0)
        let allocated = try XCTUnwrap(service.activeNewChatDraftId)
        XCTAssertNotEqual(allocated, DraftService.syntheticNewChatId)
        XCTAssertNotNil(UUID(uuidString: allocated), "The core receives a chat id, never the composer alias")
        await drafts.settle(chatId: allocated)
        XCTAssertEqual(client.calls, ["save:\(allocated):Paint the kitchen walls"])

        try await service.clearDraft(chatId: DraftService.syntheticNewChatId)
        await drafts.settle(chatId: allocated)
        XCTAssertEqual(client.calls.last, "clear:\(allocated)")
        XCTAssertNil(service.activeNewChatDraftId)
        XCTAssertFalse(client.calls.contains { $0.contains(DraftService.syntheticNewChatId) })
    }

    // contract-test: supporting surface=gui.apple assertions=drafts.draft-only.lifecycle,drafts.sync.version-authoritative
    func testEmptyComposerClearsTheCoreDraft() async throws {
        let (drafts, client, _) = makeDrafts()
        let service = try makeService(drafts: drafts)
        try await service.saveDraft(canonicalMarkdown: "Kitchen", preview: "Kitchen",
                                    chatId: Self.chatID, revision: 1, draftVersion: 0)
        await drafts.settle(chatId: Self.chatID)
        try await service.saveDraft(canonicalMarkdown: " \n ", preview: "",
                                    chatId: Self.chatID, revision: 2, draftVersion: 0)
        await drafts.settle(chatId: Self.chatID)
        XCTAssertEqual(client.calls, ["save:\(Self.chatID):Kitchen", "clear:\(Self.chatID)"])
        XCTAssertNil(service.draftPreview(chatId: Self.chatID))
    }

    // contract-test: supporting surface=gui.apple assertions=drafts.draft-only.lifecycle
    func testNewChatAliasMovesOnlyWhenItsOwnerReleasesIt() throws {
        let service = try makeService(drafts: CoreDrafts())
        XCTAssertEqual(service.reserveNewChatDraftId(preferredId: Self.chatID), Self.chatID)
        XCTAssertEqual(service.reserveNewChatDraftId(preferredId: Self.otherChatID), Self.chatID,
                       "A second window joins the reserved draft")
        XCTAssertEqual(service.beginFreshNewChatDraft(preferredId: Self.otherChatID), Self.otherChatID)
        service.releaseNewChatDraftId(ifMatches: Self.chatID)
        XCTAssertEqual(service.activeNewChatDraftId, Self.otherChatID)
        service.releaseNewChatDraftId(ifMatches: Self.otherChatID)
        XCTAssertNil(service.activeNewChatDraftId)
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract,drafts.sync.version-authoritative
    func testReadReturnsTheCoreDraftNoneOrItsTypedError() async throws {
        let (drafts, client, _) = makeDrafts()
        client.readResult = .success(remote("Paint the kitchen walls", version: 4))
        let draft = try await drafts.read(chatId: Self.chatID)
        XCTAssertEqual(draft, remote("Paint the kitchen walls", version: 4))

        client.readResult = .success(nil)
        let none = try await drafts.read(chatId: Self.chatID)
        XCTAssertNil(none)

        client.readResult = .failure(.Unavailable(code: "team_scope", reason: "Team drafts are not available"))
        do {
            _ = try await drafts.read(chatId: Self.chatID)
            XCTFail("A core error must reach the caller")
        } catch let error as CoreError {
            XCTAssertEqual(error, .Unavailable(code: "team_scope", reason: "Team drafts are not available"))
        }
        XCTAssertEqual(drafts.lastError, .Unavailable(code: "team_scope", reason: "Team drafts are not available"))
        XCTAssertEqual(client.calls, Array(repeating: "read:\(Self.chatID)", count: 3))
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    func testReadWithoutACoreThrows() async {
        let drafts = CoreDrafts()
        do {
            _ = try await drafts.read(chatId: Self.chatID)
            XCTFail("An app without a core cannot read a draft")
        } catch let error as CoreError {
            XCTAssertEqual(error, .Unavailable(code: "no_core", reason: "The client core is not running"))
        } catch {
            XCTFail("Unexpected error type \(type(of: error))")
        }
    }

    // contract-test: direct surface=gui.apple assertions=drafts.sync.version-authoritative,client-core.shell.allowed-responsibilities
    func testRemoteSaveReplacesTheLocalCopy() async throws {
        let (drafts, client, events) = makeDrafts()
        let service = try makeService(drafts: drafts)
        try await service.saveDraft(canonicalMarkdown: "Kitchen", preview: "Kitchen",
                                    chatId: Self.chatID, revision: 1, draftVersion: 1)
        await drafts.settle(chatId: Self.chatID)
        XCTAssertFalse(drafts.hasUnsyncedChanges(chatId: Self.chatID))

        events.send(.draftChanged(chatId: Self.chatID, draft: remote("Kitchen and garden", version: 3)))
        try await eventually { service.draftPreview(chatId: Self.chatID) == "Kitchen and garden" }
        let local = try await service.loadDraft(chatId: Self.chatID)
        XCTAssertEqual(local?.canonicalMarkdown, "Kitchen and garden")
        XCTAssertEqual(local?.draftVersion, 3)
        XCTAssertEqual(client.calls, ["save:\(Self.chatID):Kitchen"], "An adopted remote draft is not sent back")
    }

    // contract-test: direct surface=gui.apple assertions=drafts.sync.version-authoritative,drafts.draft-only.lifecycle
    func testRemoteClearRemovesTheLocalCopy() async throws {
        let (drafts, client, events) = makeDrafts()
        let service = try makeService(drafts: drafts)
        try await service.saveDraft(canonicalMarkdown: "Kitchen", preview: "Kitchen",
                                    chatId: Self.chatID, revision: 1, draftVersion: 1)
        await drafts.settle(chatId: Self.chatID)

        events.send(.draftChanged(chatId: Self.chatID, draft: nil))
        try await eventually { service.draftPreview(chatId: Self.chatID) == nil }
        let local = try await service.loadDraft(chatId: Self.chatID)
        XCTAssertNil(local)
        XCTAssertEqual(client.calls, ["save:\(Self.chatID):Kitchen"])
    }

    // contract-test: direct surface=gui.apple assertions=drafts.sync.version-authoritative
    func testRemoteChangeIsIgnoredWhileLocalTypingIsUnsent() async throws {
        let (drafts, client, events) = makeDrafts()
        let service = try makeService(drafts: drafts)
        client.holdsCalls = true
        try await service.saveDraft(canonicalMarkdown: "Kitchen list", preview: "Kitchen list",
                                    chatId: Self.chatID, revision: 1, draftVersion: 1)
        await waitUntil { client.heldCount == 1 }
        XCTAssertTrue(drafts.hasUnsyncedChanges(chatId: Self.chatID))

        events.send(.draftChanged(chatId: Self.chatID, draft: remote("Garden", version: 2)))
        try await Task.sleep(nanoseconds: 100_000_000)
        var local = try await service.loadDraft(chatId: Self.chatID)
        XCTAssertEqual(local?.canonicalMarkdown, "Kitchen list", "Local typing the core has not received wins")
        client.holdsCalls = false
        client.releaseHeld()
        await drafts.settle(chatId: Self.chatID)

        // A failed save keeps the chat unsent: a remote change then sends the local copy again.
        client.failure = .Offline
        try await service.saveDraft(canonicalMarkdown: "Kitchen list, paint", preview: "Kitchen list, paint",
                                    chatId: Self.chatID, revision: 2, draftVersion: 1)
        await drafts.settle(chatId: Self.chatID)
        XCTAssertTrue(drafts.hasUnsyncedChanges(chatId: Self.chatID))
        client.failure = nil
        events.send(.draftChanged(chatId: Self.chatID, draft: nil))
        try await eventually { client.calls.last == "save:\(Self.chatID):Kitchen list, paint" && client.calls.count == 3 }
        await drafts.settle(chatId: Self.chatID)
        local = try await service.loadDraft(chatId: Self.chatID)
        XCTAssertEqual(local?.canonicalMarkdown, "Kitchen list, paint")
        XCTAssertFalse(drafts.hasUnsyncedChanges(chatId: Self.chatID))
    }

    // contract-test: direct surface=gui.apple assertions=drafts.sync.version-authoritative,drafts.persistence.local-first-encrypted
    func testOpeningAChatAdoptsANewerCoreDraft() async throws {
        let (drafts, client, _) = makeDrafts()
        let service = try makeService(drafts: drafts)
        try await service.saveDraft(canonicalMarkdown: "Kitchen", preview: "Kitchen",
                                    chatId: Self.chatID, revision: 1, draftVersion: 2)
        await drafts.settle(chatId: Self.chatID)
        client.readResult = .success(remote("Kitchen from the laptop", version: 5))

        await service.refreshFromCore(chatId: Self.chatID)
        let local = try await service.loadDraft(chatId: Self.chatID)
        XCTAssertEqual(local?.canonicalMarkdown, "Kitchen from the laptop")
        XCTAssertEqual(local?.draftVersion, 5)
        XCTAssertEqual(client.calls, ["save:\(Self.chatID):Kitchen", "read:\(Self.chatID)"])
    }

    // contract-test: direct surface=gui.apple assertions=drafts.sync.version-authoritative,drafts.persistence.local-first-encrypted
    func testOpeningAChatWithoutALocalCopyAdoptsTheCoreDraft() async throws {
        let (drafts, client, _) = makeDrafts()
        let service = try makeService(drafts: drafts)
        client.readResult = .success(remote("Garden plan", version: 2))

        await service.refreshFromCore(chatId: Self.chatID)
        let local = try await service.loadDraft(chatId: Self.chatID)
        XCTAssertEqual(local?.canonicalMarkdown, "Garden plan")
        XCTAssertEqual(service.draftPreview(chatId: Self.chatID), "Garden plan")
        XCTAssertEqual(client.calls, ["read:\(Self.chatID)"])
    }

    // contract-test: direct surface=gui.apple assertions=drafts.sync.version-authoritative
    func testOpeningAChatKeepsAndResendsNewerLocalEdits() async throws {
        let (drafts, client, _) = makeDrafts()
        let service = try makeService(drafts: drafts)
        try await service.saveDraft(canonicalMarkdown: "Kitchen, typed offline", preview: "Kitchen, typed offline",
                                    chatId: Self.chatID, revision: 3, draftVersion: 4)
        await drafts.settle(chatId: Self.chatID)
        client.readResult = .success(remote("Kitchen", version: 4))

        await service.refreshFromCore(chatId: Self.chatID)
        await drafts.settle(chatId: Self.chatID)
        let local = try await service.loadDraft(chatId: Self.chatID)
        XCTAssertEqual(local?.canonicalMarkdown, "Kitchen, typed offline", "Edits on top of the core's version win")
        XCTAssertEqual(client.calls, ["save:\(Self.chatID):Kitchen, typed offline", "read:\(Self.chatID)",
                                      "save:\(Self.chatID):Kitchen, typed offline"])
    }

    // contract-test: supporting surface=gui.apple assertions=drafts.sync.version-authoritative
    func testOpeningAChatKeepsTheLocalCopyWhenTheReadFails() async throws {
        let (drafts, client, _) = makeDrafts()
        let service = try makeService(drafts: drafts)
        try await service.saveDraft(canonicalMarkdown: "Kitchen", preview: "Kitchen",
                                    chatId: Self.chatID, revision: 1, draftVersion: 1)
        await drafts.settle(chatId: Self.chatID)
        client.readResult = .failure(.Offline)

        await service.refreshFromCore(chatId: Self.chatID)
        let local = try await service.loadDraft(chatId: Self.chatID)
        XCTAssertEqual(local?.canonicalMarkdown, "Kitchen")
        XCTAssertEqual(drafts.lastError, .Offline)
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract,drafts.boundaries.session-and-incognito
    func testSignOutForgetsUnsentChangesAndDropsRequests() async {
        let (drafts, client, events) = makeDrafts()
        client.failure = .Offline
        drafts.save(chatId: Self.chatID, markdown: "Kitchen")
        await drafts.settle(chatId: Self.chatID)
        XCTAssertTrue(drafts.hasUnsyncedChanges(chatId: Self.chatID))
        client.failure = nil
        client.holdsCalls = true
        drafts.save(chatId: Self.otherChatID, markdown: "Garden")
        await waitUntil { client.heldCount == 1 }
        drafts.clear(chatId: Self.otherChatID)

        events.send(.session(event: .signedOut))
        XCTAssertFalse(drafts.hasUnsyncedChanges(chatId: Self.chatID))
        XCTAssertFalse(drafts.hasUnsyncedChanges(chatId: Self.otherChatID))
        XCTAssertFalse(drafts.isBusy(chatId: Self.otherChatID))
        XCTAssertNil(drafts.lastError)
        client.holdsCalls = false
        client.releaseHeld()
        for _ in 0..<20 { await Task.yield() }
        XCTAssertEqual(client.calls, ["save:\(Self.chatID):Kitchen", "save:\(Self.otherChatID):Garden"])
        XCTAssertFalse(drafts.hasUnsyncedChanges(chatId: Self.otherChatID),
                       "A call cancelled by sign-out does not mark the chat unsent again")
    }
}
