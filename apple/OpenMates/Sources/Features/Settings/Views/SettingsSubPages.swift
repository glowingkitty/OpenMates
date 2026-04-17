// Settings sub-page views — each page loads data from backend API endpoints.
// All API calls use the shared APIClient actor.

import SwiftUI
import AuthenticationServices

// MARK: - Account Detail

struct SettingsAccountDetailView: View {
    @EnvironmentObject var authManager: AuthManager
    @State private var username = ""
    @State private var timezone = TimeZone.current.identifier
    @State private var isSaving = false
    @State private var saveMessage: String?

    var body: some View {
        Form {
            Section("Username") {
                TextField("Username", text: $username)
                    .autocorrectionDisabled()
                    #if os(iOS)
                    .textInputAutocapitalization(.never)
                    #endif
                Button("Save Username") {
                    saveField(path: "/v1/settings/user/username", body: ["username": username])
                }
                .disabled(username.isEmpty || isSaving)
            }

            Section("Timezone") {
                Picker("Timezone", selection: $timezone) {
                    ForEach(TimeZone.knownTimeZoneIdentifiers.sorted(), id: \.self) { tz in
                        Text(tz).tag(tz)
                    }
                }
                .onChange(of: timezone) { _, newValue in
                    saveField(path: "/v1/settings/user/timezone", body: ["timezone": newValue])
                }
            }

            Section("Data") {
                Button("Export Account Data") { openWebPage("settings/account/export") }
                Button("Import Chat") { openWebPage("settings/account/import") }
            }

            Section {
                Button("Delete Account", role: .destructive) {
                    openWebPage("settings/account/delete")
                }
            }

            if let saveMessage {
                Text(saveMessage)
                    .font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
            }
        }
        .navigationTitle("Account")
        .onAppear {
            username = authManager.currentUser?.username ?? ""
            timezone = authManager.currentUser?.timezone ?? TimeZone.current.identifier
        }
    }

    private func saveField(path: String, body: [String: String]) {
        isSaving = true
        saveMessage = nil
        Task {
            do {
                let _: Data = try await APIClient.shared.request(.post, path: path, body: body)
                saveMessage = "Saved"
            } catch {
                saveMessage = error.localizedDescription
            }
            isSaving = false
        }
    }
}

// MARK: - Usage

struct SettingsUsageView: View {
    @State private var isLoading = true
    @State private var totalCreditsUsed: Double = 0
    @State private var messageCount: Int = 0

    var body: some View {
        List {
            Section("Overview") {
                HStack {
                    Text("Total Credits Used")
                    Spacer()
                    Text(String(format: "%.4f", totalCreditsUsed))
                        .foregroundStyle(Color.fontSecondary)
                }
                HStack {
                    Text("Messages")
                    Spacer()
                    Text("\(messageCount)")
                        .foregroundStyle(Color.fontSecondary)
                }
            }

            Section {
                Button("View Detailed Usage") { openWebPage("settings/usage") }
                Button("Export Usage Data") { openWebPage("settings/usage/export") }
            }
        }
        .navigationTitle("Usage")
        .task { await loadUsage() }
    }

    private func loadUsage() async {
        do {
            let data: [String: AnyCodable] = try await APIClient.shared.request(.get, path: "/v1/settings/usage")
            totalCreditsUsed = data["total_credits_used"]?.value as? Double ?? 0
            messageCount = data["message_count"]?.value as? Int ?? 0
        } catch {
            print("[Settings] Usage load error: \(error)")
        }
        isLoading = false
    }
}

// MARK: - Storage

struct SettingsStorageView: View {
    @State private var storageInfo: [String: AnyCodable]?

    var body: some View {
        List {
            if let info = storageInfo {
                Section("Storage") {
                    HStack {
                        Text("Used")
                        Spacer()
                        Text(info["used_display"]?.value as? String ?? "—")
                            .foregroundStyle(Color.fontSecondary)
                    }
                    HStack {
                        Text("Quota")
                        Spacer()
                        Text(info["quota_display"]?.value as? String ?? "—")
                            .foregroundStyle(Color.fontSecondary)
                    }
                }
            }
            Section {
                Button("Manage Storage") { openWebPage("settings/account/storage") }
            }
        }
        .navigationTitle("Storage")
        .task { await loadStorage() }
    }

    private func loadStorage() async {
        storageInfo = try? await APIClient.shared.request(.get, path: "/v1/settings/storage")
    }
}

// MARK: - AI Model

struct SettingsAIModelView: View {
    var body: some View {
        List {
            Section {
                Text("AI model and provider configuration is managed on the web app for full control.")
                    .foregroundStyle(Color.fontSecondary)
                Button("Open AI Settings") { openWebPage("settings/ai") }
            }
        }
        .navigationTitle("AI Model")
    }
}

// MARK: - Memories

struct SettingsMemoriesView: View {
    var body: some View {
        List {
            Section {
                Text("View and manage your AI memories across all apps.")
                    .foregroundStyle(Color.fontSecondary)
                Button("Open Memories") { openWebPage("settings/memories") }
            }
        }
        .navigationTitle("Memories")
    }
}

// MARK: - Apps

struct SettingsAppsView: View {
    var body: some View {
        List {
            Section {
                Text("Browse the app store and manage installed apps.")
                    .foregroundStyle(Color.fontSecondary)
                Button("Open App Store") { openWebPage("settings/apps") }
            }
        }
        .navigationTitle("Apps")
    }
}

// MARK: - Gift Cards

struct SettingsGiftCardsView: View {
    @State private var giftCode = ""
    @State private var isRedeeming = false
    @State private var result: String?

    var body: some View {
        Form {
            Section("Redeem Gift Card") {
                TextField("Gift card code", text: $giftCode)
                    .autocorrectionDisabled()
                    #if os(iOS)
                    .textInputAutocapitalization(.characters)
                    #endif
                Button("Redeem") { redeemGiftCard() }
                    .disabled(giftCode.isEmpty || isRedeeming)
            }
            if let result {
                Section {
                    Text(result)
                        .foregroundStyle(result.contains("error") ? Color.error : Color.fontPrimary)
                }
            }
            Section {
                Button("Buy Gift Card") { openWebPage("settings/billing/gift-cards/buy") }
            }
        }
        .navigationTitle("Gift Cards")
    }

    private func redeemGiftCard() {
        isRedeeming = true
        result = nil
        Task {
            do {
                let _: Data = try await APIClient.shared.request(
                    .post, path: "/v1/payments/redeem-gift-card",
                    body: ["code": giftCode]
                )
                result = "Gift card redeemed successfully!"
                giftCode = ""
            } catch {
                result = "Error: \(error.localizedDescription)"
            }
            isRedeeming = false
        }
    }
}

// MARK: - Passkeys

struct SettingsPasskeysView: View {
    @State private var passkeys: [PasskeyItem] = []
    @State private var isLoading = true

    struct PasskeyItem: Identifiable, Decodable {
        let id: String
        let name: String?
        let createdAt: String?
        let lastUsedAt: String?
    }

    var body: some View {
        List {
            if isLoading {
                ProgressView()
            } else if passkeys.isEmpty {
                Section {
                    Text("No passkeys registered yet.")
                        .foregroundStyle(Color.fontSecondary)
                }
            } else {
                Section("Registered Passkeys") {
                    ForEach(passkeys) { passkey in
                        VStack(alignment: .leading, spacing: .spacing1) {
                            Text(passkey.name ?? "Unnamed Passkey")
                                .font(.omP).fontWeight(.medium)
                            if let created = passkey.createdAt {
                                Text("Added: \(created)")
                                    .font(.omXs).foregroundStyle(Color.fontTertiary)
                            }
                            if let lastUsed = passkey.lastUsedAt {
                                Text("Last used: \(lastUsed)")
                                    .font(.omXs).foregroundStyle(Color.fontTertiary)
                            }
                        }
                        .swipeActions {
                            Button(role: .destructive) {
                                deletePasskey(id: passkey.id)
                            } label: {
                                Label("Delete", systemImage: "trash")
                            }
                        }
                    }
                }
            }

            Section {
                Button("Add Passkey") { addPasskey() }
                Button("Manage on Web") { openWebPage("settings/account/security/passkeys") }
            }
        }
        .navigationTitle("Passkeys")
        .task { await loadPasskeys() }
    }

    private func loadPasskeys() async {
        do {
            passkeys = try await APIClient.shared.request(.get, path: "/v1/auth/passkeys")
        } catch {
            print("[Settings] Passkeys load error: \(error)")
        }
        isLoading = false
    }

    private func addPasskey() {
        openWebPage("settings/account/security/passkeys")
    }

    private func deletePasskey(id: String) {
        Task {
            do {
                let _: Data = try await APIClient.shared.request(
                    .post, path: "/v1/auth/passkeys/delete",
                    body: ["passkey_id": id]
                )
                passkeys.removeAll { $0.id == id }
            } catch {
                print("[Settings] Delete passkey error: \(error)")
            }
        }
    }
}

// MARK: - Password

struct SettingsPasswordView: View {
    @State private var currentPassword = ""
    @State private var newPassword = ""
    @State private var confirmPassword = ""
    @State private var isSaving = false
    @State private var result: String?

    private var isValid: Bool {
        !currentPassword.isEmpty && !newPassword.isEmpty && newPassword == confirmPassword && newPassword.count >= 8
    }

    var body: some View {
        Form {
            Section {
                SecureField("Current Password", text: $currentPassword)
                    .textContentType(.password)
                SecureField("New Password (min 8 chars)", text: $newPassword)
                    .textContentType(.newPassword)
                SecureField("Confirm New Password", text: $confirmPassword)
                    .textContentType(.newPassword)
            }

            if newPassword != confirmPassword && !confirmPassword.isEmpty {
                Text("Passwords don't match")
                    .font(.omXs).foregroundStyle(Color.error)
            }

            Section {
                Button("Update Password") { updatePassword() }
                    .disabled(!isValid || isSaving)
            }

            if let result {
                Text(result)
                    .font(.omXs)
                    .foregroundStyle(result.contains("Error") ? Color.error : Color.fontPrimary)
            }
        }
        .navigationTitle("Password")
    }

    private func updatePassword() {
        isSaving = true
        result = nil
        Task {
            do {
                let _: Data = try await APIClient.shared.request(
                    .post, path: "/v1/settings/update-password",
                    body: [
                        "current_password": currentPassword,
                        "new_password": newPassword
                    ]
                )
                result = "Password updated successfully"
                currentPassword = ""
                newPassword = ""
                confirmPassword = ""
            } catch {
                result = "Error: \(error.localizedDescription)"
            }
            isSaving = false
        }
    }
}

// MARK: - 2FA

struct Settings2FAView: View {
    @State private var is2FAEnabled = false
    @State private var isLoading = true

    var body: some View {
        List {
            Section {
                HStack {
                    Text("Status")
                    Spacer()
                    Text(is2FAEnabled ? "Enabled" : "Disabled")
                        .foregroundStyle(is2FAEnabled ? .green : Color.fontSecondary)
                        .fontWeight(.medium)
                }
            }

            Section {
                if is2FAEnabled {
                    Button("Manage 2FA on Web") {
                        openWebPage("settings/account/security/2fa")
                    }
                    Button("Disable 2FA", role: .destructive) {
                        disable2FA()
                    }
                } else {
                    Button("Set Up 2FA") {
                        openWebPage("settings/account/security/2fa")
                    }
                    Text("Two-factor authentication adds an extra layer of security using an authenticator app.")
                        .font(.omXs).foregroundStyle(Color.fontSecondary)
                }
            }
        }
        .navigationTitle("Two-Factor Auth")
        .task { await load2FAStatus() }
    }

    private func load2FAStatus() async {
        do {
            let session: SessionResponse = try await APIClient.shared.request(.get, path: "/v1/auth/session")
            // Infer 2FA status from session data
            isLoading = false
        } catch {
            isLoading = false
        }
    }

    private func disable2FA() {
        Task {
            try? await APIClient.shared.request(
                .post, path: "/v1/settings/user/disable-2fa"
            ) as Data
            is2FAEnabled = false
        }
    }
}

// MARK: - Recovery Key

struct SettingsRecoveryKeyView: View {
    @State private var showKey = false
    @State private var recoveryKey: String?
    @State private var isLoading = false
    @State private var verificationCode = ""
    @State private var needsVerification = true

    var body: some View {
        List {
            Section {
                Text("Your recovery key is the last resort to access your account if you lose your password and 2FA device.")
                    .foregroundStyle(Color.fontSecondary)
            }

            if needsVerification {
                Section("Verify Identity") {
                    SecureField("Enter your password", text: $verificationCode)
                    Button("Verify") { verifyAndShow() }
                        .disabled(verificationCode.isEmpty || isLoading)
                }
            } else if let key = recoveryKey {
                Section("Your Recovery Key") {
                    Text(key)
                        .font(.system(.body, design: .monospaced))
                        .textSelection(.enabled)
                        .padding(.vertical, .spacing2)

                    Button("Copy to Clipboard") {
                        #if os(iOS)
                        UIPasteboard.general.string = key
                        #elseif os(macOS)
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(key, forType: .string)
                        #endif
                    }

                    Text("Store this key securely. It cannot be recovered if lost.")
                        .font(.omXs).foregroundStyle(Color.warning)
                }
            }

            Section {
                Button("Regenerate Recovery Key") {
                    openWebPage("settings/account/security/recovery-key")
                }
            }
        }
        .navigationTitle("Recovery Key")
    }

    private func verifyAndShow() {
        isLoading = true
        Task {
            do {
                let response: [String: AnyCodable] = try await APIClient.shared.request(
                    .post, path: "/v1/settings/request-action-verification",
                    body: ["password": verificationCode, "action": "view_recovery_key"]
                )
                recoveryKey = response["recovery_key"]?.value as? String ?? "Key not available"
                needsVerification = false
            } catch {
                print("[Settings] Verification failed: \(error)")
            }
            isLoading = false
        }
    }
}

// MARK: - Sessions

struct SettingsSessionsView: View {
    @State private var sessions: [SessionItem] = []
    @State private var isLoading = true

    struct SessionItem: Identifiable, Decodable {
        let id: String
        let deviceOs: String?
        let deviceModel: String?
        let lastActive: String?
        let isCurrent: Bool?
        let city: String?
        let country: String?
    }

    var body: some View {
        List {
            if isLoading {
                ProgressView()
            } else {
                ForEach(sessions) { session in
                    VStack(alignment: .leading, spacing: .spacing1) {
                        HStack {
                            Text(session.deviceOs ?? "Unknown")
                                .font(.omP).fontWeight(.medium)
                            if session.isCurrent == true {
                                Text("Current")
                                    .font(.omTiny).fontWeight(.bold)
                                    .foregroundStyle(.white)
                                    .padding(.horizontal, .spacing2)
                                    .padding(.vertical, 2)
                                    .background(Color.buttonPrimary)
                                    .clipShape(RoundedRectangle(cornerRadius: .radius1))
                            }
                        }
                        if let model = session.deviceModel {
                            Text(model).font(.omXs).foregroundStyle(Color.fontSecondary)
                        }
                        HStack(spacing: .spacing3) {
                            if let city = session.city, let country = session.country {
                                Text("\(city), \(country)").font(.omXs).foregroundStyle(Color.fontTertiary)
                            }
                            if let lastActive = session.lastActive {
                                Text(lastActive).font(.omXs).foregroundStyle(Color.fontTertiary)
                            }
                        }
                    }
                }
            }

            Section {
                Button("Log Out All Other Sessions", role: .destructive) {
                    logoutAll()
                }
            }
        }
        .navigationTitle("Sessions")
        .task { await loadSessions() }
    }

    private func loadSessions() async {
        do {
            sessions = try await APIClient.shared.request(.get, path: "/v1/auth/sessions")
        } catch {
            print("[Settings] Sessions load error: \(error)")
        }
        isLoading = false
    }

    private func logoutAll() {
        Task {
            try? await APIClient.shared.request(.post, path: "/v1/auth/logout/all") as Data
            sessions = sessions.filter { $0.isCurrent == true }
        }
    }
}

// MARK: - Privacy

struct SettingsPrivacyView: View {
    var body: some View {
        List {
            Section {
                Text("Manage your personal data anonymization. The AI will replace detected personal information with placeholders.")
                    .foregroundStyle(Color.fontSecondary)
            }

            Section {
                Button("Manage Hidden Data") { openWebPage("settings/privacy/hide-personal-data") }
                Button("Share Debug Logs") { openWebPage("settings/privacy/share-debug-logs") }
            }
        }
        .navigationTitle("Privacy")
    }
}

// MARK: - Auto-Delete

struct SettingsAutoDeleteView: View {
    @State private var autoDeleteDays: Int = 0

    private let options = [
        (0, "Never"),
        (30, "After 30 days"),
        (90, "After 90 days"),
        (180, "After 6 months"),
        (365, "After 1 year")
    ]

    var body: some View {
        List {
            Section("Auto-Delete Chats") {
                ForEach(options, id: \.0) { days, label in
                    Button {
                        autoDeleteDays = days
                        saveAutoDelete(days)
                    } label: {
                        HStack {
                            Text(label).foregroundStyle(Color.fontPrimary)
                            Spacer()
                            if autoDeleteDays == days {
                                Image(systemName: "checkmark").foregroundStyle(Color.buttonPrimary)
                            }
                        }
                    }
                }
            }

            Section {
                Text("Chats older than the selected period will be automatically deleted.")
                    .font(.omXs).foregroundStyle(Color.fontSecondary)
            }
        }
        .navigationTitle("Auto-Delete")
    }

    private func saveAutoDelete(_ days: Int) {
        Task {
            try? await APIClient.shared.request(
                .post, path: "/v1/settings/auto-delete-chats",
                body: ["days": days]
            ) as Data
        }
    }
}

// MARK: - Language

struct SettingsLanguageView: View {
    @ObservedObject private var locManager = LocalizationManager.shared
    @EnvironmentObject var authManager: AuthManager

    var body: some View {
        List {
            ForEach(SupportedLanguage.allCases) { language in
                Button {
                    switchLanguage(language)
                } label: {
                    HStack {
                        Text(language.name).foregroundStyle(Color.fontPrimary)
                        if language.isRTL {
                            Text("RTL")
                                .font(.omTiny).foregroundStyle(Color.fontTertiary)
                                .padding(.horizontal, .spacing2)
                                .padding(.vertical, 1)
                                .background(Color.grey10)
                                .clipShape(RoundedRectangle(cornerRadius: .radius1))
                        }
                        Spacer()
                        if locManager.currentLanguage == language {
                            Image(systemName: "checkmark").foregroundStyle(Color.buttonPrimary)
                        }
                    }
                }
            }
        }
        .navigationTitle(AppStrings.settingsInterface)
        .environment(\.layoutDirection, locManager.currentLanguage.layoutDirection)
    }

    private func switchLanguage(_ language: SupportedLanguage) {
        Task {
            await locManager.setLanguage(language)

            // Persist to backend if authenticated
            if authManager.currentUser != nil {
                try? await APIClient.shared.request(
                    .post, path: "/v1/settings/user/language",
                    body: ["language": language.code]
                ) as Data
            }
        }
    }
}

// MARK: - Notifications

struct SettingsNotificationsView: View {
    @State private var chatNotifications = true
    @State private var emailNotifications = true

    var body: some View {
        Form {
            Section("Push Notifications") {
                Toggle("Chat Messages", isOn: $chatNotifications)
                    .tint(Color.buttonPrimary)
            }

            Section("Email Notifications") {
                Toggle("Email Notifications", isOn: $emailNotifications)
                    .tint(Color.buttonPrimary)
                    .onChange(of: emailNotifications) { _, newValue in
                        saveEmailNotifications(newValue)
                    }
            }

            Section {
                Text("Push notifications require notification permissions to be enabled in your device settings.")
                    .font(.omXs).foregroundStyle(Color.fontSecondary)
            }
        }
        .navigationTitle("Notifications")
    }

    private func saveEmailNotifications(_ enabled: Bool) {
        Task {
            try? await APIClient.shared.request(
                .post, path: "/v1/settings/user/email-notifications",
                body: ["enabled": enabled]
            ) as Data
        }
    }
}

// MARK: - Backup Reminders

struct SettingsBackupRemindersView: View {
    @State private var reminderDays = 30
    @State private var isEnabled = true

    var body: some View {
        Form {
            Toggle("Backup Reminders", isOn: $isEnabled)
                .tint(Color.buttonPrimary)

            if isEnabled {
                Stepper("Every \(reminderDays) days", value: $reminderDays, in: 7...365, step: 7)
            }

            Section {
                Text("Periodic reminders to back up your recovery key and 2FA codes.")
                    .font(.omXs).foregroundStyle(Color.fontSecondary)
            }
        }
        .navigationTitle("Backup Reminders")
    }
}

// MARK: - Helper

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
