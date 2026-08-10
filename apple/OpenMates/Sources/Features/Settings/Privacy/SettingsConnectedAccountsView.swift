// Native connected-account privacy page rendering only decrypted safe summaries.
// Refresh-token bundles and provider account display fields are never published,
// rendered, logged, or copied into diagnostics by this view or its controller.
// Data comes from the authenticated /v1/connected-accounts encrypted row route.
// Loading, empty, and failure states remain explicit and localized.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/privacy/SettingsConnectedAccounts.svelte
// CSS:     frontend/packages/ui/src/styles/settings.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct SettingsConnectedAccountsView: View {
    @StateObject private var controller = PrivacyConnectedAccountsController()

    var body: some View {
        OMSettingsPage(title: AppStrings.privacyConnectedAccounts, showsHeader: false) {
            Text(AppStrings.privacyConnectedAccountsDescription)
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
                .lineSpacing(3)
                .padding(.horizontal, .spacing8)

            if controller.isLoading {
                ProgressView()
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, .spacing12)
            } else if let errorMessage = controller.errorMessage {
                OMSettingsSection(AppStrings.error, icon: "report_issue") {
                    Text(errorMessage)
                        .font(.omSmall)
                        .foregroundStyle(Color.error)
                        .padding(.horizontal, .spacing8)
                        .padding(.vertical, .spacing4)
                }
            } else if controller.summaries.isEmpty {
                Text(AppStrings.privacyConnectedAccountsEmpty)
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
                    .padding(.horizontal, .spacing8)
            } else {
                OMSettingsSection(AppStrings.privacyConnectedAccountsList, icon: "app") {
                    ForEach(controller.summaries) { account in
                        VStack(alignment: .leading, spacing: .spacing2) {
                            OMSettingsStaticRow(
                                title: account.label,
                                value: providerLabel(account.providerId),
                                icon: account.appId
                            )
                            Text(capabilityLabel(account.capabilities))
                                .font(.omXs)
                                .foregroundStyle(Color.fontSecondary)
                                .padding(.horizontal, .spacing8)
                        }
                        .accessibilityIdentifier("privacy-connected-account-row")
                    }
                }
            }
        }
        .accessibilityIdentifier("privacy-connected-accounts-page")
        .task { await controller.load() }
    }

    private func providerLabel(_ providerId: String) -> String {
        providerId == "google_calendar" ? AppStrings.privacyProviderGoogleCalendar : providerId
    }

    private func capabilityLabel(_ capabilities: [String]) -> String {
        guard !capabilities.isEmpty else { return AppStrings.none }
        return capabilities.map { capability in
            switch capability {
            case "read": return AppStrings.privacyCapabilityRead
            case "write": return AppStrings.privacyCapabilityWrite
            case "delete": return AppStrings.delete
            default: return capability
            }
        }.joined(separator: ", ")
    }
}
