// App string keys — type-safe accessors for ALL UI strings used in the native app.
// These resolve through LocalizationManager, which loads translations from the
// web app's i18n JSON files. All keys match the web app's translation paths.
// Every user-visible string in the app must use these keys — no hardcoded English.

import Foundation

@MainActor
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
    static var confirm: String { L("common.confirm") }
    static var edit: String { L("common.edit") }
    static var add: String { L("common.add") }
    static var remove: String { L("common.remove") }
    static var enabled: String { L("common.enabled") }
    static var disabled: String { L("common.disabled") }
    static var on: String { L("common.on") }
    static var off: String { L("common.off") }
    static var yes: String { L("common.yes") }
    static var no: String { L("common.no") }
    static var ok: String { L("common.ok") }
    static var copied: String { L("common.copied") }
    static var version: String { L("common.version") }

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
    static var chatMessageInput: String { L("chat.message_input") }
    static var typeMessage: String { L("chat.type_message") }
    static var startTyping: String { L("chat.start_typing") }
    static var aiResponding: String { L("chat.ai_responding") }
    static var stopResponse: String { L("chat.stop_response") }
    static var loadEarlierMessages: String { L("chat.load_earlier") }
    static var selectChatOrNew: String { L("chat.select_or_new") }
    static var whatToHelpWith: String { L("chat.what_to_help_with") }
    static var pinnedChats: String { L("chat.pinned") }
    static var recentChats: String { L("chat.recent") }
    static var hiddenChats: String { L("chat.hidden_chats") }
    static var noHiddenChats: String { L("chat.no_hidden_chats") }
    static var unhide: String { L("chat.unhide") }
    static var renameChat: String { L("chat.rename") }
    static var chatTitle: String { L("chat.title") }
    static var conversationForked: String { L("chat.forked") }
    static var setReminder: String { L("chat.set_reminder") }
    static var chats: String { L("common.chats") }
    static var explore: String { L("common.explore") }

    // MARK: - Settings sections
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

    // MARK: - Settings - Account
    static var username: String { L("settings.account.username") }
    static var timezone: String { L("settings.account.timezone") }
    static var email: String { L("settings.account.email") }
    static var profilePicture: String { L("settings.account.profile_picture") }
    static var usage: String { L("settings.usage") }
    static var storage: String { L("settings.storage") }
    static var importChats: String { L("settings.account.import_chats") }
    static var exportData: String { L("settings.export_data") }
    static var deleteAccount: String { L("settings.delete_account") }
    static var deleteAccountWarning: String { L("settings.delete_account.warning") }
    static var deleteAccountConfirmText: String { L("settings.delete_account.confirm_text") }
    static var permanentlyDeleteAccount: String { L("settings.delete_account.confirm_button") }

    // MARK: - Settings - AI
    static var aiModelProviders: String { L("settings.ai.ai_model_providers") }
    static var defaultModels: String { L("settings.ai_ask.ai_ask_settings.default_models") }
    static var autoSelectModel: String { L("settings.ai_ask.ai_ask_settings.auto_select_model") }
    static var autoSelectDescription: String { L("settings.ai_ask.ai_ask_settings.auto_select_description") }
    static var simpleRequests: String { L("settings.ai_ask.ai_ask_settings.simple_requests") }
    static var complexRequests: String { L("settings.ai_ask.ai_ask_settings.complex_requests") }
    static var availableModels: String { L("settings.ai_ask.ai_ask_settings.available_models") }
    static var searchModels: String { L("settings.ai_ask.ai_ask_settings.search_placeholder") }
    static var availableProviders: String { L("settings.ai.available_providers") }
    static var auto: String { L("settings.ai_ask.ai_ask_settings.model_auto") }

    // MARK: - Settings - Memories
    static var memoriesTitle: String { L("settings.app_store.settings_memories.title") }
    static var noMemoriesYet: String { L("settings.app_store.settings_memories.hub_no_entries") }
    static var memoriesDescription: String { L("settings.app_store.settings_memories.section_description") }
    static var encryptionNotice: String { L("settings.app_settings_memories.encrypted_notice") }
    static var confirmDeleteMemory: String { L("settings.app_settings_memories.confirm_delete") }
    static var entries: String { L("settings.app_settings_memories.entries") }

    // MARK: - Settings - Apps
    static var showAllApps: String { L("settings.app_store.show_all_apps") }
    static var noAppsAvailable: String { L("settings.app_store.no_apps_available") }
    static var installed: String { L("settings.app_store.installed") }
    static var searchApps: String { L("settings.app_store.search_apps") }
    static var apps: String { L("settings.apps") }

    // MARK: - Settings - Security
    static var passkeys: String { L("settings.passkeys") }
    static var password: String { L("settings.password") }
    static var twoFactorAuth: String { L("settings.two_factor_auth") }
    static var recoveryKey: String { L("settings.recovery_key") }
    static var activeSessions: String { L("settings.sessions") }
    static var pairNewDevice: String { L("settings.pair_device") }
    static var logoutAllSessions: String { L("settings.logout_all") }
    static var addPasskey: String { L("settings.passkeys.add") }
    static var setup2FA: String { L("settings.two_factor_auth.setup") }
    static var disable2FA: String { L("settings.two_factor_auth.disable") }
    static var regenerateRecoveryKey: String { L("settings.recovery_key.regenerate") }

    // MARK: - Settings - Privacy
    static var hidePersonalData: String { L("settings.hide_personal_data") }
    static var autoDeleteChats: String { L("settings.auto_delete_chats") }
    static var shareDebugLogs: String { L("settings.share_debug_logs") }
    static var never: String { L("common.never") }

    // MARK: - Settings - Billing
    static var billingCredits: String { L("settings.billing.credits") }
    static var buyCredits: String { L("settings.buy_credits") }
    static var autoTopUp: String { L("settings.auto_topup") }
    static var purchaseHistory: String { L("settings.billing.purchase_history") }
    static var invoices: String { L("settings.invoices") }
    static var giftCards: String { L("settings.gift_cards") }

    // MARK: - Settings - Notifications
    static var pushNotifications: String { L("settings.notifications.push") }
    static var chatMessages: String { L("settings.notifications.chat_messages") }
    static var emailNotifications: String { L("settings.notifications.email") }
    static var backupReminders: String { L("settings.backup_reminders") }

    // MARK: - Settings - Interface
    static var theme: String { L("settings.interface.theme") }
    static var language: String { L("settings.interface.language") }
    static var systemTheme: String { L("settings.interface.theme.system") }
    static var lightTheme: String { L("settings.interface.theme.light") }
    static var darkTheme: String { L("settings.interface.theme.dark") }

    // MARK: - Settings - Developers
    static var apiKeys: String { L("settings.api_keys") }
    static var devices: String { L("settings.devices") }
    static var webhooks: String { L("settings.webhooks") }

    // MARK: - Settings - About
    static var privacyPolicy: String { L("settings.privacy_policy") }
    static var termsOfService: String { L("settings.terms_of_service") }
    static var imprint: String { L("settings.imprint") }
    static var openSource: String { L("settings.open_source") }
    static var about: String { L("common.about") }

    // MARK: - Settings - Newsletter
    static var newsletterSubscribe: String { L("settings.newsletter.subscribe") }
    static var newsletterUnsubscribe: String { L("settings.newsletter.unsubscribe") }

    // MARK: - Settings - Server (admin)
    static var serverAdmin: String { L("settings.server") }
    static var logs: String { L("settings.logs") }

    // MARK: - Auth
    static var login: String { L("header.login") }
    static var signup: String { L("header.signup") }
    static var logout: String { L("settings.logout") }
    static var logOut: String { L("settings.logout") }
    static var enterPassword: String { L("auth.enter_password") }
    static var forgotPassword: String { L("auth.forgot_password") }
    static var loginWithPasskey: String { L("auth.login_with_passkey") }
    static var loginWithPassword: String { L("auth.login_with_password") }
    static var loginWithRecoveryKey: String { L("auth.login_with_recovery_key") }
    static var twoFactorRequired: String { L("auth.two_factor_required") }
    static var invalidCredentials: String { L("auth.invalid_credentials") }

    // MARK: - Embeds
    static var voiceRecording: String { L("embed.voice_recording") }
    static var transcription: String { L("embed.transcription") }
    static var openVideo: String { L("embed.open_video") }
    static var openInBrowser: String { L("embed.open_in_browser") }
    static var loadPDF: String { L("embed.load_pdf") }
    static var decryptingPDF: String { L("embed.decrypting_pdf") }
    static var copy: String { L("common.copy") }

    // MARK: - Notifications
    static var offline: String { L("notifications.offline") }
    static var reconnecting: String { L("notifications.reconnecting") }
    static var incognitoModeOn: String { L("notifications.incognito_on") }
    static var incognitoModeOff: String { L("notifications.incognito_off") }
    static var incognitoDescription: String { L("settings.incognito.description") }

    // MARK: - Misc
    static var dailyInspiration: String { L("common.daily_inspiration") }
    static var tapToExplore: String { L("common.tap_to_explore") }
    static var report: String { L("common.report") }
    static var send: String { L("common.send") }
    static var share: String { L("common.share") }
    static var pin: String { L("common.pin") }
    static var unpin: String { L("common.unpin") }
    static var archive: String { L("common.archive") }
    static var hide: String { L("common.hide") }
    static var rename: String { L("common.rename") }
    static var stop: String { L("common.stop") }

    // MARK: - Chat banner (ChatHeader.svelte)
    static var creatingNewChat: String { L("chat.creating_new_chat") }
    static var chatHeaderJustNow: String { L("chat.header.just_now") }
    static var incognitoModeActive: String { L("settings.incognito_mode_active") }

    static func chatHeaderMinutesAgo(count: Int) -> String {
        LocalizationManager.shared.text("chat.header.minutes_ago", replacements: ["count": "\(count)"])
    }
    static func chatHeaderStartedToday(time: String) -> String {
        LocalizationManager.shared.text("chat.header.started_today", replacements: ["time": time])
    }
    static func chatHeaderStartedYesterday(time: String) -> String {
        LocalizationManager.shared.text("chat.header.started_yesterday", replacements: ["time": time])
    }
    static func chatHeaderStartedOn(date: String, time: String) -> String {
        "\(date), \(time)"
    }

    // MARK: - Demo chats
    static var demoForEveryoneTitle: String { L("demo_chats.for_everyone.title") }
    static var demoForEveryoneDescription: String { L("demo_chats.for_everyone.description") }
    static var demoForDevelopersTitle: String { L("demo_chats.for_developers.title") }
    static var demoForDevelopersDescription: String { L("demo_chats.for_developers.description") }

    // MARK: - Credits
    static func creditsAmount(_ amount: String) -> String {
        LocalizationManager.shared.text("settings.credits_amount", replacements: ["credits_amount": amount])
    }

    static func entriesCount(_ count: Int) -> String {
        "\(count) \(L("settings.app_settings_memories.entries"))"
    }

    // MARK: - Helper
    private static func L(_ key: String) -> String {
        LocalizationManager.shared.text(key)
    }
}
