// Hidden chats list — shows all hidden chats after the user unlocks access.
// Allows viewing hidden chats and unhiding them back to the main list.

import SwiftUI

struct HiddenChatsListView: View {
    let onSelectChat: (String) -> Void
    let onUnhideChat: (String) -> Void

    @State private var hiddenChats: [Chat] = []
    @State private var isLoading = true
    @State private var error: String?

    var body: some View {
        Group {
            if isLoading {
                Text("Loading hidden chats...")
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
                    .accessibilityLabel("Loading hidden chats")
            } else if hiddenChats.isEmpty {
                VStack(spacing: .spacing4) {
                    Icon("hidden", size: 40)
                        .foregroundStyle(Color.fontTertiary)
                        .accessibilityHidden(true)
                    Text(AppStrings.noHiddenChats)
                        .font(.omP)
                        .foregroundStyle(Color.fontSecondary)
                }
                .accessibilityElement(children: .combine)
                .accessibilityLabel("No hidden chats")
            } else {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: .spacing3) {
                        ForEach(hiddenChats) { chat in
                            HStack(spacing: .spacing3) {
                                Button {
                                    onSelectChat(chat.id)
                                } label: {
                                    VStack(alignment: .leading, spacing: .spacing2) {
                                        Text(chat.displayTitle)
                                            .font(.omP)
                                            .foregroundStyle(Color.fontPrimary)
                                        if let date = chat.lastMessageAt {
                                            Text(String(date.prefix(10)))
                                                .font(.omXs)
                                                .foregroundStyle(Color.fontTertiary)
                                        }
                                    }
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                }
                                .buttonStyle(.plain)

                                Button {
                                    onUnhideChat(chat.id)
                                    hiddenChats.removeAll { $0.id == chat.id }
                                    AccessibilityAnnouncement.announce("\(chat.displayTitle) unhidden")
                                } label: {
                                    Icon("visible", size: 18)
                                        .foregroundStyle(Color.buttonPrimary)
                                        .frame(width: 34, height: 34)
                                        .background(Color.grey0)
                                        .clipShape(RoundedRectangle(cornerRadius: .radius5))
                                }
                                .buttonStyle(.plain)
                                .accessibilityLabel("Unhide \(chat.displayTitle)")
                            }
                            .padding(.horizontal, .spacing4)
                            .padding(.vertical, .spacing3)
                            .background(Color.grey10)
                            .clipShape(RoundedRectangle(cornerRadius: .radius5))
                            .accessibilityElement(children: .combine)
                            .accessibilityLabel(
                                chat.lastMessageAt.map { "\(chat.displayTitle), \(String($0.prefix(10)))" }
                                ?? chat.displayTitle
                            )
                            .accessibilityHint("Opens this hidden chat")
                            .accessibilityAddTraits(.isButton)
                        }
                    }
                    .padding(.spacing4)
                }
            }
        }
        .task {
            await loadHiddenChats()
        }
    }

    private func loadHiddenChats() async {
        do {
            let response: ChatListResponse = try await APIClient.shared.request(
                .get, path: "/v1/chats?hidden=true"
            )

            // Decrypt titles using cached chat keys
            var chats: [Chat] = []
            for var chat in response.chats {
                if let encTitle = chat.encryptedTitle,
                   let title = await ChatKeyManager.shared.decryptTitle(
                       for: chat.id, encryptedTitle: encTitle
                   ) {
                    chat.title = title
                }
                chats.append(chat)
            }
            hiddenChats = chats
        } catch {
            self.error = error.localizedDescription
        }
        isLoading = false
    }
}
