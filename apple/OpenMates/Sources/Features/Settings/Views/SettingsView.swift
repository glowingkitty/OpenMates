// Full settings screen — mirrors the web app's settings panel from settingsRoutes.ts.
// Uses List with sections for native iOS/macOS settings feel.
// ALL navigation targets are native SwiftUI views — no web redirects.
// ALL strings go through AppStrings (i18n) — no hardcoded English.

import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var authManager: AuthManager
    @EnvironmentObject var themeManager: ThemeManager
    @Environment(\.dismiss) var dismiss
    @State private var showIncognitoInfo = false

    private var isAuthenticated: Bool { authManager.currentUser != nil }
    private var isAdmin: Bool { authManager.currentUser?.isAdmin == true }

    var body: some View {
        NavigationStack {
            List {
                if !isAuthenticated {
                    pricingSection
                }
                if isAuthenticated {
                    profileSection
                }
                aiSection
                privacySection
                matesSection
                if isAuthenticated {
                    billingSection
                    notificationsSection
                    sharedSection
                }
                interfaceSection
                if isAuthenticated {
                    accountSection
                    securitySection
                    developerSection
                }
                newsletterSection
                supportSection
                reportIssueSection
                if isAdmin {
                    serverSection
                    logsSection
                }
                aboutSection
                if isAuthenticated {
                    logoutSection
                }
            }
            .navigationTitle(AppStrings.settings)
            #if os(iOS)
            .navigationBarTitleDisplayMode(.large)
            #endif
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(AppStrings.done) { dismiss() }
                }
            }
            .sheet(isPresented: $showIncognitoInfo) {
                NavigationStack {
                    SettingsIncognitoInfoView(
                        onActivate: {
                            showIncognitoInfo = false
                            NotificationCenter.default.post(name: .incognitoActivated, object: nil)
                        },
                        onCancel: { showIncognitoInfo = false }
                    )
                    .toolbar {
                        ToolbarItem(placement: .cancellationAction) {
                            Button(AppStrings.cancel) { showIncognitoInfo = false }
                        }
                    }
                }
            }
        }
    }

    // MARK: - Profile + Quick Settings

    private var profileSection: some View {
        Section {
            if let user = authManager.currentUser {
                HStack(spacing: .spacing4) {
                    Circle()
                        .fill(LinearGradient.primary)
                        .frame(width: 48, height: 48)
                        .overlay {
                            Text(String(user.username.prefix(1)).uppercased())
                                .font(.omH4).fontWeight(.bold).foregroundStyle(.white)
                        }
                    VStack(alignment: .leading, spacing: .spacing1) {
                        Text(user.username)
                            .font(.omP).fontWeight(.medium)
                        if let credits = user.credits {
                            Text(AppStrings.creditsAmount(String(format: "%.2f", credits)))
                                .font(.omXs).foregroundStyle(Color.fontSecondary)
                        }
                    }
                }
            }

            Button {
                showIncognitoInfo = true
            } label: {
                Label(AppStrings.settingsIncognito, systemImage: "eye.slash")
            }
        }
    }

    // MARK: - AI (model selection, providers, memories)

    private var aiSection: some View {
        Section(AppStrings.settingsAI) {
            NavigationLink {
                SettingsAIFullView()
            } label: {
                Label(AppStrings.aiModelProviders, systemImage: "brain")
            }

            NavigationLink {
                SettingsMemoriesFullView()
            } label: {
                Label(AppStrings.settingsMemories, systemImage: "brain.head.profile")
            }

            NavigationLink {
                SettingsAppsFullView()
            } label: {
                Label(AppStrings.settingsApps, systemImage: "square.grid.2x2")
            }
        }
    }

    // MARK: - Privacy

    private var privacySection: some View {
        Section(AppStrings.settingsPrivacy) {
            NavigationLink {
                SettingsHidePersonalDataView()
            } label: {
                Label(AppStrings.hidePersonalData, systemImage: "eye.slash")
            }

            NavigationLink {
                SettingsAutoDeleteView()
            } label: {
                Label(AppStrings.autoDeleteChats, systemImage: "trash.circle")
            }

            NavigationLink {
                SettingsShareDebugLogsView()
            } label: {
                Label(AppStrings.shareDebugLogs, systemImage: "ladybug")
            }
        }
    }

    // MARK: - Mates

    private var matesSection: some View {
        Section(AppStrings.settingsMates) {
            NavigationLink {
                SettingsMatesView()
            } label: {
                Label(AppStrings.settingsMates, systemImage: "person.2")
            }
        }
    }

    // MARK: - Billing

    private var billingSection: some View {
        Section(AppStrings.settingsBilling) {
            NavigationLink {
                SettingsBillingView()
            } label: {
                Label(AppStrings.billingCredits, systemImage: "creditcard")
            }
        }
    }

    // MARK: - Notifications

    private var notificationsSection: some View {
        Section(AppStrings.settingsNotifications) {
            NavigationLink {
                SettingsNotificationsView()
            } label: {
                Label(AppStrings.chatMessages, systemImage: "bell")
            }

            NavigationLink {
                SettingsBackupRemindersView()
            } label: {
                Label(AppStrings.backupReminders, systemImage: "clock.arrow.circlepath")
            }
        }
    }

    // MARK: - Shared

    private var sharedSection: some View {
        Section(AppStrings.settingsShared) {
            NavigationLink {
                SettingsSharedView()
            } label: {
                Label(AppStrings.settingsShared, systemImage: "person.2.wave.2")
            }
        }
    }

    // MARK: - Interface

    private var interfaceSection: some View {
        Section(AppStrings.settingsInterface) {
            Picker(selection: $themeManager.themeMode) {
                Text(AppStrings.systemTheme).tag(ThemeManager.ThemeMode.auto)
                Text(AppStrings.lightTheme).tag(ThemeManager.ThemeMode.light)
                Text(AppStrings.darkTheme).tag(ThemeManager.ThemeMode.dark)
            } label: {
                Label(AppStrings.theme, systemImage: "circle.lefthalf.filled")
            }

            NavigationLink {
                SettingsLanguageView()
            } label: {
                Label(AppStrings.language, systemImage: "globe")
            }
        }
    }

    // MARK: - Account

    private var accountSection: some View {
        Section(AppStrings.settingsAccount) {
            NavigationLink {
                SettingsAccountDetailView()
            } label: {
                Label(AppStrings.username, systemImage: "person.circle")
            }

            NavigationLink {
                SettingsEmailView()
            } label: {
                Label(AppStrings.email, systemImage: "envelope")
            }

            NavigationLink {
                SettingsProfilePictureView()
            } label: {
                Label(AppStrings.profilePicture, systemImage: "photo.circle")
            }

            NavigationLink {
                SettingsUsageView()
            } label: {
                Label(AppStrings.usage, systemImage: "chart.bar")
            }

            NavigationLink {
                SettingsStorageFullView()
            } label: {
                Label(AppStrings.storage, systemImage: "internaldrive")
            }

            NavigationLink {
                SettingsAccountChatsView()
            } label: {
                Label(AppStrings.chats, systemImage: "bubble.left.and.bubble.right")
            }

            NavigationLink {
                ChatImportView()
            } label: {
                Label(AppStrings.importChats, systemImage: "square.and.arrow.down")
            }

            NavigationLink {
                SettingsExportAccountView()
            } label: {
                Label(AppStrings.exportData, systemImage: "square.and.arrow.up")
            }

            NavigationLink {
                SettingsDeleteAccountView()
            } label: {
                Label(AppStrings.deleteAccount, systemImage: "trash")
                    .foregroundStyle(Color.error)
            }
        }
    }

    // MARK: - Security

    private var securitySection: some View {
        Section(AppStrings.settingsSecurity) {
            NavigationLink {
                SettingsPasskeysView()
            } label: {
                Label(AppStrings.passkeys, systemImage: "person.badge.key")
            }

            NavigationLink {
                SettingsPasswordView()
            } label: {
                Label(AppStrings.password, systemImage: "lock")
            }

            NavigationLink {
                Settings2FAView()
            } label: {
                Label(AppStrings.twoFactorAuth, systemImage: "lock.shield")
            }

            NavigationLink {
                SettingsRecoveryKeyView()
            } label: {
                Label(AppStrings.recoveryKey, systemImage: "key")
            }

            NavigationLink {
                SettingsSessionsView()
            } label: {
                Label(AppStrings.activeSessions, systemImage: "desktopcomputer")
            }

            NavigationLink {
                SettingsPairInitiateView()
            } label: {
                Label(AppStrings.pairNewDevice, systemImage: "qrcode")
            }
        }
    }

    // MARK: - Developers

    private var developerSection: some View {
        Section(AppStrings.settingsDevelopers) {
            NavigationLink {
                SettingsAPIKeysView()
            } label: {
                Label(AppStrings.apiKeys, systemImage: "key")
            }

            NavigationLink {
                SettingsDevicesView()
            } label: {
                Label(AppStrings.devices, systemImage: "laptopcomputer.and.iphone")
            }

            NavigationLink {
                SettingsWebhooksView()
            } label: {
                Label(AppStrings.webhooks, systemImage: "arrow.triangle.branch")
            }
        }
    }

    // MARK: - Newsletter

    private var newsletterSection: some View {
        Section(AppStrings.settingsNewsletter) {
            NavigationLink {
                NewsletterSettingsView()
            } label: {
                Label(AppStrings.settingsNewsletter, systemImage: "envelope.open")
            }
        }
    }

    // MARK: - Support

    private var supportSection: some View {
        Section(AppStrings.settingsSupport) {
            NavigationLink {
                SettingsSupportView()
            } label: {
                Label(AppStrings.settingsSupport, systemImage: "heart")
            }
        }
    }

    // MARK: - Report Issue

    private var reportIssueSection: some View {
        Section {
            NavigationLink {
                ReportIssueView()
            } label: {
                Label(AppStrings.settingsReportIssue, systemImage: "exclamationmark.bubble")
            }
        }
    }

    // MARK: - Pricing (non-authenticated)

    private var pricingSection: some View {
        Section(AppStrings.settingsPricing) {
            NavigationLink {
                SettingsPricingView()
            } label: {
                Label(AppStrings.settingsPricing, systemImage: "tag")
            }
        }
    }

    // MARK: - Server (admin only)

    private var serverSection: some View {
        Section(AppStrings.serverAdmin) {
            NavigationLink {
                SettingsServerView()
            } label: {
                Label(AppStrings.serverAdmin, systemImage: "server.rack")
            }
        }
    }

    // MARK: - Logs (admin only)

    private var logsSection: some View {
        Section {
            NavigationLink {
                SettingsLogsView()
            } label: {
                Label(AppStrings.logs, systemImage: "doc.text.magnifyingglass")
            }
        }
    }

    // MARK: - About

    private var aboutSection: some View {
        Section(AppStrings.about) {
            HStack {
                Label(AppStrings.version, systemImage: "info.circle")
                Spacer()
                Text(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0")
                    .foregroundStyle(Color.fontSecondary)
            }

            NavigationLink {
                LegalChatView(documentType: .privacy)
            } label: {
                Label(AppStrings.privacyPolicy, systemImage: "hand.raised")
            }

            NavigationLink {
                LegalChatView(documentType: .terms)
            } label: {
                Label(AppStrings.termsOfService, systemImage: "doc.text")
            }

            NavigationLink {
                LegalChatView(documentType: .imprint)
            } label: {
                Label(AppStrings.imprint, systemImage: "building.2")
            }

            Link(destination: URL(string: "https://github.com/OpenMates/OpenMates")!) {
                Label(AppStrings.openSource, systemImage: "chevron.left.forwardslash.chevron.right")
            }
        }
    }

    // MARK: - Logout

    private var logoutSection: some View {
        Section {
            Button(role: .destructive) {
                Task { await authManager.logout() }
            } label: {
                Label(AppStrings.logOut, systemImage: "rectangle.portrait.and.arrow.right")
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
        Form {
            Section {
                Text(AppStrings.deleteAccountWarning)
                    .font(.omSmall).foregroundStyle(Color.error)
            }

            Section(AppStrings.confirm) {
                SecureField(AppStrings.enterPassword, text: $password)
                    .textContentType(.password)

                TextField(AppStrings.deleteAccountConfirmText, text: $confirmText)
                    .autocorrectionDisabled()
                    #if os(iOS)
                    .textInputAutocapitalization(.never)
                    #endif
            }

            Section {
                Button(role: .destructive) {
                    deleteAccount()
                } label: {
                    HStack {
                        Spacer()
                        if isDeleting {
                            ProgressView()
                        } else {
                            Text(AppStrings.permanentlyDeleteAccount)
                                .fontWeight(.medium)
                        }
                        Spacer()
                    }
                }
                .disabled(!canDelete || isDeleting)
            }

            if let error {
                Section {
                    Text(error).font(.omSmall).foregroundStyle(Color.error)
                }
            }
        }
        .navigationTitle(AppStrings.deleteAccount)
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
            }
            isDeleting = false
        }
    }
}

// MARK: - Notifications

extension Notification.Name {
    static let incognitoActivated = Notification.Name("openmates.incognitoActivated")
}
