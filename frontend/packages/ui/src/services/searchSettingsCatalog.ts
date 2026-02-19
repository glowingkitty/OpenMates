// frontend/packages/ui/src/services/searchSettingsCatalog.ts
// Static catalog of all searchable settings pages with translation keys and keyword synonyms.
// This enables the search service to match user queries against settings menu items
// and deep-link directly into the matching settings sub-page.

/**
 * A single entry in the settings search catalog.
 * Each entry represents a settings page that can be found via search.
 */
export interface SettingsCatalogEntry {
  /** The settings navigation path (passed to navigateToSettings) */
  path: string;
  /** Translation key for the display label (resolved via $text) */
  translationKey: string;
  /** Icon class name for display (e.g., 'icon_privacy') */
  icon: string | null;
  /** Additional keyword synonyms for matching (English, lowercase).
   * These help users find settings using alternative terms.
   * e.g., "dark mode" matches "interface", "password" matches "security" */
  keywords: string[];
}

/**
 * Complete catalog of searchable settings pages.
 * Only includes top-level and commonly-accessed sub-pages.
 * Deep sub-pages (e.g., billing/buy-credits/payment) are excluded
 * because they are transactional flows, not discoverable settings.
 */
const SETTINGS_CATALOG: SettingsCatalogEntry[] = [
  // Privacy
  {
    path: "privacy",
    translationKey: "settings.privacy",
    icon: "icon_privacy",
    keywords: [
      "privacy",
      "data",
      "personal",
      "anonymize",
      "hide",
      "pii",
      "datenschutz",
    ],
  },
  {
    path: "privacy/hide-personal-data",
    translationKey: "settings.hide_personal_data",
    icon: "icon_privacy",
    keywords: [
      "hide",
      "personal data",
      "anonymize",
      "name",
      "address",
      "birthday",
      "pii",
    ],
  },
  // Usage
  {
    path: "usage",
    translationKey: "settings.usage",
    icon: "icon_chart",
    keywords: ["usage", "statistics", "stats", "nutzung"],
  },
  // Chat
  {
    path: "chat",
    translationKey: "settings.chat",
    icon: "icon_chat",
    keywords: ["chat", "conversation", "message"],
  },
  {
    path: "chat/notifications",
    translationKey: "settings.notifications",
    icon: "icon_bell",
    keywords: ["notifications", "alerts", "sounds", "benachrichtigungen"],
  },
  // Billing
  {
    path: "billing",
    translationKey: "settings.billing",
    icon: "icon_credit_card",
    keywords: [
      "billing",
      "payment",
      "credits",
      "money",
      "subscription",
      "bezahlung",
      "guthaben",
    ],
  },
  {
    path: "billing/buy-credits",
    translationKey: "settings.buy_credits",
    icon: "icon_credit_card",
    keywords: ["buy credits", "purchase", "top up", "add credits", "aufladen"],
  },
  {
    path: "billing/auto-topup",
    translationKey: "settings.auto_topup",
    icon: "icon_credit_card",
    keywords: [
      "auto topup",
      "automatic",
      "recurring",
      "low balance",
      "automatisch",
    ],
  },
  {
    path: "billing/invoices",
    translationKey: "settings.invoices",
    icon: "icon_file",
    keywords: ["invoices", "receipts", "bills", "rechnungen"],
  },
  // Gift Cards
  {
    path: "gift_cards",
    translationKey: "settings.gift_cards",
    icon: "icon_gift",
    keywords: ["gift card", "voucher", "coupon", "gutschein", "geschenkkarte"],
  },
  // App Store
  {
    path: "app_store",
    translationKey: "settings.apps",
    icon: "icon_apps",
    keywords: [
      "apps",
      "store",
      "skills",
      "plugins",
      "extensions",
      "marketplace",
    ],
  },
  // Shared
  {
    path: "shared",
    translationKey: "settings.shared",
    icon: "icon_share",
    keywords: ["share", "shared", "sharing", "teilen"],
  },
  // Developers
  {
    path: "developers",
    translationKey: "settings.developers",
    icon: "icon_code",
    keywords: ["developer", "api", "code", "integration", "entwickler"],
  },
  {
    path: "developers/api-keys",
    translationKey: "settings.api_keys",
    icon: "icon_key",
    keywords: ["api key", "token", "access", "authentication"],
  },
  {
    path: "developers/devices",
    translationKey: "settings.devices",
    icon: "icon_device",
    keywords: ["devices", "sessions", "logged in", "geräte"],
  },
  // Interface
  {
    path: "interface",
    translationKey: "settings.interface",
    icon: "icon_settings",
    keywords: [
      "interface",
      "theme",
      "dark mode",
      "light mode",
      "appearance",
      "display",
      "design",
      "oberfläche",
      "dunkel",
    ],
  },
  {
    path: "interface/language",
    translationKey: "settings.language",
    icon: "icon_language",
    keywords: [
      "language",
      "locale",
      "translation",
      "sprache",
      "english",
      "german",
      "deutsch",
    ],
  },
  // Account
  {
    path: "account",
    translationKey: "settings.account",
    icon: "icon_user",
    keywords: ["account", "profile", "user", "konto", "profil"],
  },
  {
    path: "account/email",
    translationKey: "settings.email",
    icon: "icon_mail",
    keywords: ["email", "e-mail", "mail address"],
  },
  {
    path: "account/security",
    translationKey: "settings.security",
    icon: "icon_lock",
    keywords: [
      "security",
      "password",
      "passkey",
      "2fa",
      "two factor",
      "sicherheit",
      "passwort",
    ],
  },
  {
    path: "account/security/passkeys",
    translationKey: "settings.passkeys",
    icon: "icon_key",
    keywords: [
      "passkey",
      "biometric",
      "fingerprint",
      "face id",
      "webauthn",
      "fido",
    ],
  },
  {
    path: "account/security/password",
    translationKey: "settings.password",
    icon: "icon_lock",
    keywords: ["password", "change password", "passwort ändern"],
  },
  {
    path: "account/security/2fa",
    translationKey: "settings.two_factor_auth",
    icon: "icon_lock",
    keywords: [
      "2fa",
      "two factor",
      "authenticator",
      "totp",
      "otp",
      "zwei-faktor",
    ],
  },
  {
    path: "account/security/recovery-key",
    translationKey: "settings.recovery_key",
    icon: "icon_key",
    keywords: ["recovery", "backup", "key", "wiederherstellung"],
  },
  {
    path: "account/export",
    translationKey: "settings.export_data",
    icon: "icon_download",
    keywords: ["export", "download", "gdpr", "data portability", "datenexport"],
  },
  {
    path: "account/delete",
    translationKey: "settings.delete_account",
    icon: "icon_delete",
    keywords: ["delete account", "remove account", "konto löschen"],
  },
  // Newsletter
  {
    path: "newsletter",
    translationKey: "settings.newsletter",
    icon: "icon_mail",
    keywords: ["newsletter", "subscribe", "email updates"],
  },
  // Support
  {
    path: "support",
    translationKey: "settings.support",
    icon: "icon_heart",
    keywords: ["support", "donate", "sponsor", "unterstützen", "spenden"],
  },
  // Report Issue
  {
    path: "report_issue",
    translationKey: "settings.report_issue",
    icon: "icon_flag",
    keywords: [
      "report",
      "issue",
      "bug",
      "problem",
      "feedback",
      "fehler melden",
    ],
  },
  // Server (admin)
  {
    path: "server",
    translationKey: "settings.server",
    icon: "icon_server",
    keywords: ["server", "admin", "system", "self-hosted"],
  },
];

/**
 * Get the complete settings search catalog.
 * Returns the static catalog array (no runtime computation needed).
 */
export function getSettingsSearchCatalog(): SettingsCatalogEntry[] {
  return SETTINGS_CATALOG;
}
