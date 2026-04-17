// Full settings screen — mirrors the web app's 16-category settings panel.
// Uses List with sections for native iOS/macOS settings feel.
// Links to sub-pages for each category.

import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var authManager: AuthManager
    @EnvironmentObject var themeManager: ThemeManager
    @Environment(\.dismiss) var dismiss

    var body: some View {
        NavigationStack {
            List {
                accountSection
                aiSection
                billingSection
                securitySection
                privacySection
                appearanceSection
                notificationsSection
                developerSection
                supportSection
                aboutSection
                logoutSection
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
        }
    }

    // MARK: - Account

    private var accountSection: some View {
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

            NavigationLink {
                SettingsAccountDetailView()
            } label: {
                Label("Account", systemImage: "person.circle")
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
        } header: {
            Text("Account")
        }
    }

    // MARK: - AI

    private var aiSection: some View {
        Section("AI") {
            NavigationLink {
                SettingsAIFullView()
            } label: {
                Label("AI Model", systemImage: "brain")
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

    // MARK: - Billing

    private var billingSection: some View {
        Section("Billing") {
            Button {
                openWebPage("settings/billing/buy-credits")
            } label: {
                Label("Buy Credits", systemImage: "creditcard")
            }

            Button {
                openWebPage("settings/billing/auto-topup")
            } label: {
                Label("Auto Top-Up", systemImage: "arrow.triangle.2.circlepath")
            }

            Button {
                openWebPage("settings/billing/invoices")
            } label: {
                Label("Invoices", systemImage: "doc.text")
            }

            NavigationLink {
                SettingsGiftCardsView()
            } label: {
                Label("Gift Cards", systemImage: "gift")
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
        }
    }

    // MARK: - Privacy

    private var privacySection: some View {
        Section("Privacy") {
            NavigationLink {
                SettingsPrivacyView()
            } label: {
                Label("Hide Personal Data", systemImage: "eye.slash")
            }

            NavigationLink {
                SettingsAutoDeleteView()
            } label: {
                Label("Auto-Delete Chats", systemImage: "trash.circle")
            }
        }
    }

    // MARK: - Appearance

    private var appearanceSection: some View {
        Section("Appearance") {
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

    // MARK: - Developers

    private var developerSection: some View {
        Section("Developers") {
            NavigationLink {
                SettingsDeveloperView()
            } label: {
                Label("API Keys & Webhooks", systemImage: "terminal")
            }
        }
    }

    // MARK: - Support

    private var supportSection: some View {
        Section("Support") {
            Button {
                openWebPage("settings/support")
            } label: {
                Label("Support OpenMates", systemImage: "heart")
            }

            Button {
                openWebPage("settings/newsletter")
            } label: {
                Label("Newsletter", systemImage: "envelope")
            }

            Button {
                openWebPage("settings/report-issue")
            } label: {
                Label("Report an Issue", systemImage: "exclamationmark.bubble")
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

    // MARK: - Helpers

    private func openWebPage(_ path: String) {
        Task {
            let url = await APIClient.shared.webAppURL.appendingPathComponent(path)
            #if os(iOS)
            await UIApplication.shared.open(url)
            #elseif os(macOS)
            NSWorkspace.shared.open(url)
            #endif
        }
    }
}
