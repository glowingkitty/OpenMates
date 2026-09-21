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
}

struct ChatSidebarContent<SearchContent: View>: View {
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
                topBar
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        hiddenButton
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
            }
        }
        .background(Color.grey20)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("chat-history-panel")
    }
    private var topBar: some View {
        HStack(spacing: 12) {
            Button(action: actions.search) {
                Icon("search", size: 25).foregroundStyle(LinearGradient.primary).frame(width: 25, height: 25)
            }.buttonStyle(.plain).accessibilityIdentifier("search-button")
                .help(Text(AppStrings.search)).accessibilityLabel(AppStrings.search)
            Spacer()
            Button(action: actions.close) {
                Icon("close", size: 25).foregroundStyle(LinearGradient.primary).frame(width: 25, height: 25)
            }.buttonStyle(.plain).accessibilityIdentifier("chat-sidebar-close")
                .help(Text(AppStrings.close)).accessibilityLabel(AppStrings.close)
        }
        .frame(height: 32).padding(.horizontal, 20).padding(.vertical, 16)
        .background(Color.grey20)
        .padding(.bottom, 1)
        .overlay(alignment: .bottom) { Rectangle().fill(Color.grey30).frame(height: 1) }
        .accessibilityElement(children: .contain).accessibilityIdentifier("chat-sidebar-topbar")
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
                        draftPreview: draftPreviews[chat.id], onSelect: { actions.select(chat) },
                        onShowActions: actions.showActions.map { action in { action(chat) } })
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
    let draftPreview: String?
    let onSelect: () -> Void
    let onShowActions: (() -> Void)?
    @State private var hovering = false
    var body: some View {
        Button(action: onSelect) {
            ChatListRow(chat: chat, suppliedDraftPreview: draftPreview)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(selected ? Color.grey0 : hovering ? Color.grey10 : Color.clear)
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .contentShape(RoundedRectangle(cornerRadius: 8))
        }.buttonStyle(.plain)
            .onHover { hovering = $0 }
            .onLongPressGesture { onShowActions?() }
            .accessibilityAddTraits(selected ? .isSelected : [])
    }
}
