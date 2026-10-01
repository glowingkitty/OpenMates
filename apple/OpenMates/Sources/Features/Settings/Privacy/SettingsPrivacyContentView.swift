// Native Privacy settings hub matching the web SettingsPrivacy hierarchy.
// Provides native navigation for policy, connected accounts, personal-data,
// location, retention, diagnostics, and temporary debug-session controls.
// All product controls use OpenMates primitives and stable web-aligned IDs.
// File retention remains read-only because no backend mutation route exists.
// Guest account actions enter the existing authentication flow before private access.
// Specification: specifications/features/settings-ui/specification.yml
// Assertions: settings-ui.navigation.contextual-availability, settings-ui.parity.web-apple-shell

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
    private let deepLinkPath: String?

    init(deepLinkPath: String? = nil) {
        self.deepLinkPath = deepLinkPath
        let routes: [String: Destination] = ["connected-accounts": .connectedAccounts,
            "hide-personal-data": .hidePersonalData, "auto-deletion/chats": .chatAutoDeletion,
            "share-debug-logs": .debugSession]
        _destination = State(initialValue: deepLinkPath?.hasPrefix("hide-personal-data/") == true
            ? .hidePersonalData : routes[deepLinkPath ?? ""])
    }

    var body: some View {
        Group {
            if let destination, destination == .policy || isAuthenticated {
                VStack(spacing: 0) {
                    subpageHeader(destination.title)
                    destinationView(destination)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .onAppear {
                            chatAutoDeletionPeriod = isAuthenticated
                                ? AutoDeletionPeriod.from(days: authManager.currentUser?.autoDeleteChatsAfterDays) : .ninetyDays
                        }
                }
                .background(Color.grey0)
            } else {
                privacyHub
                    .task(id: authManager.currentUser?.id) {
                        chatAutoDeletionPeriod = isAuthenticated
                                ? AutoDeletionPeriod.from(days: authManager.currentUser?.autoDeleteChatsAfterDays) : .ninetyDays
                        if isAuthenticated && !PrivacySettingsUITestFixture.enabled { await privacyService.load() }
                    }
            }
        }
        .onAppear {
            guard destination != nil, destination != .policy, !isAuthenticated else { return }
            destination = nil
            _ = requireAuthentication()
        }
        .onChange(of: authManager.currentUser?.id) { previousID, currentID in
            guard previousID != currentID else { return }
            if destination != .policy { destination = nil }
            chatAutoDeletionPeriod = isAuthenticated
                                ? AutoDeletionPeriod.from(days: authManager.currentUser?.autoDeleteChatsAfterDays) : .ninetyDays
        }
    }

    private var privacyHub: some View {
        OMSettingsPage(title: AppStrings.settingsPrivacy, showsHeader: false,
                       contentHorizontalPadding: 0, contentVerticalSpacing: 0,
                       scrollAccessibilityIdentifier: "settings-privacy-page") {
            // SettingsPrivacy.svelte is a flat SettingsItem list, without section dividers.
            VStack(alignment: .leading, spacing: 0) {
                Button { destination = .policy } label: {
                    Text(AppStrings.privacyOpenPolicy)
                        .font(.omP.weight(.bold))
                        .foregroundStyle(LinearGradient.primary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, .spacing8)
                        .padding(.vertical, .spacing5)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("settings-privacy-policy-link")

                privacyHeading(AppStrings.privacyAnonymization, icon: "anonym")
                privacyRow(title: AppStrings.privacyHidePersonalData, subtitle: AppStrings.chats,
                           icon: "anonym", identifier: "settings-hide-personal-data-row",
                           toggle: Binding(get: { visiblePrivacyState.detectionSettings.masterEnabled },
                                           set: { _ in openAccountDestination(.hidePersonalData) })) {
                    openAccountDestination(.hidePersonalData)
                }
                privacyRow(title: AppStrings.privacyConnectedAccounts,
                           subtitle: AppStrings.privacyConnectedAccountsSubtitle, icon: "privacy",
                           identifier: "settings-privacy-connected-accounts-row") {
                    openAccountDestination(.connectedAccounts)
                }
                privacyRow(title: AppStrings.privacyNearbyByDefault, subtitle: AppStrings.privacyMapsLocation,
                           icon: "maps", identifier: "settings-privacy-location-row",
                           toggle: locationBinding, toggleIdentifier: "settings-privacy-location-toggle") {
                    locationBinding.wrappedValue.toggle()
                }

                privacyHeading(AppStrings.privacyAutoDeletion, icon: "delete")
                privacyRow(title: chatRetentionValue, subtitle: AppStrings.chats, icon: "chat",
                           identifier: "settings-privacy-auto-delete-chats-row", modifies: true) {
                    openAccountDestination(.chatAutoDeletion)
                }
                staticRetentionRow(title: AppStrings.privacyAutoDeletionFiles,
                    value: AppStrings.privacyAutoDeletionFilesValue, icon: "files",
                    identifier: "settings-privacy-files-retention-row")
                staticRetentionRow(title: AppStrings.privacyAutoDeletionUsageData,
                    value: AppStrings.privacyAutoDeletionUsageDataValue, icon: "usage",
                    identifier: "settings-privacy-usage-retention-row")
                staticRetentionRow(title: AppStrings.privacyAutoDeletionComplianceLogs,
                    value: AppStrings.privacyAutoDeletionComplianceLogsValue, icon: "log",
                    identifier: "settings-privacy-compliance-retention-row")
                staticRetentionRow(title: AppStrings.privacyAutoDeletionInvoices,
                    value: AppStrings.privacyAutoDeletionInvoicesValue, icon: "billing",
                    identifier: "settings-privacy-invoices-retention-row")
                privacyNote(AppStrings.privacyAutoDeletionComplianceNote)

                privacyHeading(AppStrings.privacyStabilityLogsTitle, icon: "log")
                privacyRow(title: AppStrings.privacyStabilityLogsToggle,
                    subtitle: AppStrings.privacyStabilityLogsDescription, icon: "log",
                    identifier: "settings-privacy-stability-row", toggle: stabilityBinding,
                    toggleIdentifier: "settings-privacy-stability-toggle") {
                        stabilityBinding.wrappedValue.toggle()
                    }
                privacyNote(AppStrings.privacyStabilityLogsNote)

                privacyHeading(AppStrings.privacyDebugLoggingTitle, icon: "log")
                privacyRow(title: AppStrings.privacyDebugLoggingToggle,
                    subtitle: AppStrings.privacyDebugLoggingDescription, icon: "log",
                    identifier: "settings-privacy-debug-row", toggle: debugLoggingBinding,
                    toggleIdentifier: "settings-privacy-debug-toggle") {
                        debugLoggingBinding.wrappedValue.toggle()
                    }
                privacyNote(AppStrings.privacyDebugLoggingNeverCollected)
                privacyRow(title: AppStrings.privacyShareDebugLogs, icon: "log",
                           identifier: "settings-privacy-share-debug-logs-row", filledIcon: true) {
                    openAccountDestination(.debugSession)
                }
                if authManager.currentUser?.isAdmin == true {
                    privacyNote(AppStrings.privacyShareDebugLogsAdminNotice)
                }
                if isAuthenticated, let error = privacyService.errorMessage {
                    privacyHeading(AppStrings.error, icon: "report_issue")
                    Text(error).font(.omSmall).foregroundStyle(Color.error)
                        .padding(.horizontal, .spacing8).padding(.vertical, .spacing5)
                }
            }
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("settings-privacy-hub")
        }
    }

    // Exact SettingsItem.svelte metrics: 44pt icon slot, 12pt gap, 5×10pt padding.
    // Filled headings use white glyphs; subsubmenu glyphs use primary on grey20→30.
    private func privacyIcon(_ icon: String, filled: Bool) -> some View {
        Icon(icon, size: 22)
            .foregroundStyle(filled ? AnyShapeStyle(Color.white) : AnyShapeStyle(LinearGradient.primary))
            .frame(width: 44, height: 44)
            .background(filled ? AnyShapeStyle(LinearGradient.primary) : AnyShapeStyle(
                LinearGradient(colors: [Color.grey20, Color.grey30], startPoint: .topLeading, endPoint: .bottomTrailing)))
            .clipShape(RoundedRectangle(cornerRadius: .radius4))
            .accessibilityHidden(true)
    }

    private func privacyHeading(_ title: String, icon: String) -> some View {
        HStack(spacing: .spacing6) {
            privacyIcon(icon, filled: true)
            Text(title).font(.omP.weight(.semibold)).foregroundStyle(Color.fontPrimary)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, .spacing5)
        .padding(.vertical, CGFloat.spacing5 / 2) // CSS 5px; spacing5=10pt.
    }

    private func privacyRow(title: String, subtitle: String? = nil, icon: String, identifier: String,
                            toggle: Binding<Bool>? = nil, toggleIdentifier: String? = nil,
                            modifies: Bool = false, filledIcon: Bool = false,
                            action: (() -> Void)? = nil) -> some View {
        HStack(spacing: 0) {
            Group {
                if let action {
                    Button(action: action) {
                        privacyRowLabel(title: title, subtitle: subtitle, icon: icon,
                                        clickable: !modifies, filledIcon: filledIcon)
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier(identifier)
                } else {
                    privacyRowLabel(title: title, subtitle: subtitle, icon: icon,
                                    clickable: false, filledIcon: filledIcon)
                        .accessibilityElement(children: .combine)
                        .accessibilityIdentifier(identifier)
                }
            }
            if let toggle {
                OMToggle(isOn: toggle, accessibilityIdentifier: toggleIdentifier ?? identifier + "-toggle")
                    .accessibilityLabel(title)
                    .padding(.spacing2)
            }
            if modifies, let action {
                Button(action: action) {
                    Icon("modify", size: 15).foregroundStyle(.white)
                        .frame(width: 30, height: 30)
                        .background(LinearGradient.primary, in: Circle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(AppStrings.localized("settings.modify"))
                .accessibilityIdentifier(identifier + "-modify")
            }
        }
        .padding(.horizontal, .spacing5)
        .padding(.vertical, CGFloat.spacing5 / 2)
    }

    private func privacyRowLabel(title: String, subtitle: String?, icon: String,
                                 clickable: Bool, filledIcon: Bool) -> some View {
        HStack(spacing: .spacing6) {
            privacyIcon(icon, filled: filledIcon)
            VStack(alignment: .leading, spacing: .spacing1) {
                if let subtitle {
                    Text(subtitle).font(.omSmall).foregroundStyle(Color.grey60)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Text(title).font(.omP.weight(.medium))
                    .foregroundStyle(clickable ? AnyShapeStyle(LinearGradient.primary) : AnyShapeStyle(Color.fontPrimary))
                    .lineLimit(clickable ? 1 : 3)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
        .contentShape(Rectangle())
    }

    private var stabilityBinding: Binding<Bool> {
        Binding(get: { isAuthenticated ? stabilityLogsEnabled : true }, set: { enabled in
            guard requireAuthentication() else { return }
            diagnosticsPreferences.setStabilityLogsEnabled(enabled)
            stabilityLogsEnabled = enabled
        })
    }

    private var debugLoggingBinding: Binding<Bool> {
        Binding(get: { isAuthenticated ? detailedDebugLoggingEnabled : false }, set: { enabled in
            guard requireAuthentication() else { return }
            diagnosticsPreferences.setDetailedDebugLoggingEnabled(enabled)
            detailedDebugLoggingEnabled = enabled
        })
    }

    private var isAuthenticated: Bool {
        authManager.currentUser != nil
    }

    private var visiblePrivacyState: ApplePrivacySettingsState {
        isAuthenticated ? privacyService.state : ApplePrivacySettingsState()
    }

    private func requireAuthentication() -> Bool {
        guard isAuthenticated else {
            NotificationCenter.default.post(name: .openAuth, object: nil)
            return false
        }
        return true
    }

    private func openAccountDestination(_ destination: Destination) {
        guard requireAuthentication() else { return }
        self.destination = destination
    }

    private var locationBinding: Binding<Bool> {
        Binding(
            get: { visiblePrivacyState.locationImpreciseByDefault },
            set: { enabled in
                guard requireAuthentication() else { return }
                if PrivacySettingsUITestFixture.enabled { return }
                Task { await privacyService.setLocationImpreciseByDefault(enabled) }
            }
        )
    }

    private var chatRetentionValue: String {
        chatAutoDeletionPeriod.label
    }

    private func staticRetentionRow(title: String, value: String, icon: String, identifier: String) -> some View {
        privacyRow(title: value, subtitle: title, icon: icon, identifier: identifier)
    }

    private func privacyNote(_ text: String) -> some View {
        Text(text)
            .font(.omSmall.weight(.medium)).italic()
            .foregroundStyle(Color.grey60)
            .lineSpacing(3.5) // settings.css: 14px with line-height1.5; Lexend's line box is17.5pt.
            .padding(.horizontal, .spacing8)
            .padding(.vertical, .spacing5)
            .frame(maxWidth: .infinity, alignment: .leading)
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
        case .hidePersonalData: SettingsHidePersonalDataView(initialEntryType: {
            switch deepLinkPath?.split(separator: "/").last {
            case "add-name": return .name
            case "add-address": return .address
            case "add-birthday": return .birthday
            case "add-custom": return .custom
            default: return nil
            }
        }())
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
