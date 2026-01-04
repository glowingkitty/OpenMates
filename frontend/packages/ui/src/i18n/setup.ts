import { register, init, getLocaleFromNavigator } from 'svelte-i18n';
import { browser } from '$app/environment';
import { isValidLocale } from './types';
import { LANGUAGE_CODES } from './languages';
import { waitForTranslations } from '../stores/i18n';

/**
 * Dynamic locale import map using Vite's import.meta.glob
 * This automatically discovers all available locale files and only loads languages
 * that are defined in languages.json AND have corresponding JSON files
 */
const allLocaleFiles = import.meta.glob('./locales/*.json');

function buildLocaleImportMap(): Record<string, () => Promise<any>> {
    const map: Record<string, () => Promise<any>> = {};

    // Build import map only for languages defined in languages.json
    for (const langCode of LANGUAGE_CODES) {
        const localePath = `./locales/${langCode}.json`;
        if (allLocaleFiles[localePath]) {
            map[langCode] = allLocaleFiles[localePath] as () => Promise<any>;
        } else {
            console.warn(`Language ${langCode} is in languages.json but locale file ${localePath} does not exist`);
        }
    }

    return map;
}

const localeImportMap = buildLocaleImportMap();

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
const initialLocale = browser ? getCurrentLanguage() : 'en';
init({
    fallbackLocale: 'en',
    initialLocale: initialLocale,
    warnOnMissingMessages: true
});

// Update HTML lang attribute to match the initial locale
// This prevents browser auto-translate from activating when the app already provides translations
// Browser translate can cause rendering bugs with dynamic text (e.g., repeating/scrolling text)
if (browser && typeof document !== 'undefined') {
    document.documentElement.setAttribute('lang', initialLocale);
}

// Async function for explicit initialization if needed
// This is mainly for backwards compatibility - the init() above already ran
export async function setupI18n() {
    // Wait for initial translations to load
    await waitForTranslations();
}