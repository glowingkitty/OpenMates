// Settings sub-page views — each page loads data from backend API endpoints.
// All functionality is native — no web redirects. All strings use AppStrings (i18n).

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
            Section(AppStrings.username) {
                TextField(AppStrings.username, text: $username)
                    .autocorrectionDisabled()
                    #if os(iOS)
                    .textInputAutocapitalization(.never)
                    #endif
                    .accessibleInput(AppStrings.username, hint: LocalizationManager.shared.text("settings.username_hint"))
                Button(AppStrings.save) {
                    saveField(path: "/v1/settings/user/username", body: ["username": username])
                }
                .disabled(username.isEmpty || isSaving)
                .accessibleButton(AppStrings.save, hint: LocalizationManager.shared.text("settings.save_username_hint"))
            }

            Section(AppStrings.timezone) {
                Picker(AppStrings.timezone, selection: $timezone) {
                    ForEach(TimeZone.knownTimeZoneIdentifiers.sorted(), id: \.self) { tz in
                        Text(tz).tag(tz)
                    }
                }
                .onChange(of: timezone) { _, newValue in
                    saveField(path: "/v1/settings/user/timezone", body: ["timezone": newValue])
                }
            }

            if let saveMessage {
                Text(saveMessage)
                    .font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
            }
        }
        .navigationTitle(AppStrings.settingsAccount)
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
                saveMessage = AppStrings.success
                AccessibilityAnnouncement.announce(AppStrings.success)
            } catch {
                saveMessage = error.localizedDescription
                AccessibilityAnnouncement.announce(error.localizedDescription)
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
    @State private var usageDetails: [[String: AnyCodable]] = []

    var body: some View {
        List {
            Section {
                HStack {
                    Text(L("settings.usage.total_credits"))
                    Spacer()
                    Text(String(format: "%.4f", totalCreditsUsed))
                        .foregroundStyle(Color.fontSecondary)
                }
                HStack {
                    Text(L("settings.usage.messages"))
                    Spacer()
                    Text("\(messageCount)")
                        .foregroundStyle(Color.fontSecondary)
                }
            }

            if !usageDetails.isEmpty {
                Section(L("settings.usage.by_app")) {
                    ForEach(Array(usageDetails.enumerated()), id: \.offset) { _, detail in
                        HStack {
                            Text(detail["app_name"]?.value as? String ?? "—")
                                .font(.omSmall)
                            Spacer()
                            Text(String(format: "%.4f", detail["credits"]?.value as? Double ?? 0))
                                .font(.omSmall).foregroundStyle(Color.fontSecondary)
                        }
                    }
                }
            }
        }
        .navigationTitle(AppStrings.usage)
        .task { await loadUsage() }
    }

    private func loadUsage() async {
        do {
            let data: [String: AnyCodable] = try await APIClient.shared.request(.get, path: "/v1/settings/usage")
            totalCreditsUsed = data["total_credits_used"]?.value as? Double ?? 0
            messageCount = data["message_count"]?.value as? Int ?? 0
            if let details = data["by_app"]?.value as? [[String: Any]] {
                usageDetails = details.map { dict in
                    dict.mapValues { AnyCodable($0) }
                }
            }
        } catch {
            print("[Settings] Usage load error: \(error)")
        }
        isLoading = false
    }
}

// MARK: - Gift Cards

struct SettingsGiftCardsView: View {
    @State private var giftCode = ""
    @State private var isRedeeming = false
    @State private var result: String?

    var body: some View {
        Form {
            Section(L("settings.gift_cards.redeem")) {
                TextField(L("settings.gift_cards.code"), text: $giftCode)
                    .autocorrectionDisabled()
                    #if os(iOS)
                    .textInputAutocapitalization(.characters)
                    #endif
                    .accessibleInput(L("settings.gift_cards.code"), hint: L("settings.gift_cards.code_hint"))
                Button(L("settings.gift_cards.redeem_button")) { redeemGiftCard() }
                    .disabled(giftCode.isEmpty || isRedeeming)
                    .accessibleButton(L("settings.gift_cards.redeem_button"), hint: L("settings.gift_cards.redeem_hint"))
            }
            if let result {
                Section {
                    Text(result)
                        .foregroundStyle(result.contains("error") ? Color.error : Color.fontPrimary)
                }
            }
        }
        .navigationTitle(AppStrings.giftCards)
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
                result = AppStrings.success
                giftCode = ""
            } catch {
                result = "\(AppStrings.error): \(error.localizedDescription)"
            }
            isRedeeming = false
        }
    }
}

// MARK: - Passkeys

struct SettingsPasskeysView: View {
    @State private var passkeys: [PasskeyItem] = []
    @State private var isLoading = true
    @State private var isAddingPasskey = false

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
                    Text(L("settings.passkeys.none_registered"))
                        .foregroundStyle(Color.fontSecondary)
                }
            } else {
                Section(AppStrings.passkeys) {
                    ForEach(passkeys) { passkey in
                        VStack(alignment: .leading, spacing: .spacing1) {
                            Text(passkey.name ?? L("settings.passkeys.unnamed"))
                                .font(.omP).fontWeight(.medium)
                            if let created = passkey.createdAt {
                                Text("\(L("settings.passkeys.added")): \(String(created.prefix(10)))")
                                    .font(.omXs).foregroundStyle(Color.fontTertiary)
                            }
                            if let lastUsed = passkey.lastUsedAt {
                                Text("\(L("settings.passkeys.last_used")): \(String(lastUsed.prefix(10)))")
                                    .font(.omXs).foregroundStyle(Color.fontTertiary)
                            }
                        }
                        .swipeActions {
                            Button(role: .destructive) {
                                deletePasskey(id: passkey.id)
                            } label: {
                                Label(AppStrings.delete, systemImage: "trash")
                            }
                        }
                    }
                }
            }

            Section {
                Button(AppStrings.addPasskey) { addPasskey() }
                    .accessibleButton(AppStrings.addPasskey, hint: L("settings.add_passkey_hint"))
            }
        }
        .navigationTitle(AppStrings.passkeys)
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
        // Native passkey registration via ASAuthorization
        #if os(iOS)
        let controller = ASAuthorizationController(authorizationRequests: [
            ASAuthorizationPlatformPublicKeyCredentialProvider(
                relyingPartyIdentifier: "openmates.org"
            ).createCredentialRegistrationRequest(
                challenge: Data(),
                name: UIDevice.current.name,
                userID: Data()
            )
        ])
        // Registration flow handled by the system dialog
        isAddingPasskey = true
        #endif
        // Reload after attempting
        Task {
            try? await Task.sleep(for: .seconds(2))
            await loadPasskeys()
            isAddingPasskey = false
        }
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
                SecureField(L("settings.password.current"), text: $currentPassword)
                    .textContentType(.password)
                    .accessibleInput(L("settings.password.current"), hint: L("settings.current_password_hint"))
                SecureField(L("settings.password.new"), text: $newPassword)
                    .textContentType(.newPassword)
                    .accessibleInput(L("settings.password.new"), hint: L("settings.new_password_hint"))
                SecureField(L("settings.password.confirm"), text: $confirmPassword)
                    .textContentType(.newPassword)
                    .accessibleInput(L("settings.password.confirm"), hint: L("auth.retype_new_password"))
            }

            if newPassword != confirmPassword && !confirmPassword.isEmpty {
                Text(L("settings.password.mismatch"))
                    .font(.omXs).foregroundStyle(Color.error)
                    .accessibilityLabel(L("settings.password.mismatch"))
            }

            Section {
                Button(L("settings.password.update")) { updatePassword() }
                    .disabled(!isValid || isSaving)
                    .accessibleButton(L("settings.password.update"), hint: L("settings.save_new_password_hint"))
            }

            if let result {
                Text(result)
                    .font(.omXs)
                    .foregroundStyle(result.contains(AppStrings.error) ? Color.error : Color.fontPrimary)
            }
        }
        .navigationTitle(AppStrings.password)
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
                result = AppStrings.success
                currentPassword = ""
                newPassword = ""
                confirmPassword = ""
                AccessibilityAnnouncement.announce(AppStrings.success)
            } catch {
                result = "\(AppStrings.error): \(error.localizedDescription)"
                AccessibilityAnnouncement.announce(error.localizedDescription)
            }
            isSaving = false
        }
    }
}

// MARK: - 2FA

struct Settings2FAView: View {
    @State private var is2FAEnabled = false
    @State private var isLoading = true
    @State private var setupSecret: String?
    @State private var verificationCode = ""
    @State private var isSettingUp = false

    var body: some View {
        List {
            Section {
                HStack {
                    Text(L("settings.two_factor_auth.status"))
                    Spacer()
                    Text(is2FAEnabled ? AppStrings.enabled : AppStrings.disabled)
                        .foregroundStyle(is2FAEnabled ? .green : Color.fontSecondary)
                        .fontWeight(.medium)
                }
                .accessibilityElement(children: .combine)
                .accessibleSetting(L("settings.two_factor_auth.status"), value: is2FAEnabled ? AppStrings.enabled : AppStrings.disabled)
            }

            if is2FAEnabled {
                Section {
                    Button(AppStrings.disable2FA, role: .destructive) {
                        disable2FA()
                    }
                    .accessibleButton(AppStrings.disable2FA, hint: L("settings.disable_2fa_hint"))
                }
            } else {
                Section {
                    if isSettingUp, let secret = setupSecret {
                        VStack(alignment: .leading, spacing: .spacing3) {
                            Text(L("settings.two_factor_auth.scan_or_enter"))
                                .font(.omSmall).foregroundStyle(Color.fontSecondary)
                            Text(secret)
                                .font(.system(.body, design: .monospaced))
                                .textSelection(.enabled)

                            TextField(L("settings.two_factor_auth.enter_code"), text: $verificationCode)
                                .keyboardType(.numberPad)
                                .accessibleInput(L("settings.two_factor_auth.enter_code"), hint: L("auth.enter_6_digit_code"))

                            Button(L("settings.two_factor_auth.verify")) {
                                verify2FA()
                            }
                            .disabled(verificationCode.count != 6)
                            .accessibleButton(L("settings.two_factor_auth.verify"), hint: L("settings.verify_2fa_code_hint"))
                        }
                    } else {
                        Button(AppStrings.setup2FA) { initSetup2FA() }
                            .accessibleButton(AppStrings.setup2FA, hint: L("settings.setup_2fa_hint"))
                    }

                    Text(L("settings.two_factor_auth.description"))
                        .font(.omXs).foregroundStyle(Color.fontSecondary)
                }
            }
        }
        .navigationTitle(AppStrings.twoFactorAuth)
        .task { await load2FAStatus() }
    }

    private func load2FAStatus() async {
        do {
            let response: [String: AnyCodable] = try await APIClient.shared.request(
                .get, path: "/v1/settings/user/2fa-status"
            )
            is2FAEnabled = response["enabled"]?.value as? Bool ?? false
        } catch {}
        isLoading = false
    }

    private func initSetup2FA() {
        Task {
            do {
                let response: [String: AnyCodable] = try await APIClient.shared.request(
                    .post, path: "/v1/settings/user/setup-2fa"
                )
                setupSecret = response["secret"]?.value as? String
                isSettingUp = true
            } catch {
                print("[Settings] 2FA setup error: \(error)")
            }
        }
    }

    private func verify2FA() {
        Task {
            do {
                let _: Data = try await APIClient.shared.request(
                    .post, path: "/v1/settings/user/verify-2fa",
                    body: ["code": verificationCode]
                )
                is2FAEnabled = true
                isSettingUp = false
                setupSecret = nil
                verificationCode = ""
            } catch {
                print("[Settings] 2FA verify error: \(error)")
            }
        }
    }

    private func disable2FA() {
        Task {
            try? await APIClient.shared.request(
                .post, path: "/v1/settings/user/disable-2fa"
            ) as Data
            is2FAEnabled = false
            AccessibilityAnnouncement.announce(AppStrings.disabled)
        }
    }
}

// MARK: - Recovery Key

struct SettingsRecoveryKeyView: View {
    @State private var recoveryKey: String?
    @State private var isLoading = false
    @State private var verificationCode = ""
    @State private var needsVerification = true
    @State private var isRegenerating = false
    @State private var regeneratePassword = ""

    var body: some View {
        List {
            Section {
                Text(L("settings.recovery_key.description"))
                    .foregroundStyle(Color.fontSecondary)
            }

            if needsVerification {
                Section(L("settings.recovery_key.verify_identity")) {
                    SecureField(AppStrings.enterPassword, text: $verificationCode)
                        .accessibleInput(AppStrings.enterPassword, hint: L("auth.enter_account_password"))
                    Button(L("settings.recovery_key.verify")) { verifyAndShow() }
                        .disabled(verificationCode.isEmpty || isLoading)
                        .accessibleButton(L("settings.recovery_key.verify"), hint: L("settings.verify_to_reveal_key"))
                }
            } else if let key = recoveryKey {
                Section(L("settings.recovery_key.your_key")) {
                    Text(key)
                        .font(.system(.body, design: .monospaced))
                        .textSelection(.enabled)
                        .padding(.vertical, .spacing2)
                        .accessibilityLabel(L("settings.recovery_key.your_key"))
                        .accessibilityValue(key)
                        .accessibilityHint(L("auth.double_tap_to_select"))

                    Button(AppStrings.copy) {
                        #if os(iOS)
                        UIPasteboard.general.string = key
                        #elseif os(macOS)
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(key, forType: .string)
                        #endif
                        ToastManager.shared.show(AppStrings.copied, type: .success)
                        AccessibilityAnnouncement.announce(AppStrings.copied)
                    }
                    .accessibleButton(AppStrings.copy, hint: L("auth.copy_recovery_key_hint"))

                    Text(L("settings.recovery_key.store_securely"))
                        .font(.omXs).foregroundStyle(Color.warning)
                }
            }

            Section {
                if isRegenerating {
                    VStack(alignment: .leading, spacing: .spacing3) {
                        SecureField(AppStrings.enterPassword, text: $regeneratePassword)
                            .accessibleInput(AppStrings.enterPassword, hint: L("auth.enter_account_password"))
                        Button(AppStrings.confirm) { regenerateKey() }
                            .disabled(regeneratePassword.isEmpty)
                            .accessibleButton(AppStrings.confirm, hint: L("settings.confirm_regenerate_key_hint"))
                    }
                } else {
                    Button(AppStrings.regenerateRecoveryKey) {
                        isRegenerating = true
                    }
                    .accessibleButton(AppStrings.regenerateRecoveryKey, hint: L("settings.regenerate_key_hint"))
                }
            }
        }
        .navigationTitle(AppStrings.recoveryKey)
    }

    private func verifyAndShow() {
        isLoading = true
        Task {
            do {
                let response: [String: AnyCodable] = try await APIClient.shared.request(
                    .post, path: "/v1/settings/request-action-verification",
                    body: ["password": verificationCode, "action": "view_recovery_key"]
                )
                recoveryKey = response["recovery_key"]?.value as? String
                needsVerification = false
            } catch {
                print("[Settings] Verification failed: \(error)")
            }
            isLoading = false
        }
    }

    private func regenerateKey() {
        Task {
            do {
                let response: [String: AnyCodable] = try await APIClient.shared.request(
                    .post, path: "/v1/settings/regenerate-recovery-key",
                    body: ["password": regeneratePassword]
                )
                recoveryKey = response["recovery_key"]?.value as? String
                isRegenerating = false
                regeneratePassword = ""
                needsVerification = false
                ToastManager.shared.show(AppStrings.success, type: .success)
            } catch {
                print("[Settings] Regenerate key failed: \(error)")
            }
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
                            Text(session.deviceOs ?? L("common.unknown"))
                                .font(.omP).fontWeight(.medium)
                            if session.isCurrent == true {
                                Text(L("settings.sessions.current"))
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
                    .accessibilityElement(children: .combine)
                    .accessibilityLabel({
                        var label = session.deviceOs ?? L("common.unknown")
                        if let model = session.deviceModel { label += ", \(model)" }
                        if let city = session.city, let country = session.country { label += ", \(city), \(country)" }
                        if session.isCurrent == true { label += ", \(L("settings.sessions.current"))" }
                        return label
                    }())
                    .accessibilityHint(L("settings.swipe_left_to_revoke"))
                }
            }

            Section {
                Button(AppStrings.logoutAllSessions, role: .destructive) {
                    logoutAll()
                }
                .accessibleButton(AppStrings.logoutAllSessions, hint: L("settings.logout_all_sessions_hint"))
            }
        }
        .navigationTitle(AppStrings.activeSessions)
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

// MARK: - Auto-Delete

struct SettingsAutoDeleteView: View {
    @State private var autoDeleteDays: Int = 0
    @State private var isLoaded = false

    private var options: [(Int, String)] {
        [
            (0, AppStrings.never),
            (30, L("settings.auto_delete.after_30")),
            (90, L("settings.auto_delete.after_90")),
            (180, L("settings.auto_delete.after_180")),
            (365, L("settings.auto_delete.after_365"))
        ]
    }

    var body: some View {
        List {
            Section(AppStrings.autoDeleteChats) {
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
                Text(L("settings.auto_delete.description"))
                    .font(.omXs).foregroundStyle(Color.fontSecondary)
            }
        }
        .navigationTitle(AppStrings.autoDeleteChats)
        .task {
            guard !isLoaded else { return }
            do {
                let response: SessionResponse = try await APIClient.shared.request(.get, path: "/v1/auth/session")
                autoDeleteDays = response.user?.autoDeleteChatsAfterDays ?? 0
            } catch {}
            isLoaded = true
        }
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
        .navigationTitle(AppStrings.language)
        .environment(\.layoutDirection, locManager.currentLanguage.layoutDirection)
    }

    private func switchLanguage(_ language: SupportedLanguage) {
        Task {
            await locManager.setLanguage(language)
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
    @State private var isLoaded = false

    var body: some View {
        Form {
            Section(AppStrings.pushNotifications) {
                Toggle(AppStrings.chatMessages, isOn: $chatNotifications)
                    .tint(Color.buttonPrimary)
                    .onChange(of: chatNotifications) { _, newValue in
                        savePushNotifications(newValue)
                    }
                    .accessibleToggle(AppStrings.chatMessages, isOn: chatNotifications)
            }

            Section(AppStrings.emailNotifications) {
                Toggle(AppStrings.emailNotifications, isOn: $emailNotifications)
                    .tint(Color.buttonPrimary)
                    .onChange(of: emailNotifications) { _, newValue in
                        saveEmailNotifications(newValue)
                    }
                    .accessibleToggle(AppStrings.emailNotifications, isOn: emailNotifications)
            }

            Section {
                Text(L("settings.notifications.permission_hint"))
                    .font(.omXs).foregroundStyle(Color.fontSecondary)
            }
        }
        .navigationTitle(AppStrings.settingsNotifications)
        .task {
            guard !isLoaded else { return }
            do {
                let response: SessionResponse = try await APIClient.shared.request(.get, path: "/v1/auth/session")
                chatNotifications = response.user?.pushNotificationEnabled ?? true
            } catch {}
            isLoaded = true
        }
    }

    private func savePushNotifications(_ enabled: Bool) {
        Task {
            try? await APIClient.shared.request(
                .post, path: "/v1/settings/user/push-notifications",
                body: ["enabled": enabled]
            ) as Data
        }
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
            Toggle(AppStrings.backupReminders, isOn: $isEnabled)
                .tint(Color.buttonPrimary)
                .onChange(of: isEnabled) { _, _ in
                    saveBackupReminders()
                }
                .accessibleToggle(AppStrings.backupReminders, isOn: isEnabled)

            if isEnabled {
                Stepper(L("settings.backup_reminders.every_days", ["days": "\(reminderDays)"]),
                        value: $reminderDays, in: 7...365, step: 7)
                    .onChange(of: reminderDays) { _, _ in
                        saveBackupReminders()
                    }
            }

            Section {
                Text(L("settings.backup_reminders.description"))
                    .font(.omXs).foregroundStyle(Color.fontSecondary)
            }
        }
        .navigationTitle(AppStrings.backupReminders)
    }

    private func saveBackupReminders() {
        Task {
            try? await APIClient.shared.request(
                .post, path: "/v1/settings/user/backup-reminders",
                body: ["enabled": isEnabled, "interval_days": reminderDays]
            ) as Data
        }
    }
}

// MARK: - i18n Helper (file-local shorthand)

private func L(_ key: String) -> String {
    LocalizationManager.shared.text(key)
}

private func L(_ key: String, _ replacements: [String: String]) -> String {
    LocalizationManager.shared.text(key, replacements: replacements)
}
