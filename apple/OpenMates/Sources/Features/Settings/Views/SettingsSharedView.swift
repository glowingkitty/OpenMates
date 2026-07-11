// Shared chats hub backed by the native synchronized chat store.
// Mirrors SettingsShared.svelte without calling nonexistent settings endpoints.
// Users can open native sharing controls or unshare an existing public chat.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/SettingsShared.svelte
//          frontend/packages/ui/src/components/settings/tip/SettingsTip.svelte
// CSS:     frontend/packages/ui/src/styles/settings.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct SettingsSharedView: View {
    @EnvironmentObject private var chatStore: ChatStore
    @State private var selectedChatId: String?
    @State private var errorMessage: String?
    @State private var showsTip = false

    private var sharedChats: [Chat] {
        chatStore.chats.filter { $0.isPrivate == false }
    }

    var body: some View {
        Group {
            if let selectedChatId {
                VStack(spacing: 0) {
                    OMSettingsRow(title: AppStrings.back, icon: "back", showsChevron: false) {
                        self.selectedChatId = nil
                    }
                    ChatShareView(chatId: selectedChatId)
                }
            } else if showsTip {
                SettingsTipView()
            } else {
                OMSettingsPage(title: AppStrings.settingsShared, showsHeader: false) {
                        OMSettingsSection(LocalizationManager.shared.text("settings.shared.by_me")) {
                            if sharedChats.isEmpty {
                                Text(LocalizationManager.shared.text("settings.shared.no_shared_chats"))
                                    .font(.omSmall).foregroundStyle(Color.fontTertiary)
                                    .padding(.spacing5)
                            } else {
                                ForEach(sharedChats) { chat in
                                    OMSettingsRow(
                                        title: chat.title ?? LocalizationManager.shared.text("common.untitled_chat"),
                                        icon: chat.icon ?? "chat",
                                        accessibilityIdentifier: "settings-shared-chat-\(chat.id)"
                                    ) { selectedChatId = chat.id }
                                    OMSettingsRow(
                                        title: LocalizationManager.shared.text("settings.shared.unshare"),
                                        icon: "unlink",
                                        isDestructive: true,
                                        showsChevron: false
                                    ) { unshare(chat) }
                                }
                            }
                        }

                    if let errorMessage {
                        OMSettingsSection {
                            Text(errorMessage).font(.omSmall).foregroundStyle(Color.error)
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
    }

    private func unshare(_ chat: Chat) {
        Task {
            do {
                let _: Data = try await APIClient.shared.request(
                    .post, path: "/v1/share/chat/unshare",
                    body: ["chat_id": chat.id]
                )
                chatStore.upsertChat(chat.withPrivacy(true))
                ToastManager.shared.show(AppStrings.success, type: .success)
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("Chat unshare failed", category: "settings.shared")
            }
        }
    }
}

private extension Chat {
    func withPrivacy(_ isPrivate: Bool) -> Chat {
        Chat(
            id: id, title: title, lastMessageAt: lastMessageAt, createdAt: createdAt,
            updatedAt: updatedAt, isArchived: isArchived, isPinned: isPinned, appId: appId,
            category: category, icon: icon, chatSummary: chatSummary, encryptedTitle: encryptedTitle,
            encryptedCategory: encryptedCategory, encryptedIcon: encryptedIcon,
            encryptedChatSummary: encryptedChatSummary, encryptedChatKey: encryptedChatKey,
            messagesV: messagesV, titleV: titleV, draftV: draftV,
            lastVisibleMessageId: lastVisibleMessageId, parentId: parentId, isSubChat: isSubChat,
            subChatSettings: subChatSettings, budgetLimit: budgetLimit, budgetSpent: budgetSpent,
            encryptedActiveFocusId: encryptedActiveFocusId, activeFocusId: activeFocusId,
            isPrivate: isPrivate, isHidden: isHidden, isHiddenCandidate: isHiddenCandidate
        )
    }
}

// MARK: - Tip a friend view

struct SettingsTipView: View {
    @State private var ownerId = ""
    @State private var amount = ""
    @State private var isSending = false
    @State private var result: String?

    var body: some View {
        OMSettingsPage(title: LocalizationManager.shared.text("settings.shared.tip"), showsHeader: false) {
            OMSettingsSection(LocalizationManager.shared.text("settings.shared.recipient")) {
                TextField(LocalizationManager.shared.text("settings.tip.channel_id"), text: $ownerId)
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

            OMSettingsSection {
                Button(LocalizationManager.shared.text("settings.tip.tip_creator")) { sendTip() }
                    .disabled(ownerId.isEmpty || amount.isEmpty || isSending)
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
                    .post, path: "/v1/creators/tip",
                    body: CreatorTipRequest(
                        ownerId: ownerId,
                        contentType: "video",
                        credits: Int(amount) ?? 0
                    )
                )
                result = AppStrings.success
                ownerId = ""
                amount = ""
            } catch {
                result = "\(AppStrings.error): \(error.localizedDescription)"
                NativeDiagnostics.error("Creator tip failed", category: "settings.shared")
            }
            isSending = false
        }
    }
}

private struct CreatorTipRequest: Encodable {
    let ownerId: String
    let contentType: String
    let credits: Int
}
