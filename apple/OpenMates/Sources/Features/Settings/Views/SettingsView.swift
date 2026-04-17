// Full settings screen — mirrors the web app's settings panel from settingsRoutes.ts.
// Uses List with sections for native iOS/macOS settings feel.
// All categories link to native sub-pages; payment processing redirects to web.

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
            .navigationTitle("Settings")
            #if os(iOS)
            .navigationBarTitleDisplayMode(.large)
            #endif
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Done") { dismiss() }
                }
            }
            .sheet(isPresented: $showIncognitoInfo) {
                NavigationStack {
                    SettingsIncognitoInfoView(
                        onActivate: {
                            showIncognitoInfo = false
                            // Post notification to activate incognito mode
                            NotificationCenter.default.post(name: .incognitoActivated, object: nil)
                        },
                        onCancel: { showIncognitoInfo = false }
                    )
                    .toolbar {
                        ToolbarItem(placement: .cancellationAction) {
                            Button("Cancel") { showIncognitoInfo = false }
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
                            Text("\(String(format: "%.2f", credits)) credits")
                                .font(.omXs).foregroundStyle(Color.fontSecondary)
                        }
                    }
                }
            }

            // Incognito quick toggle
            Button {
                showIncognitoInfo = true
            } label: {
                Label("Incognito Mode", systemImage: "eye.slash")
            }
        }
    }

    // MARK: - AI (model selection, providers, memories)

    private var aiSection: some View {
        Section("AI") {
            NavigationLink {
                SettingsAIFullView()
            } label: {
                Label("AI Model & Providers", systemImage: "brain")
            }

            NavigationLink {
                SettingsMemoriesFullView()
            } label: {
                Label("Memories", systemImage: "brain.head.profile")
            }

            NavigationLink {
                SettingsAppsFullView()
            } label: {
                Label("Apps", systemImage: "square.grid.2x2")
            }
        }
    }

    // MARK: - Privacy

    private var privacySection: some View {
        Section("Privacy") {
            NavigationLink {
                SettingsHidePersonalDataView()
            } label: {
                Label("Hide Personal Data", systemImage: "eye.slash")
            }

            NavigationLink {
                SettingsAutoDeleteView()
            } label: {
                Label("Auto-Delete Chats", systemImage: "trash.circle")
            }

            NavigationLink {
                SettingsShareDebugLogsView()
            } label: {
                Label("Share Debug Logs", systemImage: "ladybug")
            }
        }
    }

    // MARK: - Mates

    private var matesSection: some View {
        Section("Mates") {
            NavigationLink {
                SettingsMatesView()
            } label: {
                Label("AI Mates", systemImage: "person.2")
            }
        }
    }

    // MARK: - Billing

    private var billingSection: some View {
        Section("Billing") {
            NavigationLink {
                SettingsBillingView()
            } label: {
                Label("Billing & Credits", systemImage: "creditcard")
            }
        }
    }

    // MARK: - Notifications

    private var notificationsSection: some View {
        Section("Notifications") {
            NavigationLink {
                SettingsNotificationsView()
            } label: {
                Label("Chat Notifications", systemImage: "bell")
            }

            NavigationLink {
                SettingsBackupRemindersView()
            } label: {
                Label("Backup Reminders", systemImage: "clock.arrow.circlepath")
            }
        }
    }

    // MARK: - Shared

    private var sharedSection: some View {
        Section("Shared") {
            NavigationLink {
                SettingsSharedView()
            } label: {
                Label("Shared Chats", systemImage: "person.2.wave.2")
            }
        }
    }

    // MARK: - Interface

    private var interfaceSection: some View {
        Section("Interface") {
            Picker(selection: $themeManager.themeMode) {
                Text("System").tag(ThemeManager.ThemeMode.auto)
                Text("Light").tag(ThemeManager.ThemeMode.light)
                Text("Dark").tag(ThemeManager.ThemeMode.dark)
            } label: {
                Label("Theme", systemImage: "circle.lefthalf.filled")
            }

            NavigationLink {
                SettingsLanguageView()
            } label: {
                Label("Language", systemImage: "globe")
            }
        }
    }

    // MARK: - Account

    private var accountSection: some View {
        Section("Account") {
            NavigationLink {
                SettingsAccountDetailView()
            } label: {
                Label("Username & Timezone", systemImage: "person.circle")
            }

            NavigationLink {
                SettingsEmailView()
            } label: {
                Label("Email", systemImage: "envelope")
            }

            NavigationLink {
                SettingsProfilePictureView()
            } label: {
                Label("Profile Picture", systemImage: "photo.circle")
            }

            NavigationLink {
                SettingsUsageView()
            } label: {
                Label("Usage", systemImage: "chart.bar")
            }

            NavigationLink {
                SettingsStorageFullView()
            } label: {
                Label("Storage", systemImage: "internaldrive")
            }

            NavigationLink {
                SettingsAccountChatsView()
            } label: {
                Label("Chats", systemImage: "bubble.left.and.bubble.right")
            }

            NavigationLink {
                ChatImportView()
            } label: {
                Label("Import Chats", systemImage: "square.and.arrow.down")
            }

            NavigationLink {
                SettingsExportAccountView()
            } label: {
                Label("Export Data", systemImage: "square.and.arrow.up")
            }

            NavigationLink {
                SettingsDeleteAccountView()
            } label: {
                Label("Delete Account", systemImage: "trash")
                    .foregroundStyle(Color.error)
            }
        }
    }

    // MARK: - Security

    private var securitySection: some View {
        Section("Security") {
            NavigationLink {
                SettingsPasskeysView()
            } label: {
                Label("Passkeys", systemImage: "person.badge.key")
            }

            NavigationLink {
                SettingsPasswordView()
            } label: {
                Label("Password", systemImage: "lock")
            }

            NavigationLink {
                Settings2FAView()
            } label: {
                Label("Two-Factor Authentication", systemImage: "lock.shield")
            }

            NavigationLink {
                SettingsRecoveryKeyView()
            } label: {
                Label("Recovery Key", systemImage: "key")
            }

            NavigationLink {
                SettingsSessionsView()
            } label: {
                Label("Active Sessions", systemImage: "desktopcomputer")
            }

            NavigationLink {
                SettingsPairInitiateView()
            } label: {
                Label("Pair New Device", systemImage: "qrcode")
            }
        }
    }

    // MARK: - Developers

    private var developerSection: some View {
        Section("Developers") {
            NavigationLink {
                SettingsAPIKeysView()
            } label: {
                Label("API Keys", systemImage: "key")
            }

            NavigationLink {
                SettingsDevicesView()
            } label: {
                Label("Devices", systemImage: "laptopcomputer.and.iphone")
            }

            NavigationLink {
                SettingsWebhooksView()
            } label: {
                Label("Webhooks", systemImage: "arrow.triangle.branch")
            }
        }
    }

    // MARK: - Newsletter

    private var newsletterSection: some View {
        Section("Newsletter") {
            NavigationLink {
                NewsletterSettingsView()
            } label: {
                Label("Newsletter", systemImage: "envelope.open")
            }
        }
    }

    // MARK: - Support

    private var supportSection: some View {
        Section("Support") {
            NavigationLink {
                SettingsSupportView()
            } label: {
                Label("Support OpenMates", systemImage: "heart")
            }
        }
    }

    // MARK: - Report Issue

    private var reportIssueSection: some View {
        Section {
            NavigationLink {
                ReportIssueView()
            } label: {
                Label("Report an Issue", systemImage: "exclamationmark.bubble")
            }
        }
    }

    // MARK: - Pricing (non-authenticated)

    private var pricingSection: some View {
        Section("Pricing") {
            NavigationLink {
                SettingsPricingView()
            } label: {
                Label("Credit Packages", systemImage: "tag")
            }
        }
    }

    // MARK: - Server (admin only)

    private var serverSection: some View {
        Section("Server") {
            NavigationLink {
                SettingsServerView()
            } label: {
                Label("Server Admin", systemImage: "server.rack")
            }
        }
    }

    // MARK: - Logs (admin only)

    private var logsSection: some View {
        Section {
            NavigationLink {
                SettingsLogsView()
            } label: {
                Label("Logs", systemImage: "doc.text.magnifyingglass")
            }
        }
    }

    // MARK: - About

    private var aboutSection: some View {
        Section("About") {
            HStack {
                Label("Version", systemImage: "info.circle")
                Spacer()
                Text(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0")
                    .foregroundStyle(Color.fontSecondary)
            }

            NavigationLink {
                LegalChatView(documentType: .privacy)
            } label: {
                Label("Privacy Policy", systemImage: "hand.raised")
            }

            NavigationLink {
                LegalChatView(documentType: .terms)
            } label: {
                Label("Terms of Service", systemImage: "doc.text")
            }

            NavigationLink {
                LegalChatView(documentType: .imprint)
            } label: {
                Label("Imprint", systemImage: "building.2")
            }

            Link(destination: URL(string: "https://github.com/OpenMates/OpenMates")!) {
                Label("Open Source", systemImage: "chevron.left.forwardslash.chevron.right")
            }
        }
    }

    // MARK: - Logout

    private var logoutSection: some View {
        Section {
            Button(role: .destructive) {
                Task { await authManager.logout() }
            } label: {
                Label("Log Out", systemImage: "rectangle.portrait.and.arrow.right")
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
                Text("This action is permanent and cannot be undone. All your data including chats, messages, embeds, and memories will be permanently deleted.")
                    .font(.omSmall).foregroundStyle(Color.error)
            }

            Section("Confirm Identity") {
                SecureField("Enter your password", text: $password)
                    .textContentType(.password)

                TextField("Type \"delete my account\" to confirm", text: $confirmText)
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
                            Text("Permanently Delete Account")
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
        .navigationTitle("Delete Account")
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
