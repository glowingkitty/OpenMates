// App string keys — type-safe accessors for the most common UI strings.
// These resolve through LocalizationManager, which loads translations from the
// web app's i18n JSON files. All keys match the web app's translation paths.

import Foundation

enum AppStrings {
    // MARK: - Common
    static var settings: String { L("common.settings") }
    static var cancel: String { L("common.cancel") }
    static var save: String { L("common.save") }
    static var done: String { L("common.done") }
    static var delete: String { L("common.delete") }
    static var close: String { L("common.close") }
    static var loading: String { L("common.loading") }
    static var error: String { L("common.error") }
    static var success: String { L("common.success") }
    static var credits: String { L("common.credits") }
    static var back: String { L("common.back") }
    static var next: String { L("common.next") }
    static var skip: String { L("common.skip") }
    static var search: String { L("activity.search") }
    static var retry: String { L("common.retry") }

    // MARK: - Chat
    static var newChat: String { L("activity.new_chat") }
    static var noChats: String { L("activity.no_chats") }
    static var loadingChats: String { L("activity.loading_chats") }
    static var syncing: String { L("activity.syncing") }
    static var syncComplete: String { L("activity.sync_complete") }
    static var incognito: String { L("activity.incognito") }
    static var sendMessage: String { L("context_menu.send") }
    static var copyMessage: String { L("context_menu.copy") }
    static var editMessage: String { L("context_menu.edit") }
    static var deleteMessage: String { L("context_menu.delete") }
    static var forkConversation: String { L("context_menu.fork") }

    // MARK: - Settings
    static var settingsAccount: String { L("settings.account") }
    static var settingsAI: String { L("settings.ai") }
    static var settingsBilling: String { L("settings.billing") }
    static var settingsSecurity: String { L("settings.security") }
    static var settingsPrivacy: String { L("settings.privacy") }
    static var settingsInterface: String { L("settings.interface") }
    static var settingsNotifications: String { L("settings.notifications") }
    static var settingsDevelopers: String { L("settings.developers") }
    static var settingsSupport: String { L("settings.support") }
    static var settingsNewsletter: String { L("settings.newsletter") }
    static var settingsReportIssue: String { L("settings.report_issue") }
    static var settingsShared: String { L("settings.shared") }
    static var settingsMates: String { L("settings.mates") }
    static var settingsApps: String { L("settings.app_store") }
    static var settingsMemories: String { L("settings.settings_memories") }
    static var settingsLogout: String { L("settings.logout") }
    static var settingsIncognito: String { L("settings.incognito") }
    static var settingsPricing: String { L("settings.pricing") }

    // MARK: - Auth
    static var login: String { L("header.login") }
    static var signup: String { L("header.signup") }
    static var logout: String { L("settings.logout") }

    // MARK: - Notifications
    static var offline: String { L("notifications.offline") }
    static var reconnecting: String { L("notifications.reconnecting") }

    // MARK: - Credits
    static func creditsAmount(_ amount: String) -> String {
        LocalizationManager.shared.text("settings.credits_amount", replacements: ["credits_amount": amount])
    }

    // MARK: - Helper
    private static func L(_ key: String) -> String {
        LocalizationManager.shared.text(key)
    }
}
