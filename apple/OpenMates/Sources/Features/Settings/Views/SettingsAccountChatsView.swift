// Native age-based chat history cleanup with server preview and local cleanup.
// Mirrors SettingsAccountChats.svelte's count, period selection, preview,
// confirmation, delete response, and immediate local chat-store update.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/account/SettingsAccountChats.svelte
// CSS:     frontend/packages/ui/src/styles/settings.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct SettingsAccountChatsView: View {
    @EnvironmentObject private var chatStore: ChatStore
    @State private var totalCount: Int?
    @State private var selectedDays = "30"
    @State private var previewCount: Int?
    @State private var isWorking = false
    @State private var showDeleteConfirmation = false
    @State private var statusMessage: String?
    @State private var errorMessage: String?

    private let dayOptions = [0, 1, 7, 14, 30, 90]

    var body: some View {
        OMSettingsPage(title: AppStrings.chats) {
            OMSettingsSection(AppStrings.chatStatistics, icon: "chat") {
                OMSettingsStaticRow(
                    title: AppStrings.chatTotal,
                    value: totalCount.map(String.init) ?? AppStrings.loading
                )
            }

            OMSettingsSection(AppStrings.chatDeleteOld, icon: "trash") {
                VStack(alignment: .leading, spacing: .spacing5) {
                    OMDropdown(
                        title: AppStrings.chatOlderThan,
                        options: dayOptions.map { OMDropdownOption("\($0)", label: dayLabel($0)) },
                        selection: $selectedDays
                    )
                    .onChange(of: selectedDays) { _, _ in previewCount = nil }

                    Button(AppStrings.preview) { previewDeletion() }
                        .buttonStyle(OMSecondaryButtonStyle())
                        .disabled(isWorking)
                        .accessibilityIdentifier("settings-chats-preview")

                    if let previewCount {
                        OMSettingsStaticRow(title: AppStrings.preview, value: String(previewCount))
                        Button(AppStrings.chatDeleteOld) { showDeleteConfirmation = true }
                            .buttonStyle(OMPrimaryButtonStyle())
                            .disabled(previewCount == 0 || isWorking)
                            .accessibilityIdentifier("settings-chats-delete")
                    }
                }
                .padding(.spacing6)
            }

            if let statusMessage { status(statusMessage, color: Color.buttonPrimary) }
            if let errorMessage { status(errorMessage, color: Color.error) }
        }
        .task { await loadCount() }
        .overlay {
            if showDeleteConfirmation {
                OMConfirmDialog(
                    title: AppStrings.chatDeleteOld,
                    message: AppStrings.chatDeleteConfirm,
                    confirmTitle: AppStrings.delete,
                    isDestructive: true,
                    onConfirm: { showDeleteConfirmation = false; deleteChats() },
                    onCancel: { showDeleteConfirmation = false }
                )
            }
        }
        .accessibilityIdentifier("settings-account-chats-page")
    }

    private func loadCount() async {
        do {
            totalCount = try await AccountSecurityService.shared.chatCount()
        } catch {
            errorMessage = error.localizedDescription
            NativeDiagnostics.error("Chat count request failed", category: "settings.account")
        }
    }

    private func previewDeletion() {
        isWorking = true
        errorMessage = nil
        Task {
            do {
                previewCount = try await AccountSecurityService.shared.previewChatDeletion(
                    olderThanDays: Int(selectedDays) ?? 30
                )
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("Chat deletion preview failed", category: "settings.account")
            }
            isWorking = false
        }
    }

    private func deleteChats() {
        isWorking = true
        errorMessage = nil
        Task {
            do {
                let response = try await AccountSecurityService.shared.deleteOldChats(
                    olderThanDays: Int(selectedDays) ?? 30
                )
                response.deletedIds.forEach(chatStore.removeChat)
                previewCount = nil
                statusMessage = AppStrings.chatDeleteSuccess
                await loadCount()
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("Old-chat deletion failed", category: "settings.account")
            }
            isWorking = false
        }
    }

    private func dayLabel(_ days: Int) -> String {
        days == 0 ? AppStrings.never : AppStrings.chatDays(days)
    }

    private func status(_ message: String, color: Color) -> some View {
        Text(message).font(.omSmall).foregroundStyle(color).padding(.horizontal, .spacing6)
    }
}
