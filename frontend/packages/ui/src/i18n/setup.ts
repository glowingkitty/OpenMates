import { register, init, getLocaleFromNavigator } from 'svelte-i18n';
import { browser } from '$app/environment';
import { isValidLocale } from './types';
import { LANGUAGE_CODES } from './languages';
import { waitForTranslations } from '../stores/i18n';

/**
 * Static import map for locale files - ensures Vite can statically analyze all imports
 * This is the same pattern as used in meta.ts to ensure proper bundling in production
 */
const localeImportMap: Record<string, () => Promise<any>> = {
    'en': () => import('./locales/en.json'),
    'de': () => import('./locales/de.json'),
    'zh': () => import('./locales/zh.json'),
    'es': () => import('./locales/es.json'),
    'fr': () => import('./locales/fr.json'),
    'pt': () => import('./locales/pt.json'),
    'ru': () => import('./locales/ru.json'),
    'ja': () => import('./locales/ja.json'),
    'ko': () => import('./locales/ko.json'),
    'it': () => import('./locales/it.json'),
    'tr': () => import('./locales/tr.json'),
    'vi': () => import('./locales/vi.json'),
    'id': () => import('./locales/id.json'),
    'pl': () => import('./locales/pl.json'),
    'nl': () => import('./locales/nl.json'),
    'ar': () => import('./locales/ar.json'),
    'hi': () => import('./locales/hi.json'),
    'th': () => import('./locales/th.json'),
    'sv': () => import('./locales/sv.json'),
    'cs': () => import('./locales/cs.json'),
    'fi': () => import('./locales/fi.json'),
    'hu': () => import('./locales/hu.json'),
    'ro': () => import('./locales/ro.json'),
    'el': () => import('./locales/el.json'),
    'bg': () => import('./locales/bg.json'),
    'hr': () => import('./locales/hr.json'),
    'sk': () => import('./locales/sk.json'),
    'sl': () => import('./locales/sl.json'),
    'lt': () => import('./locales/lt.json'),
    'lv': () => import('./locales/lv.json'),
    'et': () => import('./locales/et.json'),
    'ga': () => import('./locales/ga.json'),
    'mt': () => import('./locales/mt.json'),
};

/**
 * Load locale data using static import map
 * This ensures Vite can statically analyze all imports at build time
 */
const loadLocaleData = async (locale: string) => {
    try {
        // Use static import map instead of template literal to ensure Vite can bundle it
        const importFn = localeImportMap[locale];
        if (!importFn) {
            console.warn(`Locale import not found for ${locale}, falling back to English`);
            const enImport = localeImportMap['en'];
            if (!enImport) {
                throw new Error('English locale import not found in import map');
            }
            const module = await enImport();
            return module.default || module;
        }
        
        const module = await importFn();
        return module.default || module;
    } catch (e) {
        console.error(`Could not load locale data for ${locale}`, e);
        // Try English as fallback
        try {
            const enImport = localeImportMap['en'];
            if (enImport) {
                const module = await enImport();
                return module.default || module;
            }
        } catch (fallbackError) {
            console.error('Failed to load English locale as fallback', fallbackError);
        }
        return null;
    }
};

// Function to normalize locale code to match our supported locales
function normalizeLocale(locale: string): string {
    // First check if the locale is already supported as-is
    if (isValidLocale(locale)) {
        return locale;
    }
    
    // If not, try to match the language part (before the hyphen)
    const languagePart = locale.split('-')[0].toLowerCase();
    if (isValidLocale(languagePart)) {
        return languagePart;
    }
    
    return 'en'; // fallback to English if no match
}

// Function to get the current language - simplified to prioritize browser language
export function getCurrentLanguage(): string {
    if (browser) {
        // Only use preferredLanguage if explicitly set by user, otherwise use browser language
        const userPreference = localStorage.getItem('preferredLanguage');
        if (userPreference) {
            return userPreference;
        }
        const browserLang = normalizeLocale(getLocaleFromNavigator() || 'en');
        return browserLang;
    }
    return 'en'; // Fallback for server-side rendering
}

// Register all supported locales from languages.json immediately when module loads
// This ensures the i18n system is set up before any components try to use it
// We use LANGUAGE_CODES from languages.json as the single source of truth
LANGUAGE_CODES.forEach(locale => {
    register(locale, () => loadLocaleData(locale));
});

// Initialize i18n immediately when module loads (synchronous)
// This MUST happen before any component tries to use $_ or other i18n functions
// The init() call sets up the locale store and makes waitLocale() work properly
init({
    fallbackLocale: 'en',
    initialLocale: browser 
        ? getCurrentLanguage() // Use getCurrentLanguage to determine initial locale
        : 'en',
    warnOnMissingMessages: true
});

// Async function for explicit initialization if needed
// This is mainly for backwards compatibility - the init() above already ran
export async function setupI18n() {
    // Wait for initial translations to load
    await waitForTranslations();
}