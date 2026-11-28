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
    @State private var pendingDisconnect: ConnectedAccountSummary?
    @State private var addOpen = false
    @State private var googleCalendar = true
    @State private var googleGmail = false

    var body: some View {
        OMSettingsPage(title: AppStrings.privacyConnectedAccounts, showsHeader: false) {
            Text(AppStrings.privacyConnectedAccountsDescription)
                .font(.omSmall)
                .foregroundStyle(Color.fontSecondary)
                .lineSpacing(3)
                .padding(.horizontal, .spacing8)

            if let message = controller.actionMessage {
                Text(message).font(.omSmall).foregroundStyle(Color.fontSecondary).padding(.horizontal, .spacing8)
                    .accessibilityIdentifier("privacy-connected-accounts-success")
            }
            if let message = controller.actionError {
                Text(message).font(.omSmall).foregroundStyle(Color.error).padding(.horizontal, .spacing8)
                    .accessibilityIdentifier("privacy-connected-accounts-action-error")
            }
            if controller.canConnect { connectSection }

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
                            OMSettingsRow(
                                title: AppStrings.connectedAccountsDisconnect,
                                icon: "close",
                                isDestructive: true,
                                showsChevron: false,
                                accessibilityIdentifier: "privacy-connected-account-disconnect"
                            ) { pendingDisconnect = account }
                            .disabled(controller.actionInFlight)
                        }
                        .accessibilityElement(children: .contain)
                        .accessibilityIdentifier("privacy-connected-account-row")
                    }
                }
            }
        }
        .overlay {
            if let account = pendingDisconnect {
                OMConfirmDialog(
                    title: AppStrings.connectedAccountsDisconnect,
                    message: AppStrings.connectedAccountsDisconnectConfirm(providerLabel(account.providerId)),
                    confirmTitle: AppStrings.connectedAccountsDisconnectConfirmButton,
                    isDestructive: true,
                    onConfirm: {
                        pendingDisconnect = nil
                        Task { await controller.disconnect(account) }
                    },
                    onCancel: { pendingDisconnect = nil }
                )
            }
        }
        .accessibilityIdentifier("privacy-connected-accounts-page")
        .task { await controller.load() }
    }

    @ViewBuilder private var connectSection: some View {
        OMSettingsSection(AppStrings.connectedAccountsAdd, icon: "plus") {
            OMSettingsRow(
                title: AppStrings.connectedAccountsProviderGoogle,
                showsChevron: true,
                accessibilityIdentifier: "privacy-connected-account-connect-google"
            ) { addOpen.toggle() }
            if addOpen {
                OMSettingsRow(
                    title: AppStrings.connectedAccountsAccessCalendar,
                    icon: googleCalendar ? "check" : "app",
                    showsChevron: false,
                    accessibilityIdentifier: "privacy-connected-account-google-calendar-access"
                ) { googleCalendar.toggle() }
                OMSettingsRow(
                    title: AppStrings.connectedAccountsAccessGmail,
                    icon: googleGmail ? "check" : "app",
                    showsChevron: false,
                    accessibilityIdentifier: "privacy-connected-account-google-gmail-access"
                ) { googleGmail.toggle() }
                OMSettingsRow(
                    title: AppStrings.connectedAccountsProviderGoogle,
                    showsChevron: false,
                    accessibilityIdentifier: "privacy-connected-account-connect-google-continue"
                ) {
                    guard googleCalendar || googleGmail else { return }
                    let appId = googleCalendar ? "calendar" : "mail"
                    let request = ConnectedAccountOAuthRequest(
                        provider: .google, appId: appId,
                        capabilities: appId == "calendar" ? ["read"] : ["read", "draft"]
                    )
                    addOpen = false
                    Task { await controller.connect(request) }
                }
                .disabled(controller.actionInFlight || !(googleCalendar || googleGmail))
            }
            OMSettingsRow(
                title: AppStrings.connectedAccountsProviderFigma,
                showsChevron: false,
                accessibilityIdentifier: "privacy-connected-account-connect-figma"  // figma-visual-proof: not-required (OAuth provider, not a design)
            ) {
                Task { await controller.connect(ConnectedAccountOAuthRequest(provider: .figma, appId: "design", capabilities: ["read"])) }  // figma-visual-proof: not-required (OAuth provider, not a design)
            }
            .disabled(controller.actionInFlight)
        }
    }

    private func providerLabel(_ providerId: String) -> String {
        switch providerId {
        case "google_calendar": return AppStrings.privacyProviderGoogleCalendar
        case "figma": return AppStrings.connectedAccountsProviderFigma  // figma-visual-proof: not-required (OAuth provider, not a design)
        default: return providerId
        }
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
