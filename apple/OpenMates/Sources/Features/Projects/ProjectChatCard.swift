// Specification: specifications/features/chat-navigation/specification.yml
// Assertions: chat-navigation.projects.nested-readable, chat-navigation.activity.global-running, chat-navigation.projects.organize
// Web source: components/projects/ProjectChatPreview.svelte, ProjectChatsSection.svelte,
// components/workspace/WorkspaceContinueCard.svelte.
// Specification: specifications/features/projects/specification.yml
// Assertions: projects.links.openmates-only-encrypted, projects.items.responsive-embeds, projects.access.explicit-context
import SwiftUI

struct ProjectChatCard: View {
    let item: ProjectWorkspaceItem
    @ObservedObject var chatStore: ChatStore
    let teamID: String?
    var listMode = false
    var width: CGFloat = 300
    var processing = false
    let hydrate: (String) async -> Void
    let onOpen: (String) -> Void
    @State private var loading = true
    private var chat: Chat? {
        guard let chat = chatStore.chat(for: item.targetID), chat.teamId == teamID,
              !chat.isHiddenFromNormalSurfaces, !IncognitoChatSession.isIncognitoChatId(chat.id),
              chat.title != nil || chat.encryptedTitle == nil else { return nil }
        return chat
    }
    var body: some View {
        Group {
            if let chat {
                let card = WelcomeScreenState.cardData(for: chat)
                if listMode {
                    Button { onOpen(chat.id) } label: {
                        HStack(spacing: .spacing6) {
                            if processing { ChatProcessingWheel() }
                            else { WelcomeCardIcon(name: card.iconName, size: 24) }
                            VStack(alignment: .leading, spacing: .spacing2) {
                                Text(card.title).font(.omP).fontWeight(.bold).lineLimit(1)
                                if let summary = card.summary { Text(summary).font(.omXs).lineLimit(1) }
                            }.frame(maxWidth: .infinity, alignment: .leading)
                        }.foregroundStyle(processing ? Color.fontPrimary : Color.fontButton)
                            .padding(.vertical, .spacing5).padding(.horizontal, .spacing8)
                            .frame(width: width, height: 78).background {
                                if processing { Color.grey10 } else { CategoryMapping.gradient(for: card.category) }
                            }.clipShape(RoundedRectangle(cornerRadius: .radius8))
                    }.buttonStyle(.plain)
                } else {
                    WelcomeResumeCard(badge: AppStrings.localized("common.chat"), summaryLineLimit: 2, processing: processing, card: card, width: width, height: 200, onTap: { onOpen(chat.id) }, onLongPress: {})

                }
            } else {
                VStack(spacing: .spacing4) {
                    if loading { ProgressView() }
                    Text(loading ? AppStrings.localized("common.loading") : LocalizationManager.shared.text("common.detail_load_error", replacements: ["item": AppStrings.localized("common.chat")]))
                        .font(.omSmall).foregroundStyle(Color.fontSecondary).multilineTextAlignment(.center)
                }.frame(width: width, height: listMode ? 78 : 200)
                    .background(Color.grey10, in: RoundedRectangle(cornerRadius: 30))
                    .accessibilityIdentifier("project-chat-state")
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("project-chat-card-\(item.targetID)")
        .task(id: "\(item.targetID)|\(teamID ?? "")") {
            loading = true
            await hydrate(item.targetID)
            loading = false
        }
    }
}
