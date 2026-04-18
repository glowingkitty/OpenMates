// Hidden chats list — shows all hidden chats after the user unlocks access.
// Allows viewing hidden chats and unhiding them back to the main list.

import SwiftUI

struct HiddenChatsListView: View {
    let onSelectChat: (String) -> Void
    let onUnhideChat: (String) -> Void

    @State private var hiddenChats: [Chat] = []
    @State private var isLoading = true
    @State private var error: String?
    @Environment(\.dismiss) var dismiss

    var body: some View {
        Group {
            if isLoading {
                ProgressView("Loading hidden chats...")
            } else if hiddenChats.isEmpty {
                VStack(spacing: .spacing4) {
                    Image(systemName: "eye.slash")
                        .font(.system(size: 40))
                        .foregroundStyle(Color.fontTertiary)
                    Text(AppStrings.noHiddenChats)
                        .font(.omP)
                        .foregroundStyle(Color.fontSecondary)
                }
            } else {
                List {
                    ForEach(hiddenChats) { chat in
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
                        }
                        .swipeActions(edge: .trailing) {
                            Button {
                                onUnhideChat(chat.id)
                                hiddenChats.removeAll { $0.id == chat.id }
                            } label: {
                                Label("Unhide", systemImage: "eye")
                            }
                            .tint(Color.buttonPrimary)
                        }
                    }
                }
                .listStyle(.insetGrouped)
            }
        }
        .navigationTitle("Hidden Chats")
        #if os(iOS)
        .navigationBarTitleDisplayMode(.inline)
        #endif
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("Done") { dismiss() }
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
