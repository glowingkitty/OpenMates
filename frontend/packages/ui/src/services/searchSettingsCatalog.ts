// frontend/packages/ui/src/services/searchSettingsCatalog.ts
// Static catalog of all searchable settings pages AND app catalog entries.
// Settings catalog: enables search to find settings sub-pages and deep-link into them.
// App catalog: enables search to find apps, skills, focus modes, and memories, with deep-links.

import { appsMetadata } from "../data/appsMetadata";

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
  /**
   * Access control for this settings entry.
   * - 'public': visible to all users including unauthenticated (default)
   * - 'authenticated': only visible to logged-in users
   * - 'admin': only visible to admin users
   */
  access?: "public" | "authenticated" | "admin";
}

/**
 * A single entry in the app search catalog.
 * Represents an app, skill, focus mode, or memory field that is searchable.
 */
export interface AppCatalogEntry {
  /** The settings navigation path (e.g., "app_store/ai", "app_store/ai/skill/ask") */
  path: string;
  /** Translation key for the display label */
  nameTranslationKey: string;
  /** Translation key for description (for keyword matching) */
  descriptionTranslationKey?: string;
  /** Icon class name or image file for display */
  icon: string | null;
  /** Keywords for fuzzy matching */
  keywords: string[];
  /** The type of this entry for display grouping */
  entryType: "app" | "skill" | "focus_mode" | "memory";
  /** The app ID this entry belongs to */
  appId: string;
}

// --- Settings Catalog ---

/**
 * Complete catalog of searchable settings pages.
 * Only includes top-level and commonly-accessed sub-pages.
 * Deep transactional flows (e.g., billing/buy-credits/payment) are excluded.
 */
const SETTINGS_CATALOG: SettingsCatalogEntry[] = [
  // Privacy — requires authentication (personal data settings)
  {
    path: "privacy",
    translationKey: "settings.privacy",
    icon: "icon_privacy",
    access: "authenticated",
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
    access: "authenticated",
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
  // Usage — requires authentication (per-account statistics)
  {
    path: "usage",
    translationKey: "settings.usage",
    icon: "icon_chart",
    access: "authenticated",
    keywords: ["usage", "statistics", "stats", "nutzung"],
  },
  // Chat — requires authentication (per-account chat settings)
  {
    path: "chat",
    translationKey: "settings.chat",
    icon: "icon_chat",
    access: "authenticated",
    keywords: ["chat", "conversation", "message"],
  },
  {
    path: "chat/notifications",
    translationKey: "settings.notifications",
    icon: "icon_bell",
    access: "authenticated",
    keywords: ["notifications", "alerts", "sounds", "benachrichtigungen"],
  },
  // Billing — requires authentication (payment information)
  {
    path: "billing",
    translationKey: "settings.billing",
    icon: "icon_credit_card",
    access: "authenticated",
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
    access: "authenticated",
    keywords: ["buy credits", "purchase", "top up", "add credits", "aufladen"],
  },
  {
    path: "billing/auto-topup",
    translationKey: "settings.auto_topup",
    icon: "icon_credit_card",
    access: "authenticated",
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
    access: "authenticated",
    keywords: ["invoices", "receipts", "bills", "rechnungen"],
  },
  // Gift Cards — requires authentication (tied to user account)
  {
    path: "gift_cards",
    translationKey: "settings.gift_cards",
    icon: "icon_gift",
    access: "authenticated",
    keywords: ["gift card", "voucher", "coupon", "gutschein", "geschenkkarte"],
  },
  // App Store — requires authentication (app installations are per-account)
  {
    path: "app_store",
    translationKey: "settings.apps",
    icon: "icon_apps",
    access: "authenticated",
    keywords: [
      "apps",
      "store",
      "skills",
      "plugins",
      "extensions",
      "marketplace",
    ],
  },
  // Shared — requires authentication (shared chats are per-account)
  {
    path: "shared",
    translationKey: "settings.shared",
    icon: "icon_share",
    access: "authenticated",
    keywords: ["share", "shared", "sharing", "teilen"],
  },
  // Developers — requires authentication (API keys are per-account)
  {
    path: "developers",
    translationKey: "settings.developers",
    icon: "icon_code",
    access: "authenticated",
    keywords: ["developer", "api", "code", "integration", "entwickler"],
  },
  {
    path: "developers/api-keys",
    translationKey: "settings.api_keys",
    icon: "icon_key",
    access: "authenticated",
    keywords: ["api key", "token", "access", "authentication"],
  },
  {
    path: "developers/devices",
    translationKey: "settings.devices",
    icon: "icon_device",
    access: "authenticated",
    keywords: ["devices", "sessions", "logged in", "geräte"],
  },
  // Interface — public (theme/language can be changed by any user)
  {
    path: "interface",
    translationKey: "settings.interface",
    icon: "icon_settings",
    access: "public",
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
    access: "public",
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
  // Account — requires authentication (user account management)
  {
    path: "account",
    translationKey: "settings.account",
    icon: "icon_user",
    access: "authenticated",
    keywords: ["account", "profile", "user", "konto", "profil"],
  },
  {
    path: "account/email",
    translationKey: "settings.email",
    icon: "icon_mail",
    access: "authenticated",
    keywords: ["email", "e-mail", "mail address"],
  },
  {
    path: "account/security",
    translationKey: "settings.security",
    icon: "icon_lock",
    access: "authenticated",
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
    access: "authenticated",
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
    access: "authenticated",
    keywords: ["password", "change password", "passwort ändern"],
  },
  {
    path: "account/security/2fa",
    translationKey: "settings.two_factor_auth",
    icon: "icon_lock",
    access: "authenticated",
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
    access: "authenticated",
    keywords: ["recovery", "backup", "key", "wiederherstellung"],
  },
  {
    path: "account/export",
    translationKey: "settings.export_data",
    icon: "icon_download",
    access: "authenticated",
    keywords: ["export", "download", "gdpr", "data portability", "datenexport"],
  },
  {
    path: "account/delete",
    translationKey: "settings.delete_account",
    icon: "icon_delete",
    access: "authenticated",
    keywords: ["delete account", "remove account", "konto löschen"],
  },
  // Newsletter — requires authentication (subscription tied to user account)
  {
    path: "newsletter",
    translationKey: "settings.newsletter",
    icon: "icon_mail",
    access: "authenticated",
    keywords: ["newsletter", "subscribe", "email updates"],
  },
  // Support — public (anyone can donate/get support info)
  {
    path: "support",
    translationKey: "settings.support",
    icon: "icon_heart",
    access: "public",
    keywords: ["support", "donate", "sponsor", "unterstützen", "spenden"],
  },
  // Report Issue — public (anyone can report issues)
  {
    path: "report_issue",
    translationKey: "settings.report_issue",
    icon: "icon_flag",
    access: "public",
    keywords: [
      "report",
      "issue",
      "bug",
      "problem",
      "feedback",
      "fehler melden",
    ],
  },
  // Server — admin only (server management is restricted to admins)
  {
    path: "server",
    translationKey: "settings.server",
    icon: "icon_server",
    access: "admin",
    keywords: ["server", "admin", "system", "self-hosted"],
  },
];

/**
 * Get the complete settings search catalog.
 */
export function getSettingsSearchCatalog(): SettingsCatalogEntry[] {
  return SETTINGS_CATALOG;
}

// --- App Catalog ---

/**
 * Build the app search catalog dynamically from appsMetadata.
 * Includes apps, skills, focus modes, and memory fields, each with their own nav path.
 * This is built once per module load (static data, no auth required).
 */
function buildAppSearchCatalog(): AppCatalogEntry[] {
  const entries: AppCatalogEntry[] = [];

  for (const app of Object.values(appsMetadata)) {
    // App itself
    entries.push({
      path: `app_store/${app.id}`,
      nameTranslationKey: app.name_translation_key || `apps.${app.id}`,
      descriptionTranslationKey: app.description_translation_key,
      icon: null, // Apps use icon_image (SVG), not icon class
      keywords: ["app", app.id],
      entryType: "app",
      appId: app.id,
    });

    // Skills
    for (const skill of app.skills || []) {
      entries.push({
        path: `app_store/${app.id}/skill/${skill.id}`,
        nameTranslationKey: skill.name_translation_key,
        descriptionTranslationKey: skill.description_translation_key,
        icon: null,
        keywords: ["skill", app.id, skill.id],
        entryType: "skill",
        appId: app.id,
      });
    }

    // Focus modes
    for (const focusMode of app.focus_modes || []) {
      entries.push({
        path: `app_store/${app.id}/focus/${focusMode.id}`,
        nameTranslationKey: focusMode.name_translation_key,
        descriptionTranslationKey: focusMode.description_translation_key,
        icon: null,
        keywords: ["focus", "focus mode", app.id, focusMode.id],
        entryType: "focus_mode",
        appId: app.id,
      });
    }

    // Settings & memories
    for (const memory of app.settings_and_memories || []) {
      entries.push({
        path: `app_store/${app.id}/settings_memories/${memory.id}`,
        nameTranslationKey: memory.name_translation_key,
        descriptionTranslationKey: memory.description_translation_key,
        icon: null,
        keywords: ["memory", "memories", "settings", app.id, memory.id],
        entryType: "memory",
        appId: app.id,
      });
    }
  }

  return entries;
}

// Build catalog once at module load (appsMetadata is static build data)
let _appCatalogCache: AppCatalogEntry[] | null = null;

/**
 * Get the complete app search catalog (apps, skills, focus modes, memories).
 * Result is cached for performance.
 */
export function getAppSearchCatalog(): AppCatalogEntry[] {
  if (!_appCatalogCache) {
    _appCatalogCache = buildAppSearchCatalog();
  }
  return _appCatalogCache;
}
