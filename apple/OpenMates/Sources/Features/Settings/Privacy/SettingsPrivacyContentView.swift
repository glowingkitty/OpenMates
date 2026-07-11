// Native Privacy settings hub matching the web SettingsPrivacy hierarchy.
// Provides native navigation for policy, connected accounts, personal-data,
// location, retention, diagnostics, and temporary debug-session controls.
// All product controls use OpenMates primitives and stable web-aligned IDs.
// File retention remains read-only because no backend mutation route exists.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/SettingsPrivacy.svelte
//          frontend/packages/ui/src/components/settings/privacy/SettingsConnectedAccounts.svelte
// CSS:     frontend/packages/ui/src/styles/settings.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct SettingsPrivacyContentView: View {
    @EnvironmentObject private var authManager: AuthManager
    @StateObject private var privacyService = ApplePrivacySettingsService.shared
    @State private var destination: Destination?
    @State private var stabilityLogsEnabled = PrivacyDiagnosticsPreferences().stabilityLogsEnabled
    @State private var detailedDebugLoggingEnabled = PrivacyDiagnosticsPreferences().detailedDebugLoggingEnabled
    @State private var chatAutoDeletionPeriod: AutoDeletionPeriod = .ninetyDays

    private let diagnosticsPreferences = PrivacyDiagnosticsPreferences()

    var body: some View {
        if let destination {
            VStack(spacing: 0) {
                subpageHeader(destination.title)
                destinationView(destination)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .background(Color.grey0)
        } else {
            privacyHub
                .task {
                    chatAutoDeletionPeriod = AutoDeletionPeriod.from(days: authManager.currentUser?.autoDeleteChatsAfterDays)
                    if !PrivacySettingsUITestFixture.enabled { await privacyService.load() }
                }
        }
    }

    private var privacyHub: some View {
        OMSettingsPage(title: AppStrings.settingsPrivacy, showsHeader: false) {
            OMSettingsSection {
                OMSettingsRow(
                    title: AppStrings.privacyOpenPolicy,
                    icon: "privacy",
                    accessibilityIdentifier: "settings-privacy-policy-link"
                ) { destination = .policy }
            }

            OMSettingsSection(AppStrings.privacyAnonymization, icon: "anonym") {
                OMSettingsRow(
                    title: AppStrings.privacyHidePersonalData,
                    subtitle: AppStrings.privacyHidePersonalDataChats,
                    icon: "anonym",
                    value: privacyService.state.detectionSettings.masterEnabled ? AppStrings.enabled : AppStrings.disabled,
                    accessibilityIdentifier: "settings-hide-personal-data-row"
                ) { destination = .hidePersonalData }

                OMSettingsRow(
                    title: AppStrings.privacyConnectedAccounts,
                    subtitle: AppStrings.privacyConnectedAccountsSubtitle,
                    icon: "privacy",
                    accessibilityIdentifier: "settings-privacy-connected-accounts-row"
                ) { destination = .connectedAccounts }

                OMSettingsToggleRow(
                    title: AppStrings.privacyNearbyByDefault,
                    subtitle: AppStrings.privacyMapsLocation,
                    icon: "maps",
                    isOn: locationBinding
                )
                .accessibilityIdentifier("settings-privacy-location-toggle")
            }

            OMSettingsSection(AppStrings.privacyAutoDeletion, icon: "delete") {
                OMSettingsRow(
                    title: AppStrings.privacyAutoDeletionChats,
                    icon: "chat",
                    value: chatRetentionValue,
                    accessibilityIdentifier: "settings-privacy-auto-delete-chats-row"
                ) { destination = .chatAutoDeletion }

                staticRetentionRow(
                    title: AppStrings.privacyAutoDeletionFiles,
                    value: AppStrings.privacyAutoDeletionFilesValue,
                    icon: "files",
                    identifier: "settings-privacy-files-retention-row"
                )
                staticRetentionRow(
                    title: AppStrings.privacyAutoDeletionUsageData,
                    value: AppStrings.privacyAutoDeletionUsageDataValue,
                    icon: "usage",
                    identifier: "settings-privacy-usage-retention-row"
                )
                staticRetentionRow(
                    title: AppStrings.privacyAutoDeletionComplianceLogs,
                    value: AppStrings.privacyAutoDeletionComplianceLogsValue,
                    icon: "log",
                    identifier: "settings-privacy-compliance-retention-row"
                )
                staticRetentionRow(
                    title: AppStrings.privacyAutoDeletionInvoices,
                    value: AppStrings.privacyAutoDeletionInvoicesValue,
                    icon: "billing",
                    identifier: "settings-privacy-invoices-retention-row"
                )

                privacyNote(AppStrings.privacyAutoDeletionComplianceNote)
            }

            OMSettingsSection(AppStrings.privacyStabilityLogsTitle, icon: "log") {
                OMSettingsToggleRow(
                    title: AppStrings.privacyStabilityLogsToggle,
                    subtitle: AppStrings.privacyStabilityLogsDescription,
                    icon: "log",
                    isOn: Binding(
                        get: { stabilityLogsEnabled },
                        set: { enabled in
                            diagnosticsPreferences.setStabilityLogsEnabled(enabled)
                            stabilityLogsEnabled = enabled
                        }
                    )
                )
                .accessibilityIdentifier("settings-privacy-stability-toggle")
                privacyNote(AppStrings.privacyStabilityLogsNote)
            }

            OMSettingsSection(AppStrings.privacyDebugLoggingTitle, icon: "log") {
                OMSettingsToggleRow(
                    title: AppStrings.privacyDebugLoggingToggle,
                    subtitle: AppStrings.privacyDebugLoggingDescription,
                    icon: "log",
                    isOn: Binding(
                        get: { detailedDebugLoggingEnabled },
                        set: { enabled in
                            diagnosticsPreferences.setDetailedDebugLoggingEnabled(enabled)
                            detailedDebugLoggingEnabled = enabled
                        }
                    )
                )
                .accessibilityIdentifier("settings-privacy-debug-toggle")
                privacyNote(AppStrings.privacyDebugLoggingNeverCollected)

                OMSettingsRow(
                    title: AppStrings.privacyShareDebugLogs,
                    icon: "log",
                    accessibilityIdentifier: "settings-privacy-share-debug-logs-row"
                ) { destination = .debugSession }

                if authManager.currentUser?.isAdmin == true {
                    privacyNote(AppStrings.privacyShareDebugLogsAdminNotice)
                }
            }

            if let error = privacyService.errorMessage {
                OMSettingsSection(AppStrings.error, icon: "report_issue") {
                    Text(error)
                        .font(.omSmall)
                        .foregroundStyle(Color.error)
                        .padding(.horizontal, .spacing8)
                        .padding(.vertical, .spacing4)
                }
            }
        }
        .accessibilityIdentifier("settings-privacy-hub")
    }

    private var locationBinding: Binding<Bool> {
        Binding(
            get: { privacyService.state.locationImpreciseByDefault },
            set: { enabled in
                if PrivacySettingsUITestFixture.enabled { return }
                Task { await privacyService.setLocationImpreciseByDefault(enabled) }
            }
        )
    }

    private var chatRetentionValue: String {
        chatAutoDeletionPeriod.label
    }

    private func staticRetentionRow(title: String, value: String, icon: String, identifier: String) -> some View {
        OMSettingsStaticRow(title: title, value: value, icon: icon)
            .accessibilityIdentifier(identifier)
    }

    private func privacyNote(_ text: String) -> some View {
        Text(text)
            .font(.omXs)
            .foregroundStyle(Color.fontSecondary)
            .lineSpacing(3)
            .padding(.horizontal, .spacing8)
            .padding(.vertical, .spacing4)
    }

    private func subpageHeader(_ title: String) -> some View {
        HStack(spacing: .spacing4) {
            OMIconButton(icon: "back", label: AppStrings.back, size: 36) { destination = nil }
                .accessibilityIdentifier("settings-privacy-subpage-back")
            Text(title)
                .font(.omH3.weight(.semibold))
                .foregroundStyle(Color.fontPrimary)
            Spacer()
        }
        .padding(.horizontal, .spacing8)
        .padding(.vertical, .spacing6)
        .background(Color.grey0)
    }

    @ViewBuilder
    private func destinationView(_ destination: Destination) -> some View {
        switch destination {
        case .policy: LegalChatView(documentType: .privacy)
        case .hidePersonalData: SettingsHidePersonalDataView()
        case .connectedAccounts: SettingsConnectedAccountsView()
        case .chatAutoDeletion: SettingsAutoDeletionView(selectedPeriod: $chatAutoDeletionPeriod)
        case .debugSession: SettingsShareDebugLogsView()
        }
    }

    private enum Destination: Hashable {
        case policy, hidePersonalData, connectedAccounts, chatAutoDeletion, debugSession

        @MainActor var title: String {
            switch self {
            case .policy: return AppStrings.privacyPolicy
            case .hidePersonalData: return AppStrings.privacyHidePersonalData
            case .connectedAccounts: return AppStrings.privacyConnectedAccounts
            case .chatAutoDeletion: return AppStrings.privacyAutoDeletionChats
            case .debugSession: return AppStrings.privacyShareDebugLogs
            }
        }
    }
}

extension AutoDeletionPeriod {
    @MainActor var label: String {
        switch self {
        case .thirtyDays: return AppStrings.privacyPeriod30Days
        case .sixtyDays: return AppStrings.privacyPeriod60Days
        case .ninetyDays: return AppStrings.privacyPeriod90Days
        case .sixMonths: return AppStrings.privacyPeriod6Months
        case .oneYear: return AppStrings.privacyPeriod1Year
        case .twoYears: return AppStrings.privacyPeriod2Years
        case .fiveYears: return AppStrings.privacyPeriod5Years
        case .never: return AppStrings.privacyPeriodNever
        }
    }
}
