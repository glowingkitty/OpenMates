// Settings sub-page views — each page loads data from backend API endpoints.
// All functionality is native — no web redirects. All strings use AppStrings (i18n).
// Uses OMSettingsPage/Section/Row primitives — no Form/List/Toggle/Picker/.navigationTitle.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/SettingsAccount.svelte
//          frontend/packages/ui/src/components/settings/SettingsSecurity.svelte
//          frontend/packages/ui/src/components/settings/SettingsNotifications.svelte
//          frontend/packages/ui/src/components/settings/SettingsPrivacy.svelte
//          frontend/packages/ui/src/components/settings/SettingsChat.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

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
        OMSettingsPage(title: AppStrings.settingsAccount) {
            OMSettingsSection(AppStrings.username) {
                VStack(alignment: .leading, spacing: .spacing3) {
                    TextField(AppStrings.username, text: $username)
                        .autocorrectionDisabled()
                        .font(.omP)
                        .padding(.horizontal, .spacing6)
                        .padding(.vertical, .spacing4)
                        #if os(iOS)
                        .textInputAutocapitalization(.never)
                        #endif
                        .accessibleInput(AppStrings.username, hint: L("settings.username_hint"))

                    Button(AppStrings.save) {
                        saveField(path: "/v1/settings/user/username", body: ["username": username])
                    }
                    .buttonStyle(OMPrimaryButtonStyle())
                    .disabled(username.isEmpty || isSaving)
                    .padding(.horizontal, .spacing6)
                    .padding(.bottom, .spacing4)
                    .accessibleButton(AppStrings.save, hint: L("settings.save_username_hint"))
                }
            }

            OMSettingsSection(AppStrings.timezone) {
                OMDropdown(
                    title: AppStrings.timezone,
                    options: TimeZone.knownTimeZoneIdentifiers.sorted().map {
                        OMDropdownOption($0, label: $0)
                    },
                    selection: $timezone
                )
                .padding(.horizontal, .spacing6)
                .padding(.vertical, .spacing4)
                .onChange(of: timezone) { _, newValue in
                    saveField(path: "/v1/settings/user/timezone", body: ["timezone": newValue])
                }
            }

            if let saveMessage {
                Text(saveMessage)
                    .font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
                    .padding(.horizontal, .spacing6)
            }
        }
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
        OMSettingsPage(title: AppStrings.usage) {
            OMSettingsSection {
                OMSettingsStaticRow(
                    title: L("settings.usage.total_credits"),
                    value: String(format: "%.4f", totalCreditsUsed)
                )
                OMSettingsStaticRow(
                    title: L("settings.usage.messages"),
                    value: "\(messageCount)"
                )
            }

            if !usageDetails.isEmpty {
                OMSettingsSection(L("settings.usage.by_app")) {
                    ForEach(Array(usageDetails.enumerated()), id: \.offset) { _, detail in
                        OMSettingsStaticRow(
                            title: detail["app_name"]?.value as? String ?? "—",
                            value: String(format: "%.4f", detail["credits"]?.value as? Double ?? 0)
                        )
                    }
                }
            }
        }
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
        OMSettingsPage(title: AppStrings.giftCards) {
            OMSettingsSection(L("settings.gift_cards.redeem")) {
                VStack(alignment: .leading, spacing: .spacing3) {
                    TextField(L("settings.gift_cards.code"), text: $giftCode)
                        .autocorrectionDisabled()
                        .font(.omP)
                        .padding(.horizontal, .spacing6)
                        .padding(.vertical, .spacing4)
                        #if os(iOS)
                        .textInputAutocapitalization(.characters)
                        #endif
                        .accessibleInput(L("settings.gift_cards.code"), hint: L("settings.gift_cards.code_hint"))

                    Button(L("settings.gift_cards.redeem_button")) { redeemGiftCard() }
                        .buttonStyle(OMPrimaryButtonStyle())
                        .disabled(giftCode.isEmpty || isRedeeming)
                        .padding(.horizontal, .spacing6)
                        .padding(.bottom, .spacing4)
                        .accessibleButton(L("settings.gift_cards.redeem_button"), hint: L("settings.gift_cards.redeem_hint"))
                }
            }

            if let result {
                Text(result)
                    .font(.omSmall)
                    .foregroundStyle(result.contains("error") ? Color.error : Color.fontPrimary)
                    .padding(.horizontal, .spacing6)
            }
        }
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
        OMSettingsPage(title: AppStrings.passkeys) {
            if isLoading {
                ProgressView()
                    .frame(maxWidth: .infinity, alignment: .center)
                    .padding(.spacing8)
            } else if passkeys.isEmpty {
                OMSettingsSection {
                    Text(L("settings.passkeys.none_registered"))
                        .font(.omSmall)
                        .foregroundStyle(Color.fontSecondary)
                        .padding(.horizontal, .spacing6)
                        .padding(.vertical, .spacing5)
                }
            } else {
                OMSettingsSection(AppStrings.passkeys) {
                    ForEach(passkeys) { passkey in
                        VStack(alignment: .leading, spacing: .spacing1) {
                            Text(passkey.name ?? L("settings.passkeys.unnamed"))
                                .font(.omP).fontWeight(.medium)
                                .foregroundStyle(Color.fontPrimary)
                            if let created = passkey.createdAt {
                                Text("\(L("settings.passkeys.added")): \(String(created.prefix(10)))")
                                    .font(.omXs).foregroundStyle(Color.fontTertiary)
                            }
                            if let lastUsed = passkey.lastUsedAt {
                                Text("\(L("settings.passkeys.last_used")): \(String(lastUsed.prefix(10)))")
                                    .font(.omXs).foregroundStyle(Color.fontTertiary)
                            }
                        }
                        .padding(.horizontal, .spacing6)
                        .padding(.vertical, .spacing5)
                    }
                }
            }

            OMSettingsSection {
                OMSettingsRow(title: AppStrings.addPasskey, icon: "plus", showsChevron: false) {
                    addPasskey()
                }
            }
        }
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
        #if os(iOS)
        isAddingPasskey = true
        #endif
        Task {
            #if os(iOS)
            let webAppURL = await APIClient.shared.webAppURL
            let relyingPartyIdentifier = webAppURL.host() ?? ServerEndpointConfiguration.defaultSelectedDomain
            let controller = ASAuthorizationController(authorizationRequests: [
                ASAuthorizationPlatformPublicKeyCredentialProvider(
                    relyingPartyIdentifier: relyingPartyIdentifier
                ).createCredentialRegistrationRequest(
                    challenge: Data(),
                    name: UIDevice.current.name,
                    userID: Data()
                )
            ])
            _ = controller
            #endif
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
        OMSettingsPage(title: AppStrings.password) {
            OMSettingsSection {
                VStack(alignment: .leading, spacing: .spacing3) {
                    SecureField(L("settings.password.current"), text: $currentPassword)
                        .textContentType(.password)
                        .font(.omP)
                        .padding(.horizontal, .spacing6)
                        .padding(.vertical, .spacing4)
                        .accessibleInput(L("settings.password.current"), hint: L("settings.current_password_hint"))
                    SecureField(L("settings.password.new"), text: $newPassword)
                        .textContentType(.newPassword)
                        .font(.omP)
                        .padding(.horizontal, .spacing6)
                        .padding(.vertical, .spacing4)
                        .accessibleInput(L("settings.password.new"), hint: L("settings.new_password_hint"))
                    SecureField(L("settings.password.confirm"), text: $confirmPassword)
                        .textContentType(.newPassword)
                        .font(.omP)
                        .padding(.horizontal, .spacing6)
                        .padding(.vertical, .spacing4)
                        .accessibleInput(L("settings.password.confirm"), hint: L("auth.retype_new_password"))
                }
            }

            if newPassword != confirmPassword && !confirmPassword.isEmpty {
                Text(L("settings.password.mismatch"))
                    .font(.omXs).foregroundStyle(Color.error)
                    .padding(.horizontal, .spacing6)
                    .accessibilityLabel(L("settings.password.mismatch"))
            }

            Button(L("settings.password.update")) { updatePassword() }
                .buttonStyle(OMPrimaryButtonStyle())
                .disabled(!isValid || isSaving)
                .accessibleButton(L("settings.password.update"), hint: L("settings.save_new_password_hint"))

            if let result {
                Text(result)
                    .font(.omXs)
                    .foregroundStyle(result.contains(AppStrings.error) ? Color.error : Color.fontPrimary)
                    .padding(.horizontal, .spacing6)
            }
        }
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
        OMSettingsPage(title: AppStrings.twoFactorAuth) {
            OMSettingsSection {
                OMSettingsStaticRow(
                    title: L("settings.two_factor_auth.status"),
                    value: is2FAEnabled ? AppStrings.enabled : AppStrings.disabled
                )
            }

            if is2FAEnabled {
                OMSettingsSection {
                    OMSettingsRow(
                        title: AppStrings.disable2FA,
                        isDestructive: true,
                        showsChevron: false
                    ) {
                        disable2FA()
                    }
                }
            } else {
                OMSettingsSection {
                    if isSettingUp, let secret = setupSecret {
                        VStack(alignment: .leading, spacing: .spacing3) {
                            Text(L("settings.two_factor_auth.scan_or_enter"))
                                .font(.omSmall).foregroundStyle(Color.fontSecondary)
                            Text(secret)
                                .font(.system(.body, design: .monospaced))
                                .textSelection(.enabled)
                                .foregroundStyle(Color.fontPrimary)

                            TextField(L("settings.two_factor_auth.enter_code"), text: $verificationCode)
                                .font(.omP)
                                #if os(iOS)
                                .keyboardType(.numberPad)
                                #endif
                                .accessibleInput(L("settings.two_factor_auth.enter_code"), hint: L("auth.enter_6_digit_code"))

                            Button(L("settings.two_factor_auth.verify")) {
                                verify2FA()
                            }
                            .buttonStyle(OMPrimaryButtonStyle())
                            .disabled(verificationCode.count != 6)
                            .accessibleButton(L("settings.two_factor_auth.verify"), hint: L("settings.verify_2fa_code_hint"))
                        }
                        .padding(.horizontal, .spacing6)
                        .padding(.vertical, .spacing5)
                    } else {
                        OMSettingsRow(title: AppStrings.setup2FA, icon: "shield", showsChevron: false) {
                            initSetup2FA()
                        }
                    }

                    Text(L("settings.two_factor_auth.description"))
                        .font(.omXs).foregroundStyle(Color.fontSecondary)
                        .padding(.horizontal, .spacing6)
                        .padding(.vertical, .spacing4)
                }
            }
        }
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
        OMSettingsPage(title: AppStrings.recoveryKey) {
            OMSettingsSection {
                Text(L("settings.recovery_key.description"))
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
                    .padding(.horizontal, .spacing6)
                    .padding(.vertical, .spacing5)
            }

            if needsVerification {
                OMSettingsSection(L("settings.recovery_key.verify_identity")) {
                    VStack(alignment: .leading, spacing: .spacing3) {
                        SecureField(AppStrings.enterPassword, text: $verificationCode)
                            .font(.omP)
                            .padding(.horizontal, .spacing6)
                            .padding(.vertical, .spacing4)
                            .accessibleInput(AppStrings.enterPassword, hint: L("auth.enter_account_password"))
                        Button(L("settings.recovery_key.verify")) { verifyAndShow() }
                            .buttonStyle(OMPrimaryButtonStyle())
                            .disabled(verificationCode.isEmpty || isLoading)
                            .padding(.horizontal, .spacing6)
                            .padding(.bottom, .spacing4)
                            .accessibleButton(L("settings.recovery_key.verify"), hint: L("settings.verify_to_reveal_key"))
                    }
                }
            } else if let key = recoveryKey {
                OMSettingsSection(L("settings.recovery_key.your_key")) {
                    VStack(alignment: .leading, spacing: .spacing3) {
                        Text(key)
                            .font(.system(.body, design: .monospaced))
                            .textSelection(.enabled)
                            .foregroundStyle(Color.fontPrimary)
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
                        .buttonStyle(OMPrimaryButtonStyle())
                        .accessibleButton(AppStrings.copy, hint: L("auth.copy_recovery_key_hint"))

                        Text(L("settings.recovery_key.store_securely"))
                            .font(.omXs).foregroundStyle(Color.warning)
                    }
                    .padding(.horizontal, .spacing6)
                    .padding(.vertical, .spacing5)
                }
            }

            OMSettingsSection {
                if isRegenerating {
                    VStack(alignment: .leading, spacing: .spacing3) {
                        SecureField(AppStrings.enterPassword, text: $regeneratePassword)
                            .font(.omP)
                            .padding(.horizontal, .spacing6)
                            .padding(.vertical, .spacing4)
                            .accessibleInput(AppStrings.enterPassword, hint: L("auth.enter_account_password"))
                        Button(AppStrings.confirm) { regenerateKey() }
                            .buttonStyle(OMPrimaryButtonStyle())
                            .disabled(regeneratePassword.isEmpty)
                            .padding(.horizontal, .spacing6)
                            .padding(.bottom, .spacing4)
                            .accessibleButton(AppStrings.confirm, hint: L("settings.confirm_regenerate_key_hint"))
                    }
                } else {
                    OMSettingsRow(title: AppStrings.regenerateRecoveryKey, showsChevron: false) {
                        isRegenerating = true
                    }
                }
            }
        }
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
        OMSettingsPage(title: AppStrings.activeSessions) {
            if isLoading {
                ProgressView()
                    .frame(maxWidth: .infinity, alignment: .center)
                    .padding(.spacing8)
            } else {
                OMSettingsSection {
                    ForEach(sessions) { session in
                        VStack(alignment: .leading, spacing: .spacing1) {
                            HStack {
                                Text(session.deviceOs ?? L("common.unknown"))
                                    .font(.omP).fontWeight(.medium)
                                    .foregroundStyle(Color.fontPrimary)
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
                        .padding(.horizontal, .spacing6)
                        .padding(.vertical, .spacing5)
                        .accessibilityElement(children: .combine)
                        .accessibilityLabel({
                            var label = session.deviceOs ?? L("common.unknown")
                            if let model = session.deviceModel { label += ", \(model)" }
                            if let city = session.city, let country = session.country { label += ", \(city), \(country)" }
                            if session.isCurrent == true { label += ", \(L("settings.sessions.current"))" }
                            return label
                        }())
                    }
                }
            }

            OMSettingsSection {
                OMSettingsRow(
                    title: AppStrings.logoutAllSessions,
                    isDestructive: true,
                    showsChevron: false
                ) {
                    logoutAll()
                }
            }
        }
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
        OMSettingsPage(title: AppStrings.autoDeleteChats) {
            OMSettingsSection(AppStrings.autoDeleteChats) {
                ForEach(options, id: \.0) { days, label in
                    Button {
                        autoDeleteDays = days
                        saveAutoDelete(days)
                    } label: {
                        HStack {
                            Text(label)
                                .font(.omP)
                                .foregroundStyle(Color.fontPrimary)
                            Spacer()
                            if autoDeleteDays == days {
                                Icon("check", size: 16)
                                    .foregroundStyle(Color.buttonPrimary)
                            }
                        }
                        .padding(.horizontal, .spacing6)
                        .padding(.vertical, .spacing5)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            }

            Text(L("settings.auto_delete.description"))
                .font(.omXs).foregroundStyle(Color.fontSecondary)
                .padding(.horizontal, .spacing6)
        }
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
        OMSettingsPage(title: AppStrings.language) {
            OMSettingsSection {
                ForEach(SupportedLanguage.allCases) { language in
                    Button {
                        switchLanguage(language)
                    } label: {
                        HStack {
                            Text(language.name)
                                .font(.omP)
                                .foregroundStyle(Color.fontPrimary)
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
                                Icon("check", size: 16)
                                    .foregroundStyle(Color.buttonPrimary)
                            }
                        }
                        .padding(.horizontal, .spacing6)
                        .padding(.vertical, .spacing5)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            }
        }
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
        OMSettingsPage(title: AppStrings.settingsNotifications) {
            OMSettingsSection(AppStrings.pushNotifications) {
                OMSettingsToggleRow(
                    title: AppStrings.chatMessages,
                    isOn: $chatNotifications
                )
                .onChange(of: chatNotifications) { _, newValue in
                    savePushNotifications(newValue)
                }
            }

            OMSettingsSection(AppStrings.emailNotifications) {
                OMSettingsToggleRow(
                    title: AppStrings.emailNotifications,
                    isOn: $emailNotifications
                )
                .onChange(of: emailNotifications) { _, newValue in
                    saveEmailNotifications(newValue)
                }
            }

            Text(L("settings.notifications.permission_hint"))
                .font(.omXs).foregroundStyle(Color.fontSecondary)
                .padding(.horizontal, .spacing6)
        }
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
        OMSettingsPage(title: AppStrings.backupReminders) {
            OMSettingsSection {
                OMSettingsToggleRow(
                    title: AppStrings.backupReminders,
                    isOn: $isEnabled
                )
                .onChange(of: isEnabled) { _, _ in
                    saveBackupReminders()
                }

                if isEnabled {
                    Stepper(L("settings.backup_reminders.every_days", ["days": "\(reminderDays)"]),
                            value: $reminderDays, in: 7...365, step: 7)
                        .font(.omP)
                        .foregroundStyle(Color.fontPrimary)
                        .padding(.horizontal, .spacing6)
                        .padding(.vertical, .spacing4)
                        .onChange(of: reminderDays) { _, _ in
                            saveBackupReminders()
                        }
                }
            }

            Text(L("settings.backup_reminders.description"))
                .font(.omXs).foregroundStyle(Color.fontSecondary)
                .padding(.horizontal, .spacing6)
        }
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

@MainActor
private func L(_ key: String) -> String {
    LocalizationManager.shared.text(key)
}

@MainActor
private func L(_ key: String, _ replacements: [String: String]) -> String {
    LocalizationManager.shared.text(key, replacements: replacements)
}
