// Specification: specifications/features/chat-navigation/specification.yml
// Assertions: chat-navigation.projects.nested-readable, chat-navigation.activity.global-running, chat-navigation.projects.organize
// Production sidebar content, independently renderable with in-memory inputs.
// Web: chats/Chats.svelte .activity-history-wrapper/.group-title, chats/Chat.svelte.
// Account loading/filtering, hidden-chat authentication and shell width stay with
// the parent. This renderer never opens an account store or starts a request.
import SwiftUI

// Observe draft changes within the sidebar subtree, never the entire app shell.
// Isolated fixtures use ChatSidebarContent directly and never construct this.
struct ChatSidebarDraftContext<Content: View>: View {
    @ObservedObject private var drafts = DraftService.shared
    @ViewBuilder let content: ([String: String]) -> Content
    var body: some View { content(drafts.draftPreviews) }
}

struct ChatSidebarSection: Identifiable {
    let id: String
    let title: String
    let chats: [Chat]
}
struct ChatSidebarLoadMore {
    let totalCount: Int
    let loadedCount: Int
    let isLoading: Bool
}
struct ChatSidebarActions {
    let select: (Chat) -> Void
    let showActions: ((Chat) -> Void)?
    let search: () -> Void
    let close: () -> Void
    let showHidden: () -> Void
    let loadMore: () -> Void
    var dragPayload: ((Chat) -> ChatProjectDragPayload?)? = nil
    var dropChat: ((ChatProjectDragPayload, Chat) -> Void)? = nil
}

struct ChatSidebarContent<SearchContent: View>: View {
    var projectNavigation: ChatProjectNavigationContext? = nil
    var revealRunningRequest = 0
    var showsHiddenChatsButton = true
    var processingChatIDs: Set<String> = []
    let userSections: [ChatSidebarSection]
    let publicSections: [ChatSidebarSection]
    let selectedChatID: String?
    let draftPreviews: [String: String]
    let showSearch: Bool
    let emptyMessage: String?
    let loadMore: ChatSidebarLoadMore?
    let actions: ChatSidebarActions
    let refresh: () async -> Void
    @ViewBuilder let searchContent: () -> SearchContent

    var body: some View {
        VStack(spacing: 0) {
            if showSearch {
                searchContent()
            } else {
                WorkspaceSidebarHeader(onSearch: actions.search, onClose: actions.close)
                ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        Color.clear.frame(height: 0).id("chat-sidebar-top")
                        if showsHiddenChatsButton { hiddenButton }
                        if let projectNavigation { ChatProjectNavigator(context: projectNavigation) }
                        sections(userSections)
                        if let emptyMessage {
                            Text(emptyMessage).font(.omSmall).foregroundStyle(Color.fontTertiary)
                                .frame(maxWidth: .infinity).padding(.vertical, 20)
                        }
                        if let loadMore {
                            ShowMoreChatsButton(totalCount: loadMore.totalCount, loadedCount: loadMore.loadedCount,
                                isLoading: loadMore.isLoading, onLoadMore: actions.loadMore)
                                .padding(.horizontal, 15)
                        }
                        sections(publicSections)
                    }
                }
                .accessibilityIdentifier("chat-sidebar-scroll")
                .refreshable { await refresh() }
                .onChange(of: revealRunningRequest) { _, _ in proxy.scrollTo("chat-sidebar-top", anchor: .top) }
                .onAppear { if revealRunningRequest > 0 { proxy.scrollTo("chat-sidebar-top", anchor: .top) } }
                }
            }
        }
        .background(Color.grey20)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("chat-history-panel")
    }
    private var hiddenButton: some View {
        Button(action: actions.showHidden) {
            HStack(spacing: 8) {
                Icon("hidden", size: 20).foregroundStyle(Color.grey60).accessibilityHidden(true)
                Text(AppStrings.showHiddenChats.uppercased())
                    .font(.custom("Lexend Deca", size: 13.6).weight(.medium))
                    .tracking(0.5).foregroundStyle(Color.grey60)
                Spacer(minLength: 0)
            }.frame(height: 20).contentShape(Rectangle())
        }.buttonStyle(.plain).padding(.horizontal, 15).padding(.vertical, 10)
            .accessibilityIdentifier("chat-sidebar-show-hidden")
    }
    // Keep headers and rows as direct children of the outer LazyVStack. An
    // eager VStack around an entire section would mount every loaded row.
    @ViewBuilder private func sections(_ sections: [ChatSidebarSection]) -> some View {
        ForEach(sections) { section in
            if !section.chats.isEmpty {
                Text(section.title.uppercased())
                    .font(.custom("Lexend Deca", size: 13.6).weight(.medium))
                    .tracking(0.5).foregroundStyle(Color.grey60)
                    .padding(.horizontal, 15).padding(.top, 15).padding(.bottom, 10)
                    .accessibilityIdentifier("chat-sidebar-section-\(section.id)")
                ForEach(section.chats) { chat in
                    ChatSidebarRowButton(chat: chat, selected: selectedChatID == chat.id,
                        processing: processingChatIDs.contains(chat.id) || projectNavigation?.runningIDs.contains(chat.id) == true,
                        activeSubChatCount: projectNavigation?.activeSubChatCounts[chat.id] ?? 0,
                        draftPreview: draftPreviews[chat.id], onSelect: { actions.select(chat) },
                        onShowActions: actions.showActions.map { action in { action(chat) } })
                        .modifier(ChatProjectDragModifier(payload: actions.dragPayload?(chat),
                            onDrop: actions.dropChat.map { drop in { drop($0, chat) } }))
                        .padding(.bottom, 4)
                }
                Color.clear.frame(height: 16).accessibilityHidden(true)
            }
        }
    }
}

private struct ChatSidebarRowButton: View {
    let chat: Chat
    let selected: Bool
    let processing: Bool
    let activeSubChatCount: Int
    let draftPreview: String?
    let onSelect: () -> Void
    let onShowActions: (() -> Void)?
    @State private var hovering = false
    @GestureState private var holdingForActions = false
    @State private var suppressSelection = false
    @State private var holdMoved = false
    var body: some View {
        Button { if !suppressSelection { onSelect() } } label: {
            ChatListRow(chat: chat, suppliedDraftPreview: draftPreview, processing: processing, activeSubChatCount: activeSubChatCount)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(selected ? Color.grey0 : hovering ? Color.grey10 : Color.clear)
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .contentShape(RoundedRectangle(cornerRadius: 8))
        }.buttonStyle(.plain)
            .onHover { hovering = $0 }
            // A draggable row must not present the custom menu during the lift.
            // Complete a stationary hold on release; travel belongs to drag/drop.
            .simultaneousGesture(
                LongPressGesture(minimumDuration: 0.5, maximumDistance: 10)
                    .sequenced(before: DragGesture(minimumDistance: 0))
                    .updating($holdingForActions) { value, holding, _ in
                        switch value {
                        case .first(let recognized): holding = recognized
                        case .second(let recognized, _): holding = recognized
                        }
                    }
                    .onChanged { value in
                        switch value {
                        case .first(true): suppressSelection = true
                        case .second(true, let drag):
                            suppressSelection = true
                            if let drag, hypot(drag.translation.width, drag.translation.height) > 10 { holdMoved = true }
                        default: break
                        }
                    }
                    .onEnded { value in
                        if case .second(true, let drag) = value,
                           !holdMoved, drag.map({ hypot($0.translation.width, $0.translation.height) <= 10 }) ?? true {
                            onShowActions?()
                        }
                        resetHoldAfterRelease()
                    }
            )
            .onChange(of: holdingForActions) { _, holding in
                if !holding { resetHoldAfterRelease() }
            }
            .accessibilityAddTraits(selected ? .isSelected : [])
    }
    private func resetHoldAfterRelease() {
        // Keep the release's Button action suppressed, then permit the next tap.
        // GestureState also resets here when the native drag interaction cancels.
        DispatchQueue.main.async { suppressSelection = false; holdMoved = false }
    }
}

// Shared workspace navigator chrome. Web: chats/Chats.svelte .chats-topbar.
// Workspace lists supply their own search action and always close the shell rail.
struct WorkspaceSidebarHeader: View {
    let onSearch: () -> Void
    let onClose: () -> Void
    var searchIdentifier = "search-button"
    var closeIdentifier = "chat-sidebar-close"
    var topBarIdentifier = "chat-sidebar-topbar"
    var body: some View {
        HStack(spacing: 12) {
            Button(action: onSearch) {
                Icon("search", size: 25).foregroundStyle(LinearGradient.primary).frame(width: 25, height: 25)
            }.buttonStyle(.plain).accessibilityIdentifier(searchIdentifier)
                .help(Text(AppStrings.search)).accessibilityLabel(AppStrings.search)
            Spacer()
            Button(action: onClose) {
                Icon("close", size: 25).foregroundStyle(LinearGradient.primary).frame(width: 25, height: 25)
            }.buttonStyle(.plain).accessibilityIdentifier(closeIdentifier)
                .help(Text(AppStrings.close)).accessibilityLabel(AppStrings.close)
        }
        .frame(height: 32).padding(.horizontal, 20).padding(.vertical, 16)
        .background(Color.grey20)
        .padding(.bottom, 1)
        .overlay(alignment: .bottom) { Rectangle().fill(Color.grey30).frame(height: 1) }
        .accessibilityElement(children: .contain).accessibilityIdentifier(topBarIdentifier)
    }
}

// Searches loaded workspace metadata only; no query leaves the device.
struct WorkspaceSidebarSearchField: View {
    @Binding var query: String
    let identifier: String
    @FocusState private var focused: Bool

    var body: some View {
        TextField(AppStrings.search, text: $query)
            .textFieldStyle(OMTextFieldStyle())
            .autocorrectionDisabled()
            #if os(iOS)
            .textInputAutocapitalization(.never)
            #endif
            .focused($focused)
            .accessibilityIdentifier(identifier)
            .padding(.horizontal, .spacing4)
            .padding(.vertical, .spacing3)
            .onAppear { focused = true }
    }
}
