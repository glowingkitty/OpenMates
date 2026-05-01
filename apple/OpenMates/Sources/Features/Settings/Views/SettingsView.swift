// Full settings screen — mirrors the web app's settings panel from settingsRoutes.ts.
// Product UI must use OpenMates primitives instead of default platform List/Form chrome.
// ALL navigation targets are native SwiftUI views — no web redirects.
// ALL strings go through AppStrings (i18n) — no hardcoded English.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/CurrentSettingsPage.svelte
//          frontend/packages/ui/src/components/settings/SettingsMainHeader.svelte
// CSS:     frontend/packages/ui/src/styles/settings.css
//          frontend/packages/ui/src/components/settings/elements/SettingsItem.svelte
//          frontend/packages/ui/src/components/settings/elements/SettingsSectionHeading.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var authManager: AuthManager
    @EnvironmentObject var themeManager: ThemeManager
    @Environment(\.dismiss) var dismiss
    @Environment(\.openURL) private var openURL
    @State private var showIncognitoInfo = false
    @State private var destination: SettingsDestination?

    private var isAuthenticated: Bool { authManager.currentUser != nil }
    private var isAdmin: Bool { authManager.currentUser?.isAdmin == true }

    var body: some View {
        ZStack {
            if let destination {
                settingsDestinationView(destination)
            } else {
                settingsHome
            }

            if showIncognitoInfo {
                incognitoOverlay
            }
        }
    }

    private var settingsHome: some View {
        OMSettingsPage(
            title: AppStrings.settings,
            trailing: AnyView(
                OMIconButton(icon: "close", label: AppStrings.done) {
                    dismiss()
                }
            )
        ) {
            if !isAuthenticated {
                OMSettingsSection(AppStrings.settingsPricing) {
                    row(.pricing, AppStrings.settingsPricing, icon: "coins", gradient: .appFinance)
                }
            }

            if isAuthenticated {
                profileCard
            }

            OMSettingsSection(AppStrings.settingsAI) {
                row(.ai, AppStrings.aiModelProviders, icon: "ai", gradient: .appAi)
                row(.memories, AppStrings.settingsMemories, icon: "insight", gradient: .appMessages)
                row(.apps, AppStrings.settingsApps, icon: "app", gradient: .primary)
            }

            OMSettingsSection(AppStrings.settingsPrivacy) {
                row(.hidePersonalData, AppStrings.hidePersonalData, icon: "anonym", gradient: .appSecrets)
                row(.autoDelete, AppStrings.autoDeleteChats, icon: "delete", gradient: .appNews)
                row(.debugLogs, AppStrings.shareDebugLogs, icon: "bug", gradient: .appCode)
            }

            OMSettingsSection(AppStrings.settingsMates) {
                row(.mates, AppStrings.settingsMates, icon: "mate", gradient: .appMessages)
            }

            if isAuthenticated {
                OMSettingsSection(AppStrings.settingsBilling) {
                    row(.billing, AppStrings.billingCredits, icon: "coins", gradient: .appFinance)
                }

                OMSettingsSection(AppStrings.settingsNotifications) {
                    row(.notifications, AppStrings.chatMessages, icon: "chat", gradient: .appMessages)
                    row(.backupReminders, AppStrings.backupReminders, icon: "reminder", gradient: .appReminder)
                }

                OMSettingsSection(AppStrings.settingsShared) {
                    row(.shared, AppStrings.settingsShared, icon: "share", gradient: .appSocialmedia)
                }
            }

            OMSettingsSection(AppStrings.settingsInterface) {
                VStack(alignment: .leading, spacing: .spacing4) {
                    HStack(spacing: .spacing4) {
                        Icon("darkmode", size: 14)
                            .foregroundStyle(.white)
                            .frame(width: 28, height: 28)
                            .background(LinearGradient.appDesign)
                            .clipShape(RoundedRectangle(cornerRadius: .radius3))
                        Text(AppStrings.theme)
                            .font(.omP)
                            .fontWeight(.medium)
                            .foregroundStyle(Color.fontPrimary)
                    }
                    OMSegmentedControl(
                        items: [
                            .init(id: ThemeManager.ThemeMode.auto, title: AppStrings.systemTheme),
                            .init(id: ThemeManager.ThemeMode.light, title: AppStrings.lightTheme),
                            .init(id: ThemeManager.ThemeMode.dark, title: AppStrings.darkTheme)
                        ],
                        selection: Binding(
                            get: { themeManager.themeMode },
                            set: { themeManager.setTheme($0) }
                        )
                    )
                }
                .padding(.horizontal, .spacing6)
                .padding(.vertical, .spacing5)
                row(.language, AppStrings.language, icon: "language", gradient: .appLanguage)
            }

            if isAuthenticated {
                OMSettingsSection(AppStrings.settingsAccount) {
                    row(.account, AppStrings.username, icon: "user", gradient: .primary)
                    row(.email, AppStrings.email, icon: "mail", gradient: .appMail)
                    row(.profilePicture, AppStrings.profilePicture, icon: "image", gradient: .appPhotos)
                    row(.usage, AppStrings.usage, icon: "usage", gradient: .appFinance)
                    row(.storage, AppStrings.storage, icon: "cloud", gradient: .appFiles)
                    row(.chats, AppStrings.chats, icon: "chat", gradient: .appMessages)
                    row(.importChats, AppStrings.importChats, icon: "download", gradient: .appDocs)
                    row(.exportData, AppStrings.exportData, icon: "upload", gradient: .appDocs)
                    row(.deleteAccount, AppStrings.deleteAccount, icon: "delete", isDestructive: true)
                }

                OMSettingsSection(AppStrings.settingsSecurity) {
                    row(.passkeys, AppStrings.passkeys, icon: "passkey", gradient: .appSecrets)
                    row(.password, AppStrings.password, icon: "lock", gradient: .appSecrets)
                    row(.twoFactor, AppStrings.twoFactorAuth, icon: "tfas", gradient: .appSecrets)
                    row(.recoveryKey, AppStrings.recoveryKey, icon: "secret", gradient: .appSecrets)
                    row(.sessions, AppStrings.activeSessions, icon: "desktop", gradient: .appCode)
                    row(.pairDevice, AppStrings.pairNewDevice, icon: "dummyqr", gradient: .primary)
                }

                OMSettingsSection(AppStrings.settingsDevelopers) {
                    row(.apiKeys, AppStrings.apiKeys, icon: "secret", gradient: .appCode)
                    row(.devices, AppStrings.devices, icon: "laptop", gradient: .appCode)
                    row(.webhooks, AppStrings.webhooks, icon: "coding", gradient: .appCode)
                }
            }

            OMSettingsSection(AppStrings.settingsNewsletter) {
                row(.newsletter, AppStrings.settingsNewsletter, icon: "mail", gradient: .appPublishing)
            }

            OMSettingsSection(AppStrings.settingsSupport) {
                row(.support, AppStrings.settingsSupport, icon: "heart", gradient: .appHealth)
                row(.reportIssue, AppStrings.settingsReportIssue, icon: "bug", gradient: .appNews)
            }

            if isAdmin {
                OMSettingsSection(AppStrings.serverAdmin) {
                    row(.server, AppStrings.serverAdmin, icon: "server", gradient: .appHosting)
                    row(.logs, AppStrings.logs, icon: "log", gradient: .appCode)
                }
            }

            OMSettingsSection(AppStrings.about) {
                OMSettingsStaticRow(
                    title: AppStrings.version,
                    value: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0",
                    icon: "info"
                )
                row(.privacyPolicy, AppStrings.privacyPolicy, icon: "lock", gradient: .appLegal)
                row(.terms, AppStrings.termsOfService, icon: "legal", gradient: .appLegal)
                row(.imprint, AppStrings.imprint, icon: "eu", gradient: .appLegal)
                OMSettingsRow(
                    title: AppStrings.openSource,
                    icon: "opensource",
                    iconGradient: .appCode,
                    showsChevron: true
                ) {
                    if let url = URL(string: "https://github.com/OpenMates/OpenMates") {
                        openURL(url)
                    }
                }
            }

            if isAuthenticated {
                OMSettingsSection {
                    OMSettingsRow(
                        title: AppStrings.logOut,
                        icon: "logout",
                        isDestructive: true,
                        showsChevron: false
                    ) {
                        Task { await authManager.logout() }
                    }
                }
            }
        }
    }

    private var profileCard: some View {
        OMSettingsSection {
            if let user = authManager.currentUser {
                HStack(spacing: .spacing5) {
                    Circle()
                        .fill(LinearGradient.primary)
                        .frame(width: 52, height: 52)
                        .overlay {
                            Text(String(user.username.prefix(1)).uppercased())
                                .font(.omH4)
                                .fontWeight(.bold)
                                .foregroundStyle(.white)
                        }

                    VStack(alignment: .leading, spacing: .spacing1) {
                        Text(user.username)
                            .font(.omP)
                            .fontWeight(.semibold)
                            .foregroundStyle(Color.fontPrimary)
                        if let credits = user.credits {
                            Text(AppStrings.creditsAmount(String(format: "%.2f", credits)))
                                .font(.omXs)
                                .foregroundStyle(Color.fontSecondary)
                        }
                    }

                    Spacer()
                }
                .padding(.horizontal, .spacing6)
                .padding(.vertical, .spacing6)
            }

            OMSettingsRow(
                title: AppStrings.settingsIncognito,
                icon: "eye-off",
                showsChevron: false
            ) {
                showIncognitoInfo = true
            }
        }
    }

    private func row(
        _ destination: SettingsDestination,
        _ title: String,
        icon: String,
        gradient: LinearGradient? = nil,
        isDestructive: Bool = false
    ) -> some View {
        OMSettingsRow(title: title, icon: icon, iconGradient: gradient, isDestructive: isDestructive) {
            self.destination = destination
        }
    }

    private var incognitoOverlay: some View {
        ZStack {
            Color.black.opacity(0.35)
                .ignoresSafeArea()
                .onTapGesture {
                    showIncognitoInfo = false
                }

            VStack(spacing: 0) {
                HStack {
                    Text(AppStrings.settingsIncognito)
                        .font(.omH3)
                        .fontWeight(.semibold)
                        .foregroundStyle(Color.fontPrimary)
                    Spacer()
                    OMIconButton(icon: "close", label: AppStrings.cancel, size: 32) {
                        showIncognitoInfo = false
                    }
                }
                .padding(.spacing6)

                SettingsIncognitoInfoView(
                    onActivate: {
                        showIncognitoInfo = false
                        NotificationCenter.default.post(name: .incognitoActivated, object: nil)
                    },
                    onCancel: { showIncognitoInfo = false }
                )
            }
            .frame(maxWidth: 620, maxHeight: 720)
            .background(Color.grey0)
            .clipShape(RoundedRectangle(cornerRadius: .radius8))
            .overlay(
                RoundedRectangle(cornerRadius: .radius8)
                    .stroke(Color.grey20, lineWidth: 1)
            )
            .padding(.spacing8)
        }
    }

    private func settingsShell<Content: View>(
        title: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(spacing: 0) {
            HStack(spacing: .spacing4) {
                OMIconButton(icon: "back", label: AppStrings.back, size: 36) {
                    destination = nil
                }
                Text(title)
                    .font(.omH3)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.fontPrimary)
                Spacer()
                OMIconButton(icon: "close", label: AppStrings.done, size: 36) {
                    dismiss()
                }
            }
            .padding(.horizontal, .spacing8)
            .padding(.vertical, .spacing6)
            .background(Color.grey0)

            content()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .background(Color.grey0)
    }

    @ViewBuilder
    private func settingsDestinationView(_ destination: SettingsDestination) -> some View {
        settingsShell(title: destination.title) {
            destination.view
        }
    }

    @MainActor
    private enum SettingsDestination: Hashable {
        case pricing, ai, memories, apps, hidePersonalData, autoDelete, debugLogs, mates
        case billing, notifications, backupReminders, shared, language
        case account, email, profilePicture, usage, storage, chats, importChats, exportData, deleteAccount
        case passkeys, password, twoFactor, recoveryKey, sessions, pairDevice
        case apiKeys, devices, webhooks, newsletter, support, reportIssue, server, logs
        case privacyPolicy, terms, imprint

        var title: String {
            switch self {
            case .pricing: return AppStrings.settingsPricing
            case .ai: return AppStrings.aiModelProviders
            case .memories: return AppStrings.settingsMemories
            case .apps: return AppStrings.settingsApps
            case .hidePersonalData: return AppStrings.hidePersonalData
            case .autoDelete: return AppStrings.autoDeleteChats
            case .debugLogs: return AppStrings.shareDebugLogs
            case .mates: return AppStrings.settingsMates
            case .billing: return AppStrings.settingsBilling
            case .notifications: return AppStrings.settingsNotifications
            case .backupReminders: return AppStrings.backupReminders
            case .shared: return AppStrings.settingsShared
            case .language: return AppStrings.language
            case .account: return AppStrings.username
            case .email: return AppStrings.email
            case .profilePicture: return AppStrings.profilePicture
            case .usage: return AppStrings.usage
            case .storage: return AppStrings.storage
            case .chats: return AppStrings.chats
            case .importChats: return AppStrings.importChats
            case .exportData: return AppStrings.exportData
            case .deleteAccount: return AppStrings.deleteAccount
            case .passkeys: return AppStrings.passkeys
            case .password: return AppStrings.password
            case .twoFactor: return AppStrings.twoFactorAuth
            case .recoveryKey: return AppStrings.recoveryKey
            case .sessions: return AppStrings.activeSessions
            case .pairDevice: return AppStrings.pairNewDevice
            case .apiKeys: return AppStrings.apiKeys
            case .devices: return AppStrings.devices
            case .webhooks: return AppStrings.webhooks
            case .newsletter: return AppStrings.settingsNewsletter
            case .support: return AppStrings.settingsSupport
            case .reportIssue: return AppStrings.settingsReportIssue
            case .server: return AppStrings.serverAdmin
            case .logs: return AppStrings.logs
            case .privacyPolicy: return AppStrings.privacyPolicy
            case .terms: return AppStrings.termsOfService
            case .imprint: return AppStrings.imprint
            }
        }

        @ViewBuilder
        var view: some View {
            switch self {
            case .pricing: SettingsPricingView()
            case .ai: SettingsAIFullView()
            case .memories: SettingsMemoriesFullView()
            case .apps: SettingsAppsFullView()
            case .hidePersonalData: SettingsHidePersonalDataView()
            case .autoDelete: SettingsAutoDeleteView()
            case .debugLogs: SettingsShareDebugLogsView()
            case .mates: SettingsMatesView()
            case .billing: SettingsBillingView()
            case .notifications: SettingsNotificationsView()
            case .backupReminders: SettingsBackupRemindersView()
            case .shared: SettingsSharedView()
            case .language: SettingsLanguageView()
            case .account: SettingsAccountDetailView()
            case .email: SettingsEmailView()
            case .profilePicture: SettingsProfilePictureView()
            case .usage: SettingsUsageView()
            case .storage: SettingsStorageFullView()
            case .chats: SettingsAccountChatsView()
            case .importChats: ChatImportView()
            case .exportData: SettingsExportAccountView()
            case .deleteAccount: SettingsDeleteAccountView()
            case .passkeys: SettingsPasskeysView()
            case .password: SettingsPasswordView()
            case .twoFactor: Settings2FAView()
            case .recoveryKey: SettingsRecoveryKeyView()
            case .sessions: SettingsSessionsView()
            case .pairDevice: SettingsPairInitiateView()
            case .apiKeys: SettingsAPIKeysView()
            case .devices: SettingsDevicesView()
            case .webhooks: SettingsWebhooksView()
            case .newsletter: NewsletterSettingsView()
            case .support: SettingsSupportView()
            case .reportIssue: ReportIssueView()
            case .server: SettingsServerView()
            case .logs: SettingsLogsView()
            case .privacyPolicy: LegalChatView(documentType: .privacy)
            case .terms: LegalChatView(documentType: .terms)
            case .imprint: LegalChatView(documentType: .imprint)
            }
        }
    }
}

// MARK: - Delete Account

struct SettingsDeleteAccountView: View {
    @EnvironmentObject var authManager: AuthManager
    @State private var password = ""
    @State private var confirmText = ""
    @State private var isDeleting = false
    @State private var error: String?

    private var canDelete: Bool {
        !password.isEmpty && confirmText.lowercased() == "delete my account"
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: .spacing8) {
                Text(AppStrings.deleteAccountWarning)
                    .font(.omSmall)
                    .foregroundStyle(Color.error)
                    .padding(.spacing6)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.error.opacity(0.08))
                    .clipShape(RoundedRectangle(cornerRadius: .radius7))

                OMSettingsSection(AppStrings.confirm) {
                    VStack(alignment: .leading, spacing: .spacing5) {
                        SecureField(AppStrings.enterPassword, text: $password)
                            .textContentType(.password)
                            .textFieldStyle(OMTextFieldStyle())
                            .accessibleInput(AppStrings.enterPassword, hint: LocalizationManager.shared.text("auth.enter_account_password"))

                        TextField(AppStrings.deleteAccountConfirmText, text: $confirmText)
                            .textFieldStyle(OMTextFieldStyle())
                            .autocorrectionDisabled()
                            #if os(iOS)
                            .textInputAutocapitalization(.never)
                            #endif
                            .accessibleInput(AppStrings.deleteAccountConfirmText, hint: LocalizationManager.shared.text("settings.type_delete_confirm_hint"))
                    }
                    .padding(.spacing6)
                }

                Button(role: .destructive) {
                    deleteAccount()
                } label: {
                    HStack {
                        Spacer()
                        if isDeleting {
                            Text(AppStrings.loading)
                                .font(.omP)
                                .fontWeight(.medium)
                        } else {
                            Text(AppStrings.permanentlyDeleteAccount)
                                .font(.omP)
                                .fontWeight(.medium)
                        }
                        Spacer()
                    }
                    .foregroundStyle(Color.fontButton)
                    .padding(.vertical, .spacing5)
                    .background(canDelete && !isDeleting ? Color.error : Color.buttonSecondary)
                    .clipShape(RoundedRectangle(cornerRadius: .radius7))
                }
                .buttonStyle(.plain)
                .disabled(!canDelete || isDeleting)
                .accessibleButton(AppStrings.permanentlyDeleteAccount, hint: LocalizationManager.shared.text("settings.delete_account_hint"))

                if let error {
                    Text(error)
                        .font(.omSmall)
                        .foregroundStyle(Color.error)
                        .padding(.spacing6)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color.error.opacity(0.08))
                        .clipShape(RoundedRectangle(cornerRadius: .radius7))
                }
            }
            .padding(.spacing8)
        }
        .background(Color.grey0)
    }

    private func deleteAccount() {
        isDeleting = true
        error = nil
        Task {
            do {
                let _: Data = try await APIClient.shared.request(
                    .post, path: "/v1/settings/account/delete",
                    body: ["password": password]
                )
                await authManager.logout()
            } catch {
                self.error = error.localizedDescription
                AccessibilityAnnouncement.announce(error.localizedDescription)
            }
            isDeleting = false
        }
    }
}

// MARK: - Notifications

extension Notification.Name {
    static let incognitoActivated = Notification.Name("openmates.incognitoActivated")
}
