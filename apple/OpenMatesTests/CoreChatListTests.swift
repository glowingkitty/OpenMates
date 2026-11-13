// Tests of `CoreChatList` and `CoreChatRowMapper` (plan
// apple-client-core-migration A4 lane 2): the sidebar's chat list from the
// client core over an in-memory credential store (`InMemoryCredentialStore`
// from CoreSessionTests) and a temporary cache container. Core events are fed
// through `CoreSession.events`, the same subject the core's relay publishes
// on. They cover the mapping of a full row (including the sub-chat, sharing,
// app and last-visible-message fields), the refusal of saved-item home
// entries, Partial then Complete replacing the list in core order, a team
// scope's list replacing the previous one, sign-out emptying it, and list
// calls settling with the core's typed error instead of hanging. No network:
// the API host never resolves.
import Combine
import Foundation
import XCTest
@testable import OpenMates

final class CoreChatListTests: XCTestCase {
    private static let apiURL = "https://never-contact.example.invalid"

    @MainActor
    private func makeList() throws -> (CoreChatList, CoreSession) {
        let container = FileManager.default.temporaryDirectory.path
        let name = "core-chat-list-\(UUID().uuidString)"
        let directory = (container as NSString).appendingPathComponent(name)
        addTeardownBlock { try? FileManager.default.removeItem(atPath: directory) }
        let session = try CoreSession(
            config: CoreConfig(
                apiUrl: Self.apiURL, appUrl: "https://app.example.invalid",
                cacheContainer: container, cacheDirectoryName: name),
            credentials: InMemoryCredentialStore())
        let list = CoreChatList()
        list.attach(session)
        return (list, session)
    }

    /// Polls `condition` for up to five seconds; core calls finish asynchronously.
    @MainActor
    private func waitUntil(_ condition: () -> Bool, file: StaticString = #filePath, line: UInt = #line) async throws {
        for _ in 0..<500 {
            if condition() { return }
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        XCTFail("condition not reached", file: file, line: line)
    }

    private static func metadata(teamId: String? = nil, parentId: String? = nil, draftPreview: String? = nil,
                                 isSharedByOthers: Bool? = nil, lastVisibleMessageId: String? = nil,
                                 appId: String? = nil, wait: Bool? = nil, trigger: String? = nil) -> ChatRowMetadataRecord {
        ChatRowMetadataRecord(
            icon: "rocket", activeFocusId: "focus-plan", parentId: parentId, isSubChat: parentId == nil ? nil : true,
            teamId: teamId, isShared: false, isPrivate: true, isHidden: false,
            lastMessageAt: 1_700_000_120, lastEditedAt: 1_700_000_180,
            budgetLimit: 500, budgetSpent: 120, draftV: 3, draftPreview: draftPreview,
            isSharedByOthers: isSharedByOthers, lastVisibleMessageId: lastVisibleMessageId, appId: appId,
            subChatWaitForCompletion: wait, subChatReportTrigger: trigger)
    }

    private static func row(_ id: String, title: String = "Kitchen renovation", status: ChatRowStatusRecord = .ready,
                            unread: UInt64 = 0, pinned: Bool = false, hasDraft: Bool = false,
                            metadata: ChatRowMetadataRecord = CoreChatListTests.metadata()) -> ChatListRowRecord {
        ChatListRowRecord(
            id: id, title: title, chatListTitle: title, summary: "Tiles and lighting", category: "general_knowledge",
            status: status, createdAt: 1_700_000_000, updatedAt: 1_700_000_060, messagesV: 7,
            unreadCount: unread, pinned: pinned, archived: false, hasDraft: hasDraft, footer: nil,
            isSavedItem: id.hasPrefix("embed:"), metadata: metadata)
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract,client-core.shell.allowed-responsibilities
    @MainActor
    func testMapsAFullCoreRowIncludingSubChatSharingAndAppFields() throws {
        let record = Self.row("sub-chat-1", unread: 12, pinned: true, hasDraft: true, metadata: Self.metadata(
            teamId: "team-garden", parentId: "parent-chat", draftPreview: "Ask about the  grout\ncolour",
            isSharedByOthers: true, lastVisibleMessageId: "message-42", appId: "travel",
            wait: true, trigger: "each"))
        let mapped = try XCTUnwrap(CoreChatRowMapper.map(record))
        let chat = mapped.chat
        XCTAssertEqual(chat.id, "sub-chat-1")
        XCTAssertEqual(chat.title, "Kitchen renovation")
        XCTAssertEqual(chat.chatSummary, "Tiles and lighting")
        XCTAssertEqual(chat.category, "general_knowledge")
        XCTAssertEqual(chat.icon, "rocket")
        XCTAssertEqual(chat.activeFocusId, "focus-plan")
        XCTAssertEqual(chat.isPinned, true)
        XCTAssertEqual(chat.isArchived, false)
        XCTAssertEqual(chat.messagesV, 7)
        XCTAssertEqual(chat.draftV, 3)
        XCTAssertEqual(chat.hasNonEmptyDraft, true)
        XCTAssertEqual(chat.unreadCount, 12)
        XCTAssertEqual(chat.parentId, "parent-chat")
        XCTAssertEqual(chat.isSubChat, true)
        XCTAssertEqual(chat.subChatSettings, SubChatSettings(waitForCompletion: true, reportTrigger: "each"))
        XCTAssertEqual(chat.budgetLimit, 500)
        XCTAssertEqual(chat.budgetSpent, 120)
        XCTAssertEqual(chat.teamId, "team-garden")
        XCTAssertEqual(chat.isSharedByOthers, true)
        XCTAssertEqual(chat.isPrivate, true)
        XCTAssertEqual(chat.isHidden, false)
        XCTAssertEqual(chat.lastVisibleMessageId, "message-42")
        XCTAssertEqual(chat.appId, "travel")
        XCTAssertNil(chat.encryptedChatKey, "the core never hands keys to the shell")
        XCTAssertEqual(chat.createdDate, Date(timeIntervalSince1970: 1_700_000_000))
        XCTAssertEqual(chat.updatedDate, Date(timeIntervalSince1970: 1_700_000_060))
        XCTAssertEqual(chat.lastMessageDate, Date(timeIntervalSince1970: 1_700_000_120))
        XCTAssertEqual(chat.sidebarActivityDate, Date(timeIntervalSince1970: 1_700_000_180))
        XCTAssertEqual(mapped.presentation, ChatSidebarRowPresentation(
            unreadCount: 12, isDraftOnly: false, draftPreview: "Ask about the grout colour"))

        let draftOnly = try XCTUnwrap(CoreChatRowMapper.map(Self.row("draft-chat", title: "Draft", status: .draft,
            hasDraft: true, metadata: Self.metadata(draftPreview: "Plan the garden"))))
        XCTAssertTrue(draftOnly.presentation.isDraftOnly)
        XCTAssertEqual(draftOnly.presentation.draftPreview, "Plan the garden")
        // The core's draft-only shape: status `.draft`, `hasDraft` false (set only for established chats).
        let coreDraftOnly = try XCTUnwrap(CoreChatRowMapper.map(Self.row("ui-test-draft-chat",
            title: "Header navigation draft", status: .draft,
            metadata: Self.metadata(draftPreview: "Header navigation draft"))))
        XCTAssertTrue(coreDraftOnly.presentation.isDraftOnly)
        XCTAssertEqual(coreDraftOnly.presentation.draftPreview, "Header navigation draft")
        let noSubChat = try XCTUnwrap(CoreChatRowMapper.map(Self.row("plain-chat")))
        XCTAssertNil(noSubChat.chat.subChatSettings)
        XCTAssertNil(noSubChat.presentation.draftPreview)
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    @MainActor
    func testPartialThenCompleteReplacesTheListInCoreOrderWithoutDuplicates() throws {
        let (list, session) = try makeList()
        XCTAssertNil(list.completeness)
        session.events.send(.chatList(rows: [Self.row("chat-b"), Self.row("chat-a")], completeness: .cached, totalCount: nil))
        XCTAssertEqual(list.chats.map(\.id), ["chat-b", "chat-a"])
        session.events.send(.chatList(rows: [Self.row("chat-a"), Self.row("chat-c")], completeness: .partial, totalCount: nil))
        XCTAssertEqual(list.chats.map(\.id), ["chat-a", "chat-c"])
        XCTAssertEqual(list.completeness, .partial)
        session.events.send(.chatList(
            rows: [Self.row("chat-c", unread: 2), Self.row("chat-a"), Self.row("chat-b")], completeness: .complete, totalCount: nil))
        XCTAssertEqual(list.chats.map(\.id), ["chat-c", "chat-a", "chat-b"], "the core order is kept, never appended to")
        XCTAssertEqual(list.completeness, .complete)
        XCTAssertEqual(list.presentations["chat-c"]?.unreadCount, 2)
        XCTAssertEqual(list.chat(for: "chat-b")?.id, "chat-b")

        // Other core events (stream, status) leave the list untouched.
        session.events.send(.status(message: "synthetic progress note"))
        XCTAssertEqual(list.chats.map(\.id), ["chat-c", "chat-a", "chat-b"])
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    @MainActor
    func testSavedItemHomeEntriesAreRefusedNotShownAsChats() throws {
        let (list, session) = try makeList()
        session.events.send(.chatList(
            rows: [Self.row("embed:saved-item-1", title: "Saved recipe"), Self.row("chat-a")], completeness: .complete, totalCount: nil))
        XCTAssertEqual(list.chats.map(\.id), ["chat-a"])
        XCTAssertEqual(list.refusedRowCount, 1)
        XCTAssertNil(list.presentations["embed:saved-item-1"])
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    @MainActor
    func testSavedItemsAreKeptApartAndTheCoreTotalGivesTheRemainingCount() throws {
        let (list, session) = try makeList()
        XCTAssertNil(list.totalCount)
        XCTAssertEqual(list.remainingChatCount, 0)
        session.events.send(.chatList(
            rows: [Self.row("embed:saved-1", title: "Saved recipe"), Self.row("chat-a"), Self.row("chat-b")],
            completeness: .partial, totalCount: 5))
        XCTAssertEqual(list.chats.map(\.id), ["chat-a", "chat-b"])
        XCTAssertEqual(list.savedItemIDs, ["embed:saved-1"])
        XCTAssertEqual(list.totalCount, 5)
        XCTAssertEqual(list.remainingChatCount, 3)
        session.events.send(.chatList(rows: [Self.row("chat-a"), Self.row("chat-b")], completeness: .complete, totalCount: 2))
        XCTAssertEqual(list.savedItemIDs, [])
        XCTAssertEqual(list.remainingChatCount, 0)
        session.events.send(.session(event: .signedOut))
        XCTAssertNil(list.totalCount)
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    @MainActor
    func testATeamScopeListReplacesThePersonalListAndASignedOutSwitchIsTyped() async throws {
        let (list, session) = try makeList()
        session.events.send(.chatList(rows: [Self.row("personal-chat")], completeness: .complete, totalCount: nil))
        let team = Self.metadata(teamId: "team-garden")
        session.events.send(.chatList(
            rows: [Self.row("team-chat-1", metadata: team), Self.row("team-chat-2", metadata: team)],
            completeness: .complete, totalCount: nil))
        XCTAssertEqual(list.chats.map(\.id), ["team-chat-1", "team-chat-2"])
        XCTAssertNil(list.chat(for: "personal-chat"))
        XCTAssertEqual(Set(list.chats.compactMap(\.teamId)), ["team-garden"])

        try await session.start()
        let switched = await list.switchTeam("team-garden")
        XCTAssertFalse(switched, "a switch without a session must fail, not hang")
        XCTAssertEqual(list.lastError, .Authentication)
        XCTAssertNil(list.coreTeamID)
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract,client-core.credentials.snapshot-boundary
    @MainActor
    func testSignOutEmptiesTheList() throws {
        let (list, session) = try makeList()
        session.events.send(.chatList(rows: [Self.row("chat-a"), Self.row("chat-b")], completeness: .complete, totalCount: nil))
        XCTAssertEqual(list.chats.count, 2)
        session.events.send(.session(event: .signedOut))
        XCTAssertTrue(list.chats.isEmpty)
        XCTAssertTrue(list.presentations.isEmpty)
        XCTAssertNil(list.completeness)
        XCTAssertNil(list.chat(for: "chat-a"))

        session.events.send(.chatList(rows: [Self.row("chat-c")], completeness: .cached, totalCount: nil))
        session.events.send(.session(event: .expired))
        XCTAssertTrue(list.chats.isEmpty, "an expired session drops the list too")
    }

    // contract-test: supporting surface=gui.apple assertions=client-core.viewmodel.capability-contract
    @MainActor
    func testListCallsSettleWithTheCoreErrorInsteadOfHanging() async throws {
        let (list, session) = try makeList()
        try await session.start()
        await list.refresh()
        XCTAssertEqual(list.lastError, .Authentication)

        // An admission runs bootSync; signed out the core refuses it, typed.
        let (other, otherSession) = try makeList()
        try await otherSession.start()
        otherSession.events.send(.session(event: .admitted(username: "synthetic-user", expiresAt: nil)))
        try await waitUntil { other.lastError != nil }
        XCTAssertEqual(other.lastError, .Authentication)
        XCTAssertTrue(other.chats.isEmpty)
    }
}
