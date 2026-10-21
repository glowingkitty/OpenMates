// Typed accessors for existing web Usage translations.
import Foundation

@MainActor
extension AppStrings {
    static var usageOpenMessage: String { localized("settings.usage.open_message") }
    static var usageOpenEmbed: String { localized("settings.usage.open_embed") }
    static var usageHistoryAvailabilityUnavailable: String { localized("settings.usage.summary_availability_unavailable") }
    static var usageLoading: String { localized("settings.usage.loading") }
    static var usageLoadError: String { localized("settings.usage.error_loading") }
    static var usageEmpty: String { localized("settings.usage.no_usage_title") }
    static var usageEmptyDay: String { localized("settings.usage.no_usage_on_day") }
    static var usageLoadMoreDays: String { localized("settings.usage.load_more_days") }
    static var usageShowMore: String { localized("settings.usage.show_more") }
    static var usageIncognito: String { localized("settings.usage.incognito_chat") }
    static var usageDeletedChat: String { localized("settings.usage.deleted_chat") }
    static var usageUnsentDraft: String { localized("settings.usage.unsent_draft") }
    static var usageAPIKeyDetails: String { localized("settings.usage.api_key_details") }
    static var usageAppActivity: String { localized("settings.usage.workflow_app_activity") }
    static var usageWorkflowRun: String { localized("settings.usage.workflow_run") }
    static var usageWorkflowTest: String { localized("settings.usage.workflow_test") }
    static var usageBenchmark: String { localized("settings.usage.benchmark") }
    static var usageContextUnavailable: String { localized("settings.usage.context_unavailable") }
    static var usageInterruptedRecording: String { localized("settings.usage.interrupted_recording") }
    static var usageStandaloneActivity: String { localized("settings.usage.standalone_app_activity") }
    static var usageAPIKeyActivity: String { localized("settings.usage.api_key_activity") }
    static var usageDeviceActivity: String { localized("settings.usage.device_activity") }
    static var usageTotalCredits: String { localized("settings.usage.total_credits_label") }
    static var usageModel: String { localized("settings.usage.model_label") }
    static var usageProvider: String { localized("settings.usage.provider_label") }
    static var usageServerProvider: String { localized("settings.usage.server_provider_label") }
    static var usageServerRegion: String { localized("settings.usage.server_region_label") }
    static var usageCreditsSystemPrompt: String { localized("settings.usage.credits_system_prompt_label") }
    static var usageCreditsHistory: String { localized("settings.usage.credits_history_label") }
    static var usageCreditsResponse: String { localized("settings.usage.credits_response_label") }
    static var usageAppSkillsHint: String { localized("settings.usage.app_skills_hint") }
    static func usageRequests(_ count: Int) -> String {
        "\(count) " + localized(count == 1 ? "settings.usage.request" : "settings.usage.requests")
    }
    static func usageStartedMinutes(_ count: Int) -> String {
        "\(count) " + localized(count == 1 ? "settings.usage.started_minute" : "settings.usage.started_minutes")
    }
    static func usageDevice(_ identifier: String) -> String {
        let key = identifier.hasPrefix("apple-ios:") ? "apple_ios_device"
            : identifier.hasPrefix("apple-macos:") ? "apple_macos_device"
            : identifier.hasPrefix("apple:") ? "apple_device" : "cli_device"
        return localized("settings.usage.\(key)")
    }
    static func usageAppName(_ id: String, translationKey: String?) -> String {
        let key = translationKey ?? "apps.\(id)"
        let value = localized(key)
        return value == key ? id : value
    }
    static func usageSkillName(_ id: String, translationKey: String?) -> String {
        guard let translationKey else { return id }
        let value = localized(translationKey)
        return value == translationKey ? id : value
    }
    static func usageDay(_ value: String) -> String {
        let parser = DateFormatter(); parser.locale = Locale(identifier: "en_US_POSIX")
        parser.dateFormat = "yyyy-MM-dd"
        guard let date = parser.date(from: value) else { return value }
        if Calendar.current.isDateInToday(date) { return localized("settings.usage.today") }
        if Calendar.current.isDateInYesterday(date) { return localized("settings.usage.yesterday") }
        let formatter = DateFormatter(); formatter.dateStyle = .medium
        return formatter.string(from: date)
    }
}
