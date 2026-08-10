// Native chat auto-deletion period editor using the backend period-string schema.
// The server accepts only POST /v1/settings/auto-delete-chats with {period}.
// File retention is intentionally absent because no server mutation route exists.
// Failed saves keep the previous selection and expose a localized error state.
// OpenMates settings primitives replace stock picker and list controls.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/privacy/SettingsAutoDeletion.svelte
// CSS:     frontend/packages/ui/src/styles/settings.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct SettingsAutoDeletionView: View {
    @Binding var selectedPeriod: AutoDeletionPeriod
    @State private var isSaving = false
    @State private var errorMessage: String?

    var body: some View {
        OMSettingsPage(title: AppStrings.privacyAutoDeletionChats, showsHeader: false) {
            Text(AppStrings.privacyAutoDeletionChatsDescription)
                .font(.omP)
                .foregroundStyle(Color.grey100)
                .lineSpacing(3)
                .padding(.horizontal, .spacing8)

            OMSettingsSection(AppStrings.privacyAutoDeletionSelectPeriod, icon: "chat") {
                ForEach(AutoDeletionPeriod.allCases) { period in
                    Button {
                        Task { await save(period) }
                    } label: {
                        HStack(spacing: .spacing4) {
                            Text(period.label)
                                .font(.omP.weight(selectedPeriod == period ? .semibold : .regular))
                                .foregroundStyle(Color.fontPrimary)
                            Spacer()
                            if selectedPeriod == period {
                                Icon("check", size: 16)
                                    .foregroundStyle(Color.buttonPrimary)
                            }
                        }
                        .padding(.horizontal, .spacing8)
                        .padding(.vertical, .spacing6)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .disabled(isSaving)
                    .accessibilityIdentifier("privacy-auto-deletion-period-\(period.rawValue)")
                }
            }

            if let errorMessage {
                Text(errorMessage)
                    .font(.omSmall)
                    .foregroundStyle(Color.error)
                    .padding(.horizontal, .spacing8)
            }
        }
        .accessibilityIdentifier("privacy-auto-deletion-page")
    }

    private func save(_ period: AutoDeletionPeriod) async {
        guard period != selectedPeriod, !isSaving else { return }
        if PrivacySettingsUITestFixture.enabled {
            selectedPeriod = period
            return
        }
        isSaving = true
        errorMessage = nil
        defer { isSaving = false }
        do {
            let _: Data = try await APIClient.shared.request(
                .post,
                path: PrivacyAPIContract.autoDeleteChatsPath,
                body: AutoDeleteChatsRequest(period: period)
            )
            selectedPeriod = period
        } catch {
            NativeDiagnostics.error("Chat retention save failed: \(type(of: error))", category: "privacy")
            errorMessage = AppStrings.privacySaveError
        }
    }
}
