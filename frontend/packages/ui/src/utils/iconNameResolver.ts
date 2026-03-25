// frontend/packages/ui/src/utils/iconNameResolver.ts
//
// Single source of truth for mapping logical icon names (used in settings UI)
// to the SVG filenames that back the --icon-url-{name} CSS variables.
//
// Used by: SettingsItem.svelte, AppDetailsHeader.svelte, validate-icon-refs.js
// Related: scripts/generate-icon-urls.js, src/styles/icon-urls.generated.css

/**
 * Maps logical icon names to their SVG filename (without .svg extension).
 * Only entries where the name differs from the filename need to be listed.
 * Names that match their SVG filename exactly (e.g. "chat" → chat.svg)
 * are resolved automatically via --icon-url-{name} CSS variables.
 */
export const ICON_NAME_MAP: Record<string, string> = {
    // Settings section names → SVG filenames
    'account': 'user',
    'apps': 'app',
    'app_store': 'app',
    'developers': 'coding',
    'gift_cards': 'gift',
    'incognito': 'anonym',
    'interface': 'language',
    'mates': 'mate',
    'messengers': 'chat',
    'newsletter': 'mail',
    'notifications': 'announcement',
    'passkeys': 'passkey',
    'pricing': 'coins',
    'privacy': 'lock',
    'recovery_key': 'warning',
    'report_issue': 'bug',
    'security': 'lock',
    'settings_memories': 'heart',
    'shared': 'share',
    'storage': 'files',
    'support': 'volunteering',
    'tfa': '2fa',
    'users': 'team',
    // Subsetting aliases
    'clock': 'time',
    'devices': 'desktop',
    'document': 'pdf',
    'email': 'mail',
    'icon_gift': 'gift',
    'icon_info': 'question',
    'info': 'question',
    'key': 'security_key',
    'low_balance': 'coins',
    'secrets': 'lock',
    // Icon names that don't match SVG filenames
    'api-keys': 'coding',
    'app-ai': 'ai',
    'dark_mode': 'darkmode',
    'focus': 'search',
    'light_mode': 'darkmode',
    'link': 'web',
    'notification': 'announcement',
    'profile-picture': 'user',
    'shield': 'lock',
    'username': 'user',
};

/**
 * Resolves an icon name to the CSS variable name for its SVG URL.
 * Strips the legacy "subsetting_icon " prefix if present, then maps through ICON_NAME_MAP.
 */
export function resolveIconName(name: string): string {
    const clean = name.startsWith('subsetting_icon ') ? name.slice('subsetting_icon '.length) : name;
    return ICON_NAME_MAP[clean] || clean;
}
