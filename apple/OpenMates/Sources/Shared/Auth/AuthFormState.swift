// Shared signup-basics state. This does not implement account creation or key setup.
import Foundation
import Combine

struct SignupBasicsForm: Equatable {
    var email = ""
    var username = ""
    var stayLoggedIn = false
    var newsletter = false
    var termsAccepted = false
    var privacyAccepted = false

    // Mirrors Basics.svelte's immediate format checks, including JS UTF-16
    // length after NFC normalization. Availability/invite checks stay server-owned.
    var emailErrorKey: String? {
        guard !email.isEmpty else { return nil }
        guard email.contains("@") else { return "signup.at_missing" }
        return email.range(of: #"\.[A-Za-z]{2,}$"#, options: .regularExpression) == nil
            ? "signup.domain_ending_missing" : nil
    }
    var usernameErrorKey: String? {
        guard !username.isEmpty else { return nil }
        let normalized = username.precomposedStringWithCanonicalMapping
        if normalized.utf16.count < 3 { return "signup.username_too_short" }
        if normalized.utf16.count > 20 { return "signup.username_too_long" }
        if normalized.range(of: #"\p{L}"#, options: .regularExpression) == nil { return "signup.password_needs_letter" }
        if normalized.range(of: #"^[\p{L}\p{M}0-9._]+$"#, options: .regularExpression) == nil { return "signup.username_invalid_chars" }
        return nil
    }
    var canSubmit: Bool {
        !email.isEmpty && emailErrorKey == nil && !email.contains(where: \.isWhitespace) &&
        !username.isEmpty && usernameErrorKey == nil && termsAccepted && privacyAccepted
    }
    mutating func suggestUsernameIfEmpty() {
        guard username.isEmpty, let at = email.firstIndex(of: "@") else { return }
        username = String(email[..<at])
            .replacingOccurrences(of: #"[^\p{L}\p{M}0-9._]"#, with: "_", options: .regularExpression)
            .replacingOccurrences(of: "_+", with: "_", options: .regularExpression)
            .trimmingCharacters(in: CharacterSet(charactersIn: "_"))
    }
}

struct SignupBasicsConfiguration: Equatable {
    let inviteCode: String?
    let language: String
    let darkmode: Bool
}

enum AuthFormError: Error, Equatable { case invalidForm, rejected }

@MainActor protocol SignupBasicsRuntime {
    func requestCode(form: SignupBasicsForm, configuration: SignupBasicsConfiguration) async throws
}

@MainActor final class SignupBasicsFormModel: ObservableObject {
    @Published var form = SignupBasicsForm()
    @Published private(set) var loading = false
    @Published private(set) var submittedForm: SignupBasicsForm?
    @Published private(set) var error: AuthFormError?
    private let runtime: (any SignupBasicsRuntime)?
    private let configuration: SignupBasicsConfiguration
    var isAvailable: Bool { runtime != nil }
    var canSubmit: Bool { isAvailable && form.canSubmit && !loading && submittedForm == nil }

    init(runtime: (any SignupBasicsRuntime)?, configuration: SignupBasicsConfiguration) {
        self.runtime = runtime
        self.configuration = configuration
    }

    @discardableResult
    func submit() async -> SignupBasicsForm? {
        guard canSubmit, let runtime else { return nil }
        // This exact accepted snapshot, including preferences, goes to the parent.
        let submitted = form
        loading = true
        error = nil
        defer { loading = false }
        do {
            try await runtime.requestCode(form: submitted, configuration: configuration)
            submittedForm = submitted
            return submitted
        } catch {
            self.error = (error as? AuthFormError) ?? .rejected
            return nil
        }
    }
}

// PasswordAndTfaOtp.svelte/handleTfaInput: six ASCII OTP digits or the visible
// XXXX-XXXX-XXXX backup format. Keep hyphens in the submitted backup payload.
enum PasswordLoginInputPolicy {
    static func sanitizedCode(_ raw: String, backup: Bool) -> String {
        if backup {
            // Keyboard/IME updates may deliver several characters at once.
            // Derive the complete grouping each time; counting only updates
            // of length four/nine misses separators during fast typing/paste.
            let characters = Array(raw.uppercased().filter {
                $0.isASCII && ($0.isLetter || $0.isNumber)
            }.prefix(12))
            var value = ""
            for (index, character) in characters.enumerated() {
                value.append(character)
                if index == 3 || index == 7 { value.append("-") }
            }
            return value
        }
        return String(raw.filter { $0.isASCII && $0.isNumber }.prefix(6))
    }
}
