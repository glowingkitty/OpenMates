// Shared chats and embeds — lists chats/embeds shared by the user and shared with them.
// Mirrors the web app's SettingsShared.svelte: two sections showing owned shared items
// and items shared by others. Users can unshare owned items.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/SettingsShared.svelte
//          frontend/packages/ui/src/components/settings/tip/SettingsTip.svelte
// CSS:     frontend/packages/ui/src/styles/settings.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct SettingsSharedView: View {
    @State private var sharedByMe: [SharedItem] = []
    @State private var sharedWithMe: [SharedItem] = []
    @State private var isLoading = true
    @State private var error: String?
    @State private var showsTip = false

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
        Group {
            if showsTip {
                SettingsTipView()
            } else {
                OMSettingsPage(title: AppStrings.settingsShared, showsHeader: false) {
                    if isLoading {
                        ProgressView()
                            .frame(maxWidth: .infinity)
                            .padding(.spacing8)
                    } else {
                        OMSettingsSection(LocalizationManager.shared.text("settings.shared.by_me")) {
                            if sharedByMe.isEmpty {
                                Text(LocalizationManager.shared.text("settings.shared.no_shared_chats"))
                                    .font(.omSmall).foregroundStyle(Color.fontTertiary)
                                    .padding(.spacing5)
                            } else {
                                ForEach(sharedByMe) { item in
                                    SharedItemRow(item: item)
                                        .padding(.horizontal, .spacing5)
                                        .padding(.vertical, .spacing3)

                                    Button(LocalizationManager.shared.text("settings.shared.unshare")) {
                                        unshare(item.id)
                                    }
                                    .buttonStyle(OMPrimaryButtonStyle())
                                    .padding(.horizontal, .spacing5)
                                    .padding(.bottom, .spacing4)
                                }
                            }
                        }

                        OMSettingsSection(LocalizationManager.shared.text("settings.shared.with_me")) {
                            if sharedWithMe.isEmpty {
                                Text(LocalizationManager.shared.text("settings.shared.no_chats_shared_with_you"))
                                    .font(.omSmall).foregroundStyle(Color.fontTertiary)
                                    .padding(.spacing5)
                            } else {
                                ForEach(sharedWithMe) { item in
                                    SharedItemRow(item: item)
                                        .padding(.horizontal, .spacing5)
                                        .padding(.vertical, .spacing3)
                                }
                            }
                        }
                    }

                    if let error {
                        OMSettingsSection {
                            Text(error).font(.omSmall).foregroundStyle(Color.error)
                                .padding(.spacing5)
                        }
                    }

                    OMSettingsSection {
                        OMSettingsRow(title: LocalizationManager.shared.text("settings.shared.tip"), icon: "gift") {
                            showsTip = true
                        }
                    }
                }
            }
        }
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
        OMSettingsPage(title: LocalizationManager.shared.text("settings.shared.tip"), showsHeader: false) {
            OMSettingsSection(LocalizationManager.shared.text("settings.shared.recipient")) {
                TextField("Username", text: $recipientUsername)
                    .textFieldStyle(OMTextFieldStyle())
                    .padding(.spacing5)
                    .autocorrectionDisabled()
                    #if os(iOS)
                    .textInputAutocapitalization(.never)
                    #endif
            }

            OMSettingsSection(LocalizationManager.shared.text("settings.shared.amount")) {
                HStack {
                    Text(LocalizationManager.shared.text("settings.shared.credits_label"))
                    TextField("0.00", text: $amount)
                        .textFieldStyle(OMTextFieldStyle())
                        #if os(iOS)
                        .keyboardType(.decimalPad)
                        #endif
                }
                .padding(.spacing5)
            }

            OMSettingsSection(LocalizationManager.shared.text("settings.shared.message_optional")) {
                TextField("Add a note", text: $message)
                    .textFieldStyle(OMTextFieldStyle())
                    .padding(.spacing5)
            }

            OMSettingsSection {
                Button("Send Tip") { sendTip() }
                    .disabled(recipientUsername.isEmpty || amount.isEmpty || isSending)
                    .buttonStyle(OMPrimaryButtonStyle())
                    .padding(.spacing5)
            }

            if let result {
                OMSettingsSection {
                    Text(result)
                        .font(.omSmall)
                        .foregroundStyle(result.contains("Error") ? Color.error : .green)
                        .padding(.spacing5)
                }
            }
        }
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
