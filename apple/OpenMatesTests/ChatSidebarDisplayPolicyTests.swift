// Production sidebar policy contract; no account, network or persisted data.
// Reference: Chats.svelte chatsForDisplay and chatGroupUtils.ts groupChats.
import XCTest
@testable import OpenMates

final class ChatSidebarDisplayPolicyTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_789_214_400)
    private var utc: Calendar {
        var value = Calendar(identifier: .gregorian)
        value.timeZone = TimeZone(secondsFromGMT: 0)!
        return value
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testElevenRowCapIncludesPinnedChatsAndEachExpansionAddsTwenty() {
        let chats = (0..<45).map { chat("chat-\($0)", age: $0, pinned: $0 < 15) }
        let first = ChatSidebarDisplayPolicy.visibleChats(sortedUserChats: chats,
            limit: ChatSidebarDisplayPolicy.initialLimit, selectedChatID: nil, lastActiveChatID: nil)
        XCTAssertEqual(first.map(\.id), Array(chats.prefix(11)).map(\.id))
        XCTAssertTrue(first.allSatisfy { $0.isPinned == true })
        let expandedLimit = ChatSidebarDisplayPolicy.nextLimit(after: 11)
        XCTAssertEqual(expandedLimit, 31)
        let expanded = ChatSidebarDisplayPolicy.visibleChats(sortedUserChats: chats,
            limit: expandedLimit, selectedChatID: nil, lastActiveChatID: nil)
        XCTAssertEqual(expanded.map(\.id), Array(chats.prefix(31)).map(\.id))
        XCTAssertEqual(Set(expanded.map(\.id)).count, 31)
        XCTAssertEqual(ChatSidebarDisplayPolicy.visibleChats(sortedUserChats: chats,
            limit: ChatSidebarDisplayPolicy.nextLimit(after: 31), selectedChatID: nil, lastActiveChatID: nil).count, 45)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testActiveOutsideWindowReplacesFinalRowAndSurvivesNewChatWithoutDuplicating() {
        let chats = (0..<35).map { chat("chat-\($0)", age: $0, pinned: $0 < 15) }
        let active = ChatSidebarDisplayPolicy.visibleChats(sortedUserChats: chats,
            limit: 11, selectedChatID: "chat-34", lastActiveChatID: "chat-20")
        XCTAssertEqual(active.map(\.id), (0..<10).map { "chat-\($0)" } + ["chat-34"])
        let returned = ChatSidebarDisplayPolicy.visibleChats(sortedUserChats: chats,
            limit: 11, selectedChatID: nil, lastActiveChatID: "chat-34")
        XCTAssertEqual(returned.map(\.id), active.map(\.id))
        let alreadyVisible = ChatSidebarDisplayPolicy.visibleChats(sortedUserChats: chats,
            limit: 11, selectedChatID: "chat-2", lastActiveChatID: "chat-34")
        XCTAssertEqual(alreadyVisible.map(\.id), Array(chats.prefix(11)).map(\.id))
        let removed = ChatSidebarDisplayPolicy.visibleChats(sortedUserChats: chats,
            limit: 11, selectedChatID: "not-in-filtered-chats", lastActiveChatID: "chat-34")
        XCTAssertEqual(removed.map(\.id), Array(chats.prefix(11)).map(\.id),
                       "Missing/hidden selections must not bypass the caller's filtered input")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testRetainedSelectionCannotCrossAccountOrServerScope() {
        let scope = ChatSidebarDisplayPolicy.Scope(userID: "account-a", serverOrigin: "https://api.example.org")
        let retained = ChatSidebarDisplayPolicy.RetainedSelection(chatID: "private-row", scope: scope)
        XCTAssertEqual(retained.chatID(in: scope), "private-row")
        XCTAssertNil(retained.chatID(in: .init(userID: "account-b", serverOrigin: scope.serverOrigin)))
        XCTAssertNil(retained.chatID(in: .init(userID: "account-a", serverOrigin: "https://api.other.example.org")))
        XCTAssertNil(retained.chatID(in: .init(userID: nil, serverOrigin: scope.serverOrigin)))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testDateSectionsMatchWebThresholdsAndPreserveSortedRowsWithinEachSection() {
        let source = [chat("july-pinned", age: 70, pinned: true), chat("august", age: 40),
                      chat("today-a", age: 0), chat("six-days", age: 6), chat("yesterday", age: 1),
                      chat("seven-days", age: 7), chat("today-b", age: 0), chat("twenty-nine-days", age: 29)]
        let groups = ChatSidebarDisplayPolicy.groups(source, now: now, calendar: utc)
        XCTAssertEqual(groups.map(\.key), ["today", "yesterday", "previous_7_days", "previous_30_days", "month_2026_7", "month_2026_8"])
        XCTAssertEqual(groups.first?.chats.map(\.id), ["today-a", "today-b"])
        XCTAssertEqual(groups[3].chats.map(\.id), ["seven-days", "twenty-nine-days"])
        XCTAssertEqual(groups.flatMap(\.chats).count, source.count)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testMissingAndZeroDatesUseWebFallbackAndServerSecondsDecodeIntoDateGroups() throws {
        XCTAssertEqual(ChatSidebarDisplayPolicy.groupKey(for: nil, now: now, calendar: utc), "today")
        XCTAssertEqual(ChatSidebarDisplayPolicy.groupKey(for: Date(timeIntervalSince1970: 0), now: now, calendar: utc), "today")
        let stamp = Int(now.addingTimeInterval(-86_400).timeIntervalSince1970)
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        let data = try JSONSerialization.data(withJSONObject: ["id": "timestamp-chat",
            "last_edited_overall_timestamp": stamp, "created_at": stamp])
        let decoded = try decoder.decode(Chat.self, from: data)
        XCTAssertEqual(ChatSidebarDisplayPolicy.groups([decoded], now: now, calendar: utc).first?.key, "yesterday")
        XCTAssertTrue(ChatSidebarDisplayPolicy.visibleChats(sortedUserChats: [chat("a", age: 0)],
            limit: 0, selectedChatID: "a", lastActiveChatID: nil).isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testSnapshotKeepsLargeInputBoundedAndDerivesGroupsFromTheVisibleRows() {
        let chats = (0..<2_000).map { chat("chat-\($0)", age: $0 % 90, pinned: $0 < 15) }
        let snapshot = ChatSidebarDisplayPolicy.snapshot(sortedUserChats: chats,
            appliesDisplayLimit: true, limit: 11, selectedChatID: "chat-1999", lastActiveChatID: nil,
            totalChatCount: 2_000, serverChatPagesExhausted: true, now: now, calendar: utc)
        XCTAssertEqual(snapshot.filteredCount, 2_000)
        XCTAssertTrue(snapshot.shouldShowMore)
        XCTAssertEqual(snapshot.visibleChats.map(\.id), (0..<10).map { "chat-\($0)" } + ["chat-1999"])
        XCTAssertEqual(snapshot.groups.flatMap(\.chats).count, 11,
                       "Grouping work must remain bounded by the visible window, even for a large sidebar")
        XCTAssertEqual(snapshot.groups.map(\.key), ChatSidebarDisplayPolicy.groups(
            snapshot.visibleChats, now: now, calendar: utc).map(\.key))
        XCTAssertEqual(Set(snapshot.groups.flatMap(\.chats).map(\.id)), Set(snapshot.visibleChats.map(\.id)))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testSnapshotBypassesLimitForSearchAndAnonymousViewsAndUsesOnlyFilteredInput() {
        // Represents the caller's already-filtered search/anonymous list. The
        // snapshot must not reintroduce a selected chat removed by that filter.
        let filtered = (0..<14).map { chat("match-\($0)", age: $0, pinned: $0 < 2) }
        let unlimited = ChatSidebarDisplayPolicy.snapshot(sortedUserChats: filtered,
            appliesDisplayLimit: false, limit: 11, selectedChatID: "excluded-chat", lastActiveChatID: nil,
            totalChatCount: 50, serverChatPagesExhausted: false, now: now, calendar: utc)
        XCTAssertEqual(unlimited.visibleChats.map(\.id), filtered.map(\.id))
        XCTAssertEqual(unlimited.filteredCount, filtered.count)
        XCTAssertEqual(unlimited.groups.flatMap(\.chats).count, filtered.count)
        XCTAssertFalse(unlimited.shouldShowMore)
        let limited = ChatSidebarDisplayPolicy.snapshot(sortedUserChats: filtered,
            appliesDisplayLimit: true, limit: 11, selectedChatID: "excluded-chat", lastActiveChatID: nil,
            totalChatCount: 50, serverChatPagesExhausted: false, now: now, calendar: utc)
        XCTAssertEqual(limited.visibleChats.map(\.id), Array(filtered.prefix(11)).map(\.id))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testSnapshotLoadMorePreservesLocalAndServerPaginationRules() {
        let chats = (0..<5).map { chat("chat-\($0)", age: $0) }
        func snapshot(total: Int, exhausted: Bool, limit: Int = 11) -> ChatSidebarDisplayPolicy.Snapshot {
            ChatSidebarDisplayPolicy.snapshot(sortedUserChats: chats,
                appliesDisplayLimit: true, limit: limit, selectedChatID: nil, lastActiveChatID: nil,
                totalChatCount: total, serverChatPagesExhausted: exhausted, now: now, calendar: utc)
        }
        XCTAssertTrue(snapshot(total: 50, exhausted: false).shouldShowMore)
        XCTAssertFalse(snapshot(total: 50, exhausted: true).shouldShowMore)
        XCTAssertFalse(snapshot(total: 5, exhausted: false).shouldShowMore)
        XCTAssertTrue(snapshot(total: 5, exhausted: true, limit: 3).shouldShowMore)
        XCTAssertEqual(snapshot(total: 50, exhausted: false).filteredCount, 5)
    }

    private func chat(_ id: String, age: Int, pinned: Bool = false) -> Chat {
        let stamp = ISO8601DateFormatter().string(from: now.addingTimeInterval(-Double(age) * 86_400))
        return Chat(id: id, title: id, lastMessageAt: stamp, createdAt: stamp, updatedAt: stamp,
                    isArchived: false, isPinned: pinned, appId: nil, encryptedTitle: nil,
                    encryptedChatKey: nil, messagesV: 1)
    }
}
