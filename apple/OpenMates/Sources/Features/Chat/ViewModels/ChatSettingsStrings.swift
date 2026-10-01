// Typed Chat Settings labels, mirrored from chat_settings.yml.
import Foundation

@MainActor
extension AppStrings {
    static var chatSettingsPlan: String { localized("chat_settings.plan") }
    static var chatSettingsSummaryEmpty: String { localized("chat_settings.summary_empty") }
    static var chatSettingsLoadingPlans: String { localized("chat_settings.loading_plans") }
    static var chatSettingsLoadingTasks: String { localized("chat_settings.loading_tasks") }
    static var chatSettingsNoPlan: String { localized("chat_settings.no_plan") }
    static var chatSettingsNoSharedPlan: String { localized("chat_settings.no_shared_plan") }
    static var chatSettingsNoTasks: String { localized("chat_settings.no_tasks") }
    static var chatSettingsNoSharedTasks: String { localized("chat_settings.no_shared_tasks") }
    static var chatSettingsCreateTask: String { localized("chat_settings.create_task") }
    static var chatSettingsCreating: String { localized("chat_settings.creating") }
    static var chatSettingsTaskTitle: String { localized("chat_settings.task_title") }
    static var chatSettingsTaskContext: String { localized("chat_settings.task_context") }
    static var chatSettingsSharedReadonly: String { localized("chat_settings.shared_readonly") }
    static var chatSettingsShareReadonly: String { localized("chat_settings.share_readonly") }
    static var chatSettingsFiles: String { localized("chat_settings.files") }
    static var chatSettingsDownloadFiles: String { localized("chat_settings.download_files") }
    static func chatSettingsDownloadableCount(_ count: Int) -> String {
        let key = count == 0 ? "chat_settings.downloadable_empty" : count == 1 ? "chat_settings.downloadable_one" : "chat_settings.downloadable_many"
        return LocalizationManager.shared.text(key, replacements: ["count": String(count)])
    }
    static var chatSettingsNoFiles: String { localized("chat_settings.no_files") }
    static var chatSettingsCommunity: String { localized("chat_settings.community") }
    static var chatSettingsCommunityDetail: String { localized("chat_settings.community_detail") }
    static var chatSettingsPassword: String { localized("chat_settings.password") }
    static var chatSettingsPasswordDetail: String { localized("chat_settings.password_detail") }
    static var chatSettingsAutoExpire: String { localized("chat_settings.auto_expire") }
    static var chatSettingsExpireDetail: String { localized("chat_settings.expire_detail") }
    static var chatSettingsShowQr: String { localized("chat_settings.show_qr") }
    static var chatSettingsHideQr: String { localized("chat_settings.hide_qr") }
    static var chatSettingsShowUrl: String { localized("chat_settings.show_url") }
    static var chatSettingsHideUrl: String { localized("chat_settings.hide_url") }
    static var chatSettingsStopSharing: String { localized("chat_settings.stop_sharing") }
    static var chatSettingsDownloadChat: String { localized("chat_settings.download_chat") }
    static var chatSettingsDownloadZip: String { localized("chat_settings.download_zip") }
    static var chatSettingsLinkUnavailable: String { localized("chat_settings.link_unavailable") }
    static var chatSettingsShortFallback: String { localized("chat_settings.short_fallback") }
    static var chatSettingsShareFailed: String { localized("chat_settings.share_failed") }
    static var chatSettingsStopFailed: String { localized("chat_settings.stop_failed") }
    static var chatSettingsPasswordInvalid: String { localized("chat_settings.password_invalid") }
    static var chatSettingsExportFailed: String { localized("chat_settings.export_failed") }
    static var chatSettingsUsageEmpty: String { localized("chat_settings.usage_empty") }
    static var chatSettingsDownloadUsage: String { localized("chat_settings.download_usage") }
    static var chatSettingsShareCreated: String { localized("chat_settings.share_created") }
    static var chatSettingsTenMinutes: String { localized("chat_settings.ten_minutes") }
    static var chatSettingsNever: String { localized("chat_settings.never") }
    static func chatSettingsProgress(_ value: Int) -> String { LocalizationManager.shared.text("chat_settings.progress", replacements: ["percent": String(value)]) }
}
