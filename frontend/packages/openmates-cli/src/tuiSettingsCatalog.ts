import type { OpenMatesClient } from "./client.js";
import { TEAM_SETTINGS_PAGES } from "./tuiTeamsSettings.js";

export type SettingsField = {
  id: string; label: string; kind: "text" | "number" | "boolean" | "choice";
  required?: boolean; options?: readonly string[]; hint?: string;
  validate?: (value: string) => string | null;
};
export type SettingsAction = { id: string; label: string; authenticatedOnly?: boolean; confirm?: string; roles?: readonly string[]; requiredFields?: readonly string[]; run: (client: OpenMatesClient, draft: Record<string, string>) => Promise<unknown> };
export type SettingsRow = { id: string; label: string; switchTeam?: string; route?: string; field?: string; value?: string; details?: Record<string, unknown> };
export type SettingsPage = {
  route: string; title: string; parent: string | null; description?: string;
  auth?: boolean; billing?: boolean; admin?: boolean; teamRoles?: readonly string[]; webOnly?: string; webReason?: string;
  fields?: SettingsField[];
  requiresLoad?: boolean;
  load?: (client: OpenMatesClient) => Promise<unknown>;
  defaults?: (value: unknown) => Record<string, string>;
  save?: (client: OpenMatesClient, draft: Record<string, string>) => Promise<unknown>;
  saveConfirm?: string;
  saveRoles?: readonly string[];
  actions?: SettingsAction[];
  rows?: (value: unknown) => SettingsRow[];
};

const object = (value: unknown): Record<string, unknown> => value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
const string = (value: unknown) => value == null ? "" : String(value);
const bool = (value: unknown) => value === true ? "on" : "off";
const required = (label: string) => (value: string) => value.trim() ? null : `${label} is required.`;
const positive = (label: string) => (value: string) => Number.isSafeInteger(Number(value)) && Number(value) > 0 ? null : `${label} must be a positive whole number.`;
const email = (value: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value) ? null : "Enter a valid email address.";
const field = (id: string, label: string, kind: SettingsField["kind"] = "text", extras: Partial<SettingsField> = {}): SettingsField => ({ id, label, kind, ...extras });
const branch = (route: string, title: string, parent: string | null, description?: string): SettingsPage => ({ route, title, parent, description, auth: route !== "main" });
const web = (route: string, title: string, parent: string, webReason: string, billing = false): SettingsPage => ({ route, title, parent, auth: true, billing, webOnly: route, webReason });
const user = (client: OpenMatesClient) => client.whoAmI();

/** Web route names are the canonical navigation IDs; operations mirror cli.ts. */
export const SETTINGS_PAGES: readonly SettingsPage[] = [
  { ...branch("main", "Settings", null, "Account and app preferences"), actions: [{ id: "logout", label: "Log out", authenticatedOnly: true, confirm: "Log out of this CLI session?", run: (client) => client.logout() }] },
  { route: "pricing", title: "Pricing", parent: "main", webOnly: "pricing", webReason: "Plans and pricing are available in the browser." },
  branch("ai", "AI", "main"),
  branch("privacy", "Privacy", "main"),
  web("projects", "Projects", "main", "Project settings are available in the browser."),
  ...TEAM_SETTINGS_PAGES,
  branch("mates", "Mates", "main"),
  branch("billing", "Billing & Usage", "main"),
  branch("notifications", "Notifications", "main"),
  branch("interface", "Interface", "main", "These preferences affect the web app."),
  branch("account", "Account", "main"),
  branch("developers", "Developers", "main"),
  { route: "server", title: "Server", parent: "main", auth: true, admin: true, webOnly: "server", webReason: "Server administration is available in the browser or the openmates server CLI commands." },
  { route: "support", title: "Support & Community", parent: "main", webOnly: "support", webReason: "Support and community options are available in the browser." },
  { route: "newsletter", title: "Newsletter", parent: "main" },
  branch("settings_memories", "Memories", "main"),
  { route: "account/info", title: "Profile", parent: "account", auth: true, load: user },
  { route: "account/timezone", title: "Timezone", parent: "account", auth: true, load: user,
    fields: [field("timezone", "Timezone", "text", { required: true, hint: "IANA name, for example Europe/Berlin", validate: (v) => { try { new Intl.DateTimeFormat("en", { timeZone: v }); return null; } catch { return "Enter a valid IANA timezone."; } } })],
    defaults: (v) => ({ timezone: string(object(v).timezone) || "UTC" }),
    save: (c, d) => c.settingsPost("user/timezone", { timezone: d.timezone }) },
  { route: "account/interests", title: "Interests", parent: "account", auth: true,
    load: (c) => c.getTopicPreferences(), fields: [field("tags", "Interest tags", "text", { required: true, hint: "Comma separated tag IDs" })],
    defaults: (v) => ({ tags: Array.isArray(object(v).selectedTagIds) ? (object(v).selectedTagIds as string[]).join(", ") : "" }),
    save: (c, d) => c.setTopicPreferences(d.tags.split(",").map((v) => v.trim()).filter(Boolean)),
    actions: [{ id: "clear", label: "Clear interests", confirm: "Clear all account interests?", run: (c) => c.clearTopicPreferences() }] },
  { route: "account/username", title: "Username", parent: "account", auth: true, load: user,
    fields: [field("username", "Username", "text", { required: true, validate: (v) => /^[a-zA-Z0-9_]{3,30}$/.test(v) ? null : "Use 3–30 letters, numbers or underscores." })],
    defaults: (v) => ({ username: string(object(v).username) }), save: (c, d) => c.updateUsername(d.username) },
  { route: "account/storage", title: "Storage", parent: "account", auth: true, load: (c) => c.settingsGet("storage") },
  { route: "account/storage/files", title: "Stored Files", parent: "account/storage", auth: true, load: (c) => c.settingsGet("storage/files") },
  { route: "account/storage/delete-file", title: "Delete Stored File", parent: "account/storage", auth: true,
    fields: [field("file_id", "File ID", "text", { required: true })],
    actions: [{ id: "delete", label: "Delete file", confirm: "Delete this stored file permanently?", run: (c, d) => d.file_id.trim() ? c.settingsDelete("storage/files", { scope: "single", file_id: d.file_id.trim() }) : Promise.reject(new Error("Enter a file ID.")) }] },
  { route: "account/chats", title: "Chat Statistics", parent: "account", auth: true, load: (c) => c.settingsGet("chats") },
  { route: "interface/language", title: "Language", parent: "interface", auth: true, load: user, description: "Changes the web app language.",
    fields: [field("language", "Language code", "text", { required: true, validate: (v) => /^[a-z]{2}(?:-[A-Z]{2})?$/.test(v) ? null : "Use a language code such as en or de." })],
    defaults: (v) => ({ language: string(object(v).language) || "en" }), save: (c, d) => c.settingsPost("user/language", { language: d.language }) },
  { route: "interface/dark_mode", title: "Dark Mode", parent: "interface", auth: true, load: user, description: "Changes the web app theme.",
    fields: [field("enabled", "Dark mode", "boolean")], defaults: (v) => ({ enabled: bool(object(v).dark_mode) }),
    save: (c, d) => c.settingsPost("user/darkmode", { dark_mode: d.enabled === "on" }) },
  { route: "interface/font", title: "Font", parent: "interface", auth: true, load: user, description: "Changes the web app font.",
    fields: [field("font", "Font", "choice", { options: ["lexend", "figtree", "rubik", "inter", "public_sans", "atkinson", "ibm_plex_sans", "source_serif", "jetbrains_mono", "ibm_plex_mono", "system", "serif", "mono"] })],
    defaults: (v) => ({ font: string(object(v).ui_font) || "lexend" }), save: (c, d) => c.settingsPost("user/ui-font", { ui_font: d.font }) },
  { route: "ai/models", title: "Default AI Models", parent: "ai", auth: true, load: user,
    fields: [field("simple", "Simple requests", "text", { required: true, hint: "Model ID or auto" }), field("complex", "Complex requests", "text", { required: true, hint: "Model ID or auto" }), field("most_demanding", "Most demanding", "text", { required: true, hint: "Model ID or auto" })],
    defaults: (v) => { const o = object(v); return { simple: string(o.default_ai_model_simple) || "auto", complex: string(o.default_ai_model_complex) || "auto", most_demanding: string(o.default_ai_model_most_demanding) || "auto" }; },
    save: (c, d) => c.settingsPost("ai-model-defaults", { default_ai_model_simple: d.simple === "auto" ? null : d.simple, default_ai_model_complex: d.complex === "auto" ? null : d.complex, default_ai_model_most_demanding: d.most_demanding === "auto" ? null : d.most_demanding }) },
  { route: "privacy/auto-deletion/chats", title: "Delete Chats Automatically", parent: "privacy", auth: true, load: user,
    fields: [field("period", "Delete after", "choice", { options: ["30d", "60d", "90d", "6m", "1y", "2y", "5y", "never"] })],
    defaults: (v) => { const days = object(v).auto_delete_chats_after_days; return { period: days == null ? "never" : ({ 30: "30d", 60: "60d", 90: "90d", 180: "6m", 365: "1y", 730: "2y", 1825: "5y" } as Record<number, string>)[Number(days)] ?? "90d" }; },
    save: (c, d) => c.settingsPost("auto-delete-chats", { period: d.period }) },
  { route: "privacy/share-debug-logs", title: "Share Debug Logs", parent: "privacy", auth: true,
    fields: [field("duration", "Sharing duration", "choice", { options: ["1h", "24h", "7d"] })],
    actions: [{ id: "share", label: "Share debug logs", confirm: "Share diagnostic logs with support?", run: (c, d) => c.settingsPost("debug-session", { duration: d.duration || "1h" }) }] },
  { route: "billing/overview", title: "Overview", parent: "billing", auth: true, billing: true, load: (c) => c.settingsGet("billing") },
  { route: "billing/usage", title: "Usage", parent: "billing", auth: true, billing: true, load: (c) => c.settingsGet("usage/summaries") },
  { route: "billing/invoices", title: "Invoices", parent: "billing", auth: true, billing: true, load: (c) => c.listInvoices(),
    fields: [field("invoice_id", "Invoice ID for refund", "text")],
    actions: [{ id: "refund", label: "Request refund", confirm: "Request a refund for this invoice?", run: (c, d) => d.invoice_id.trim() ? c.requestRefund(d.invoice_id.trim()) : Promise.reject(new Error("Enter an invoice ID.")) }] },
  { route: "billing/bank-transfer", title: "Bank Transfer", parent: "billing", auth: true, billing: true, load: (c) => c.listBankTransferOrders(),
    fields: [field("credits", "Credits to buy", "number", { required: true, validate: positive("Credits") })],
    actions: [{ id: "create-order", label: "Create bank transfer order", confirm: "Create a bank transfer order for these credits?", run: (c, d) => c.createBankTransferOrder(Number(d.credits)) }] },
  { route: "billing/gift-cards", title: "Gift Cards", parent: "billing", auth: true, billing: true, load: (c) => c.listRedeemedGiftCards(),
    fields: [field("code", "Gift card code", "text", { required: true, validate: required("Gift card code") })],
    actions: [{ id: "redeem", label: "Redeem gift card", run: (c, d) => c.redeemGiftCard(d.code) }] },
  { route: "billing/gift-cards/bank-transfer", title: "Gift Card Bank Transfer", parent: "billing/gift-cards", auth: true, billing: true, load: (c) => c.listPurchasedGiftCards(),
    fields: [field("credits", "Gift card credits", "number", { required: true, validate: positive("Gift card credits") })],
    actions: [{ id: "create-order", label: "Create gift card order", confirm: "Create a gift card bank transfer order?", run: (c, d) => c.createGiftCardBankTransferOrder(Number(d.credits)) }] },
  { route: "billing/auto-topup/low-balance", title: "Low Balance Auto Top-up", parent: "billing", auth: true, billing: true,
    description: "The server fixes the trigger threshold at 100 credits.", requiresLoad: true, load: user,
    fields: [field("enabled", "Enabled", "boolean"), field("amount", "Credit amount", "number", { required: true, validate: (v) => Number.isSafeInteger(Number(v)) && Number(v) >= 0 ? null : "Credit amount must be a non-negative whole number." }), field("currency", "Currency", "choice", { options: ["eur", "usd"] }), field("email", "Receipt email", "text", { validate: (v) => v ? email(v) : null })],
    defaults: (v) => { const o = object(v); return { enabled: bool(o.auto_topup_low_balance_enabled ?? o.auto_topup_enabled), amount: String(o.auto_topup_low_balance_amount ?? o.auto_topup_amount ?? 0), currency: String(o.auto_topup_low_balance_currency ?? o.auto_topup_currency ?? "eur").toLowerCase(), email: String(o.email ?? "") }; },
    save: (c, d) => c.settingsPost("auto-topup/low-balance", { enabled: d.enabled === "on", threshold: 100, amount: Number(d.amount), currency: d.currency, email: d.email || undefined }) },
  { route: "notifications/chat", title: "Email Notifications", parent: "notifications", auth: true, requiresLoad: true,
    description: "Notifications use your verified account email. Enter it only if you need to confirm the address.", load: (c) => c.getEmailNotificationSettings(),
    fields: [field("enabled", "Enabled", "boolean"), field("email", "Verified email (optional)", "text", { validate: (v) => v ? email(v) : null }), field("ai", "AI responses", "boolean"), field("backup", "Backup reminder", "boolean"), field("webhook", "Webhook chats", "boolean")],
    defaults: (v) => { const o = object(v), p = object(o.preferences); return { enabled: bool(o.enabled), email: "", ai: bool(p.aiResponses), backup: bool(p.backupReminder), webhook: bool(p.webhookChats) }; },
    save: (c, d) => c.updateEmailNotificationSettings({ enabled: d.enabled === "on", ...(d.email ? { email: d.email } : {}), preferences: { aiResponses: d.ai === "on", backupReminder: d.backup === "on", webhookChats: d.webhook === "on" } }) },
  { route: "developers/api-keys", title: "API Keys", parent: "developers", auth: true, load: (c) => c.listApiKeys(),
    fields: [field("name", "New key name", "text", { required: true, validate: required("Key name") }), field("key_id", "Key ID to revoke", "text")],
    actions: [
      { id: "create", label: "Create full-access key", confirm: "Create a full-access API key with unlimited credits and no expiration? The key is shown once.", run: (c, d) => c.createApiKey({ name: d.name }) },
      { id: "revoke", label: "Revoke key ID", confirm: "Revoke this API key permanently?", run: (c, d) => d.key_id.trim() ? c.revokeApiKey(d.key_id.trim()) : Promise.reject(new Error("Enter a key ID to revoke.")) },
    ] },
  { route: "mates/consent", title: "Mate Settings Consent", parent: "mates", auth: true,
    actions: [{ id: "consent", label: "Record consent", confirm: "Record consent for mate settings?", run: (c) => c.settingsPost("user/consent/mates", { consent: true }) }] },
  { route: "newsletter/categories", title: "Newsletter Categories", parent: "newsletter", auth: true, load: (c) => c.getNewsletterCategories(),
    fields: [field("updates", "Updates", "boolean"), field("tips", "Tips", "boolean"), field("daily", "Daily inspiration", "boolean")],
    defaults: (v) => { const o = object(object(v).categories ?? v); return { updates: bool(o.updates_and_announcements), tips: bool(o.tips_and_tricks), daily: bool(o.daily_inspirations) }; },
    save: (c, d) => c.updateNewsletterCategories({ updates_and_announcements: d.updates === "on", tips_and_tricks: d.tips === "on", daily_inspirations: d.daily === "on" }) },
  { route: "newsletter/subscribe", title: "Subscribe", parent: "newsletter",
    fields: [field("email", "Email", "text", { required: true, validate: email }), field("language", "Language", "text", { required: true, validate: (v) => /^[a-z]{2}$/.test(v) ? null : "Use a two-letter language code." }), field("darkmode", "Dark newsletter", "boolean")],
    save: (c, d) => c.subscribeNewsletter(d.email, d.language, d.darkmode === "on") },
  { route: "settings_memories/list", title: "Saved Memories", parent: "settings_memories", auth: true, load: (c) => c.listMemories({ personal: true }),
    fields: [field("memory_id", "Memory ID to delete", "text")],
    actions: [{ id: "delete", label: "Delete memory", confirm: "Delete this memory permanently?", run: (c, d) => d.memory_id.trim() ? c.deleteMemory(d.memory_id.trim(), { personal: true }) : Promise.reject(new Error("Enter a memory ID.")) }] },
  web("account/email", "Email", "account", "Changing email requires browser identity verification."),
  web("account/security", "Security", "account", "Security changes need browser verification."),
  web("account/security/passkeys", "Passkeys", "account/security", "Passkeys require browser WebAuthn."),
  web("account/security/password", "Password", "account/security", "Password changes require browser reauthentication."),
  web("account/security/2fa", "Two-factor Authentication", "account/security", "Setup requires a guided browser flow."),
  web("account/security/recovery-key", "Recovery Key", "account/security", "Recovery keys are managed in the browser."),
  web("account/security/sessions", "Sessions", "account/security", "Paired session approval and revocation stay in the browser."),
  web("account/delete", "Delete Account", "account", "Account deletion requires verified codes and guided review."),
  web("account/export", "Export Account", "account", "Use the web app for guided export or the CLI command for a file export."),
  web("account/import", "Import Account", "account", "Use the web app for guided import or the CLI command for a file import."),
  web("billing/buy-credits", "Buy Credits", "billing", "Card checkout requires the browser/payment provider.", true),
  web("billing/gift-cards/buy", "Buy Gift Card", "billing/gift-cards", "Card checkout requires the browser/payment provider.", true),
  web("billing/auto-topup/monthly", "Monthly Auto Top-up", "billing", "Recurring payment setup requires the browser.", true),
  web("privacy/hide-personal-data", "Personal Data", "privacy", "Encrypted personal-data editing is available in the web app."),
  web("developers/devices", "Devices", "developers", "Device approval is available in the browser."),
  web("developers/webhooks", "Webhooks", "developers", "Webhook management is available in the browser."),
];

export const settingsPage = (route: string): SettingsPage | undefined => SETTINGS_PAGES.find((page) => page.route === route);
export function settingsChildren(route: string, options: { authenticated: boolean; restricted?: boolean; paymentEnabled: boolean; isAdmin?: boolean; teamRole?: string; features?: ReadonlySet<string> }): SettingsPage[] {
  return SETTINGS_PAGES.filter((page) => page.parent === route && (!page.auth || options.authenticated) && (!page.billing || options.paymentEnabled)
    && (!page.admin || options.isAdmin === true)
    && (!options.restricted || !["account", "settings_memories", "billing"].includes(page.route.split("/")[0]))
    && (page.route !== "pricing" || !options.authenticated)
    && (page.route !== "projects" || options.features?.has("projects") !== false)
    && (!page.route.startsWith("teams") || options.features?.has("teams") !== false)
    && (!page.teamRoles || page.teamRoles.includes(options.teamRole ?? "")));
}
