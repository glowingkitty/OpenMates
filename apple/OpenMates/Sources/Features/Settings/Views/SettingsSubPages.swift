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
import CryptoKit
import Security

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
    var body: some View {
        BillingUsageView()
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
    @EnvironmentObject private var authManager: AuthManager
    @State private var passkeys: [PasskeyRecord] = []
    @State private var deviceNames: [String: String] = [:]
    @State private var isLoading = true
    @State private var isAddingPasskey = false
    @State private var pendingDeletion: PasskeyRecord?
    @State private var statusMessage: String?
    @State private var errorMessage: String?

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
                            Text(deviceNames[passkey.id] ?? AppStrings.passkeyUnknownDevice)
                                .font(.omP).fontWeight(.medium)
                                .foregroundStyle(Color.fontPrimary)
                            if let created = passkey.registeredAt {
                                Text(AppStrings.passkeyAdded(String(created.prefix(10))))
                                    .font(.omXs).foregroundStyle(Color.fontTertiary)
                            }
                            if let lastUsed = passkey.lastUsedAt {
                                Text(AppStrings.passkeyLastUsed(String(lastUsed.prefix(10))))
                                    .font(.omXs).foregroundStyle(Color.fontTertiary)
                            }
                        }
                        .padding(.horizontal, .spacing6)
                        .padding(.vertical, .spacing5)
                        OMSettingsRow(
                            title: AppStrings.remove,
                            icon: "trash",
                            isDestructive: true,
                            showsChevron: false,
                            accessibilityIdentifier: "settings-passkey-remove-\(passkey.id)"
                        ) {
                            pendingDeletion = passkey
                        }
                    }
                }
            }

            OMSettingsSection {
                OMSettingsRow(title: AppStrings.addPasskey, icon: "plus", showsChevron: false) {
                    addPasskey()
                }
                .accessibilityIdentifier("settings-passkey-add")
            }

            if let statusMessage {
                settingsStatus(statusMessage, color: Color.buttonPrimary)
            }
            if let errorMessage {
                settingsStatus(errorMessage, color: Color.error)
            }
        }
        .task { await loadPasskeys() }
        .overlay {
            if let pendingDeletion {
                OMConfirmDialog(
                    title: AppStrings.passkeyDeleteTitle,
                    message: AppStrings.passkeyDeleteDescription,
                    confirmTitle: AppStrings.delete,
                    isDestructive: true,
                    onConfirm: {
                        self.pendingDeletion = nil
                        deletePasskey(id: pendingDeletion.id)
                    },
                    onCancel: { self.pendingDeletion = nil }
                )
            }
        }
    }

    private func loadPasskeys() async {
        isLoading = true
        errorMessage = nil
        do {
            let loaded = try await AccountSecurityService.shared.passkeys()
            var decryptedNames: [String: String] = [:]
            if let user = authManager.currentUser,
               let masterKey = try await CryptoManager.shared.loadMasterKey(for: user.id) {
                for passkey in loaded {
                    guard let encryptedName = passkey.encryptedDeviceName else { continue }
                    do {
                        decryptedNames[passkey.id] = try await CryptoManager.shared.decryptContent(
                            base64String: encryptedName,
                            key: masterKey
                        )
                    } catch {
                        NativeDiagnostics.warning("Could not decrypt passkey device name", category: "settings.security")
                    }
                }
            }
            passkeys = loaded
            deviceNames = decryptedNames
        } catch {
            errorMessage = error.localizedDescription
            NativeDiagnostics.error("Passkey inventory request failed", category: "settings.security")
        }
        isLoading = false
    }

    private func addPasskey() {
        isAddingPasskey = true
        errorMessage = nil
        statusMessage = nil
        Task {
            do {
                guard let user = authManager.currentUser else {
                    throw AccountSecurityError.missingAccountData
                }
                try await PasskeyRegistrationCoordinator.register(
                    user: user,
                    deviceName: nativeDeviceName
                )
                statusMessage = AppStrings.passkeyAddedSuccessfully
                await loadPasskeys()
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("Passkey registration failed", category: "settings.security")
            }
            isAddingPasskey = false
        }
    }

    private func deletePasskey(id: String) {
        Task {
            do {
                try await AccountSecurityService.shared.deletePasskey(id: id)
                statusMessage = AppStrings.passkeyDeletedSuccessfully
                await loadPasskeys()
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("Passkey deletion failed", category: "settings.security")
            }
        }
    }

    private var nativeDeviceName: String {
        #if os(iOS)
        UIDevice.current.name
        #elseif os(macOS)
        Host.current().localizedName ?? AppStrings.passkeyUnknownDevice
        #endif
    }

    private func settingsStatus(_ message: String, color: Color) -> some View {
        Text(message)
            .font(.omSmall)
            .foregroundStyle(color)
            .padding(.horizontal, .spacing6)
            .accessibilityIdentifier("settings-passkeys-status")
    }
}

// MARK: - Password

struct SettingsPasswordView: View {
    @EnvironmentObject private var authManager: AuthManager
    @State private var currentPassword = ""
    @State private var newPassword = ""
    @State private var confirmPassword = ""
    @State private var isSaving = false
    @State private var result: String?
    @State private var hasPassword = true

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
        .task { await loadAuthMethods() }
    }

    private func updatePassword() {
        isSaving = true
        result = nil
        Task {
            do {
                guard let user = authManager.currentUser,
                      let email = user.email,
                      let emailSaltBase64 = user.userEmailSalt,
                      let emailSalt = Data(base64Encoded: emailSaltBase64),
                      let masterKey = try await CryptoManager.shared.loadMasterKey(for: user.id)
                else {
                    throw AccountSecurityError.missingAccountData
                }
                let passwordSalt = randomSalt()
                try await AccountSecurityService.shared.verifyPasswordReauth(
                    hashedEmail: await CryptoManager.shared.hashEmail(email),
                    lookupHash: await CryptoManager.shared.hashKey(currentPassword, salt: emailSalt)
                )
                let wrappingKey = await CryptoManager.shared.deriveWrappingKeyFromPassword(
                    password: newPassword,
                    salt: passwordSalt
                )
                let wrapped = try await CryptoManager.shared.encrypt(
                    masterKey.withUnsafeBytes { Data($0) },
                    using: wrappingKey
                )
                try await AccountSecurityService.shared.updatePassword(PasswordUpdateRequest(
                    hashedEmail: await CryptoManager.shared.hashEmail(email),
                    lookupHash: await CryptoManager.shared.hashKey(newPassword, salt: emailSalt),
                    encryptedMasterKey: wrapped.ciphertext.base64EncodedString(),
                    salt: passwordSalt.base64EncodedString(),
                    keyIv: wrapped.nonce.base64EncodedString(),
                    isNewPassword: !hasPassword
                ))
                result = AppStrings.success
                currentPassword = ""
                newPassword = ""
                confirmPassword = ""
                AccessibilityAnnouncement.announce(AppStrings.success)
            } catch {
                result = "\(AppStrings.error): \(error.localizedDescription)"
                AccessibilityAnnouncement.announce(error.localizedDescription)
                NativeDiagnostics.error("Password update failed", category: "settings.security")
            }
            isSaving = false
        }
    }

    private func loadAuthMethods() async {
        do {
            hasPassword = try await AccountSecurityService.shared.authMethods().hasPassword
        } catch {
            result = error.localizedDescription
            NativeDiagnostics.error("Authentication methods request failed", category: "settings.security")
        }
    }

    private func randomSalt() -> Data {
        var bytes = [UInt8](repeating: 0, count: 16)
        let status = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        precondition(status == errSecSuccess, "Secure random generation failed")
        return Data(bytes)
    }
}

// MARK: - 2FA

struct Settings2FAView: View {
    @EnvironmentObject private var authManager: AuthManager
    @State private var is2FAEnabled = false
    @State private var isLoading = true
    @State private var setupSecret: String?
    @State private var verificationCode = ""
    @State private var isSettingUp = false
    @State private var backupCodes: [String] = []
    @State private var codesStored = false
    @State private var errorMessage: String?

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
                        title: AppStrings.twoFactorChangeApp,
                        icon: "tfas",
                        showsChevron: false
                    ) {
                        initSetup2FA()
                    }
                    OMSettingsRow(
                        title: AppStrings.twoFactorResetBackupCodes,
                        icon: "key",
                        showsChevron: false
                    ) {
                        resetBackupCodes()
                    }
                }
            } else {
                OMSettingsSection {
                    if isSettingUp, let secret = setupSecret {
                        VStack(alignment: .leading, spacing: .spacing3) {
                            Text(L("settings.two_factor_auth.scan_or_enter"))
                                .font(.omSmall).foregroundStyle(Color.fontSecondary)
                            Text(secret)
                                .font(.omP.monospaced())
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

            if !backupCodes.isEmpty {
                OMSettingsSection(AppStrings.twoFactorBackupCodes) {
                    VStack(alignment: .leading, spacing: .spacing3) {
                        ForEach(backupCodes, id: \.self) { code in
                            Text(code)
                                .font(.omP.monospaced())
                                .textSelection(.enabled)
                        }
                        OMSettingsToggleRow(
                            title: AppStrings.twoFactorCodesStored,
                            isOn: $codesStored
                        )
                        Button(AppStrings.confirm) { confirmCodesStored() }
                            .buttonStyle(OMPrimaryButtonStyle())
                            .disabled(!codesStored)
                            .accessibilityIdentifier("settings-2fa-confirm-codes")
                    }
                    .padding(.spacing6)
                }
            }

            if let errorMessage {
                Text(errorMessage)
                    .font(.omSmall)
                    .foregroundStyle(Color.error)
                    .padding(.horizontal, .spacing6)
                    .accessibilityIdentifier("settings-2fa-error")
            }
        }
        .task { await load2FAStatus() }
    }

    private func load2FAStatus() async {
        do {
            is2FAEnabled = try await AccountSecurityService.shared.authMethods().has2Fa
        } catch {
            errorMessage = error.localizedDescription
            NativeDiagnostics.error("2FA status request failed", category: "settings.security")
        }
        isLoading = false
    }

    private func initSetup2FA() {
        Task {
            do {
                guard let user = authManager.currentUser,
                      let email = user.email,
                      let saltBase64 = user.userEmailSalt,
                      let salt = Data(base64Encoded: saltBase64)
                else {
                    throw AccountSecurityError.missingAccountData
                }
                let emailKey = await CryptoManager.shared.deriveEmailEncryptionKey(
                    email: email,
                    salt: salt
                )
                let response = try await AccountSecurityService.shared.initiateTwoFactor(
                    emailEncryptionKey: emailKey.base64EncodedString()
                )
                setupSecret = response.secret
                isSettingUp = true
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("2FA setup failed", category: "settings.security")
            }
        }
    }

    private func verify2FA() {
        Task {
            do {
                try await AccountSecurityService.shared.verifyTwoFactor(code: verificationCode)
                try await AccountSecurityService.shared.setTwoFactorProvider("authenticator")
                backupCodes = try await AccountSecurityService.shared.requestBackupCodes(reset: false)
                isSettingUp = false
                setupSecret = nil
                verificationCode = ""
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("2FA verification failed", category: "settings.security")
            }
        }
    }

    private func resetBackupCodes() {
        Task {
            do {
                backupCodes = try await AccountSecurityService.shared.requestBackupCodes(reset: true)
                codesStored = false
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("Backup-code reset failed", category: "settings.security")
            }
        }
    }

    private func confirmCodesStored() {
        Task {
            do {
                try await AccountSecurityService.shared.confirmBackupCodesStored()
                backupCodes = []
                codesStored = false
                is2FAEnabled = true
                AccessibilityAnnouncement.announce(AppStrings.success)
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("Backup-code confirmation failed", category: "settings.security")
            }
        }
    }
}

// MARK: - Recovery Key

struct SettingsRecoveryKeyView: View {
    @EnvironmentObject private var authManager: AuthManager
    @State private var recoveryKey: String?
    @State private var isLoading = false
    @State private var verificationCode = ""
    @State private var needsVerification = true
    @State private var isRegenerating = false
    @State private var regeneratePassword = ""
    @State private var errorMessage: String?

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
                            .font(.omP.monospaced())
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

            if let errorMessage {
                Text(errorMessage)
                    .font(.omSmall)
                    .foregroundStyle(Color.error)
                    .padding(.horizontal, .spacing6)
                    .accessibilityIdentifier("settings-recovery-key-error")
            }
        }
    }

    private func verifyAndShow() {
        isLoading = true
        Task {
            do {
                try await createAndStoreRecoveryKey(authSecret: verificationCode)
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("Recovery-key creation failed", category: "settings.security")
            }
            isLoading = false
        }
    }

    private func regenerateKey() {
        Task {
            do {
                try await createAndStoreRecoveryKey(authSecret: regeneratePassword)
                isRegenerating = false
                regeneratePassword = ""
                ToastManager.shared.show(AppStrings.success, type: .success)
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("Recovery-key regeneration failed", category: "settings.security")
            }
        }
    }

    private func createAndStoreRecoveryKey(authSecret: String) async throws {
        guard !authSecret.isEmpty,
              let user = authManager.currentUser,
              let email = user.email,
              let emailSaltBase64 = user.userEmailSalt,
              let emailSalt = Data(base64Encoded: emailSaltBase64),
              let masterKey = try await CryptoManager.shared.loadMasterKey(for: user.id)
        else {
            throw AccountSecurityError.missingAccountData
        }
        try await AccountSecurityService.shared.verifyPasswordReauth(
            hashedEmail: await CryptoManager.shared.hashEmail(email),
            lookupHash: await CryptoManager.shared.hashKey(authSecret, salt: emailSalt)
        )
        let key = secureRecoveryKey()
        let wrappingSalt = randomBytes(count: 16)
        let wrappingKey = await CryptoManager.shared.deriveWrappingKeyFromPassword(
            password: key,
            salt: wrappingSalt
        )
        let wrapped = try await CryptoManager.shared.encrypt(
            masterKey.withUnsafeBytes { Data($0) },
            using: wrappingKey
        )
        try await AccountSecurityService.shared.regenerateRecoveryKey(RecoveryKeyUpdateRequest(
            newLookupHash: await CryptoManager.shared.hashKey(key, salt: emailSalt),
            newWrappedMasterKey: wrapped.ciphertext.base64EncodedString(),
            newKeyIv: wrapped.nonce.base64EncodedString(),
            newSalt: wrappingSalt.base64EncodedString()
        ))
        recoveryKey = key
        needsVerification = false
        verificationCode = ""
        errorMessage = nil
    }

    private func secureRecoveryKey() -> String {
        randomBytes(count: 32).base64URLEncodedString()
    }

    private func randomBytes(count: Int) -> Data {
        var bytes = [UInt8](repeating: 0, count: count)
        let status = SecRandomCopyBytes(kSecRandomDefault, count, &bytes)
        precondition(status == errSecSuccess, "Secure random generation failed")
        return Data(bytes)
    }
}

// MARK: - Sessions

struct SettingsSessionsView: View {
    @EnvironmentObject private var authManager: AuthManager
    @State private var sessions: [AccountSession] = []
    @State private var isLoading = true
    @State private var errorMessage: String?
    @State private var sessionNames: [String: String] = [:]
    @State private var pendingSession: AccountSession?
    @State private var confirmation: Confirmation?

    private enum Confirmation { case logoutOthers, logoutAll }

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
                                Text(sessionNames[session.id] ?? session.deviceName ?? AppStrings.passkeyUnknownDevice)
                                    .font(.omP).fontWeight(.medium)
                                    .foregroundStyle(Color.fontPrimary)
                                if session.isCurrent {
                                    Text(L("settings.sessions.current"))
                                        .font(.omTiny).fontWeight(.bold)
                                        .foregroundStyle(.white)
                                        .padding(.horizontal, .spacing2)
                                        .padding(.vertical, 2)
                                        .background(Color.buttonPrimary)
                                        .clipShape(RoundedRectangle(cornerRadius: .radius1))
                                }
                            }
                            HStack(spacing: .spacing3) {
                                if let city = session.city, let country = session.countryCode {
                                    Text("\(city), \(country)").font(.omXs).foregroundStyle(Color.fontTertiary)
                                }
                                Text(Date(timeIntervalSince1970: TimeInterval(session.createdAt)).formatted())
                                    .font(.omXs).foregroundStyle(Color.fontTertiary)
                            }
                        }
                        .padding(.horizontal, .spacing6)
                        .padding(.vertical, .spacing5)
                        .accessibilityElement(children: .combine)
                        .accessibilityLabel({
                            var label = sessionNames[session.id] ?? session.deviceName ?? AppStrings.passkeyUnknownDevice
                            if let city = session.city, let country = session.countryCode { label += ", \(city), \(country)" }
                            if session.isCurrent { label += ", \(L("settings.sessions.current"))" }
                            return label
                        }())
                        if !session.isCurrent {
                            OMSettingsRow(
                                title: AppStrings.sessionRemove,
                                icon: "trash",
                                isDestructive: true,
                                showsChevron: false,
                                accessibilityIdentifier: "settings-session-remove-\(session.id)"
                            ) { pendingSession = session }
                        }
                    }
                }
            }

            OMSettingsSection {
                OMSettingsRow(
                    title: AppStrings.sessionLogoutOthers,
                    isDestructive: true,
                    showsChevron: false
                ) { confirmation = .logoutOthers }
                OMSettingsRow(
                    title: AppStrings.logoutAllSessions,
                    isDestructive: true,
                    showsChevron: false
                ) { confirmation = .logoutAll }
            }

            if let errorMessage {
                Text(errorMessage)
                    .font(.omSmall)
                    .foregroundStyle(Color.error)
                    .padding(.horizontal, .spacing6)
            }
        }
        .task { await loadSessions() }
        .overlay { confirmationOverlay }
    }

    private func loadSessions() async {
        isLoading = true
        errorMessage = nil
        do {
            let loaded = try await AccountSecurityService.shared.sessions()
            sessions = loaded
            sessionNames = await decryptSessionNames(loaded)
        } catch {
            errorMessage = error.localizedDescription
            NativeDiagnostics.error("Session inventory request failed", category: "settings.security")
        }
        isLoading = false
    }

    private func logoutAll() {
        Task {
            do {
                try await AccountSecurityService.shared.logoutAllDevices()
                await authManager.logout()
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("Logout-all request failed", category: "settings.security")
            }
        }
    }

    private func logoutOthers() {
        Task {
            do {
                try await AccountSecurityService.shared.logoutOtherSessions()
                await loadSessions()
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("Logout-other-sessions request failed", category: "settings.security")
            }
        }
    }

    private func revoke(_ session: AccountSession) {
        Task {
            do {
                try await AccountSecurityService.shared.revokeSession(id: session.id)
                await loadSessions()
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("Session revocation failed", category: "settings.security")
            }
        }
    }

    @ViewBuilder
    private var confirmationOverlay: some View {
        if let pendingSession {
            OMConfirmDialog(
                title: AppStrings.sessionRemove,
                message: AppStrings.sessionConfirmRemove,
                confirmTitle: AppStrings.remove,
                isDestructive: true,
                onConfirm: { self.pendingSession = nil; revoke(pendingSession) },
                onCancel: { self.pendingSession = nil }
            )
        } else if confirmation == .logoutOthers {
            OMConfirmDialog(
                title: AppStrings.sessionLogoutOthers,
                message: AppStrings.sessionConfirmLogoutOthers,
                confirmTitle: AppStrings.confirm,
                isDestructive: true,
                onConfirm: { confirmation = nil; logoutOthers() },
                onCancel: { confirmation = nil }
            )
        } else if confirmation == .logoutAll {
            OMConfirmDialog(
                title: AppStrings.logoutAllSessions,
                message: AppStrings.sessionConfirmLogoutAll,
                confirmTitle: AppStrings.confirm,
                isDestructive: true,
                onConfirm: { confirmation = nil; logoutAll() },
                onCancel: { confirmation = nil }
            )
        }
    }

    private func decryptSessionNames(_ values: [AccountSession]) async -> [String: String] {
        guard let user = authManager.currentUser else { return [:] }
        let masterKey: SymmetricKey
        do {
            guard let loadedKey = try await CryptoManager.shared.loadMasterKey(for: user.id) else { return [:] }
            masterKey = loadedKey
        } catch {
            NativeDiagnostics.error("Session metadata key load failed", category: "settings.security")
            return [:]
        }
        var names: [String: String] = [:]
        for session in values {
            guard let encrypted = session.encryptedMeta else { continue }
            do {
                let json = try await CryptoManager.shared.decryptContent(base64String: encrypted, key: masterKey)
                guard let data = json.data(using: .utf8) else { continue }
                let decoder = JSONDecoder()
                decoder.keyDecodingStrategy = .convertFromSnakeCase
                let metadata = try decoder.decode(SessionMetadata.self, from: data)
                names[session.id] = metadata.deviceName
            } catch {
                NativeDiagnostics.warning("Could not decrypt session metadata", category: "settings.security")
            }
        }
        return names
    }

    private struct SessionMetadata: Decodable { let deviceName: String? }
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
                                    .accessibilityIdentifier("settings-language-option-\(language.code)-selected")
                            }
                        }
                        .padding(.horizontal, .spacing6)
                        .padding(.vertical, .spacing5)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("settings-language-option-\(language.code)")
                }
            }
        }
        .accessibilityIdentifier("settings-language-page")
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
