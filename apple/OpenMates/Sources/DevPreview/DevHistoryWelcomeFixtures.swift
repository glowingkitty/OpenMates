// Isolated production history and continuation components with synthetic local state.
// Parent runtime is detached; no account, draft, upload or socket work may start.
#if DEBUG
import SwiftUI

@MainActor
enum DevHistoryWelcomeData {
    static func chat(_ id: String, title: String? = nil, messages: Int = 2, draft: Int = 0,
                     pinned: Bool = false, hidden: Bool = false, parent: String? = nil) -> Chat {
        Chat(id: id, title: title, lastMessageAt: "2026-09-12T12:00:00Z",
             createdAt: "2026-09-12T10:00:00Z", updatedAt: "2026-09-12T12:00:00Z",
             isArchived: false, isPinned: pinned, appId: nil,
             category: title == nil ? nil : "technology", encryptedTitle: nil,
             encryptedChatKey: nil, messagesV: messages, titleV: title == nil ? 0 : 1,
             draftV: draft, parentId: parent, isHiddenCandidate: hidden, hasNonEmptyDraft: draft > 0)
    }
    static let historyChat = chat("component-history", title: "Synthetic history", messages: 160)
    // Pane/reflow acceptance needs a real anchor, not a second long-history run.
    // The separate history fixture retains its full160-message workload.
    static let workspaceChat = chat("component-history", title: "Synthetic history", messages: 8)
    static let messages: [Message] = (0..<160).map { index in
        Message(id: "fixture-message-\(index)", chatId: historyChat.id,
                role: index.isMultiple(of: 2) ? .user : .assistant,
                content: index.isMultiple(of: 2) ? "Question \(index): explain this example." :
                    "## Answer \(index)\n\nA readable paragraph with **emphasis** and [a citation](https://example.invalid/source).\n\n- First item\n- Second item\n\n```swift\nlet result = \(index)\n```",
                encryptedContent: nil, createdAt: String(format: "2026-09-12T12:%02d:%02dZ", index / 60, index % 60),
                updatedAt: nil, appId: nil, isStreaming: false, embedRefs: nil)
    }
    static let welcomeChats = [
        chat("fixture-resume", title: "Continue the research"),
        chat("fixture-pinned", title: "Pinned research", pinned: true),
        chat("fixture-draft", messages: 0, draft: 1),
        chat("fixture-hidden-empty", messages: 0, hidden: true),
        chat("demo-excluded", title: "Public example"),
        chat("fixture-child", title: "Child chat", parent: "fixture-resume")
    ]
}

struct DevHistoryComponentFixture: View {
    var workspace = false
    @State private var constrainedWidth: CGFloat?
    @State private var sidebarOpen = false
    @State private var settingsOpen = false
    @State private var showSidebarSearch = false
    @State private var hiddenBoundary = false
    @StateObject private var sidebarStore: ChatStore
    init(workspace: Bool = false) {
        self.workspace = workspace
        let store = ChatStore()
        store.performWithoutPersistence {
            store.upsertChats([workspace ? DevHistoryWelcomeData.workspaceChat : DevHistoryWelcomeData.historyChat])
        }
        _sidebarStore = StateObject(wrappedValue: store)
    }
    private var fixtureChat: Chat { workspace ? DevHistoryWelcomeData.workspaceChat : DevHistoryWelcomeData.historyChat }
    private var skill: DevEmbedPreviewSkill { DevEmbedPreviewFixtures.skills(for: .web)[0] }
    private var messages: [Message] {
        guard workspace else { return DevHistoryWelcomeData.messages }
        var result = Array(DevHistoryWelcomeData.messages.prefix(8))
        result[result.count - 1].content = "Workspace result reference.\n\n[[embed:\(skill.primaryEmbed.id)]]"
        return result
    }
    var body: some View {
        VStack(spacing: 0) {
            if workspace {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 100))]) {
                    Button("Toggle settings") { settingsOpen.toggle() }
                    Button("Toggle sidebar") { sidebarOpen.toggle() }
                    Button("Available width") { constrainedWidth = nil }
                    Button("730pt") { constrainedWidth = 730 }
                    Button("390pt") { constrainedWidth = 390 }
                }
            }
            GeometryReader { geometry in
                let width = min(constrainedWidth ?? geometry.size.width, geometry.size.width)
                WorkspaceSidebarLayout(width: width, isOpen: sidebarOpen) {
                    ChatSidebarContent(userSections: [.init(id: "fixture", title: "Today", chats: [fixtureChat])],
                        publicSections: [], selectedChatID: fixtureChat.id, draftPreviews: [:],
                        showSearch: showSidebarSearch, emptyMessage: nil, loadMore: nil,
                        actions: .init(select: { _ in sidebarOpen = false }, showActions: nil,
                            search: { showSidebarSearch = true }, close: { sidebarOpen = false }, showHidden: { hiddenBoundary = true }, loadMore: {}),
                        refresh: {}) {
                            ChatSearchView(chats: sidebarStore.chats, activeChatId: fixtureChat.id, chatStore: sidebarStore,
                                onSelectResult: { _ in sidebarOpen = false; showSidebarSearch = false },
                                onClose: { showSidebarSearch = false }, prepareSearchMetadata: {}, draftPreviews: [:], allowsOfflineContent: false)
                        }
                        .overlay {
                            if hiddenBoundary {
                                VStack {
                                    Text("Hidden-chat authentication is disconnected in this isolated fixture.")
                                    Button(AppStrings.back) { hiddenBoundary = false }
                                }.padding().background(Color.grey20)
                            }
                        }
                } content: {
                    WorkspaceSettingsLayout(windowWidth: width, windowFrame: CGRect(x: geometry.frame(in: .global).minX, y: geometry.frame(in: .global).minY, width: width, height: geometry.size.height), isOpen: $settingsOpen) {
            ChatView(isolatedHistory: true, chatId: fixtureChat.id,
                     bannerState: .loaded(title: "Synthetic history", appId: "technology", summary: "Real production transcript and bounded navigation"),
                     initialChat: fixtureChat,
                     initialMessages: messages,
                     initialEmbeds: workspace ? [skill.primaryEmbed] + skill.childEmbeds : [])

                    } settings: {
                        SettingsView(isolatedNavigation: true, onClose: { settingsOpen = false })
                    }

                }
                .onChange(of: sidebarOpen) { _, opened in
                    if opened && width <= 600 { settingsOpen = false }
                }
            }

        }
    }
}

struct DevWelcomeComponentFixture: View {
    let empty: Bool
    let onAction: (String) -> Void
    @State private var selection: String?
    var body: some View {
        GeometryReader { geometry in
            let chats = empty ? [] : DevHistoryWelcomeData.welcomeChats
            let resume = WelcomeScreenState.resumeChat(from: chats, lastOpened: "fixture-resume")
            let recent = WelcomeScreenState.recentChats(from: chats, excluding: resume?.id)
            let cards = ([resume].compactMap { $0 } + recent).map {
                WelcomeScreenState.cardData(for: $0, draftPreview: $0.id == "fixture-draft" ? "A real draft preview" : nil)
            }
            VStack(spacing: 16) {
                if let selection {
                    ChatBannerView(state: .loaded(title: selection, appId: "technology", summary: nil), viewportHeight: geometry.size.height)
                }
                WelcomeContinuationCarousel(cards: cards, containerSize: geometry.size,
                    onOpenChat: { id in
                        if let card = cards.first(where: { $0.id == id }) { select(card) }
                    }, onShowChatActions: { onAction("actions:\($0)") })
                Text(cards.map(\.id).joined(separator: ","))
                    .font(.caption).accessibilityIdentifier("dev-welcome-eligible-ids")
            }
        }
    }
    private func select(_ card: WelcomeChatCardData) {
        selection = card.title; onAction("open:\(card.id)")
    }
}
#endif
