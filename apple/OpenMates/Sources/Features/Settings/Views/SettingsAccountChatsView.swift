// Account chats management — bulk operations on chat history.
// Mirrors the web app's account/SettingsAccountChats.svelte.
// Provides chat count, bulk delete, and archive operations.

import SwiftUI

struct SettingsAccountChatsView: View {
    @State private var chatCount = 0
    @State private var archivedCount = 0
    @State private var isLoading = true
    @State private var showDeleteConfirm = false
    @State private var showArchiveConfirm = false
    @State private var isDeleting = false
    @State private var error: String?

    var body: some View {
        List {
            Section("Chat Statistics") {
                HStack {
                    Text("Total Chats")
                    Spacer()
                    Text("\(chatCount)")
                        .foregroundStyle(Color.fontSecondary)
                }
                HStack {
                    Text("Archived")
                    Spacer()
                    Text("\(archivedCount)")
                        .foregroundStyle(Color.fontSecondary)
                }
            }

            Section("Actions") {
                Button {
                    showArchiveConfirm = true
                } label: {
                    Label("Archive All Chats", systemImage: "archivebox")
                }

                Button(role: .destructive) {
                    showDeleteConfirm = true
                } label: {
                    Label("Delete All Chats", systemImage: "trash")
                }
            }

            if let error {
                Section {
                    Text(error).font(.omSmall).foregroundStyle(Color.error)
                }
            }
        }
        .navigationTitle("Chats")
        .task { await loadStats() }
        .confirmationDialog("Archive All Chats?", isPresented: $showArchiveConfirm) {
            Button("Archive All") { archiveAll() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This will archive all \(chatCount) chats. They can be restored later.")
        }
        .confirmationDialog("Delete All Chats?", isPresented: $showDeleteConfirm) {
            Button("Delete All", role: .destructive) { deleteAll() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This will permanently delete all \(chatCount) chats. This action cannot be undone.")
        }
    }

    private func loadStats() async {
        do {
            let response: [String: AnyCodable] = try await APIClient.shared.request(
                .get, path: "/v1/settings/account/chats/stats"
            )
            chatCount = response["total"]?.value as? Int ?? 0
            archivedCount = response["archived"]?.value as? Int ?? 0
        } catch {
            self.error = error.localizedDescription
        }
        isLoading = false
    }

    private func archiveAll() {
        Task {
            do {
                let _: Data = try await APIClient.shared.request(
                    .post, path: "/v1/settings/account/chats/archive-all",
                    body: [:] as [String: String]
                )
                ToastManager.shared.show("All chats archived", type: .success)
                await loadStats()
            } catch {
                self.error = error.localizedDescription
            }
        }
    }

    private func deleteAll() {
        isDeleting = true
        Task {
            do {
                let _: Data = try await APIClient.shared.request(
                    .post, path: "/v1/settings/account/chats/delete-all",
                    body: [:] as [String: String]
                )
                ToastManager.shared.show("All chats deleted", type: .success)
                await loadStats()
            } catch {
                self.error = error.localizedDescription
            }
            isDeleting = false
        }
    }
}
