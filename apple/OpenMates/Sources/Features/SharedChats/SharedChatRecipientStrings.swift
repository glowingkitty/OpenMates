// Typed localization for the encrypted share route and read-only transcript.
// Web: frontend/apps/web_app/src/routes/share/chat/[chatId]/+page.svelte
// Specification: specifications/features/chat-share-settings/specification.yml
// Assertions: chat-share-settings.shared-link-open, chat-share-settings.readonly-viewer-controls

import Foundation

extension AppStrings {
    static var sharedRecipientDecrypting: String { localized("chat_settings.recipient_decrypting") }
    static var sharedRecipientPasswordTitle: String { localized("chat_settings.recipient_password_title") }
    static var sharedRecipientPasswordDetail: String { localized("chat_settings.recipient_password_detail") }
    static var sharedRecipientPasswordPlaceholder: String { localized("chat_settings.recipient_password_placeholder") }
    static var sharedRecipientAccess: String { localized("chat_settings.recipient_access") }
    static var sharedRecipientUnavailableTitle: String { localized("chat_settings.recipient_unavailable_title") }
    static var sharedRecipientUnavailableDetail: String { localized("chat_settings.recipient_unavailable_detail") }
    static var sharedRecipientExpired: String { localized("chat_settings.recipient_expired") }
    static var sharedRecipientInvalidPassword: String { localized("chat_settings.recipient_invalid_password") }
    static var sharedRecipientShortDisabled: String { localized("chat_settings.recipient_short_disabled") }
    static var sharedRecipientLockSymbol: String { localized("chat_settings.recipient_lock_symbol") }
    static var sharedRecipientWarningSymbol: String { localized("chat_settings.recipient_warning_symbol") }
    static var sharedRecipientBadge: String { localized("chat.header.shared_chat") }
    static var sharedRecipientReadonly: String { localized("chat.read_only_shared") }
    static var sharedRecipientOlder: String { localized("chat.history.show_older_messages") }
}
