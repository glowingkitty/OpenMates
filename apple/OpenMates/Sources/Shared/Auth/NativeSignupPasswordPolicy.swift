// Pure password validation for the private native signup implementation.
// Mirrors PasswordTopContent.svelte without UI, storage, or network effects.
// Length and confirmation use UTF-16 code units to match JavaScript strings.
// Unicode categories preserve the web's letter, ASCII digit, and special rules.
// Returns existing localization keys; callers decide when to show feedback.

enum NativeSignupPasswordPolicy {
    static let minimumLength = 10
    static let maximumLength = 60

    // Keep in sync with COMMON_PASSWORD_BLOCKLIST in
    // frontend/packages/ui/src/components/signup/steps/password/PasswordTopContent.svelte.
    static let commonPasswordBlocklist: Set<String> = [
        "password1!", "password1@", "password1#", "password123!", "password123@",
        "qwerty12345", "qwerty123!", "iloveyou123!", "letmein123!", "admin12345!",
        "welcome123!", "changeme123!", "openmates123!", "openmates2024!",
        "openmates2025!", "openmates2026!", "abcd1234!", "test1234!", "test12345!",
        "12345678", "123456789", "1234567890", "12345678910", "qwerty123",
        "qwerty1234", "qwertyuiop", "password", "password1", "password12",
        "password123", "password1234", "passw0rd", "admin123", "welcome123",
        "letmein123", "iloveyou123", "changeme123", "openmates123", "openmates2024",
        "openmates2025", "openmates2026", "abcd1234", "abc12345", "test1234",
        "test12345", "asdf1234", "zxcv1234", "aa123456", "11111111", "00000000"
    ]

    struct Validation: Equatable {
        let strengthErrorKey: String?
        let confirmationErrorKey: String?
        let isValid: Bool

        var errorKey: String? { strengthErrorKey ?? confirmationErrorKey }
    }

    static func validate(password: String, confirmation: String) -> Validation {
        // Empty inputs have no visible warning in the web component, but cannot submit.
        let strengthError = password.isEmpty ? nil : strengthErrorKey(for: password)
        let confirmationError = confirmationErrorKey(password: password, confirmation: confirmation)
        return Validation(
            strengthErrorKey: strengthError,
            confirmationErrorKey: confirmationError,
            isValid: !password.isEmpty && !confirmation.isEmpty
                && strengthError == nil && confirmationError == nil
        )
    }

    static func strengthErrorKey(for password: String) -> String? {
        let length = password.utf16.count
        if length < minimumLength { return "signup.password_too_short" }
        if length > maximumLength { return "signup.password_too_long" }
        if commonPasswordBlocklist.contains(password.lowercased()) {
            return "signup.password_too_common"
        }

        let scalars = password.unicodeScalars
        if !scalars.contains(where: isLetter) { return "signup.password_needs_letter" }
        if !scalars.contains(where: isASCIIDigit) { return "signup.password_needs_number" }
        if !scalars.contains(where: { !isLetter($0) && !isASCIIDigit($0) }) {
            return "signup.password_needs_special"
        }
        return nil
    }

    static func confirmationErrorKey(password: String, confirmation: String) -> String? {
        guard !confirmation.isEmpty else { return nil }
        // Swift String equality normalizes canonically equivalent text; JavaScript does not.
        return password.utf16.elementsEqual(confirmation.utf16)
            ? nil : "signup.passwords_do_not_match"
    }

    private static func isLetter(_ scalar: Unicode.Scalar) -> Bool {
        switch scalar.properties.generalCategory {
        case .uppercaseLetter, .lowercaseLetter, .titlecaseLetter, .modifierLetter, .otherLetter:
            return true
        default:
            return false
        }
    }

    private static func isASCIIDigit(_ scalar: Unicode.Scalar) -> Bool {
        (0x30...0x39).contains(scalar.value)
    }
}
