// Watch-local localization bridge.
// Loads the same generated web i18n JSON resources as the iOS/macOS app while
// keeping the standalone Watch target independent from the larger AppStrings
// dependency graph. Watch views use typed WatchStrings accessors, not literals.
// Missing keys deliberately surface as key paths during development.

import Foundation

@MainActor
enum WatchLocalization {
    private static let preferredLanguage = Locale.preferredLanguages.first?
        .split(whereSeparator: { $0 == "-" || $0 == "_" }).first.map(String.init) ?? "en"
    private static let fallbackTranslations: [String: Any] = loadBundledJSON(locale: "en") ?? [:]
    private static let preferredTranslations: [String: Any] = loadBundledJSON(locale: preferredLanguage) ?? fallbackTranslations

    // These labels belong only to the compact Watch flow. Shared labels still
    // resolve from the generated web locale resources bundled with the app.
    private static let watchTranslations: [String: [String: String]] = [
        "en": [
            "settings.sessions.pair_confirm_on_iphone": "Confirm login on your iPhone",
            "settings.sessions.pair_tap_short_url": "Or tap here to login via short URL",
            "settings.sessions.pair_login_via_short_url": "Login via short URL:",
            "settings.sessions.pair_iphone_label": "iPhone",
            "settings.sessions.pair_cloud_label": "Cloud",
            "settings.sessions.pair_short_url_label": "Short URL",
            "settings.sessions.pair_self_hosted_domain_prompt": "Enter your self hosting domain",
            "settings.sessions.pair_enter_code_prompt": "Enter the code shown on your other device",
            "settings.sessions.pair_official_cloud_edition": "Tap here for Official Cloud Edition",
            "settings.sessions.pair_self_hosted_edition": "Tap here for Self Hosting Edition",
            "watch.chats.welcome_prompt": "What do you want to learn or need help with?",
            "watch.hub.in_progress": "In progress",
            "watch.hub.todo": "Todo",
            "watch.hub.backlog": "Backlog",
            "watch.hub.done": "Done",
            "watch.hub.empty_tasks": "No tasks yet",
            "watch.hub.empty_workflows": "No workflows yet",
            "watch.hub.settings_link_sent": "A link to change settings was sent to your iPhone.",
            "watch.hub.open_on_phone": "Open on iPhone",
            "watch.hub.new_on_phone": "Create on iPhone",
        ],
        "de": [
            "settings.sessions.pair_confirm_on_iphone": "Login auf deinem iPhone bestätigen",
            "settings.sessions.pair_tap_short_url": "Oder hier tippen, um dich über die Kurz-URL anzumelden",
            "settings.sessions.pair_login_via_short_url": "Anmeldung über Kurz-URL:",
            "settings.sessions.pair_iphone_label": "iPhone",
            "settings.sessions.pair_cloud_label": "Cloud",
            "settings.sessions.pair_short_url_label": "Kurz-URL",
            "settings.sessions.pair_self_hosted_domain_prompt": "Gib deine Self-Hosting-Domain ein",
            "settings.sessions.pair_enter_code_prompt": "Gib den Code von deinem anderen Gerät ein",
            "settings.sessions.pair_official_cloud_edition": "Hier für die offizielle Cloud-Edition tippen",
            "settings.sessions.pair_self_hosted_edition": "Hier für die selbst gehostete Edition tippen",
            "watch.chats.welcome_prompt": "Was möchtest du lernen oder wobei brauchst du Hilfe?",
            "watch.hub.in_progress": "In Bearbeitung",
            "watch.hub.todo": "Zu erledigen",
            "watch.hub.backlog": "Backlog",
            "watch.hub.done": "Erledigt",
            "watch.hub.empty_tasks": "Noch keine Aufgaben",
            "watch.hub.empty_workflows": "Noch keine Workflows",
            "watch.hub.settings_link_sent": "Ein Link zum Ändern der Einstellungen wurde an dein iPhone gesendet.",
            "watch.hub.open_on_phone": "Auf dem iPhone öffnen",
            "watch.hub.new_on_phone": "Auf dem iPhone erstellen",
        ],
    ]

    static func text(_ keyPath: String, replacements: [String: String] = [:]) -> String {
        var result = watchTranslations[preferredLanguage]?[keyPath]
            ?? watchTranslations["en"]?[keyPath]
            ?? resolveKeyPath(keyPath, in: preferredTranslations)
            ?? resolveKeyPath(keyPath, in: fallbackTranslations)
            ?? keyPath
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
    static var cancel: String { WatchLocalization.text("common.cancel") }
    static var clientEncrypted: String { WatchLocalization.text("embeds.stored_encrypted") }
    static var embedTapToShowDetails: String { WatchLocalization.text("embeds.tap_to_show_details") }
    static var loadingChats: String { WatchLocalization.text("activity.loading_chats") }
    static var loginFailed: String { WatchLocalization.text("login.login_failed") }
    static var messagePlaceholder: String { WatchLocalization.text("enter_message.placeholder.touch") }
    static var newChat: String { WatchLocalization.text("chat.new_chat") }
    static var noChats: String { WatchLocalization.text("activity.no_chats") }
    static var offlineBanner: String { WatchLocalization.text("notifications.connection.offline_banner") }
    static var pairWaiting: String { WatchLocalization.text("settings.sessions.pair_waiting") }
    static var pairConfirmOnIphone: String { WatchLocalization.text("settings.sessions.pair_confirm_on_iphone") }
    static var pairConfirmOnIphoneDescription: String { WatchLocalization.text("settings.sessions.pair_confirm_on_iphone_description") }
    static var pairFullURLLabel: String { WatchLocalization.text("settings.sessions.pair_full_url_label") }
    static var pairLoginWithoutIphone: String { WatchLocalization.text("settings.sessions.pair_login_without_iphone") }
    static var pairLoginViaShortURL: String { WatchLocalization.text("settings.sessions.pair_login_via_short_url") }
    static var pairIphoneLabel: String { WatchLocalization.text("settings.sessions.pair_iphone_label") }
    static var pairCloudLabel: String { WatchLocalization.text("settings.sessions.pair_cloud_label") }
    static var pairShortURLLabel: String { WatchLocalization.text("settings.sessions.pair_short_url_label") }
    static var pairSelfHostedDomainPrompt: String { WatchLocalization.text("settings.sessions.pair_self_hosted_domain_prompt") }
    static var pairEnterCodePrompt: String { WatchLocalization.text("settings.sessions.pair_enter_code_prompt") }
    static var pairOfficialCloudEdition: String { WatchLocalization.text("settings.sessions.pair_official_cloud_edition") }
    static var pairTapShortURL: String { WatchLocalization.text("settings.sessions.pair_tap_short_url") }
    static var pairSelfHostedEdition: String { WatchLocalization.text("settings.sessions.pair_self_hosted_edition") }
    static var pairSelfHostedPlaceholder: String { WatchLocalization.text("settings.sessions.pair_self_hosted_placeholder") }
    static var pairSelfHostedConnect: String { WatchLocalization.text("settings.sessions.pair_self_hosted_connect") }
    static var pairSelfHostedInvalidURL: String { WatchLocalization.text("settings.sessions.pair_self_hosted_invalid_url") }
    static var pairUseProduction: String { WatchLocalization.text("settings.sessions.pair_use_production") }
    static var pairGenerating: String { WatchLocalization.text("settings.sessions.pair_generating") }
    static var pairExpired: String { WatchLocalization.text("settings.sessions.pair_expired") }
    static var pairRefresh: String { WatchLocalization.text("settings.sessions.pair_refresh") }
    static var pairEnterPinTitle: String { WatchLocalization.text("settings.sessions.pair_enter_pin_title") }
    static var pairEnterPinDescription: String { WatchLocalization.text("settings.sessions.pair_enter_pin_description") }
    static var pairPinPlaceholder: String { WatchLocalization.text("settings.sessions.pair_pin_placeholder") }
    static var pairLoggingIn: String { WatchLocalization.text("settings.sessions.pair_logging_in") }
    static var pairPinLocked: String { WatchLocalization.text("settings.sessions.pair_pin_locked") }
    static var pendingSend: String { WatchLocalization.text("enter_message.sending") }
    static var retry: String { WatchLocalization.text("common.retry") }
    static var send: String { WatchLocalization.text("enter_message.send") }
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
