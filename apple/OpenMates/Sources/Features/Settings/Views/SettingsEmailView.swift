// Email management — view and update the account email address.
// Mirrors the web app's account/SettingsEmail.svelte.
// Requires identity verification before changing email.

import SwiftUI

struct SettingsEmailView: View {
    @EnvironmentObject var authManager: AuthManager
    @State private var currentEmail = ""
    @State private var newEmail = ""
    @State private var password = ""
    @State private var verificationCode = ""
    @State private var step: EmailChangeStep = .enterNew
    @State private var isSaving = false
    @State private var error: String?
    @State private var success: String?

    enum EmailChangeStep {
        case enterNew
        case verifyIdentity
        case confirmCode
    }

    private var isValidEmail: Bool {
        newEmail.contains("@") && newEmail.contains(".")
    }

    var body: some View {
        Form {
            Section("Current Email") {
                HStack {
                    Text(currentEmail.isEmpty ? "Not set" : currentEmail)
                        .foregroundStyle(currentEmail.isEmpty ? Color.fontTertiary : Color.fontPrimary)
                    Spacer()
                }
            }

            switch step {
            case .enterNew:
                Section("New Email") {
                    TextField("Enter new email", text: $newEmail)
                        #if os(iOS)
                        .keyboardType(.emailAddress)
                        #endif
                        .autocorrectionDisabled()
                        #if os(iOS)
                        .textInputAutocapitalization(.never)
                        #endif
                        .textContentType(.emailAddress)

                    Button("Continue") {
                        step = .verifyIdentity
                    }
                    .disabled(!isValidEmail || newEmail == currentEmail)
                }

            case .verifyIdentity:
                Section("Verify Identity") {
                    SecureField("Enter your password", text: $password)
                        .textContentType(.password)

                    Button("Verify & Send Code") {
                        requestEmailChange()
                    }
                    .disabled(password.isEmpty || isSaving)
                }

            case .confirmCode:
                Section("Verification Code") {
                    Text("\(LocalizationManager.shared.text("settings.email.verification_code_sent")): \(newEmail)")
                        .font(.omXs).foregroundStyle(Color.fontSecondary)

                    TextField("Enter code", text: $verificationCode)
                        #if os(iOS)
                        .keyboardType(.numberPad)
                        #endif

                    Button("Confirm Email Change") {
                        confirmEmailChange()
                    }
                    .disabled(verificationCode.isEmpty || isSaving)
                }
            }

            if let error {
                Section {
                    Text(error).font(.omSmall).foregroundStyle(Color.error)
                }
            }

            if let success {
                Section {
                    Text(success).font(.omSmall).foregroundStyle(.green)
                }
            }
        }
        .navigationTitle("Email")
        .onAppear {
            currentEmail = authManager.currentUser?.email ?? ""
        }
    }

    private func requestEmailChange() {
        isSaving = true
        error = nil
        Task {
            do {
                let _: Data = try await APIClient.shared.request(
                    .post, path: "/v1/settings/user/email/request-change",
                    body: ["new_email": newEmail, "password": password]
                )
                step = .confirmCode
            } catch {
                self.error = error.localizedDescription
            }
            isSaving = false
        }
    }

    private func confirmEmailChange() {
        isSaving = true
        error = nil
        Task {
            do {
                let _: Data = try await APIClient.shared.request(
                    .post, path: "/v1/settings/user/email/confirm-change",
                    body: ["code": verificationCode]
                )
                currentEmail = newEmail
                success = "Email updated successfully"
                step = .enterNew
                newEmail = ""
                password = ""
                verificationCode = ""
            } catch {
                self.error = error.localizedDescription
            }
            isSaving = false
        }
    }
}
