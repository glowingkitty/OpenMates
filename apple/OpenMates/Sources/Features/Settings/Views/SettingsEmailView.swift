// Native encrypted email management with code verification and recent re-auth.
// Preserves the account email salt so existing password and passkey wrapping
// material remains valid, matching SettingsEmail.svelte and backend contracts.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/account/SettingsEmail.svelte
// CSS:     frontend/packages/ui/src/styles/settings.css
//          frontend/packages/ui/src/styles/fields.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import CryptoKit
import Sodium
import SwiftUI

struct SettingsEmailView: View {
    @EnvironmentObject private var authManager: AuthManager
    @State private var currentEmail = ""
    @State private var newEmail = ""
    @State private var password = ""
    @State private var verificationCode = ""
    @State private var step: Step = .requestCode
    @State private var isWorking = false
    @State private var errorMessage: String?
    @State private var successMessage: String?

    private enum Step { case requestCode, verifyCode, reauthenticate }

    private var normalizedEmail: String {
        newEmail.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }

    private var canRequest: Bool {
        normalizedEmail.contains("@") && normalizedEmail.contains(".") && normalizedEmail != currentEmail
    }

    var body: some View {
        OMSettingsPage(title: AppStrings.email) {
            OMSettingsSection(AppStrings.currentEmail, icon: "mail") {
                OMSettingsStaticRow(title: AppStrings.currentEmail, value: currentEmail)
            }

            OMSettingsSection(AppStrings.email, icon: "mail") {
                VStack(alignment: .leading, spacing: .spacing4) {
                    TextField(AppStrings.newEmailPlaceholder, text: $newEmail)
                        .textFieldStyle(OMTextFieldStyle())
                        .textContentType(.emailAddress)
                        .autocorrectionDisabled()
                        #if os(iOS)
                        .keyboardType(.emailAddress)
                        .textInputAutocapitalization(.never)
                        #endif
                        .disabled(step != .requestCode || isWorking)
                        .accessibilityIdentifier("email-change-new-email")

                    if step == .verifyCode {
                        TextField(AppStrings.verifyEmailChangeCode, text: $verificationCode)
                            .textFieldStyle(OMTextFieldStyle())
                            #if os(iOS)
                            .keyboardType(.numberPad)
                            #endif
                            .onChange(of: verificationCode) { _, value in
                                verificationCode = String(value.filter(\.isNumber).prefix(6))
                            }
                            .accessibilityIdentifier("email-change-code")
                    }

                    if step == .reauthenticate {
                        SecureField(AppStrings.enterPassword, text: $password)
                            .textFieldStyle(OMTextFieldStyle())
                            .textContentType(.password)
                            .accessibilityIdentifier("email-change-password")
                    }

                    actionButton
                }
                .padding(.spacing6)
            }

            if let successMessage { status(successMessage, color: Color.buttonPrimary) }
            if let errorMessage { status(errorMessage, color: Color.error) }
        }
        .onAppear { currentEmail = authManager.currentUser?.email ?? "" }
        .accessibilityIdentifier("settings-email-page")
    }

    @ViewBuilder
    private var actionButton: some View {
        switch step {
        case .requestCode:
            Button(AppStrings.sendEmailChangeCode) { requestCode() }
                .buttonStyle(OMPrimaryButtonStyle())
                .disabled(!canRequest || isWorking)
                .accessibilityIdentifier("email-change-request-code")
        case .verifyCode:
            Button(AppStrings.verifyEmailChangeCode) { verifyCode() }
                .buttonStyle(OMPrimaryButtonStyle())
                .disabled(verificationCode.count != 6 || isWorking)
                .accessibilityIdentifier("email-change-verify-code")
        case .reauthenticate:
            Button(AppStrings.confirmEmailChange) { confirmChange() }
                .buttonStyle(OMPrimaryButtonStyle())
                .disabled(password.isEmpty || isWorking)
                .accessibilityIdentifier("email-change-confirm")
        }
    }

    private func requestCode() {
        run {
            let response: ActionResponse = try await APIClient.shared.request(
                .post,
                path: "/v1/settings/user/email/request-change-code",
                body: ["new_email": normalizedEmail]
            )
            guard response.success else { throw AccountSecurityError.server(response.message) }
            step = .verifyCode
            successMessage = AppStrings.emailChangeCodeSent
        }
    }

    private func verifyCode() {
        run {
            let response: ActionResponse = try await APIClient.shared.request(
                .post,
                path: "/v1/settings/user/email/verify-change-code",
                body: ["new_email": normalizedEmail, "code": verificationCode]
            )
            guard response.success else { throw AccountSecurityError.server(response.message) }
            step = .reauthenticate
            successMessage = AppStrings.emailChangeCodeVerified
        }
    }

    private func confirmChange() {
        run {
            guard let user = authManager.currentUser,
                  let oldEmail = user.email,
                  let saltBase64 = user.userEmailSalt,
                  let salt = Data(base64Encoded: saltBase64),
                  let masterKey = try await CryptoManager.shared.loadMasterKey(for: user.id)
            else { throw AccountSecurityError.missingAccountData }

            let hashedOldEmail = await CryptoManager.shared.hashEmail(oldEmail)
            let lookupHash = await CryptoManager.shared.hashKey(password, salt: salt)
            try await AccountSecurityService.shared.verifyPasswordReauth(
                hashedEmail: hashedOldEmail,
                lookupHash: lookupHash
            )

            let emailKey = await CryptoManager.shared.deriveEmailEncryptionKey(
                email: normalizedEmail,
                salt: salt
            )
            let sodium = Sodium()
            guard let secretBox = sodium.secretBox.seal(
                message: Array(normalizedEmail.utf8),
                secretKey: Array(emailKey)
            ) else { throw AccountSecurityError.missingAccountData }
            let encryptedWithMasterKey = try await CryptoManager.shared.encryptWithMasterKey(
                normalizedEmail,
                masterKey: masterKey
            )
            let hashedNewEmail = await CryptoManager.shared.hashEmail(normalizedEmail)
            let response: ActionResponse = try await APIClient.shared.request(
                .post,
                path: "/v1/settings/user/email/confirm-change",
                body: EmailConfirmRequest(
                    newEmail: normalizedEmail,
                    hashedEmail: hashedNewEmail,
                    encryptedEmailAddress: Data(secretBox).base64EncodedString(),
                    encryptedEmailWithMasterKey: encryptedWithMasterKey,
                    authMethod: "password",
                    authCode: ""
                )
            )
            guard response.success else { throw AccountSecurityError.server(response.message) }
            currentEmail = normalizedEmail
            newEmail = ""
            password = ""
            verificationCode = ""
            step = .requestCode
            successMessage = AppStrings.emailChangeSuccess
        }
    }

    private func run(_ operation: @escaping @MainActor () async throws -> Void) {
        isWorking = true
        errorMessage = nil
        Task {
            do {
                try await operation()
            } catch {
                errorMessage = error.localizedDescription
                NativeDiagnostics.error("Email settings operation failed", category: "settings.account")
            }
            isWorking = false
        }
    }

    private func status(_ message: String, color: Color) -> some View {
        Text(message)
            .font(.omSmall)
            .foregroundStyle(color)
            .padding(.horizontal, .spacing6)
            .accessibilityIdentifier("settings-email-status")
    }
}

private struct EmailConfirmRequest: Encodable {
    let newEmail: String
    let hashedEmail: String
    let encryptedEmailAddress: String
    let encryptedEmailWithMasterKey: String
    let authMethod: String
    let authCode: String
}
