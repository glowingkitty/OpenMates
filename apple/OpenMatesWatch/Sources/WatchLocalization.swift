// Watch-local localization bridge.
// Loads the same generated web i18n JSON resources as the iOS/macOS app while
// keeping the standalone Watch target independent from the larger AppStrings
// dependency graph. Watch views use typed WatchStrings accessors, not literals.
// Missing keys deliberately surface as key paths during development.

import Foundation

@MainActor
enum WatchLocalization {
    private static let fallbackTranslations: [String: Any] = loadBundledJSON(locale: "en") ?? [:]

    static func text(_ keyPath: String, replacements: [String: String] = [:]) -> String {
        var result = resolveKeyPath(keyPath, in: fallbackTranslations) ?? keyPath
        for (placeholder, value) in replacements {
            result = result.replacingOccurrences(of: "{\(placeholder)}", with: value)
        }
        return result
    }

    private static func resolveKeyPath(_ keyPath: String, in dict: [String: Any]) -> String? {
        let components = keyPath.split(separator: ".").map(String.init)
        var current: Any = dict
        for component in components {
            guard let dict = current as? [String: Any], let next = dict[component] else { return nil }
            current = next
        }
        if let wrapped = current as? [String: Any], let text = wrapped["text"] as? String {
            return text
        }
        return current as? String
    }

    private static func loadBundledJSON(locale: String) -> [String: Any]? {
        let candidates = [
            Bundle.main.url(forResource: locale, withExtension: "json", subdirectory: "i18n"),
            Bundle.main.url(forResource: locale, withExtension: "json", subdirectory: "locales"),
            Bundle.main.url(forResource: locale, withExtension: "json", subdirectory: "i18n/locales"),
            Bundle.main.url(forResource: locale, withExtension: "json"),
        ]
        for url in candidates.compactMap({ $0 }) {
            guard let data = try? Data(contentsOf: url),
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }
            return json
        }
        return nil
    }
}

@MainActor
enum WatchStrings {
    static var back: String { WatchLocalization.text("common.back") }
    static var clientEncrypted: String { WatchLocalization.text("embeds.stored_encrypted") }
    static var loadingChats: String { WatchLocalization.text("activity.loading_chats") }
    static var loginFailed: String { WatchLocalization.text("login.login_failed") }
    static var messagePlaceholder: String { WatchLocalization.text("chat.placeholder.touch") }
    static var newChat: String { WatchLocalization.text("chat.new_chat") }
    static var noChats: String { WatchLocalization.text("activity.no_chats") }
    static var offlineBanner: String { WatchLocalization.text("notifications.connection.offline_banner") }
    static var pairWaiting: String { WatchLocalization.text("settings.sessions.pair_waiting") }
    static var pairGenerating: String { WatchLocalization.text("settings.sessions.pair_generating") }
    static var pairExpired: String { WatchLocalization.text("settings.sessions.pair_expired") }
    static var pairRefresh: String { WatchLocalization.text("settings.sessions.pair_refresh") }
    static var pairEnterPinTitle: String { WatchLocalization.text("settings.sessions.pair_enter_pin_title") }
    static var pairEnterPinDescription: String { WatchLocalization.text("settings.sessions.pair_enter_pin_description") }
    static var pairPinPlaceholder: String { WatchLocalization.text("settings.sessions.pair_pin_placeholder") }
    static var pairLoggingIn: String { WatchLocalization.text("settings.sessions.pair_logging_in") }
    static var pairPinLocked: String { WatchLocalization.text("settings.sessions.pair_pin_locked") }
    static var pendingSend: String { WatchLocalization.text("chat.sending") }
    static var scanCode: String { WatchLocalization.text("settings.sessions.pair_code_label") }
    static var send: String { WatchLocalization.text("chat.send") }
    static var syncing: String { WatchLocalization.text("activity.syncing") }
    static var microphoneBlocked: String { WatchLocalization.text("enter_message.record_audio.microphone_blocked") }
    static var transcribing: String { WatchLocalization.text("app_skills.audio.transcribe.transcribing") }
    static var untitledChat: String { WatchLocalization.text("common.new_chat") }
    static var voiceRecording: String { WatchLocalization.text("app_skills.audio.transcribe.audio_recording") }
    static func recordingDuration(seconds: TimeInterval) -> String {
        let roundedSeconds = max(0, Int(seconds.rounded()))
        return "\(roundedSeconds)s"
    }
    static func pairPinError(attempts: String) -> String {
        WatchLocalization.text("settings.sessions.pair_pin_error", replacements: ["n": attempts])
    }
}
