#if DEBUG
import SwiftUI

// Actual production sidebar, rows and search engine with a detached in-memory
// store. Public fixtures reuse bundled production chats. Account rows are plainly
// synthetic; they never inspect saved accounts, messages, drafts or credentials.
struct DevSidebarComponentFixture: View {
    let variant: String
    @StateObject private var store: ChatStore
    @State private var selected: Chat?
    @State private var showSearch = false
    @State private var isOpen = true
    @State private var hiddenBoundary = false
    @State private var limit: Int
    @State private var lastActiveID: String?
    private let userChats: [Chat]
    private let publicSections: [ChatSidebarSection]
    private let drafts = ["sidebar-draft": "A local draft kept in memory"]

    init(variant: String) {
        self.variant = variant
        let users = variant == "dated" ? Self.datedChats : variant == "account" ? Self.accountChats : []
        _limit = State(initialValue: variant == "dated" ? ChatSidebarDisplayPolicy.initialLimit : 2)
        let sections = variant == "empty" ? [] : Self.bundledPublicSections
        userChats = users; publicSections = sections
        let store = ChatStore()
        store.performWithoutPersistence {
            store.upsertChats(users + sections.flatMap(\.chats))
            for chat in users {
                store.setMessages(for: chat.id, messages: [Message(id: "\(chat.id)-message", chatId: chat.id, role: .user,
                    content: "A deterministic local transcript about telescope lenses.", encryptedContent: nil,
                    createdAt: "2026-09-12T12:00:00Z", updatedAt: nil, appId: nil, isStreaming: false, embedRefs: nil)])
            }
        }
        _store = StateObject(wrappedValue: store)
    }
    var body: some View {
        GeometryReader { geometry in
            VStack(spacing: 0) {
                if hiddenBoundary {
                    Text("Hidden-chat authentication is not connected in this isolated component.")
                        .font(.omSmall).accessibilityIdentifier("sidebar-fixture-hidden-boundary")
                    Button(AppStrings.back) { hiddenBoundary = false }
                        .accessibilityIdentifier("sidebar-fixture-hidden-return")
                }
                ZStack(alignment: .leading) {
                    if let selected {
                        VStack(spacing: 12) {
                            ChatBannerView(state: .loaded(title: selected.displayTitle, appId: selected.category ?? "ai", summary: selected.chatSummary),
                                viewportHeight: geometry.size.height)
                            Text(store.messages(for: selected.id).first?.content ?? selected.displayTitle)
                                .accessibilityIdentifier("sidebar-fixture-selected-content")
                            Text(selected.id).accessibilityIdentifier("sidebar-fixture-selected-id")
                        }.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                    } else {
                        Color.grey20
                    }
                    if isOpen {
                        ChatSidebarContent(userSections: userSections, publicSections: publicSections,
                            selectedChatID: selected?.id, draftPreviews: drafts, showSearch: showSearch,
                            emptyMessage: variant == "empty" ? AppStrings.noChats : nil,
                            loadMore: limit < userChats.count ? .init(totalCount: userChats.count, loadedCount: limit, isLoading: false) : nil,
                            actions: .init(select: select, showActions: nil, search: { showSearch = true },
                                close: { isOpen = false }, showHidden: { hiddenBoundary = true },
                                loadMore: { limit = ChatSidebarDisplayPolicy.nextLimit(after: limit) }), refresh: {}) {
                            ChatSearchView(chats: store.chats, activeChatId: selected?.id, chatStore: store,
                                onSelectResult: { result in
                                    if let chat = store.chat(for: result.chatId) { select(chat) }
                                }, onClose: { showSearch = false }, prepareSearchMetadata: {},
                                draftPreviews: drafts, allowsOfflineContent: false)
                        }
                        .frame(width: geometry.size.width <= 600 ? geometry.size.width : 325)
                    }
                }
                if !isOpen {
                    HStack {
                        Button(AppStrings.chats) { isOpen = true }
                            .accessibilityIdentifier("sidebar-fixture-reopen")
                        if variant == "dated" {
                            Button(AppStrings.newChat) { selected = nil; isOpen = true }
                                .accessibilityIdentifier("sidebar-fixture-new-chat")
                        }
                    }
                }
                Text("Local fixture; account/network/persistence disabled.")
                    .font(.omXs).accessibilityIdentifier("sidebar-fixture-boundary")
            }
        }
    }
    private var userSections: [ChatSidebarSection] {
        let visible = ChatSidebarDisplayPolicy.visibleChats(sortedUserChats: userChats, limit: limit,
            selectedChatID: selected?.id, lastActiveChatID: lastActiveID)
        return ChatSidebarDisplayPolicy.groups(visible, now: Self.fixtureNow, calendar: Self.fixtureCalendar).map { group in
            ChatSidebarSection(id: group.key,
                title: ChatSidebarDisplayPolicy.title(for: group.key, locale: Locale(identifier: "en_US")), chats: group.chats)
        }
    }
    private func select(_ chat: Chat) {
        selected = chat
        lastActiveID = chat.id
        showSearch = false
        isOpen = false
    }
    private static var accountChats: [Chat] {
        [DevHistoryWelcomeData.chat("sidebar-pinned", title: "Telescope research", pinned: true),
         DevHistoryWelcomeData.chat("sidebar-draft", title: "A weekend in Berlin", draft: 1),
         DevHistoryWelcomeData.chat("sidebar-long", title: "Understanding the performance of a long conversation and its many source previews"),
         DevHistoryWelcomeData.chat("sidebar-final", title: "Latest local conversation")]
    }
    private static let fixtureNow = Date(timeIntervalSince1970: 1_789_214_400) // 2026-09-12 12:00 UTC
    private static var fixtureCalendar: Calendar {
        var value = Calendar(identifier: .gregorian); value.timeZone = TimeZone(secondsFromGMT: 0)!
        return value
    }
    private static var datedChats: [Chat] {
        (0..<35).map { index in
            let age = index == 34 ? 70 : index < 5 ? 0 : index < 10 ? 1 : index < 15 ? 4 : index < 25 ? 20 : 40
            let date = fixtureNow.addingTimeInterval(-Double(age) * 86_400 - Double(index) * 60)
            let stamp = ISO8601DateFormatter().string(from: date)
            return Chat(id: "sidebar-dated-\(index)",
                title: index == 34 ? "Historic telescope archive" : "Dated conversation \(index)",
                lastMessageAt: stamp, createdAt: stamp, updatedAt: stamp, isArchived: false,
                isPinned: index < 15, appId: nil, encryptedTitle: nil, encryptedChatKey: nil, messagesV: 1)
        }
    }
    private static var bundledPublicSections: [ChatSidebarSection] {
        let definitions: [(String, String, [String])] = [
            ("intro", AppStrings.introSection, ["demo-who-develops-openmates"]),
            ("examples", AppStrings.exampleChatsSection, ["example-gigantic-airplanes", "example-artemis-ii-mission", "example-beautiful-single-page-html", "example-eu-chat-control-law", "example-flights-berlin-bangkok", "example-creativity-drawing-meetups-berlin"]),
            ("announcements", AppStrings.announcementsSection, ["announcements-introducing-openmates-v09"]),
            ("legal", AppStrings.legalSection, ["legal-privacy", "legal-terms", "legal-imprint"])
        ]
        return definitions.map { id, title, ids in
            ChatSidebarSection(id: id, title: title, chats: ids.compactMap { PublicChatContent.chat(for: $0)?.chat })
        }
    }
}
#endif
