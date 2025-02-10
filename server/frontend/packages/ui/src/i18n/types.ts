export const SUPPORTED_LOCALES = [
    'en',
    'de',
    'ja',
    'es',
    'fr',
    'zh'] as const;
export type SupportedLocale = typeof SUPPORTED_LOCALES[number];

declare module 'svelte-i18n' {
    export type Locale = SupportedLocale;
}

export function isValidLocale(locale: string): locale is SupportedLocale {
    return SUPPORTED_LOCALES.includes(locale as SupportedLocale);
} 