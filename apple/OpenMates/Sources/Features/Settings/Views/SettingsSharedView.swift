// Shared chats and embeds — lists chats/embeds shared by the user and shared with them.
// Mirrors the web app's SettingsShared.svelte: two sections showing owned shared items
// and items shared by others. Users can unshare owned items.

import SwiftUI

struct SettingsSharedView: View {
    @State private var sharedByMe: [SharedItem] = []
    @State private var sharedWithMe: [SharedItem] = []
    @State private var isLoading = true
    @State private var error: String?

    struct SharedItem: Identifiable, Decodable {
        let id: String
        let chatId: String
        let title: String?
        let sharedAt: String?
        let expiresAt: String?
        let shareUrl: String?
        let ownerUsername: String?
    }

    var body: some View {
        List {
            if isLoading {
                ProgressView()
            } else {
                Section("Shared by Me") {
                    if sharedByMe.isEmpty {
                        Text(LocalizationManager.shared.text("settings.shared.no_shared_chats"))
                            .font(.omSmall).foregroundStyle(Color.fontTertiary)
                    } else {
                        ForEach(sharedByMe) { item in
                            SharedItemRow(item: item)
                                .swipeActions {
                                    Button(role: .destructive) {
                                        unshare(item.id)
                                    } label: {
                                        Label("Unshare", systemImage: "link.badge.plus")
                                    }
                                }
                        }
                    }
                }

                Section("Shared with Me") {
                    if sharedWithMe.isEmpty {
                        Text(LocalizationManager.shared.text("settings.shared.no_chats_shared_with_you"))
                            .font(.omSmall).foregroundStyle(Color.fontTertiary)
                    } else {
                        ForEach(sharedWithMe) { item in
                            SharedItemRow(item: item)
                        }
                    }
                }
            }

            if let error {
                Section {
                    Text(error).font(.omSmall).foregroundStyle(Color.error)
                }
            }

            Section {
                NavigationLink {
                    SettingsTipView()
                } label: {
                    Label("Tip a Friend", systemImage: "gift")
                }
            }
        }
        .navigationTitle("Shared")
        .task { await loadShared() }
    }

    private func loadShared() async {
        do {
            let response: [String: AnyCodable] = try await APIClient.shared.request(
                .get, path: "/v1/settings/shared"
            )

            if let mine = response["shared_by_me"]?.value as? [[String: Any]] {
                sharedByMe = mine.compactMap(parseSharedItem)
            }
            if let theirs = response["shared_with_me"]?.value as? [[String: Any]] {
                sharedWithMe = theirs.compactMap(parseSharedItem)
            }
        } catch {
            self.error = error.localizedDescription
        }
        isLoading = false
    }

    private func parseSharedItem(_ dict: [String: Any]) -> SharedItem? {
        guard let id = dict["id"] as? String,
              let chatId = dict["chat_id"] as? String else { return nil }
        return SharedItem(
            id: id, chatId: chatId,
            title: dict["title"] as? String,
            sharedAt: dict["shared_at"] as? String,
            expiresAt: dict["expires_at"] as? String,
            shareUrl: dict["share_url"] as? String,
            ownerUsername: dict["owner_username"] as? String
        )
    }

    private func unshare(_ id: String) {
        Task {
            try? await APIClient.shared.request(
                .post, path: "/v1/settings/shared/\(id)/unshare",
                body: [:] as [String: String]
            ) as Data
            sharedByMe.removeAll { $0.id == id }
            ToastManager.shared.show("Chat unshared", type: .success)
        }
    }
}

// MARK: - Shared item row

struct SharedItemRow: View {
    let item: SettingsSharedView.SharedItem

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing1) {
            Text(item.title ?? "Untitled Chat")
                .font(.omSmall).fontWeight(.medium)

            HStack(spacing: .spacing3) {
                if let owner = item.ownerUsername {
                    Text("by \(owner)")
                        .font(.omXs).foregroundStyle(Color.fontSecondary)
                }
                if let shared = item.sharedAt {
                    Text(shared)
                        .font(.omXs).foregroundStyle(Color.fontTertiary)
                }
                if let expires = item.expiresAt {
                    Text("expires \(expires)")
                        .font(.omTiny).foregroundStyle(Color.warning)
                }
            }
        }
    }
}

// MARK: - Tip a friend view

struct SettingsTipView: View {
    @State private var recipientUsername = ""
    @State private var amount = ""
    @State private var message = ""
    @State private var isSending = false
    @State private var result: String?

    var body: some View {
        Form {
            Section("Recipient") {
                TextField("Username", text: $recipientUsername)
                    .autocorrectionDisabled()
                    #if os(iOS)
                    .textInputAutocapitalization(.never)
                    #endif
            }

            Section("Amount") {
                HStack {
                    Text(LocalizationManager.shared.text("settings.shared.credits_label"))
                    TextField("0.00", text: $amount)
                        .keyboardType(.decimalPad)
                }
            }

            Section("Message (optional)") {
                TextField("Add a note", text: $message)
            }

            Section {
                Button("Send Tip") { sendTip() }
                    .disabled(recipientUsername.isEmpty || amount.isEmpty || isSending)
            }

            if let result {
                Section {
                    Text(result)
                        .font(.omSmall)
                        .foregroundStyle(result.contains("Error") ? Color.error : .green)
                }
            }
        }
        .navigationTitle("Tip a Friend")
    }

    private func sendTip() {
        isSending = true
        result = nil
        Task {
            do {
                let _: Data = try await APIClient.shared.request(
                    .post, path: "/v1/settings/shared/tip",
                    body: [
                        "recipient_username": recipientUsername,
                        "amount": amount,
                        "message": message
                    ]
                )
                result = "Tip sent successfully!"
                recipientUsername = ""
                amount = ""
                message = ""
            } catch {
                result = "Error: \(error.localizedDescription)"
            }
            isSending = false
        }
    }
}
