// Decrypted, current-owner chat choices for Workflow send-message steps.
// MainApp supplies these from its scoped in-memory chat list; this view never
// loads, persists, or sends chat display metadata.
// Web source: WorkflowGraphRenderer.svelte chooseChat / visibleChats.

import SwiftUI

struct WorkflowChatChoice: Identifiable, Sendable {
    let id: String
    let title: String
    let category: String?
    let icon: String?
    let summary: String?
}

struct WorkflowChatDestinationPicker: View {
    let chats: [WorkflowChatChoice]
    let onSelect: (String?) -> Void

    @State private var search = ""

    private var visibleChats: [WorkflowChatChoice] {
        let query = search.trimmingCharacters(in: .whitespacesAndNewlines)
        if query.isEmpty { return Array(chats.prefix(6)) }
        return chats.filter { $0.title.localizedCaseInsensitiveContains(query) }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            Text(AppStrings.localized("workflows.builder.chat_question"))
                .font(.omH3)
                .foregroundStyle(Color.fontPrimary)

            ScrollView {
                LazyVStack(spacing: .spacing3) {
                    ForEach(visibleChats) { chat in
                        Button { onSelect(chat.id) } label: {
                            HStack(spacing: .spacing4) {
                                Icon(chat.icon ?? CategoryMapping.iconName(for: chat.category ?? "general_knowledge"), size: 22)
                                    .foregroundStyle(Color.fontButton)
                                    .frame(width: 42, height: 42)
                                    .background(CategoryMapping.gradient(for: chat.category ?? "general_knowledge"),
                                                in: RoundedRectangle(cornerRadius: .radius6))
                                VStack(alignment: .leading, spacing: .spacing1) {
                                    Text(chat.title).font(.omP.weight(.semibold))
                                    if let summary = chat.summary, !summary.isEmpty {
                                        Text(summary).font(.omSmall).foregroundStyle(Color.fontSecondary)
                                            .lineLimit(2)
                                    }
                                }
                                .foregroundStyle(Color.fontPrimary)
                                Spacer(minLength: 0)
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.spacing3)
                            .background(Color.grey0, in: RoundedRectangle(cornerRadius: .radius6))
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("workflow-chat-destination")
                    }
                }
            }
            .frame(maxHeight: 250)

            TextField(AppStrings.localized("workflows.builder.search_chats"), text: $search)
                .textFieldStyle(OMTextFieldStyle())
                .accessibilityIdentifier("workflow-chat-search")

            Button {
                onSelect(nil)
            } label: {
                HStack(spacing: .spacing3) {
                    Icon("create", size: 20)
                    Text(AppStrings.newChat)
                }
            }
            .buttonStyle(OMPrimaryButtonStyle())
            .accessibilityIdentifier("workflow-new-chat-destination")
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("workflow-chat-destination-picker")
    }
}
