// Localization manager — loads and serves translated strings from the web app's i18n JSON files.
// Supports 21 languages with on-demand loading. Falls back to English for missing keys.
// Handles RTL layout direction for Arabic and Hebrew.

import SwiftUI

@MainActor
final class LocalizationManager: ObservableObject {
    static let shared = LocalizationManager()

    @Published private(set) var currentLanguage: SupportedLanguage = .en
    @Published private(set) var isRTL: Bool = false
    @Published private(set) var isLoading: Bool = false

    private var translations: [String: Any] = [:]
    private var fallbackTranslations: [String: Any] = [:]
    private var loadedLocale: String?

    private init() {
        if let bundled = loadBundledJSON(locale: "en") {
            fallbackTranslations = bundled
            translations = bundled
            loadedLocale = "en"
        }
    }

    // MARK: - Language switching

    func setLanguage(_ language: SupportedLanguage) async {
        guard language != currentLanguage || loadedLocale != language.code else { return }
        isLoading = true

        if language.code == "en" {
            translations = fallbackTranslations
        } else {
            if let loaded = await fetchTranslations(locale: language.code) {
                translations = loaded
            } else if let bundled = loadBundledJSON(locale: language.code) {
                translations = bundled
            }
        }

        currentLanguage = language
        isRTL = language.isRTL
        loadedLocale = language.code

        UserDefaults.standard.set(language.code, forKey: "app_language")
        isLoading = false
    }

    func restoreSavedLanguage() async {
        if let saved = UserDefaults.standard.string(forKey: "app_language"),
           let language = SupportedLanguage.from(code: saved) {
            await setLanguage(language)
        }
    }

    // MARK: - Translation lookup

    func text(_ keyPath: String) -> String {
        if let value = resolveKeyPath(keyPath, in: translations) {
            return value
        }
        if let value = resolveKeyPath(keyPath, in: fallbackTranslations) {
            return value
        }
        if let alias = legacyAuthKeyAliases[keyPath] {
            if let value = resolveKeyPath(alias, in: translations) {
                return value
            }
            if let value = resolveKeyPath(alias, in: fallbackTranslations) {
                return value
            }
        }
        return keyPath
    }

    func text(_ keyPath: String, replacements: [String: String]) -> String {
        var result = text(keyPath)
        for (placeholder, value) in replacements {
            result = result.replacingOccurrences(of: "{\(placeholder)}", with: value)
        }
        return result
    }

    // MARK: - Key path resolution

    private func resolveKeyPath(_ keyPath: String, in dict: [String: Any]) -> String? {
        let components = keyPath.split(separator: ".").map(String.init)
        var current: Any = dict

        for component in components {
            guard let dict = current as? [String: Any],
                  let next = dict[component] else { return nil }
            current = next
        }

        // The web app JSON uses {"text": "..."} wrappers
        if let textDict = current as? [String: Any], let text = textDict["text"] as? String {
            return text
        }
        if let text = current as? String {
            return text
        }
        return nil
    }

    // MARK: - JSON loading

    private func loadBundledJSON(locale: String) -> [String: Any]? {
        for url in candidateTranslationURLs(locale: locale) {
            guard let data = try? Data(contentsOf: url),
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                continue
            }
            return json
        }
        return nil
    }

    private func candidateTranslationURLs(locale: String) -> [URL] {
        var urls: [URL] = []

        // 1. Bundle resource (for release builds — copied by Xcode build phase)
        if let bundled = Bundle.main.url(forResource: locale, withExtension: "json", subdirectory: "i18n") {
            urls.append(bundled)
        }
        if let flatBundled = Bundle.main.url(forResource: locale, withExtension: "json") {
            urls.append(flatBundled)
        }

        // 2. Web app generated locales (for dev/simulator — built from YML sources by npm run build:translations)
        let sourceFile = URL(fileURLWithPath: #filePath)
        let repoRoot = sourceFile
            .deletingLastPathComponent() // I18n/
            .deletingLastPathComponent() // Core/
            .deletingLastPathComponent() // Sources/
            .deletingLastPathComponent() // OpenMates/
            .deletingLastPathComponent() // apple/
        urls.append(repoRoot.appendingPathComponent("frontend/packages/ui/src/i18n/locales/\(locale).json"))

        return urls
    }

    private func fetchTranslations(locale: String) async -> [String: Any]? {
        do {
            let url = await APIClient.shared.webAppURL
                .appendingPathComponent("i18n/locales/\(locale).json")
            let (data, response) = try await URLSession.shared.data(from: url)
            guard let httpResponse = response as? HTTPURLResponse,
                  httpResponse.statusCode == 200 else { return nil }
            return try JSONSerialization.jsonObject(with: data) as? [String: Any]
        } catch {
            print("[I18n] Failed to fetch \(locale): \(error)")
            return nil
        }
    }

    private let legacyAuthKeyAliases: [String: String] = [
        "auth.create_account": "signup.create_new_account",
        "auth.cancel_signup": "signup.cancel_signup",
        "auth.lets_get_started": "signup.create_new_account",
        "auth.email": "login.email_placeholder",
        "auth.enter_account_email": "login.email_placeholder",
        "auth.choose_username_hint": "signup.enter_username",
        "auth.create_account_hint": "signup.create_new_account",
        "auth.check_your_email": "signup.you_received_a_one_time_code_via_email",
        "auth.sent_verification_code": "signup.you_received_a_one_time_code_via_email",
        "auth.verification_code": "signup.enter_one_time_code",
        "auth.enter_code_from_email": "signup.enter_one_time_code",
        "auth.verify": "common.continue",
        "auth.verify_email_hint": "signup.enter_one_time_code",
        "auth.set_a_password": "signup.create_password",
        "auth.password_min_chars": "signup.create_password",
        "auth.password": "signup.password",
        "auth.password_min_chars_hint": "signup.password_needs_number",
        "auth.confirm_password": "signup.confirm_password",
        "auth.retype_new_password": "signup.repeat_password",
        "auth.passwords_dont_match": "signup.passwords_do_not_match",
        "auth.set_password_and_continue": "signup.create_password",
        "auth.add_a_passkey": "signup.passkey_instruction_title",
        "auth.passkey_description": "signup.passkey_instruction_text",
        "auth.set_up_passkey": "signup.create_passkey",
        "auth.use_face_id_or_touch_id": "signup.passkey_info",
        "auth.skip_passkey_hint": "signup.skip_for_now",
        "auth.save_your_recovery_key": "common.recovery_key",
        "auth.recovery_key_description": "signup.recovery_key_save_description",
        "auth.recovery_key": "common.recovery_key",
        "auth.double_tap_to_select": "common.copy",
        "auth.copy_key": "common.copy",
        "auth.copy_recovery_key_hint": "common.copy",
        "auth.ive_saved_my_key": "common.continue",
        "auth.confirm_key_saved_hint": "common.continue",
        "auth.backup_codes": "login.login_with_backup_code",
        "auth.backup_codes_description": "login.backup_code_is_single_use",
        "auth.copy_all_codes": "common.copy",
        "auth.copy_all_backup_codes_hint": "common.copy",
        "auth.continue_after_saving_codes": "common.continue",
        "auth.add_credits": "common.credits",
        "auth.credits_description": "common.credits",
        "auth.opens_payment_in_browser": "common.credits",
        "auth.skip_payment_hint": "signup.skip_for_now",
        "auth.continue_with_profile_picture": "common.continue",
        "auth.skip_profile_picture_hint": "signup.skip_for_now",
        "auth.welcome_to_openmates": "signup.sign_up",
        "auth.account_ready": "signup.recovery_key_downloaded",
        "auth.get_started": "common.continue",
        "auth.open_app_hint": "common.continue",
        "auth.enter_password": "login.password_placeholder",
        "auth.forgot_password": "login.forgot_password",
        "auth.login_with_passkey": "login.login_with_passkey",
        "auth.login_with_password": "login.login_with_password_and_tfa",
        "auth.login_with_recovery_key": "login.login_with_recovery_key",
        "auth.two_factor_required": "login.check_your_2fa_app",
        "auth.invalid_credentials": "login.email_or_password_wrong",
        "auth.lookup_login_methods": "login.continue",
        "auth.passkey_login_screen": "login.login_with_passkey",
        "auth.password_login_screen": "login.password_placeholder",
        "auth.account_recovery": "login.cant_login",
        "auth.enter_recovery_key_description": "login.recovery_use_recovery_key",
        "auth.recovery_key_placeholder": "login.recoverykey_placeholder",
        "auth.enter_24_char_recovery_key": "login.recoverykey_placeholder",
        "auth.recover_account": "login.complete_reset",
        "auth.sign_in_with_recovery_key": "login.login_with_recovery_key",
        "auth.recovery_failed": "login.recovery_key_wrong",
        "auth.use_backup_code": "login.login_with_backup_code",
        "auth.enter_password_and_backup_code": "login.enter_backup_code_description",
        "auth.backup_code_format": "login.enter_backup_code",
        "auth.backup_code": "login.enter_backup_code",
        "auth.backup_code_format_hint": "login.backup_code_is_single_use",
        "auth.login_with_backup_code": "login.login_with_backup_code",
        "auth.sign_in_using_backup_code": "login.login_with_backup_code",
        "auth.login_failed_check_credentials": "login.login_failed",
        "auth.verify_this_device": "login.verify_device_passkey_button",
        "auth.verify_device_description": "login.verify_device_location_change_notice",
        "auth.six_digit_code": "login.2fa_code_placeholder",
        "auth.enter_6_digit_code_auto_submit": "login.check_your_2fa_app",
        "auth.verify_device_hint": "login.verify_device_passkey_prompt",
        "auth.verification_failed": "login.verify_device_passkey_error"
    ]
}

// MARK: - SwiftUI Environment

private struct LocalizationManagerKey: @preconcurrency EnvironmentKey {
    @MainActor static let defaultValue = LocalizationManager.shared
}

extension EnvironmentValues {
    var localization: LocalizationManager {
        get { self[LocalizationManagerKey.self] }
        set { self[LocalizationManagerKey.self] = newValue }
    }
}

// MARK: - View helper

extension View {
    func localized(_ keyPath: String) -> String {
        LocalizationManager.shared.text(keyPath)
    }
}
